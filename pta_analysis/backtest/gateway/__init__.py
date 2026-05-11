#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gateway抽象层 - 对标vnpy.trader.gateway

提供交易接口的统一抽象,支持多种数据源和经纪商。

用法:
```python
from backtest.gateway import TqGateway, CtpGateway

# 天勤网关
gateway = TqGateway()
gateway.connect()
gateway.subscribe(["TA.CZCE"])

# 发送订单
orderid = gateway.send_order(
    symbol="TA",
    exchange="CZCE",
    direction=Direction.LONG,
    offset=Offset.OPEN,
    price=6000,
    volume=1
)

# 撤销订单
gateway.cancel_order(orderid)
```
"""

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
import threading

from vnpy.trader.constant import Direction, Exchange, Offset, Status, OrderType, Interval
from vnpy.trader.object import AccountData, PositionData, TradeData, OrderData, TickData


class GatewayType(Enum):
    """网关类型"""
    TQSdk = "tq"           # 天勤
    CTP = "ctp"           # 期货CTP
    FIBIT = "fbit"         # 富途
    UFT = "uft"           # 证券UF2
    OTC = "otc"           # 柜台
    SIMNOW = "simnow"      # 模拟交易


@dataclass
class GatewaySetting:
    """网关配置"""
    userid: str = ""
    password: str = ""
    broker_id: str = ""
    md_server: str = ""
    td_server: str = ""
    app_id: str = ""
    auth_code: str = ""
    
    # TQ专用
    tq_account: str = ""
    tq_password: str = ""
    
    # CTP专用
    front_uri: str = ""


class BaseGateway(ABC):
    """
    交易网关基类
    
    定义所有网关必须实现的接口:
    - connect: 连接
    - close: 关闭
    - subscribe: 订阅行情
    - send_order: 发送订单
    - cancel_order: 撤销订单
    - query_account: 查询账户
    - query_position: 查询持仓
    """
    
    gateway_name: str = "BASE"
    gateway_type: GatewayType = None
    
    def __init__(self, event_engine=None):
        self.event_engine = event_engine
        
        # 连接状态
        self.connected: bool = False
        
        # 数据
        self.orders: Dict[str, OrderData] = {}
        self.trades: Dict[str, TradeData] = {}
        self.positions: Dict[str, PositionData] = {}
        self.accounts: Dict[str, AccountData] = {}
        self.ticks: Dict[str, TickData] = {}
        
        # 合约信息
        self.contracts: Dict[str, Any] = {}
        
        # 线程锁
        self._lock = threading.Lock()
        
        # 订阅的合约
        self._subscribed_symbols: set = set()
    
    @abstractmethod
    def connect(self, setting: GatewaySetting) -> None:
        """连接网关"""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """关闭网关"""
        pass
    
    @abstractmethod
    def subscribe(self, symbols: List[str]) -> None:
        """订阅行情"""
        pass
    
    @abstractmethod
    def send_order(
        self,
        symbol: str,
        exchange: Exchange,
        direction: Direction,
        offset: Offset,
        price: float,
        volume: float,
        order_type: OrderType = OrderType.LIMIT
    ) -> str:
        """发送订单,返回orderid"""
        pass
    
    @abstractmethod
    def cancel_order(self, orderid: str) -> None:
        """撤销订单"""
        pass
    
    @abstractmethod
    def query_account(self) -> None:
        """查询账户"""
        pass
    
    @abstractmethod
    def query_position(self) -> None:
        """查询持仓"""
        pass
    
    def get_order(self, orderid: str) -> Optional[OrderData]:
        """获取订单"""
        return self.orders.get(orderid)
    
    def get_trade(self, tradeid: str) -> Optional[TradeData]:
        """获取成交"""
        return self.trades.get(tradeid)
    
    def get_position(self, vt_positionid: str) -> Optional[PositionData]:
        """获取持仓"""
        return self.positions.get(vt_positionid)
    
    def get_tick(self, vt_symbol: str) -> Optional[TickData]:
        """获取行情"""
        return self.ticks.get(vt_symbol)
    
    def get_account(self, accountid: str = "") -> Optional[AccountData]:
        """获取账户"""
        if not accountid and self.accounts:
            return list(self.accounts.values())[0]
        return self.accounts.get(accountid)
    
    def _new_orderid(self) -> str:
        """生成新的订单号"""
        import time
        return f"{self.gateway_name}_{int(time.time() * 1000)}"
    
    def _generate_orderid(self) -> str:
        """生成订单号"""
        with self._lock:
            return self._new_orderid()


class TqGateway(BaseGateway):
    """
    天勤网关
    
    对接TqSdk实现实盘/模拟交易
    """
    
    gateway_name = "TQ"
    gateway_type = GatewayType.TQSdk
    
    def __init__(self, event_engine=None):
        super().__init__(event_engine)
        self._tq_api = None
    
    def connect(self, setting: GatewaySetting) -> None:
        """连接天勤"""
        try:
            from tqsdk import TqApi
            
            # 创建TqApi
            if setting.tq_account:
                self._tq_api = TqApi(
                    front=setting.tq_account,
                    password=setting.tq_password,
                    event_loop=self.event_engine
                )
            else:
                self._tq_api = TqApi()
            
            self.connected = True
            print(f"{self.gateway_name} 网关连接成功")
            
        except ImportError:
            print("TqSdk未安装,请运行: pip install tqsdk")
        except Exception as e:
            print(f"{self.gateway_name} 网关连接失败: {e}")
    
    def close(self) -> None:
        """关闭连接"""
        if self._tq_api:
            self._tq_api.close()
        self.connected = False
        print(f"{self.gateway_name} 网关已关闭")
    
    def subscribe(self, symbols: List[str]) -> None:
        """订阅行情"""
        if not self._tq_api:
            return
        
        for symbol in symbols:
            self._subscribed_symbols.add(symbol)
        
        # TqSdk会自动订阅
    
    def send_order(
        self,
        symbol: str,
        exchange: Exchange,
        direction: Direction,
        offset: Offset,
        price: float,
        volume: float,
        order_type: OrderType = OrderType.LIMIT
    ) -> str:
        """发送订单"""
        if not self._tq_api or not self.connected:
            return ""
        
        orderid = self._generate_orderid()
        
        # 构造合约代码
        full_symbol = f"{symbol}.{exchange.value}"
        
        try:
            # TqSdk下单
            order = self._tq_api.insert_order(
                symbol=full_symbol,
                direction=direction.value,
                offset=offset.value,
                price=price,
                volume=volume
            )
            
            # 记录订单
            order_data = OrderData(
                gateway_name=self.gateway_name,
                symbol=symbol,
                exchange=exchange,
                orderid=orderid,
                direction=direction,
                offset=offset,
                price=price,
                volume=volume,
                status=Status.SUBMITTING,
            )
            
            with self._lock:
                self.orders[orderid] = order_data
            
            return orderid
            
        except Exception as e:
            print(f"下单失败: {e}")
            return ""
    
    def cancel_order(self, orderid: str) -> None:
        """撤销订单"""
        if not self._tq_api:
            return
        
        with self._lock:
            order = self.orders.get(orderid)
            if not order:
                return
        
        try:
            # TqSdk撤单
            # self._tq_api.cancel_order(order_id)
            pass
        except Exception as e:
            print(f"撤单失败: {e}")
    
    def query_account(self) -> None:
        """查询账户"""
        if not self._tq_api:
            return
        
        try:
            # TqSdk获取账户信息
            account = self._tq_api.get_account()
            
            account_data = AccountData(
                accountid=str(account.get("account_id", "")),
                balance=float(account.get("balance", 0)),
                frozen=float(account.get("frozen", 0)),
                datetime=datetime.now(),
                gateway_name=self.gateway_name
            )
            
            with self._lock:
                self.accounts[account_data.accountid] = account_data
                
        except Exception as e:
            print(f"查询账户失败: {e}")
    
    def query_position(self) -> None:
        """查询持仓"""
        if not self._tq_api:
            return
        
        try:
            positions = self._tq_api.get_position()
            
            for symbol, pos_data in positions.items():
                position_data = PositionData(
                    gateway_name=self.gateway_name,
                    symbol=symbol.split(".")[0],
                    exchange=Exchange[symbol.split(".")[1]] if "." in symbol else Exchange.SSE,
                    direction=Direction.LONG if pos_data.get("direction", "") == "BUY" else Direction.SHORT,
                    volume=pos_data.get("volume", 0),
                    frozen=pos_data.get("frozen", 0),
                    price=float(pos_data.get("price", 0)),
                )
                
                with self._lock:
                    self.positions[position_data.vt_positionid] = position_data
                    
        except Exception as e:
            print(f"查询持仓失败: {e}")


class SimNowGateway(BaseGateway):
    """
    SimNow模拟交易网关
    
    对接SimNow CTP模拟服务器
    """
    
    gateway_name = "SIMNOW"
    gateway_type = GatewayType.SIMNOW
    
    def __init__(self, event_engine=None):
        super().__init__(event_engine)
        self._ctp_api = None
    
    def connect(self, setting: GatewaySetting) -> None:
        """连接SimNow"""
        # SimNow配置
        # BrokerID: 9999
        # FrontID: 交易前置(默认: 2011)
        # MDFrontID: 行情前置(默认: 2013)
        
        try:
            print(f"{self.gateway_name} 网关连接成功(模拟)")
            self.connected = True
        except Exception as e:
            print(f"{self.gateway_name} 网关连接失败: {e}")
    
    def close(self) -> None:
        """关闭连接"""
        self.connected = False
    
    def subscribe(self, symbols: List[str]) -> None:
        """订阅行情"""
        for symbol in symbols:
            self._subscribed_symbols.add(symbol)
    
    def send_order(
        self,
        symbol: str,
        exchange: Exchange,
        direction: Direction,
        offset: Offset,
        price: float,
        volume: float,
        order_type: OrderType = OrderType.LIMIT
    ) -> str:
        """发送订单"""
        if not self.connected:
            return ""
        
        orderid = self._generate_orderid()
        
        order_data = OrderData(
            gateway_name=self.gateway_name,
            symbol=symbol,
            exchange=exchange,
            orderid=orderid,
            direction=direction,
            offset=offset,
            price=price,
            volume=volume,
            status=Status.SUBMITTING,
        )
        
        with self._lock:
            self.orders[orderid] = order_data
        
        # 模拟成交
        import threading
        threading.Timer(0.5, self._simulate_trade, args=(orderid, price, volume)).start()
        
        return orderid
    
    def _simulate_trade(self, orderid: str, price: float, volume: float) -> None:
        """模拟成交"""
        with self._lock:
            order = self.orders.get(orderid)
            if not order:
                return
            
            # 更新订单状态
            order.traded = volume
            order.status = Status.ALLTRADED
            
            # 生成成交
            tradeid = f"{orderid}_trade"
            trade = TradeData(
                gateway_name=self.gateway_name,
                symbol=order.symbol,
                exchange=order.exchange,
                orderid=orderid,
                tradeid=tradeid,
                direction=order.direction,
                offset=order.offset,
                price=price,
                volume=volume,
            )
            
            self.trades[tradeid] = trade
            
            # 更新持仓
            position_key = f"{order.symbol}.{order.exchange.value}.{order.direction.value}"
            position = self.positions.get(position_key)
            
            if not position:
                position = PositionData(
                    gateway_name=self.gateway_name,
                    symbol=order.symbol,
                    exchange=order.exchange,
                    direction=order.direction,
                    volume=0,
                )
                self.positions[position_key] = position
            
            if order.offset == Offset.OPEN:
                position.volume += volume
            else:
                position.volume -= volume
    
    def cancel_order(self, orderid: str) -> None:
        """撤销订单"""
        with self._lock:
            order = self.orders.get(orderid)
            if order and order.status == Status.SUBMITTING:
                order.status = Status.CANCELLED
    
    def query_account(self) -> None:
        """查询账户"""
        account_data = AccountData(
            gateway_name=self.gateway_name,
            accountid="SIMNOW_ACCOUNT",
            balance=1000000.0,
            frozen=0.0,
        )
        
        with self._lock:
            self.accounts[account_data.accountid] = account_data
    
    def query_position(self) -> None:
        """查询持仓"""
        pass


# ==================== Gateway管理器 ====================

class GatewayManager:
    """
    Gateway管理器
    
    统一管理多个网关实例
    """
    
    def __init__(self):
        self.gateways: Dict[str, BaseGateway] = {}
        self.default_gateway: Optional[BaseGateway] = None
    
    def add_gateway(self, name: str, gateway: BaseGateway) -> None:
        """添加网关"""
        self.gateways[name] = gateway
        if self.default_gateway is None:
            self.default_gateway = gateway
    
    def remove_gateway(self, name: str) -> None:
        """移除网关"""
        if name in self.gateways:
            self.gateways[name].close()
            del self.gateways[name]
    
    def get_gateway(self, name: str) -> Optional[BaseGateway]:
        """获取网关"""
        return self.gateways.get(name)
    
    def set_default(self, name: str) -> None:
        """设置默认网关"""
        gateway = self.gateways.get(name)
        if gateway:
            self.default_gateway = gateway
    
    def connect_all(self, setting: GatewaySetting) -> None:
        """连接所有网关"""
        for gateway in self.gateways.values():
            gateway.connect(setting)
    
    def close_all(self) -> None:
        """关闭所有网关"""
        for gateway in self.gateways.values():
            gateway.close()
    
    def subscribe(self, symbols: List[str], gateway_name: Optional[str] = None) -> None:
        """订阅行情"""
        if gateway_name:
            gateway = self.gateways.get(gateway_name)
            if gateway:
                gateway.subscribe(symbols)
        elif self.default_gateway:
            self.default_gateway.subscribe(symbols)
    
    def send_order(
        self,
        symbol: str,
        exchange: Exchange,
        direction: Direction,
        offset: Offset,
        price: float,
        volume: float,
        gateway_name: Optional[str] = None
    ) -> str:
        """发送订单"""
        if gateway_name:
            gateway = self.gateways.get(gateway_name)
        else:
            gateway = self.default_gateway
        
        if gateway:
            return gateway.send_order(symbol, exchange, direction, offset, price, volume)
        return ""
    
    def get_all_orders(self) -> List[OrderData]:
        """获取所有订单"""
        orders = []
        for gateway in self.gateways.values():
            orders.extend(gateway.orders.values())
        return orders
    
    def get_all_trades(self) -> List[TradeData]:
        """获取所有成交"""
        trades = []
        for gateway in self.gateways.values():
            trades.extend(gateway.trades.values())
        return trades


if __name__ == "__main__":
    print("Gateway测试")
    print("=" * 50)
    
    # 测试SimNow网关
    gateway = SimNowGateway()
    gateway.connect(GatewaySetting())
    
    print(f"连接状态: {gateway.connected}")
    
    # 订阅行情
    gateway.subscribe(["TA.CZCE", "MA.CZCE"])
    
    # 发送订单
    orderid = gateway.send_order(
        symbol="TA",
        exchange=Exchange.CZCE,
        direction=Direction.LONG,
        offset=Offset.OPEN,
        price=6000,
        volume=1
    )
    
    print(f"订单号: {orderid}")
    
    import time
    time.sleep(1)
    
    # 查询账户
    gateway.query_account()
    account = gateway.get_account()
    print(f"账户: {account}")
    
    # 关闭
    gateway.close()
