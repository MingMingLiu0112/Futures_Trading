#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
事件引擎 - VNpy事件驱动架构的实现

事件引擎是VNpy的核心,实现了发布-订阅模式,用于解耦各个模块。

用法:
```python
from backtest.event import EventEngine, Event

# 创建事件引擎
ee = EventEngine()

# 注册事件处理函数
def on_bar(bar):
    print(f"收到K线: {bar.datetime}")

ee.register(Event.EVENT_BAR, on_bar)

# 触发事件
bar = {...}
ee.put(Event(EVENT_BAR, bar))
```
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from queue import Empty, Queue
from threading import Thread
from typing import Any, Callable, Dict, List, Optional, Set
from enum import Enum


class EventType(Enum):
    """事件类型"""
    # 行情事件
    BAR = "bar"                    # K线事件
    TICK = "tick"                  # Tick事件
    
    # 交易事件
    ORDER = "order"                # 订单事件
    TRADE = "trade"                # 成交事件
    POSITION = "position"          # 持仓事件
    ACCOUNT = "account"            # 账户事件
    
    # 策略事件
    STRATEGY_INIT = "strategy_init"
    STRATEGY_START = "strategy_start"
    STRATEGY_STOP = "strategy_stop"
    
    # 系统事件
    TIMER = "timer"                # 定时器事件
    LOG = "log"                    # 日志事件
    ERROR = "error"                # 错误事件


@dataclass
class Event:
    """事件对象"""
    type: str
    data: Any = None
    datetime: datetime = None
    
    def __post_init__(self):
        if self.datetime is None:
            self.datetime = datetime.now()


class EventHandler:
    """事件处理器基类"""
    
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)
    
    def register(self, event_type: str, handler: Callable) -> None:
        """注册事件处理函数"""
        self._handlers[event_type].append(handler)
    
    def unregister(self, event_type: str, handler: Callable) -> None:
        """注销事件处理函数"""
        if handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)
    
    def unregister_all(self, event_type: str) -> None:
        """注销所有处理函数"""
        self._handlers[event_type].clear()
    
    def _call_handlers(self, event: Event) -> None:
        """调用所有处理函数"""
        for handler in self._handlers[event.type]:
            try:
                handler(event)
            except Exception as e:
                print(f"事件处理错误: {event.type}, {e}")


class EventEngine:
    """
    事件引擎
    
    VNpy的核心组件,实现事件驱动架构:
    - 事件队列: 接收所有事件
    - 工作线程: 处理队列中的事件
    - 处理器注册: 各个模块注册感兴趣的事件
    """
    
    def __init__(self, timer_interval: int = 1):
        """
        初始化事件引擎
        
        Args:
            timer_interval: 定时器间隔(秒)
        """
        self._queue: Queue = Queue()
        self._active: bool = False
        self._thread: Optional[Thread] = None
        self._timer_interval = timer_interval
        
        # 事件处理器
        self._handlers: Dict[str, Set[Callable]] = defaultdict(set)
        
        # 统计
        self._event_count: int = 0
        self._last_timer_time: datetime = datetime.now()
    
    def register(self, event_type: str, handler: Callable) -> None:
        """
        注册事件处理器
        
        Args:
            event_type: 事件类型
            handler: 处理函数,签名为 handler(event: Event)
        """
        handler_set = self._handlers.get(event_type, set())
        handler_set.add(handler)
        self._handlers[event_type] = handler_set
    
    def unregister(self, event_type: str, handler: Callable) -> None:
        """注销事件处理器"""
        if event_type in self._handlers:
            self._handlers[event_type].discard(handler)
    
    def put(self, event: Event) -> None:
        """
        放入事件到队列
        
        Args:
            event: 事件对象
        """
        self._queue.put(event)
        self._event_count += 1
    
    def put_bar(self, bar) -> None:
        """快捷方法: 放入K线事件"""
        self.put(Event(EventType.BAR.value, bar))
    
    def put_tick(self, tick) -> None:
        """快捷方法: 放入Tick事件"""
        self.put(Event(EventType.TICK.value, tick))
    
    def put_trade(self, trade) -> None:
        """快捷方法: 放入成交事件"""
        self.put(Event(EventType.TRADE.value, trade))
    
    def put_order(self, order) -> None:
        """快捷方法: 放入订单事件"""
        self.put(Event(EventType.ORDER.value, order))
    
    def start(self) -> None:
        """启动事件引擎"""
        if self._active:
            return
        
        self._active = True
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()
        print("事件引擎已启动")
    
    def stop(self) -> None:
        """停止事件引擎"""
        self._active = False
        
        if self._thread:
            self._thread.join()
            self._thread = None
        
        print("事件引擎已停止")
    
    def _run(self) -> None:
        """事件处理循环"""
        while self._active:
            try:
                # 获取事件,带超时以便检查停止标志
                event = self._queue.get(timeout=0.1)
                
                # 处理事件
                self._process(event)
                
            except Empty:
                # 超时,继续循环
                pass
            except Exception as e:
                print(f"事件处理错误: {e}")
    
    def _process(self, event: Event) -> None:
        """处理单个事件"""
        if event.type in self._handlers:
            for handler in self._handlers[event.type]:
                try:
                    handler(event.data)
                except Exception as e:
                    print(f"处理器执行错误 [{event.type}]: {e}")
    
    @property
    def event_count(self) -> int:
        """事件总数"""
        return self._event_count
    
    @property
    def is_active(self) -> bool:
        """是否运行中"""
        return self._active


class StrategyEventHandler(EventHandler):
    """策略事件处理器"""
    
    def __init__(self, strategy):
        super().__init__()
        self.strategy = strategy
    
    def on_bar(self, bar) -> None:
        """处理K线事件"""
        if hasattr(self.strategy, 'on_bar'):
            self.strategy.on_bar(bar)
    
    def on_tick(self, tick) -> None:
        """处理Tick事件"""
        if hasattr(self.strategy, 'on_tick'):
            self.strategy.on_tick(tick)
    
    def on_trade(self, trade) -> None:
        """处理成交事件"""
        if hasattr(self.strategy, 'on_trade'):
            self.strategy.on_trade(trade)
    
    def on_order(self, order) -> None:
        """处理订单事件"""
        if hasattr(self.strategy, 'on_order'):
            self.strategy.on_order(order)


class LogEvent:
    """日志事件"""
    
    def __init__(self, level: str, msg: str, strategy_name: str = ""):
        self.level = level
        self.msg = msg
        self.strategy_name = strategy_name
        self.datetime = datetime.now()
    
    def __str__(self):
        if self.strategy_name:
            return f"[{self.level}] {self.datetime} {self.strategy_name}: {self.msg}"
        return f"[{self.level}] {self.datetime}: {self.msg}"


def print_log_handler(log_event: LogEvent) -> None:
    """打印日志的处理器"""
    print(str(log_event))
