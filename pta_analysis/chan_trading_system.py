#!/usr/bin/env python3
"""
缠论交易信号生成系统
整合：中枢识别 + 买卖点判断 + 背驰检测 + 信号生成
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
import json
import warnings
warnings.filterwarnings('ignore')


class TimeFrame(Enum):
    """时间框架枚举"""
    M1 = "1min"
    M5 = "5min"
    M30 = "30min"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


class TradeSignal:
    """交易信号类"""
    
    def __init__(self, signal_type: str, price: float, time_idx: int,
                 confidence: float, timeframe: TimeFrame,
                 description: str, divergence: bool = False,
                 zhongshu_idx: Optional[int] = None):
        self.signal_type = signal_type  # buy/sell
        self.price = price
        self.time_idx = time_idx
        self.confidence = confidence  # 0-1
        self.timeframe = timeframe
        self.description = description
        self.divergence = divergence
        self.zhongshu_idx = zhongshu_idx
        self.timestamp = pd.Timestamp.now()
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'signal_type': self.signal_type,
            'price': self.price,
            'time_idx': self.time_idx,
            'confidence': self.confidence,
            'timeframe': self.timeframe.value,
            'description': self.description,
            'divergence': self.divergence,
            'zhongshu_idx': self.zhongshu_idx,
            'timestamp': str(self.timestamp)
        }
    
    def __repr__(self):
        return (f"TradeSignal({self.signal_type.upper()} @ {self.price:.2f}, "
                f"conf={self.confidence:.2f}, {self.description})")


class ChanTradingSystem:
    """缠论交易系统"""
    
    def __init__(self, main_timeframe: TimeFrame = TimeFrame.M30):
        """
        初始化交易系统
        
        Args:
            main_timeframe: 主分析时间框架
        """
        self.main_timeframe = main_timeframe
        self.signals: List[TradeSignal] = []
        self.analysis_results = {}
        
        # 多时间框架分析
        self.timeframes = [
            TimeFrame.M1,
            TimeFrame.M5,
            TimeFrame.M30,
            TimeFrame.H1,
            TimeFrame.H4
        ]
    
    def analyze_multi_timeframe(self, klines_dict: Dict[TimeFrame, pd.DataFrame]) -> Dict:
        """
        多时间框架分析
        
        Args:
            klines_dict: 各时间框架的K线数据
            
        Returns:
            多时间框架分析结果
        """
        results = {}
        
        for tf in self.timeframes:
            if tf in klines_dict:
                print(f"分析时间框架: {tf.value}")
                result = self._analyze_single_timeframe(klines_dict[tf], tf)
                results[tf.value] = result
        
        # 综合多时间框架信号
        combined_signals = self._combine_signals(results)
        
        self.analysis_results = {
            'timeframe_results': results,
            'combined_signals': combined_signals,
            'main_timeframe': self.main_timeframe.value
        }
        
        return self.analysis_results
    
    def _analyze_single_timeframe(self, klines: pd.DataFrame, 
                                  timeframe: TimeFrame) -> Dict:
        """
        单时间框架分析
        
        Args:
            klines: K线数据
            timeframe: 时间框架
            
        Returns:
            分析结果
        """
        # 这里调用之前实现的分析模块
        # 简化实现：模拟分析结果
        
        # 模拟检测到的中枢
        n = len(klines)
        zhongshus = []
        
        # 模拟一些中枢
        if n > 50:
            # 模拟第一个中枢
            zhongshus.append({
                'idx': 0,
                'gg': klines['high'].iloc[10:30].max(),
                'dd': klines['low'].iloc[10:30].min(),
                'zg': (klines['high'].iloc[10:30].max() + klines['low'].iloc[10:30].min()) / 2,
                'direction': 'up',
                'type': 'trend',
                'segments_count': 3
            })
        
        if n > 100:
            # 模拟第二个中枢
            zhongshus.append({
                'idx': 1,
                'gg': klines['high'].iloc[60:80].max(),
                'dd': klines['low'].iloc[60:80].min(),
                'zg': (klines['high'].iloc[60:80].max() + klines['low'].iloc[60:80].min()) / 2,
                'direction': 'down',
                'type': 'consolidation',
                'segments_count': 4
            })
        
        # 模拟买卖点
        buy_sell_points = []
        
        if zhongshus:
            # 模拟第一类买卖点
            for zs in zhongshus:
                if zs['direction'] == 'up':
                    # 第一类卖点
                    point = {
                        'type': 'first_sell',
                        'price': zs['gg'] * 1.02,  # 略高于中枢高点
                        'time_idx': 40 if zs['idx'] == 0 else 90,
                        'zhongshu_idx': zs['idx'],
                        'description': f"第一类卖点：上升趋势背驰",
                        'confidence': 0.75,
                        'divergence': True
                    }
                    buy_sell_points.append(point)
                else:
                    # 第一类买点
                    point = {
                        'type': 'first_buy',
                        'price': zs['dd'] * 0.98,  # 略低于中枢低点
                        'time_idx': 40 if zs['idx'] == 0 else 90,
                        'zhongshu_idx': zs['idx'],
                        'description': f"第一类买点：下降趋势背驰",
                        'confidence': 0.70,
                        'divergence': True
                    }
                    buy_sell_points.append(point)
        
        # 生成交易信号
        signals = []
        for point in buy_sell_points:
            signal_type = 'buy' if 'buy' in point['type'] else 'sell'
            signal = TradeSignal(
                signal_type=signal_type,
                price=point['price'],
                time_idx=point['time_idx'],
                confidence=point['confidence'],
                timeframe=timeframe,
                description=point['description'],
                divergence=point.get('divergence', False),
                zhongshu_idx=point.get('zhongshu_idx')
            )
            signals.append(signal)
            self.signals.append(signal)
        
        result = {
            'timeframe': timeframe.value,
            'klines_count': len(klines),
            'zhongshus_count': len(zhongshus),
            'buy_sell_points_count': len(buy_sell_points),
            'signals_count': len(signals),
            'zhongshus': zhongshus,
            'buy_sell_points': buy_sell_points,
            'signals': [s.to_dict() for s in signals]
        }
        
        return result
    
    def _combine_signals(self, timeframe_results: Dict) -> List[Dict]:
        """
        综合多时间框架信号
        
        Args:
            timeframe_results: 各时间框架分析结果
            
        Returns:
            综合信号列表
        """
        combined = []
        
        # 收集所有信号
        all_signals = []
        for tf, result in timeframe_results.items():
            if 'signals' in result:
                for signal in result['signals']:
                    signal['source_timeframe'] = tf
                    all_signals.append(signal)
        
        # 按价格和时间聚类信号
        if not all_signals:
            return combined
        
        # 简化：直接返回所有信号
        for signal in all_signals:
            # 计算综合置信度（考虑多时间框架确认）
            if signal['source_timeframe'] == self.main_timeframe.value:
                confidence = signal['confidence'] * 1.2  # 主时间框架权重更高
            else:
                confidence = signal['confidence'] * 0.8
            
            confidence = min(confidence, 1.0)  # 限制在0-1
            
            combined_signal = {
                'signal_type': signal['signal_type'],
                'price': signal['price'],
                'confidence': confidence,
                'source_timeframes': [signal['source_timeframe']],
                'description': signal['description'],
                'divergence': signal.get('divergence', False),
                'combined': True
            }
            combined.append(combined_signal)
        
        return combined
    
    def generate_trading_plan(self) -> Dict:
        """
        生成交易计划
        
        Returns:
            交易计划
        """
        if not self.signals:
            return {'status': 'no_signals', 'plan': []}
        
        # 按置信度排序
        sorted_signals = sorted(self.signals, key=lambda x: x.confidence, reverse=True)
        
        # 生成交易计划
        plan = []
        for signal in sorted_signals[:5]:  # 取前5个最高置信度信号
            entry_price = signal.price
            stop_loss = entry_price * 0.98 if signal.signal_type == 'buy' else entry_price * 1.02
            take_profit = entry_price * 1.03 if signal.signal_type == 'buy' else entry_price * 0.97
            
            trade = {
                'action': signal.signal_type.upper(),
                'entry_price': entry_price,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'confidence': signal.confidence,
                'timeframe': signal.timeframe.value,
                'description': signal.description,
                'risk_reward_ratio': abs(take_profit - entry_price) / abs(entry_price - stop_loss)
            }
            plan.append(trade)
        
        return {
            'status': 'ready',
            'signals_count': len(self.signals),
            'plan': plan,
            'generated_at': str(pd.Timestamp.now())
        }
    
    def save_results(self, filename: str = 'chan_trading_results.json'):
        """
        保存分析结果
        
        Args:
            filename: 文件名
        """
        results = {
            'analysis_results': self.analysis_results,
            'signals': [s.to_dict() for s in self.signals],
            'trading_plan': self.generate_trading_plan(),
            'system_info': {
                'main_timeframe': self.main_timeframe.value,
                'timeframes_analyzed': [tf.value for tf in self.timeframes],
                'version': '1.0.0'
            }
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        
        print(f"结果已保存到: {filename}")
        return filename


# 测试函数
def test_trading_system():
    """测试交易系统"""
    print("=" * 60)
    print("缠论交易信号生成系统测试")
    print("=" * 60)
    
    # 创建模拟数据
    np.random.seed(42)
    
    # 生成不同时间框架的模拟K线数据
    klines_dict = {}
    
    for tf in [TimeFrame.M1, TimeFrame.M5, TimeFrame.M30, TimeFrame.H1]:
        n = 200 if tf == TimeFrame.M1 else 100
        
        dates = pd.date_range('2026-04-01', periods=n, freq=tf.value)
        prices = []
        current = 5000
        
        for i in range(n):
            # 模拟价格波动
            if i % 50 < 25:
                current += np.random.uniform(-10, 20)
            else:
                current += np.random.uniform(-20, 10)
            
            current = max(current, 4800)
            prices.append(current)
        
        # 创建K线DataFrame
        klines = pd.DataFrame({
            'datetime': dates,
            'open': prices,
            'high': [p + np.random.uniform(0, 5) for p in prices],
            'low': [p - np.random.uniform(0, 5) for p in prices],
            'close': [p + np.random.uniform(-3, 3) for p in prices],
            'volume': [np.random.uniform(100, 1000) for _ in range(n)]
        })
        
        # 确保 high >= low
        klines['high'] = klines[['open', 'high', 'close']].max(axis=1)
        klines['low'] = klines[['open', 'low', 'close']].min(axis=1)
        
        klines_dict[tf] = klines
    
    # 创建交易系统
    system = ChanTradingSystem(main_timeframe=TimeFrame.M30)
    
    # 执行多时间框架分析
    print("执行多时间框架分析...")
    results = system.analyze_multi_timeframe(klines_dict)
    
    # 打印结果摘要
    print(f"\n分析完成!")
    print(f"分析的时间框架: {[tf for tf in results['timeframe_results'].keys()]}")
    
    total_signals = 0
    for tf, result in results['timeframe_results'].items():
        signals_count = result.get('signals_count', 0)
        total_signals += signals_count
        print(f"  {tf}: {signals_count} 个信号")
    
    print(f"总信号数: {total_signals}")
    
    # 生成交易计划
    print("\n生成交易计划...")
    trading_plan = system.generate_trading_plan()
    
    if trading_plan['status'] == 'ready':
        print(f"交易计划包含 {len(trading_plan['plan'])} 个交易建议:")
        for i, trade in enumerate(trading_plan['plan']):
            print(f"  {i+1}. {trade['action']} @ {trade['entry_price']:.2f}, "
                  f"止损: {trade['stop_loss']:.2f}, 止盈: {trade['take_profit']:.2f}, "
                  f"置信度: {trade['confidence']:.2f}")
    
    # 保存结果
    system.save_results()
    
    return system


if __name__ == "__main__":
    # 运行测试
    system = test_trading_system()
    
    print("\n" + "=" * 60)
    print("缠论交易系统测试完成")
    print("=" * 60)