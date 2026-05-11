#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
框架自测脚本

测试所有模块的功能，确保框架正常工作。
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import time
from datetime import datetime, timedelta
from typing import List
import numpy as np

# ==================== 测试数据准备 ====================

def generate_test_bars(
    symbol: str = "TA",
    exchange_str: str = "CZCE",
    count: int = 2000,
    start_date: datetime = None
) -> List:
    """生成测试K线数据"""
    from vnpy.trader.constant import Exchange
    from vnpy.trader.object import BarData
    
    if start_date is None:
        start_date = datetime(2024, 3, 1)
    
    exchange = Exchange[exchange_str]
    np.random.seed(42)
    
    bars = []
    base = 6000
    for i in range(count):
        dt = start_date + timedelta(minutes=i)
        base += np.random.randn() * 5
        bars.append(BarData(
            gateway_name="TEST",
            symbol=symbol,
            exchange=exchange,
            datetime=dt,
            interval=1,  # MINUTE
            open_price=round(base - 5, 2),
            high_price=round(base + 10, 2),
            low_price=round(base - 10, 2),
            close_price=round(base, 2),
            volume=100 + np.random.randint(-20, 20)
        ))
    
    return bars


# ==================== 测试 EventEngine ====================

def test_event_engine():
    """测试事件引擎"""
    print("\n" + "=" * 60)
    print("测试 1: EventEngine")
    print("=" * 60)
    
    from backtest.event import EventEngine, Event, EventType
    
    # 测试注册和触发
    events_received = []
    
    def on_bar(bar):
        events_received.append(bar)
    
    ee = EventEngine()
    ee.register(EventType.BAR.value, on_bar)
    ee.start()
    
    # 发送测试事件
    class MockBar:
        def __init__(self):
            self.datetime = datetime.now()
            self.close_price = 6000
    
    for i in range(5):
        ee.put_bar(MockBar())
    
    time.sleep(0.3)
    ee.stop()
    
    assert len(events_received) == 5, f"期望5个事件,实际{len(events_received)}"
    print(f"  ✓ 事件注册和触发: 收到 {len(events_received)} 个事件")
    
    # 测试快捷方法
    ee2 = EventEngine()
    tick_received = []
    def on_tick(tick):
        tick_received.append(tick)
    
    ee2.register(EventType.TICK.value, on_tick)
    ee2.start()
    
    class MockTick:
        def __init__(self):
            self.datetime = datetime.now()
            self.last_price = 6000
    
    ee2.put_tick(MockTick())
    time.sleep(0.2)
    ee2.stop()
    
    assert len(tick_received) == 1
    print(f"  ✓ 快捷方法 put_tick: 正常")
    
    # 测试统计
    ee3 = EventEngine()
    ee3.start()
    assert ee3.is_active == True
    assert ee3.event_count == 0
    ee3.stop()
    assert ee3.is_active == False
    print(f"  ✓ 启动/停止/统计: 正常")
    
    return True


# ==================== 测试 AlphaLab ====================

def test_alpha_lab():
    """测试数据加载模块"""
    print("\n" + "=" * 60)
    print("测试 2: AlphaLab (数据加载)")
    print("=" * 60)
    
    from backtest.lab import AlphaLab, bars_to_dataframe, dataframe_to_bars
    from vnpy.trader.constant import Interval
    
    lab = AlphaLab()
    
    # 测试合约配置
    settings = lab.load_contract_setttings()
    assert len(settings) > 0, "应该有合约配置"
    print(f"  ✓ 加载合约配置: {len(settings)} 个合约")
    
    # 测试单个配置
    ta_setting = lab.get_contract_setting("TA.CZCE")
    assert ta_setting is not None, "应该有TA.CZCE配置"
    assert ta_setting["size"] == 10
    assert ta_setting["pricetick"] == 2
    print(f"  ✓ 获取单个配置: TA size={ta_setting['size']}, pricetick={ta_setting['pricetick']}")
    
    # 测试添加配置
    lab.add_contract_setting("TEST.SSE", {
        "name": "测试",
        "size": 10,
        "pricetick": 0.01
    })
    test_setting = lab.get_contract_setting("TEST.SSE")
    assert test_setting is not None
    print(f"  ✓ 添加配置: TEST.SSE")
    
    # 测试数据信息
    info = lab.get_data_info()
    assert info["contract_count"] > 0
    print(f"  ✓ 数据信息: {info['data_path']}, {info['contract_count']} 合约")
    
    # 测试bars_to_dataframe
    test_bars = generate_test_bars(count=100)
    df = bars_to_dataframe(test_bars)
    assert len(df) == 100
    assert "close" in df.columns
    print(f"  ✓ bars_to_dataframe: {len(df)} 行")
    
    # 测试dataframe_to_bars
    bars_back = dataframe_to_bars(df, "TA.CZCE", Interval.MINUTE)
    assert len(bars_back) == 100
    print(f"  ✓ dataframe_to_bars: {len(bars_back)} 根K线")
    
    return True


# ==================== 测试 Gateway ====================

def test_gateway():
    """测试交易网关"""
    print("\n" + "=" * 60)
    print("测试 3: Gateway (交易网关)")
    print("=" * 60)
    
    from backtest.gateway import (
        SimNowGateway, GatewaySetting, GatewayType,
        GatewayManager, BaseGateway
    )
    from vnpy.trader.constant import Direction, Exchange, Offset
    
    # 测试SimNow网关
    gateway = SimNowGateway()
    assert gateway.gateway_name == "SIMNOW"
    assert gateway.gateway_type == GatewayType.SIMNOW
    
    gateway.connect(GatewaySetting())
    assert gateway.connected == True
    print(f"  ✓ SimNowGateway 连接: {gateway.connected}")
    
    # 测试订阅
    gateway.subscribe(["TA.CZCE", "MA.CZCE"])
    print(f"  ✓ 订阅行情: TA.CZCE, MA.CZCE")
    
    # 测试下单
    orderid = gateway.send_order(
        symbol="TA",
        exchange=Exchange.CZCE,
        direction=Direction.LONG,
        offset=Offset.OPEN,
        price=6000,
        volume=1
    )
    assert orderid != ""
    print(f"  ✓ 发送订单: {orderid}")
    
    # 等待模拟成交
    time.sleep(0.6)
    
    # 测试查询账户
    gateway.query_account()
    account = gateway.get_account()
    assert account is not None
    assert account.balance > 0
    print(f"  ✓ 查询账户: balance={account.balance:.2f}")
    
    # 测试获取订单
    order = gateway.get_order(orderid)
    assert order is not None
    print(f"  ✓ 获取订单: status={order.status}")
    
    # 测试获取成交
    trades = list(gateway.trades.values())
    assert len(trades) > 0
    print(f"  ✓ 获取成交: {len(trades)} 笔")
    
    # 测试GatewayManager
    manager = GatewayManager()
    manager.add_gateway("sim", gateway)
    manager.set_default("sim")
    assert manager.default_gateway == gateway
    
    manager2 = manager.get_gateway("sim")
    assert manager2 == gateway
    print(f"  ✓ GatewayManager: 添加/获取/设置默认")
    
    gateway.close()
    
    return True


# ==================== 测试 CtaStrategy ====================

def test_cta_strategy():
    """测试CTA策略模板"""
    print("\n" + "=" * 60)
    print("测试 4: CtaStrategy (CTA策略模板)")
    print("=" * 60)
    
    from backtest.strategy import CtaStrategy, MultiTimeframeStrategy, StrategyManager
    from backtest.native_engine import BacktestingEngine
    
    # 创建模拟引擎
    class MockEngine:
        def __init__(self):
            self.sent_orders = []
        
        def send_order(self, strategy, vt_symbol, direction, offset, price, volume):
            orderid = f"order_{len(self.sent_orders)}"
            self.sent_orders.append({
                "orderid": orderid,
                "vt_symbol": vt_symbol,
                "direction": direction,
                "offset": offset,
                "price": price,
                "volume": volume
            })
            return [orderid]
        
        def cancel_order(self, strategy, orderid):
            pass
        
        def write_log(self, msg, strategy):
            pass
    
    mock_engine = MockEngine()
    
    # 创建策略
    class TestMACD(CtaStrategy):
        author = "Test"
        fast_period = 12
        slow_period = 26
        
        def on_init(self):
            self.fast_ema = 0
            self.slow_ema = 0
            self.init_called = True
        
        def on_calculate(self, bar):
            # MACD计算
            k = 2 / (self.fast_period + 1)
            
            if self.fast_ema == 0:
                self.fast_ema = bar.close_price
                self.slow_ema = bar.close_price
            else:
                self.fast_ema = bar.close_price * k + self.fast_ema * (1 - k)
                slow_k = 2 / (self.slow_period + 1)
                self.slow_ema = bar.close_price * slow_k + self.slow_ema * (1 - slow_k)
            
            # 交易逻辑
            if self.pos == 0 and self.fast_ema > self.slow_ema:
                self.buy(bar.close_price, 1)
            elif self.pos > 0 and self.fast_ema < self.slow_ema:
                self.sell(bar.close_price, abs(self.pos))
    
    strategy = TestMACD(
        strategy_engine=mock_engine,
        strategy_name="TestMACD",
        vt_symbols=["TA.CZCE"],
        setting={"fast_period": 12, "slow_period": 26}
    )
    
    assert strategy.author == "Test"
    assert strategy.fast_period == 12
    print(f"  ✓ 策略创建: author={strategy.author}, fast_period={strategy.fast_period}")
    
    # 测试初始化
    strategy.on_init()
    assert strategy.init_called == True
    assert strategy.fast_ema == 0  # 还没收到K线
    assert strategy.slow_ema == 0  # 初始化后应该是0
    print(f"  ✓ 策略初始化: on_init 调用")
    
    # 测试K线计算
    class MockBar:
        def __init__(self, close):
            self.vt_symbol = "TA.CZCE"
            self.close_price = close
            self.datetime = datetime.now()
    
    strategy.on_calculate(MockBar(6000))
    assert strategy.fast_ema == 6000  # 第一根K线初始化
    strategy.on_calculate(MockBar(6010))
    assert strategy.fast_ema != 6000  # 应该有更新
    print(f"  ✓ K线计算: EMA更新正常")
    
    # 测试买卖
    strategy.pos = 0
    strategy.on_calculate(MockBar(6050))
    assert len(mock_engine.sent_orders) > 0
    print(f"  ✓ 交易信号: 买入订单已发送")
    
    # 测试StrategyManager
    manager = StrategyManager(mock_engine)
    s2 = manager.add_strategy(TestMACD, "S2", ["TA.CZCE"], {})
    assert s2.strategy_name == "S2"
    print(f"  ✓ StrategyManager: 添加/获取策略")
    
    return True


# ==================== 测试 BacktestingEngine ====================

def test_backtesting_engine():
    """测试回测引擎"""
    print("\n" + "=" * 60)
    print("测试 5: BacktestingEngine (回测引擎)")
    print("=" * 60)
    
    from backtest import BacktestingEngine, AlphaStrategy
    from backtest.examples.macd_strategy import MacdStrategy
    from vnpy.trader.constant import Interval, Exchange
    from datetime import datetime, timedelta
    
    # 生成测试数据
    test_bars = generate_test_bars(count=2000)
    
    # 创建引擎
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbols=["TA.CZCE"],
        interval=Interval.MINUTE,
        start=datetime(2024, 3, 1),
        end=datetime(2024, 6, 30),
        capital=100000,
    )
    
    # 添加合约配置
    engine.add_contract_setting(
        "TA.CZCE",
        size=10,
        pricetick=2,
        long_rate=0.00005,
        short_rate=0.00005,
        commission_rate=0.00005,
        margin_rate=0.10
    )
    
    # 加载数据
    engine.load_data(test_bars)
    print(f"  ✓ 引擎配置: 加载 {len(test_bars)} 根K线")
    
    # 添加策略
    engine.add_strategy(MacdStrategy, setting={"size": 1})
    print(f"  ✓ 添加策略: MacdStrategy")
    
    # 运行回测
    engine.run_backtesting()
    print(f"  ✓ 回测运行完成")
    
    # 计算结果
    engine.calculate_result()
    stats = engine.calculate_statistics()
    
    print(f"    起始资金: {stats.get('start_balance', 0):,.2f}")
    print(f"    结束资金: {stats.get('end_balance', 0):,.2f}")
    print(f"    总收益率: {stats.get('total_return', 0):.2f}%")
    print(f"    成交笔数: {stats.get('total_trade_count', 0)}")
    
    assert stats.get('total_trade_count', 0) > 0, "应该有成交"
    print(f"  ✓ 结果计算: 统计正常")
    
    # 测试数据转换
    from backtest import pandas_to_bars
    import pandas as pd
    
    df = pd.DataFrame({
        'datetime': [datetime(2024, 1, 1) + timedelta(minutes=i) for i in range(100)],
        'open': [6000 + i for i in range(100)],
        'high': [6010 + i for i in range(100)],
        'low': [5990 + i for i in range(100)],
        'close': [6005 + i for i in range(100)],
        'volume': [100 for i in range(100)],
    })
    
    bars = pandas_to_bars(df, "TA.CZCE")
    assert len(bars) == 100
    print(f"  ✓ pandas_to_bars: {len(bars)} 根K线")
    
    return True


# ==================== 测试 ParameterOptimizer ====================

def test_optimizer():
    """测试参数优化器"""
    print("\n" + "=" * 60)
    print("测试 6: ParameterOptimizer (参数优化)")
    print("=" * 60)
    
    from backtest.optimizer import (
        ParameterOptimizer, OptimizationTarget, OptimizationResult
    )
    from backtest.examples.macd_strategy import MacdStrategy
    from vnpy.trader.constant import Interval
    from datetime import datetime
    
    # 生成测试数据
    test_bars = generate_test_bars(count=500)
    
    # 创建优化器
    optimizer = ParameterOptimizer(strategy_class=MacdStrategy)
    optimizer.set_engine_config(
        vt_symbols=["TA.CZCE"],
        interval=Interval.MINUTE,
        start=datetime(2024, 3, 1),
        end=datetime(2024, 6, 30),
        capital=100000,
    )
    
    # 添加合约配置
    optimizer.set_engine_config(
        vt_symbols=["TA.CZCE"],
        interval=Interval.MINUTE,
        start=datetime(2024, 3, 1),
        end=datetime(2024, 6, 30),
        capital=100000,
        size=10,
        pricetick=2,
        long_rate=0.00005,
        short_rate=0.00005,
    )
    
    # 设置数据
    optimizer.set_data(test_bars)
    
    # 添加参数
    optimizer.add_parameter("fast_period", 5, 15, 5)  # 5, 10, 15
    optimizer.add_parameter("slow_period", 20, 30, 10)  # 20, 30
    
    # 设置目标
    optimizer.set_target(OptimizationTarget.SHARPE_RATIO)
    
    print(f"  ✓ 优化器配置: fast_period [5,15] 步长5, slow_period [20,30] 步长10")
    
    # 运行优化
    results = optimizer.run(progress=False)
    assert len(results) > 0, "应该有优化结果"
    print(f"  ✓ 优化运行: {len(results)} 种组合")
    
    # 打印结果
    optimizer.print_top_results(3)
    
    # 测试获取最优
    top = optimizer.get_top_results(1)
    assert len(top) == 1
    print(f"  ✓ 最优结果: sharpe={top[0].sharpe_ratio:.4f}")
    
    return True


# ==================== 测试 StrategyIndicator ====================

def test_indicator():
    """测试指标计算器"""
    print("\n" + "=" * 60)
    print("测试 7: StrategyIndicator (指标计算)")
    print("=" * 60)
    
    from backtest.strategy_base import StrategyIndicator, PositionManager, IndicatorBar
    from vnpy.trader.object import BarData
    from vnpy.trader.constant import Exchange
    
    indicator = StrategyIndicator()
    
    # 创建测试K线
    bars = generate_test_bars(count=100)
    vt_symbol = "TA.CZCE"
    
    # 更新指标
    for bar in bars:
        indicator.update(bar)
    
    # 测试EMA
    ema20 = indicator.ema(vt_symbol, 20)
    assert ema20 is not None
    print(f"  ✓ EMA(20): {ema20:.2f}")
    
    # 测试MACD
    macd = indicator.macd(vt_symbol)
    assert macd is not None
    assert isinstance(macd, tuple)
    assert len(macd) == 3
    dif, dea, histogram = macd
    print(f"  ✓ MACD: dif={dif:.4f}, dea={dea:.4f}, histogram={histogram:.4f}")
    
    # 测试RSI
    rsi6 = indicator.rsi(vt_symbol, 6)
    rsi14 = indicator.rsi(vt_symbol, 14)
    assert rsi6 is not None
    assert rsi14 is not None
    print(f"  ✓ RSI: RSI(6)={rsi6:.2f}, RSI(14)={rsi14:.2f}")
    
    # 测试布林带
    bb = indicator.bollinger(vt_symbol, 20, 2)
    assert bb is not None
    upper, mid, lower = bb
    print(f"  ✓ 布林带: upper={upper:.2f}, middle={mid:.2f}, lower={lower:.2f}")

    # 测试ATR
    atr = indicator.atr(vt_symbol, 14)
    assert atr is not None
    print(f"  ✓ ATR(14): {atr:.4f}")

    # 测试KDJ
    kdj = indicator.kdj(vt_symbol, 9, 3, 3)
    assert kdj is not None
    k_val, d_val, j_val = kdj
    print(f"  ✓ KDJ: k={k_val:.2f}, d={d_val:.2f}, j={j_val:.2f}")

    # 测试PositionManager
    class MockTrade:
        def __init__(self, volume, price):
            from vnpy.trader.constant import Direction, Offset
            self.vt_symbol = "TA.CZCE"
            self.volume = volume
            self.price = price
            self.direction = Direction.LONG
            self.offset = Offset.OPEN

    class MockStrategy:
        pass

    mock_strat = MockStrategy()
    pos_mgr = PositionManager(mock_strat)
    pos_mgr.update_position(MockTrade(100, 6000))
    print(f"  ✓ PositionManager: 正常")
    
    return True


# ==================== 测试多合约 ====================

def test_multi_symbol():
    """测试多合约支持"""
    print("\n" + "=" * 60)
    print("测试 8: 多合约支持")
    print("=" * 60)
    
    from backtest import BacktestingEngine
    from backtest.examples.macd_strategy import MacdStrategy
    from vnpy.trader.constant import Interval
    
    # 生成多合约数据
    ta_bars = generate_test_bars(symbol="TA", count=1000)
    ma_bars = generate_test_bars(symbol="MA", count=1000)
    
    # 创建引擎
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbols=["TA.CZCE", "MA.CZCE"],
        interval=Interval.MINUTE,
        start=datetime(2024, 3, 1),
        end=datetime(2024, 6, 30),
        capital=100000,
    )
    
    # 添加合约配置
    engine.add_contract_setting("TA.CZCE", size=10, pricetick=2, long_rate=0.00005, short_rate=0.00005)
    engine.add_contract_setting("MA.CZCE", size=10, pricetick=1, long_rate=0.00005, short_rate=0.00005)
    
    # 加载数据
    all_bars = {**{b.vt_symbol: b for b in ta_bars}, **{b.vt_symbol: b for b in ma_bars}}
    # 合并
    combined_bars = ta_bars + ma_bars
    engine.load_data(combined_bars)
    
    # 添加策略
    engine.add_strategy(MacdStrategy, setting={"size": 1})
    
    # 运行
    engine.run_backtesting()
    engine.calculate_result()
    stats = engine.calculate_statistics()
    
    print(f"  ✓ 多合约回测: TA + MA, 成交笔数={stats.get('total_trade_count', 0)}")
    
    return True


# ==================== 主函数 ====================

def main():
    print("=" * 60)
    print("VNpy 回测框架 - 完整自测")
    print("=" * 60)
    
    tests = [
        ("EventEngine", test_event_engine),
        ("AlphaLab", test_alpha_lab),
        ("Gateway", test_gateway),
        ("CtaStrategy", test_cta_strategy),
        ("BacktestingEngine", test_backtesting_engine),
        ("ParameterOptimizer", test_optimizer),
        ("StrategyIndicator", test_indicator),
        ("MultiSymbol", test_multi_symbol),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            result = test_func()
            if result:
                passed += 1
                print(f"\n✅ {name}: 通过")
        except Exception as e:
            failed += 1
            print(f"\n❌ {name}: 失败 - {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
