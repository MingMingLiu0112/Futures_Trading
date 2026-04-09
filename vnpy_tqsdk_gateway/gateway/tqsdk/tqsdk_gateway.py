import json
import threading
import datetime
from typing import Dict, List, Optional

from vnpy.event import EventEngine
from vnpy.trader.gateway import BaseGateway
from vnpy.trader.object import (
    TickData, OrderData, TradeData, PositionData, AccountData,
    ContractData, LogData, SubscribeRequest, OrderRequest, CancelRequest,
    HistoryRequest, Exchange, BarData
)
from vnpy.trader.constant import Direction, Offset, Status, Product, OrderType, Interval
from vnpy.trader.database import DB_TZ
from vnpy.trader.converter import OffsetConverter, PositionHolding

from tqsdk import TqApi, TqSim, TqAuth, TqKq

from .option_parser import OptionContractParser


class TqSdkOffsetConverter(OffsetConverter):
    """
    天勤网关的持仓转换器
    实现与期权模块兼容的PositionHolding结构
    """
    
    def __init__(self, oms_engine):
        """
        初始化转换器
        
        Args:
            oms_engine: OmsEngine实例
        """
        super().__init__(oms_engine)
        self.oms_engine = oms_engine
    
    def get_position_holding(self, vt_symbol: str) -> PositionHolding | None:
        """
        获取持仓数据
        
        Args:
            vt_symbol: 合约的vt_symbol
            
        Returns:
            PositionHolding: 持仓数据结构
        """
        # 首先调用父类方法获取持仓数据
        holding = super().get_position_holding(vt_symbol)
        
        # 如果持仓数据存在，更新从网关获取的实际持仓数据
        if holding:
            # 从网关的持仓数据中获取对应合约的持仓
            for key, position in self.oms_engine.positions.items():
                if key.startswith(vt_symbol):
                    if "_LONG" in key:
                        holding.long_pos = position.volume
                        holding.long_pos_frozen = position.frozen
                    elif "_SHORT" in key:
                        holding.short_pos = position.volume
                        holding.short_pos_frozen = position.frozen
        
        return holding


class TqSdkGateway(BaseGateway):
    """
    天勤网关实现，支持订阅行情和基本交易功能
    """
    default_name: str = "TQSDK"
    default_setting: Dict[str, str | int | float | bool | list] = {
        "auto_load": True,
        "contracts_file": "tqsdk_contracts.json",
        "账户类型": ["模拟账户", "快期实盘"],
        "快期账号": "",
        "快期密码": "",
        "模拟账号编号": 0,
        "交易服务器地址": "",
        "期货公司": "",
        "期货账号": "",
        "期货密码": ""
    }
    exchanges: List[Exchange] = [Exchange.SHFE, Exchange.CZCE, Exchange.DCE, Exchange.INE, Exchange.CFFEX]
    
    def __init__(self, event_engine: EventEngine, gateway_name: str) -> None:
        """
        初始化天勤网关
        """
        super().__init__(event_engine, gateway_name)
        
        self.api: Optional[TqApi] = None
        self.thread: Optional[threading.Thread] = None
        self.running: bool = False
        
        self.contracts: Dict[str, ContractData] = {}
        self.orders: Dict[str, OrderData] = {}
        self.positions: Dict[str, PositionData] = {}
        self.account: Optional[AccountData] = None
        
        self.auto_load: bool = True
        self.contracts_file: str = "tqsdk_contracts.json"
        self.username: str = ""
        self.password: str = ""
        
        # 存储行情引用
        self.quote_cache: Dict[str, object] = {}
        # 存储K线引用
        self.kline_cache: Dict[str, object] = {}
        # 存储Tick数据引用
        self.tick_cache: Dict[str, object] = {}
    
    def connect(self, setting: Dict) -> None:
        """
        连接到天勤服务器
        """
        try:
            # 读取配置
            self.auto_load = setting.get("auto_load", True)
            self.contracts_file = setting.get("contracts_file", "tqsdk_contracts.json")
            
            # 读取快期账号和密码（用于TqAuth）
            tq_username = setting.get("快期账号", "")
            tq_password = setting.get("快期密码", "")
            
            # 处理账户类型
            account_type_str = setting.get("账户类型", "模拟账户")
            
            # 处理模拟账号编号
            account_number = setting.get("模拟账号编号", None)
            if account_number:
                try:
                    account_number = int(account_number)
                except:
                    account_number = None
            
            # 处理交易服务器地址
            td_url = setting.get("交易服务器地址", None)
            
            # 读取期货公司、期货账号和期货密码（用于TqAccount）
            broker_id = setting.get("期货公司", "")
            account_id = setting.get("期货账号", "")
            account_password = setting.get("期货密码", "")
            
            # 创建账户实例
            if account_type_str == "模拟账户":
                # 使用TqKq模拟账户
                if account_number:
                    if td_url:
                        account = TqKq(td_url=td_url, number=account_number)
                    else:
                        account = TqKq(number=account_number)
                else:
                    if td_url:
                        account = TqKq(td_url=td_url)
                    else:
                        account = TqKq()
            else:
                # 使用TqAccount实盘账户
                if broker_id and account_id and account_password:
                    account = TqAccount(broker_id, account_id, account_password)
                else:
                    # 如果实盘参数不全，使用模拟账户
                    account = TqKq()
            
            # 创建天勤API实例
            if tq_username and tq_password:
                self.api = TqApi(account=account, auth=TqAuth(tq_username, tq_password))
            else:
                self.api = TqApi(account=account)
            
            # 启动行情线程
            self.running = True
            self.thread = threading.Thread(target=self.run)
            self.thread.daemon = True
            self.thread.start()
            
            # 加载合约列表
            if self.auto_load:
                self.load_contracts()
            
            self.write_log(f"天勤网关连接成功，账户类型: {account_type_str}")
        except Exception as e:
            self.write_log(f"天勤网关连接失败: {str(e)}")
    
    def close(self) -> None:
        """
        关闭天勤网关连接
        """
        try:
            self.running = False
            if self.api:
                self.api.close()
                self.api = None
            if self.thread:
                self.thread.join(timeout=5)
            self.write_log("天勤网关连接已关闭")
        except Exception as e:
            self.write_log(f"关闭天勤网关失败: {str(e)}")
    
    def process_account_data(self) -> None:
        """
        处理账户数据更新
        """
        try:
            if not self.api:
                return
            
            # 获取账户信息
            account_info = self.api.get_account()
            if self.api.is_changing(account_info):
                # 创建账户数据对象
                account = AccountData(
                    accountid="TQSDK_ACCOUNT",
                    balance=account_info.get("balance", 0),
                    frozen=account_info.get("frozen", 0),
                    gateway_name=self.gateway_name
                )
                
                self.account = account
                # 推送账户数据
                self.on_account(account)
        except Exception as e:
            self.write_log(f"处理账户数据错误: {str(e)}")
    
    def process_position_data(self) -> None:
        """
        处理持仓数据更新
        """
        try:
            if not self.api:
                return
            
            # 获取持仓信息
            positions = self.api.get_position()
            if not positions:
                return
            
            # 处理持仓数据
            for symbol, pos_info in positions.items():
                if self.api.is_changing(pos_info):
                    # 解析合约信息
                    parts = symbol.split(".")
                    if len(parts) != 2:
                        continue
                    
                    exchange_str = parts[0]
                    symbol = parts[1]
                    exchange = Exchange(exchange_str)
                    vt_symbol = f"{symbol}.{exchange.value}"
                    
                    # 创建多头持仓对象
                    long_position = PositionData(
                        symbol=symbol,
                        exchange=exchange,
                        direction=Direction.LONG,
                        volume=pos_info.get("volume_long", 0),
                        frozen=pos_info.get("frozen_long", 0),
                        price=pos_info.get("open_price_long", 0),
                        gateway_name=self.gateway_name,
                        pnl=pos_info.get("position_profit_long", 0),
                        yd_volume=pos_info.get("pos_long_his", 0)
                    )
                    self.positions[f"{vt_symbol}_LONG"] = long_position
                    self.on_position(long_position)
                    
                    # 创建空头持仓对象
                    short_position = PositionData(
                        symbol=symbol,
                        exchange=exchange,
                        direction=Direction.SHORT,
                        volume=pos_info.get("volume_short", 0),
                        frozen=pos_info.get("frozen_short", 0),
                        price=pos_info.get("open_price_short", 0),
                        gateway_name=self.gateway_name,
                        pnl=pos_info.get("position_profit_short", 0),
                        yd_volume=pos_info.get("pos_short_his", 0)
                    )
                    self.positions[f"{vt_symbol}_SHORT"] = short_position
                    self.on_position(short_position)
        except Exception as e:
            self.write_log(f"处理持仓数据错误: {str(e)}")
    
    def process_order_data(self) -> None:
        """
        处理委托数据更新
        """
        try:
            if not self.api:
                return
            
            # 获取所有订单
            orders = self.api.get_order()
            if not orders:
                return
            
            # 处理委托数据
            for tq_order_id, order in orders.items():
                if self.api.is_changing(order):
                    # 解析合约信息
                    symbol = getattr(order, "symbol", "")
                    if not symbol:
                        continue
                    
                    parts = symbol.split(".")
                    if len(parts) != 2:
                        continue
                    
                    exchange_str = parts[0]
                    symbol = parts[1]
                    exchange = Exchange(exchange_str)
                    
                    # 转换订单状态
                    if order.status == "ALIVE":
                        if order.volume_orign == order.volume_left:
                            status = Status.NOTTRADED
                        else:
                            status = Status.PARTTRADED
                    elif order.status == "FINISHED":
                        if order.volume_orign == order.volume_left:
                            status = Status.CANCELLED
                        else:
                            status = Status.ALLTRADED
                    elif order.status == "ALIVE" and order.volume_left == 0:
                        status = Status.ALLTRADED
                    else:
                        status = Status.NOTTRADED
                    
                    # 转换订单方向
                    direction = Direction.LONG if order.direction == "BUY" else Direction.SHORT
                    
                    # 转换订单偏移
                    if order.offset == "OPEN":
                        offset = Offset.OPEN
                    elif order.offset == "CLOSETODAY":
                        offset = Offset.CLOSETODAY
                    elif order.offset == "CLOSEYESTERDAY":
                        offset = Offset.CLOSEYESTERDAY
                    else:
                        offset = Offset.CLOSE
                    
                    # 使用订单对象的order_id属性，确保与send_order方法使用的ID一致
                    tq_order_id = getattr(order, "order_id", "")
                    if not tq_order_id:
                        # 尝试使用其他属性获取订单ID
                        tq_order_id = str(id(order))
                    
                    # 从成交记录中获取实际成交数量
                    traded = 0
                    if hasattr(order, "trade_records"):
                        for trade in order.trade_records.values():
                            traded += trade.volume
                    
                    # 创建订单数据对象
                    order_data = OrderData(
                        symbol=symbol,
                        exchange=exchange,
                        orderid=tq_order_id,
                        type=OrderType.LIMIT,
                        direction=direction,
                        offset=offset,
                        price=order.limit_price,
                        volume=order.volume_orign,
                        traded=traded,
                        status=status,
                        datetime=datetime.now(),
                        reference="ManualTrading",
                        gateway_name=self.gateway_name
                    )
                    
                    # 推送订单数据
                    self.write_log(f"推送委托信息: {order_data.__dict__}")
                    self.on_order(order_data)
        except Exception as e:
            self.write_log(f"处理委托数据错误: {str(e)}")
    
    def process_trade_data(self) -> None:
        """
        处理成交数据更新
        """
        try:
            if not self.api:
                return
            
            # 获取所有订单
            orders = self.api.get_order()
            if not orders:
                return
            
            # 处理成交数据
            for _, order in orders.items():
                if hasattr(order, "trade_records"):
                    for trade in order.trade_records.values():
                        if self.api.is_changing(trade):
                            # 解析合约信息
                            symbol = getattr(order, "symbol", "")
                            if not symbol:
                                continue
                            
                            parts = symbol.split(".")
                            if len(parts) != 2:
                                continue
                            
                            exchange_str = parts[0]
                            symbol = parts[1]
                            exchange = Exchange(exchange_str)
                            
                            # 转换成交方向
                            direction = Direction.LONG if trade.direction == "BUY" else Direction.SHORT
                            
                            # 转换成交偏移
                            if trade.offset == "OPEN":
                                offset = Offset.OPEN
                            elif trade.offset == "CLOSETODAY":
                                offset = Offset.CLOSETODAY
                            elif trade.offset == "CLOSEYESTERDAY":
                                offset = Offset.CLOSEYESTERDAY
                            else:
                                offset = Offset.CLOSE
                            
                            # 使用订单对象的order_id属性，确保与订单数据的ID一致
                            tq_order_id = getattr(order, "order_id", "")
                            if not tq_order_id:
                                continue
                            
                            # 使用成交记录的trade_id属性作为成交ID
                            trade_id = getattr(trade, "trade_id", str(id(trade)))
                            
                            # 创建成交数据对象
                            trade_data = TradeData(
                                symbol=symbol,
                                exchange=exchange,
                                orderid=tq_order_id,
                                tradeid=trade_id,
                                direction=direction,
                                offset=offset,
                                price=trade.price,
                                volume=trade.volume,
                                datetime=trade.datetime,
                                gateway_name=self.gateway_name
                            )
                            
                            # 推送成交数据
                            self.write_log(f"推送成交信息: {trade_data.__dict__}")
                            self.on_trade(trade_data)
        except Exception as e:
            self.write_log(f"处理成交数据错误: {str(e)}")
    
    def run(self) -> None:
        """
        运行行情订阅和数据处理
        """
        while self.running:
            try:
                if self.api:
                    self.api.wait_update()
                    # 处理行情数据
                    self.process_tick_data()
                    # 处理账户数据
                    self.process_account_data()
                    # 处理持仓数据
                    self.process_position_data()
                    # 处理委托数据
                    self.process_order_data()
                    # 处理成交数据
                    self.process_trade_data()
            except Exception as e:
                self.write_log(f"行情处理错误: {str(e)}")
    
    def process_tick_data(self) -> None:
        """
        处理天勤推送的行情数据
        """
        try:
            if not self.api:
                return
            
            # 处理行情数据
            for vt_symbol, quote in self.quote_cache.items():
                if self.api.is_changing(quote):
                    # 解析合约信息
                    parts = vt_symbol.split(".")
                    if len(parts) != 2:
                        continue
                    symbol = parts[0]
                    exchange_str = parts[1]
                    exchange = Exchange(exchange_str)
                    
                    # 处理datetime字段，确保它是一个有效的datetime对象，并带有正确的时区信息
                    datetime_value = None
                    if hasattr(quote, 'datetime'):
                        from datetime import datetime
                        if isinstance(quote.datetime, str):
                            try:
                                # 尝试解析ISO格式的时间字符串
                                datetime_value = datetime.fromisoformat(quote.datetime.replace('Z', '+00:00'))
                                # 确保datetime带有时区信息，如果没有则添加数据库时区
                                if datetime_value.tzinfo is None:
                                    datetime_value = datetime_value.replace(tzinfo=DB_TZ)
                            except:
                                # 如果解析失败，使用当前时间并添加时区
                                datetime_value = datetime.now(DB_TZ)
                        else:
                            # 如果是datetime对象，确保带有时区信息
                            if quote.datetime.tzinfo is None:
                                # 如果没有时区信息，添加数据库时区
                                datetime_value = quote.datetime.replace(tzinfo=DB_TZ)
                            else:
                                # 如果已有时间信息，转换为数据库时区
                                datetime_value = quote.datetime.astimezone(DB_TZ)
                    else:
                        # 如果没有datetime字段，使用当前时间并添加时区
                        from datetime import datetime
                        datetime_value = datetime.now(DB_TZ)
                    
                    # 创建TickData对象
                    tick = TickData(
                        symbol=symbol,
                        exchange=exchange,
                        datetime=datetime_value,
                        name=quote.instrument_name if hasattr(quote, 'instrument_name') else symbol,
                        volume=quote.volume if hasattr(quote, 'volume') else 0,
                        turnover=quote.turnover if hasattr(quote, 'turnover') else 0,
                        open_interest=quote.open_interest if hasattr(quote, 'open_interest') else 0,
                        last_price=quote.last_price if hasattr(quote, 'last_price') else 0,
                        limit_up=quote.upper_limit if hasattr(quote, 'upper_limit') else 0,
                        limit_down=quote.lower_limit if hasattr(quote, 'lower_limit') else 0,
                        open_price=quote.open if hasattr(quote, 'open') else 0,
                        high_price=quote.high if hasattr(quote, 'high') else 0,
                        low_price=quote.low if hasattr(quote, 'low') else 0,
                        pre_close=quote.prev_settlement if hasattr(quote, 'prev_settlement') else 0,
                        bid_price_1=quote.bid_price1 if hasattr(quote, 'bid_price1') else 0,
                        bid_volume_1=quote.bid_volume1 if hasattr(quote, 'bid_volume1') else 0,
                        ask_price_1=quote.ask_price1 if hasattr(quote, 'ask_price1') else 0,
                        ask_volume_1=quote.ask_volume1 if hasattr(quote, 'ask_volume1') else 0,
                        bid_price_2=quote.bid_price2 if hasattr(quote, 'bid_price2') else 0,
                        bid_volume_2=quote.bid_volume2 if hasattr(quote, 'bid_volume2') else 0,
                        ask_price_2=quote.ask_price2 if hasattr(quote, 'ask_price2') else 0,
                        ask_volume_2=quote.ask_volume2 if hasattr(quote, 'ask_volume2') else 0,
                        bid_price_3=quote.bid_price3 if hasattr(quote, 'bid_price3') else 0,
                        bid_volume_3=quote.bid_volume3 if hasattr(quote, 'bid_volume3') else 0,
                        ask_price_3=quote.ask_price3 if hasattr(quote, 'ask_price3') else 0,
                        ask_volume_3=quote.ask_volume3 if hasattr(quote, 'ask_volume3') else 0,
                        bid_price_4=quote.bid_price4 if hasattr(quote, 'bid_price4') else 0,
                        bid_volume_4=quote.bid_volume4 if hasattr(quote, 'bid_volume4') else 0,
                        ask_price_4=quote.ask_price4 if hasattr(quote, 'ask_price4') else 0,
                        ask_volume_4=quote.ask_volume4 if hasattr(quote, 'ask_volume4') else 0,
                        bid_price_5=quote.bid_price5 if hasattr(quote, 'bid_price5') else 0,
                        bid_volume_5=quote.bid_volume5 if hasattr(quote, 'bid_volume5') else 0,
                        ask_price_5=quote.ask_price5 if hasattr(quote, 'ask_price5') else 0,
                        ask_volume_5=quote.ask_volume5 if hasattr(quote, 'ask_volume5') else 0,
                        gateway_name=self.gateway_name
                    )
                    
                    # 推送行情数据
                    self.on_tick(tick)
            
            # 处理K线数据
            for key, klines in self.kline_cache.items():
                if self.api.is_changing(klines.iloc[-1], "datetime"):
                    # 新K线生成，可以在这里处理
                    pass
            
            # 处理Tick数据
            for key, ticks in self.tick_cache.items():
                if self.api.is_changing(ticks):
                    # Tick数据变化，可以在这里处理
                    pass
        except Exception as e:
            self.write_log(f"处理行情数据错误: {str(e)}")
    
    def load_contracts(self) -> None:
        """
        调用generate_contracts.py生成合约列表，支持期权合约解析
        """
        try:
            from .generate_contracts import get_contracts_dict
            
            self.write_log(f"正在调用脚本生成合约...")
            
            # 从设置中获取账号密码（如果有）
            account = "16740529999"
            password = "19841228"
            
            # 调用generate_contracts.py中的函数生成合约字典
            contracts_data = get_contracts_dict(account, password)
            
            option_count = 0
            futures_count = 0
            
            for contract_info in contracts_data:
                symbol = contract_info.get("symbol")
                exchange_str = contract_info.get("exchange")
                
                if not symbol or not exchange_str:
                    continue
                
                exchange = Exchange(exchange_str)
                vt_symbol = f"{symbol}.{exchange.value}"
                
                name = contract_info.get("name", symbol)
                size = contract_info.get("size", 1)
                pricetick = contract_info.get("price_tick", 0.01)
                min_volume = contract_info.get("min_volume", 1)
                
                if OptionContractParser.is_option_contract(symbol, exchange):
                    contract = OptionContractParser.create_option_contract(
                        symbol=symbol,
                        exchange=exchange,
                        name=name,
                        size=size,
                        pricetick=pricetick,
                        min_volume=min_volume,
                        gateway_name=self.gateway_name
                    )
                    if contract:
                        self.contracts[vt_symbol] = contract
                        self.on_contract(contract)
                        option_count += 1
                else:
                    contract = ContractData(
                        symbol=symbol,
                        exchange=exchange,
                        name=name,
                        product=Product.FUTURES,
                        size=size,
                        pricetick=pricetick,
                        min_volume=min_volume,
                        gateway_name=self.gateway_name
                    )
                    self.contracts[vt_symbol] = contract
                    self.on_contract(contract)
                    futures_count += 1
            
            self.write_log(f"生成并加载合约: 期货 {futures_count} 个, 期权 {option_count} 个")
        except Exception as e:
            self.write_log(f"加载合约列表失败: {str(e)}")
    
    def subscribe(self, req: SubscribeRequest) -> None:
        """
        订阅行情
        """
        try:
            if not self.api:
                self.write_log("天勤网关未连接")
                return
            
            # 订阅天勤行情
            symbol = req.symbol
            exchange = req.exchange.value
            tq_symbol = f"{exchange}.{symbol}"
            
            # 获取行情引用并存储
            quote = self.api.get_quote(tq_symbol)
            self.quote_cache[req.vt_symbol] = quote
            
            self.write_log(f"订阅行情成功: {req.vt_symbol}")
        except Exception as e:
            self.write_log(f"订阅行情失败: {str(e)}")
    
    def send_order(self, req: OrderRequest) -> str:
        """
        发送订单
        """
        try:
            if not self.api:
                self.write_log("天勤网关未连接")
                return ""
            
            # 转换订单参数
            symbol = req.symbol
            exchange = req.exchange.value
            tq_symbol = f"{exchange}.{symbol}"
            
            direction = "BUY" if req.direction == Direction.LONG else "SELL"
            if req.offset == Offset.OPEN:
                offset = "OPEN"
            elif req.offset == Offset.CLOSETODAY:
                offset = "CLOSETODAY"
            elif req.offset == Offset.CLOSEYESTERDAY:
                offset = "CLOSEYESTERDAY"
            else:
                offset = "CLOSE"
            
            # 发送订单
            order = self.api.insert_order(
                symbol=tq_symbol,
                direction=direction,
                offset=offset,
                volume=req.volume,
                limit_price=req.price
            )
            
            # 等待订单ID生成
            while not hasattr(order, "order_id") or not order.order_id:
                self.api.wait_update()
            
            # 使用天勤API返回的订单ID
            tq_order_id = order.order_id
            vt_orderid = f"{self.gateway_name}.{tq_order_id}"
            
            # 存储订单引用
            self.orders[vt_orderid] = order
            
            self.write_log(f"发送订单成功: {vt_orderid}")
            return vt_orderid
        except Exception as e:
            self.write_log(f"发送订单失败: {str(e)}")
            return ""
    
    def cancel_order(self, req: CancelRequest) -> None:
        """
        取消订单
        """
        try:
            if not self.api:
                self.write_log("天勤网关未连接")
                return
            
            # 获取订单引用
            order = self.orders.get(req.vt_orderid)
            if not order:
                self.write_log(f"订单不存在: {req.vt_orderid}")
                return
            
            # 取消订单
            self.api.cancel_order(order)
            self.write_log(f"取消订单成功: {req.vt_orderid}")
        except Exception as e:
            self.write_log(f"取消订单失败: {str(e)}")
    
    def query_account(self) -> None:
        """
        查询账户信息
        """
        try:
            if not self.api:
                self.write_log("天勤网关未连接")
                return
            
            # 获取账户信息
            account_info = self.api.get_account()
            
            # 创建账户数据对象
            account = AccountData(
                accountid="TQSDK_ACCOUNT",
                balance=account_info.get("balance", 0),
                frozen=account_info.get("frozen", 0),
                available=account_info.get("available", 0),
                gateway_name=self.gateway_name
            )
            
            self.account = account
            self.on_account(account)
            self.write_log("查询账户信息成功")
        except Exception as e:
            self.write_log(f"查询账户信息失败: {str(e)}")
    
    def query_position(self) -> None:
        """
        查询持仓信息
        """
        try:
            if not self.api:
                self.write_log("天勤网关未连接")
                return
            
            # 获取持仓信息
            positions = self.api.get_position()
            
            # 处理持仓数据
            for symbol, pos_info in positions.items():
                # 解析合约信息
                parts = symbol.split(".")
                if len(parts) != 2:
                    continue
                
                exchange_str, symbol = parts
                exchange = Exchange(exchange_str)
                vt_symbol = f"{symbol}.{exchange.value}"
                
                # 创建多头持仓对象
                long_position = PositionData(
                    symbol=symbol,
                    exchange=exchange,
                    direction=Direction.LONG,
                    volume=pos_info.get("volume_long", 0),
                    frozen=pos_info.get("frozen_long", 0),
                    price=pos_info.get("open_price_long", 0),
                    gateway_name=self.gateway_name
                )
                self.positions[f"{vt_symbol}_LONG"] = long_position
                self.on_position(long_position)
                
                # 创建空头持仓对象
                short_position = PositionData(
                    symbol=symbol,
                    exchange=exchange,
                    direction=Direction.SHORT,
                    volume=pos_info.get("volume_short", 0),
                    frozen=pos_info.get("frozen_short", 0),
                    price=pos_info.get("open_price_short", 0),
                    gateway_name=self.gateway_name
                )
                self.positions[f"{vt_symbol}_SHORT"] = short_position
                self.on_position(short_position)
            
            self.write_log("查询持仓信息成功")
        except Exception as e:
            self.write_log(f"查询持仓信息失败: {str(e)}")
    
    def query_history(self, req: HistoryRequest) -> List[BarData]:
        """
        查询历史K线数据
        """
        try:
            if not self.api:
                self.write_log("天勤网关未连接")
                return []
            
            # 转换参数
            symbol = req.symbol
            exchange = req.exchange.value
            tq_symbol = f"{exchange}.{symbol}"
            
            # 转换周期
            duration_seconds = {
                "tick": 0,
                "1m": 60,
                "5m": 300,
                "15m": 900,
                "30m": 1800,
                "1h": 3600,
                "2h": 7200,
                "4h": 14400,
                "d": 86400,
                "w": 604800,
                "M": 2592000
            }.get(req.interval.value, 60)
            
            # 查询历史数据
            klines = self.api.get_kline_serial(
                symbol=tq_symbol,
                duration_seconds=duration_seconds,
                data_length=req.size
            )
            
            # 转换为BarData对象
            bars = []
            for i in range(len(klines)):
                bar = BarData(
                    symbol=symbol,
                    exchange=req.exchange,
                    datetime=klines[i]["datetime"],
                    interval=req.interval,
                    volume=klines[i]["volume"],
                    open_price=klines[i]["open"],
                    high_price=klines[i]["high"],
                    low_price=klines[i]["low"],
                    close_price=klines[i]["close"],
                    gateway_name=self.gateway_name
                )
                bars.append(bar)
            
            return bars
        except Exception as e:
            self.write_log(f"查询历史数据失败: {str(e)}")
            return []
    
    def query_settlement(self, symbol: str, exchange: Exchange, days: int = 1, start_dt: datetime.date = None) -> object:
        """
        查询交易所合约每日结算价
        """
        try:
            if not self.api:
                self.write_log("天勤网关未连接")
                return None
            
            # 转换参数
            tq_symbol = f"{exchange.value}.{symbol}"
            
            # 查询结算价
            if start_dt:
                df = self.api.query_symbol_settlement(tq_symbol, days=days, start_dt=start_dt)
            else:
                df = self.api.query_symbol_settlement(tq_symbol, days=days)
            
            self.write_log(f"查询结算价成功: {symbol}.{exchange.value}")
            return df
        except Exception as e:
            self.write_log(f"查询结算价失败: {str(e)}")
            return None
    
    def query_ranking(self, symbol: str, exchange: Exchange, ranking_type: str = "VOLUME", days: int = 1) -> object:
        """
        查询合约成交排名/持仓排名
        """
        try:
            if not self.api:
                self.write_log("天勤网关未连接")
                return None
            
            # 转换参数
            tq_symbol = f"{exchange.value}.{symbol}"
            
            # 查询排名
            df = self.api.query_symbol_ranking(tq_symbol, ranking_type=ranking_type, days=days)
            
            self.write_log(f"查询排名成功: {symbol}.{exchange.value}")
            return df
        except Exception as e:
            self.write_log(f"查询排名失败: {str(e)}")
            return None