#!/usr/bin/env python3
"""
缠论集成模块
整合现有缠论算法与新的中枢识别、买卖点判断系统
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Tuple, Optional, Any
import json
import sys
import os

# 添加现有缠论算法路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 导入现有缠论算法
try:
    from chan_analysis_system import ChanAnalysisSystem
    from chan_zhongshu_detector import ZhongShuDetector, Segment, Direction
    from chan_trading_system import ChanTradingSystem, TimeFrame, TradeSignal
    print("成功导入缠论模块")
except ImportError as e:
    print(f"导入模块时出错: {e}")
    print("将使用简化实现")


class ChanIntegrationSystem:
    """缠论集成系统"""
    
    def __init__(self, config: Dict = None):
        """
        初始化集成系统
        
        Args:
            config: 配置字典
        """
        self.config = config or {
            'main_timeframe': '30min',
            'analyze_timeframes': ['1min', '5min', '30min', '1h'],
            'min_segments_for_zhongshu': 3,
            'divergence_threshold': 0.7,
            'confidence_threshold': 0.6
        }
        
        # 初始化子系统
        self.analysis_system = ChanAnalysisSystem(level=self.config['main_timeframe'])
        self.zhongshu_detector = ZhongShuDetector(level=self.config['main_timeframe'])
        self.trading_system = ChanTradingSystem(
            main_timeframe=TimeFrame(self.config['main_timeframe'])
        )
        
        self.results = {}
    
    def process_klines(self, klines: pd.DataFrame, 
                       timeframe: str = '30min') -> Dict:
        """
        处理K线数据
        
        Args:
            klines: K线数据
            timeframe: 时间框架
            
        Returns:
            处理结果
        """
        print(f"处理K线数据，时间框架: {timeframe}")
        print(f"K线数量: {len(klines)}")
        
        # 1. 使用现有缠论算法检测笔和线段
        print("1. 检测笔和线段...")
        bis = self.analysis_system.detect_bis(klines)
        segments = self.analysis_system.detect_segments(bis)
        
        # 转换为Segment对象供中枢检测器使用
        chan_segments = self._convert_to_chan_segments(segments)
        
        # 2. 使用中枢检测器识别中枢
        print("2. 识别中枢...")
        zhongshus = self.zhongshu_detector.detect_zhongshu_from_segments(chan_segments)
        
        # 3. 检测买卖点
        print("3. 检测买卖点...")
        buy_sell_points = self.zhongshu_detector.detect_buy_sell_points()
        
        # 4. 生成交易信号
        print("4. 生成交易信号...")
        signals = self.zhongshu_detector.generate_signals(buy_sell_points)
        
        # 5. 综合结果
        result = {
            'timeframe': timeframe,
            'klines_count': len(klines),
            'bis_count': len(bis),
            'segments_count': len(segments),
            'zhongshus_count': len(zhongshus),
            'buy_sell_points_count': len(buy_sell_points),
            'signals_count': len(signals),
            'bis': self.analysis_system.bis[:10],  # 只取前10个
            'segments': self.analysis_system.segments[:10],
            'zhongshus': zhongshus,
            'buy_sell_points': buy_sell_points,
            'signals': signals
        }
        
        self.results[timeframe] = result
        return result
    
    def _convert_to_chan_segments(self, segments: List) -> List[Segment]:
        """
        转换线段格式
        
        Args:
            segments: 分析系统检测到的线段
            
        Returns:
            中枢检测器使用的Segment对象列表
        """
        chan_segments = []
        
        for i, seg in enumerate(segments):
            direction = Direction.UP if seg.direction == 'up' else Direction.DOWN
            
            chan_seg = Segment(
                idx=i,
                start_idx=seg.start_bi_idx,
                end_idx=seg.end_bi_idx,
                start_price=seg.start_price,
                end_price=seg.end_price,
                high=seg.high,
                low=seg.low,
                direction=direction
            )
            chan_segments.append(chan_seg)
        
        return chan_segments
    
    def multi_timeframe_analysis(self, klines_dict: Dict[str, pd.DataFrame]) -> Dict:
        """
        多时间框架分析
        
        Args:
            klines_dict: 各时间框架的K线数据
            
        Returns:
            多时间框架分析结果
        """
        print("开始多时间框架分析...")
        
        results = {}
        for timeframe, klines in klines_dict.items():
            print(f"\n分析时间框架: {timeframe}")
            result = self.process_klines(klines, timeframe)
            results[timeframe] = result
        
        # 综合多时间框架信号
        combined_signals = self._combine_multi_tf_signals(results)
        
        # 生成交易计划
        trading_plan = self._generate_trading_plan(combined_signals)
        
        final_result = {
            'multi_timeframe_results': results,
            'combined_signals': combined_signals,
            'trading_plan': trading_plan,
            'summary': self._generate_summary(results)
        }
        
        self.results = final_result
        return final_result
    
    def _combine_multi_tf_signals(self, results: Dict) -> List[Dict]:
        """
        综合多时间框架信号
        
        Args:
            results: 各时间框架分析结果
            
        Returns:
            综合信号列表
        """
        combined = []
        
        # 收集所有信号
        all_signals = []
        for timeframe, result in results.items():
            if 'signals' in result:
                for signal in result['signals']:
                    signal['source_timeframe'] = timeframe
                    all_signals.append(signal)
        
        # 按信号类型和价格聚类
        signal_groups = {}
        for signal in all_signals:
            key = f"{signal.get('type', 'unknown')}_{signal.get('price', 0):.2f}"
            if key not in signal_groups:
                signal_groups[key] = []
            signal_groups[key].append(signal)
        
        # 生成综合信号
        for key, signals in signal_groups.items():
            if len(signals) >= 2:  # 至少两个时间框架确认
                # 计算平均价格和置信度
                avg_price = np.mean([s.get('price', 0) for s in signals])
                avg_confidence = np.mean([s.get('confidence', 0) for s in signals])
                
                # 时间框架确认越多，置信度越高
                confidence_boost = min(0.2 * len(signals), 0.4)
                final_confidence = min(avg_confidence + confidence_boost, 1.0)
                
                # 获取主要信息
                main_signal = signals[0]
                
                combined_signal = {
                    'type': main_signal.get('type'),
                    'price': avg_price,
                    'confidence': final_confidence,
                    'confirming_timeframes': [s['source_timeframe'] for s in signals],
                    'confirmations_count': len(signals),
                    'description': f"多时间框架确认: {main_signal.get('description', '')}",
                    'divergence': any(s.get('divergence', False) for s in signals),
                    'combined': True
                }
                combined.append(combined_signal)
        
        return combined
    
    def _generate_trading_plan(self, signals: List[Dict]) -> Dict:
        """
        生成交易计划
        
        Args:
            signals: 综合信号列表
            
        Returns:
            交易计划
        """
        if not signals:
            return {'status': 'no_signals', 'plan': []}
        
        # 按置信度排序
        sorted_signals = sorted(signals, key=lambda x: x.get('confidence', 0), reverse=True)
        
        plan = []
        for i, signal in enumerate(sorted_signals[:3]):  # 取前3个
            signal_type = signal.get('type', '')
            price = signal.get('price', 0)
            confidence = signal.get('confidence', 0)
            
            if 'buy' in signal_type:
                action = 'BUY'
                stop_loss = price * 0.98
                take_profit = price * 1.03
            elif 'sell' in signal_type:
                action = 'SELL'
                stop_loss = price * 1.02
                take_profit = price * 0.97
            else:
                continue
            
            trade = {
                'id': i + 1,
                'action': action,
                'entry_price': price,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'confidence': confidence,
                'confirmations': signal.get('confirmations_count', 0),
                'timeframes': signal.get('confirming_timeframes', []),
                'description': signal.get('description', ''),
                'risk_reward_ratio': abs(take_profit - price) / abs(price - stop_loss)
            }
            plan.append(trade)
        
        return {
            'status': 'ready',
            'signals_count': len(signals),
            'plan': plan,
            'recommendation': self._get_recommendation(plan)
        }
    
    def _get_recommendation(self, plan: List[Dict]) -> str:
        """
        获取交易建议
        
        Args:
            plan: 交易计划
            
        Returns:
            建议文本
        """
        if not plan:
            return "无明确交易信号，建议观望"
        
        best_trade = plan[0]
        action = best_trade['action']
        confidence = best_trade['confidence']
        
        if confidence >= 0.8:
            strength = "强烈"
        elif confidence >= 0.6:
            strength = "中等"
        else:
            strength = "谨慎"
        
        return f"{strength}建议{action}，置信度{confidence:.2f}，{best_trade['confirmations']}个时间框架确认"
    
    def _generate_summary(self, results: Dict) -> Dict:
        """
        生成分析摘要
        
        Args:
            results: 多时间框架结果
            
        Returns:
            摘要信息
        """
        summary = {
            'total_timeframes': len(results),
            'total_signals': 0,
            'total_zhongshus': 0,
            'timeframe_details': {}
        }
        
        for timeframe, result in results.items():
            signals_count = result.get('signals_count', 0)
            zhongshus_count = result.get('zhongshus_count', 0)
            
            summary['total_signals'] += signals_count
            summary['total_zhongshus'] += zhongshus_count
            
            summary['timeframe_details'][timeframe] = {
                'signals': signals_count,
                'zhongshus': zhongshus_count,
                'segments': result.get('segments_count', 0),
                'bis': result.get('bis_count', 0)
            }
        
        return summary
    
    def save_results(self, filename: str = 'chan_integration_results.json'):
        """
        保存结果
        
        Args:
            filename: 文件名
        """
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2, default=str)
        
        print(f"结果已保存到: {filename}")
        return filename


# 测试函数
def test_integration_system():
    """测试集成系统"""
    print("=" * 60)
    print("缠论集成系统测试")
    print("=" * 60)
    
    # 创建模拟数据
    np.random.seed(42)
    
    # 生成不同时间框架的模拟K线数据
    klines_dict = {}
    
    timeframes = ['1min', '5min', '30min']
    for tf in timeframes:
        n = 300 if tf == '1min' else 150
        
        # 生成价格序列
        dates = pd.date_range('2026-04-01', periods=n, freq=tf)
        prices = []
        current = 5000
        
        # 模拟趋势和盘整
        for i in range(n):
            if i < 100:
                # 上升趋势
                current += np.random.uniform(-2, 8)
            elif i < 200:
                # 盘整
                current += np.random.uniform(-5, 5)
            else:
                # 下降趋势
                current += np.random.uniform(-8, 2)
            
            current = max(current, 4800)
            prices.append(current)
        
        # 创建K线DataFrame
        klines = pd.DataFrame({
            'datetime': dates,
            'open': prices,
            'high': [p + np.random.uniform(0, 3) for p in prices],
            'low': [p - np.random.uniform(0, 3) for p in prices],
            'close': [p + np.random.uniform(-2, 2) for p in prices],
            'volume': [np.random.uniform(100, 1000) for _ in range(n)]
        })
        
        # 确保 high >= low
        klines['high'] = klines[['open', 'high', 'close']].max(axis=1)
        klines['low'] = klines[['open', 'low', 'close']].min(axis=1)
        
        klines_dict[tf] = klines
    
    # 创建集成系统
    config = {
        'main_timeframe': '30min',
        'analyze_timeframes': timeframes,
        'min_segments_for_zhongshu': 3,
        'divergence_threshold': 0.7,
        'confidence_threshold': 0.6
    }
    
    system = ChanIntegrationSystem(config)
    
    # 执行多时间框架分析
    print("执行多时间框架分析...")
    results = system.multi_timeframe_analysis(klines_dict)
    
    # 打印摘要
    summary = results['summary']
    print(f"\n分析摘要:")
    print(f"分析的时间框架数: {summary['total_timeframes']}")
    print(f"总信号数: {summary['total_signals']}")
    print(f"总中枢数: {summary['total_zhongshus']}")
    
    print("\n各时间框架详情:")
    for tf, details in summary['timeframe_details'].items():
        print(f"  {tf}: {details['signals']}信号, {details['zhongshus']}中枢, "
              f"{details['segments']}线段, {details['bis']}笔")
    
    # 打印交易计划
    trading_plan = results['trading_plan']
    if trading_plan['status'] == 'ready':
        print(f"\n交易计划 ({len(trading_plan['plan'])}个建议):")
        for trade in trading_plan['plan']:
            print(f"  {trade['id']}. {trade['action']} @ {trade['entry_price']:.2f}, "
                  f"止损: {trade['stop_loss']:.2f}, 止盈: {trade['take_profit']:.2f}, "
                  f"置信度: {trade['confidence']:.2f}")
        
        print(f"\n建议: {trading_plan['recommendation']}")
    
    # 保存结果
    system.save_results()
    
    return system


if __name__ == "__main__":
    # 运行测试
    system = test_integration_system()
    
    print("\n" + "=" * 60)
    print("缠论集成系统测试完成")
    print("=" * 60)