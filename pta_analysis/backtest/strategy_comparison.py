#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多策略对比分析模块
"""

from typing import List, Dict, Any, Optional
from .backtest_engine import BacktestEngine
from .strategy_base import StrategyBase


class StrategyComparator:
    """多策略对比分析器"""

    def __init__(self, initial_balance: float = 100000.0, 
                 commission_rate: float = 0.0001):
        self.initial_balance = initial_balance
        self.commission_rate = commission_rate
        self.results: Dict[str, Dict[str, Any]] = {}

    def run_single_strategy(self, strategy: StrategyBase, 
                           data: List[Dict[str, Any]],
                           strategy_name: str,
                           params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        运行单个策略回测
        """
        engine = BacktestEngine(
            initial_balance=self.initial_balance,
            commission_rate=self.commission_rate
        )
        
        result = engine.run(strategy, data)
        result['strategy_name'] = strategy_name
        result['params'] = params or {}
        
        self.results[strategy_name] = result
        return result

    def run_multiple_strategies(self,
                               strategies: Dict[str, StrategyBase],
                               data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        运行多个策略并对比
        :param strategies: 策略名字典 {策略名: 策略实例}
        :param data: K线数据
        :return: 对比结果
        """
        self.results = {}
        
        for name, strategy in strategies.items():
            try:
                result = self.run_single_strategy(strategy, data, name)
                print(f"[策略对比] {name}: 收益率 {result['statistics'].get('total_return', 0):.2f}%")
            except Exception as e:
                print(f"[策略对比] {name} 执行失败: {e}")
                self.results[name] = {'success': False, 'error': str(e)}
        
        return self.compare()

    def compare(self) -> Dict[str, Any]:
        """
        对比所有策略结果
        """
        valid_results = {k: v for k, v in self.results.items() 
                        if v.get('success', False)}
        
        if not valid_results:
            return {'success': False, 'error': '没有成功的策略结果'}
        
        # 按总收益率排序
        sorted_results = sorted(
            valid_results.items(),
            key=lambda x: x[1]['statistics'].get('total_return', 0),
            reverse=True
        )
        
        # 生成对比表格数据
        comparison_data = []
        for name, result in sorted_results:
            stats = result['statistics']
            comparison_data.append({
                'strategy': name,
                'total_return': stats.get('total_return', 0),
                'win_rate': stats.get('win_rate', 0),
                'profit_factor': stats.get('profit_factor', 0),
                'max_drawdown': stats.get('max_drawdown', 0),
                'sharpe_ratio': stats.get('sharpe_ratio', 0),
                'sortino_ratio': stats.get('sortino_ratio', 0),
                'calmar_ratio': stats.get('calmar_ratio', 0),
                'total_trades': stats.get('total_trades', 0),
                'total_pnl': stats.get('total_pnl', 0),
                'final_balance': stats.get('final_balance', 0),
            })
        
        # 计算排名
        metrics = ['total_return', 'win_rate', 'profit_factor', 
                   'sharpe_ratio', 'sortino_ratio', 'calmar_ratio']
        
        for metric in metrics:
            values = [d[metric] for d in comparison_data]
            if metric in ['max_drawdown']:  # 回撤越小越好
                sorted_values = sorted(values)
                for d in comparison_data:
                    d[f'{metric}_rank'] = sorted_values.index(d[metric]) + 1
            else:
                sorted_values = sorted(values, reverse=True)
                for d in comparison_data:
                    d[f'{metric}_rank'] = sorted_values.index(d[metric]) + 1
        
        # 综合排名（平均排名）
        for d in comparison_data:
            ranks = [d.get(f'{m}_rank', 0) for m in metrics]
            d['avg_rank'] = sum(ranks) / len(ranks) if ranks else 0
        
        # 重新按综合排名排序
        comparison_data.sort(key=lambda x: x['avg_rank'])
        
        return {
            'success': True,
            'total_strategies': len(valid_results),
            'comparison': comparison_data,
            'best_by_return': sorted_results[0][0] if sorted_results else None,
            'best_by_sharpe': max(valid_results.items(), 
                                   key=lambda x: x[1]['statistics'].get('sharpe_ratio', 0))[0],
            'best_by_drawdown': min(valid_results.items(),
                                    key=lambda x: x[1]['statistics'].get('max_drawdown', 999))[0],
            'details': valid_results
        }


class StrategyMultiPeriod:
    """多周期策略对比"""

    def __init__(self, initial_balance: float = 100000.0):
        self.initial_balance = initial_balance

    def run(self, strategy_class, data_by_period: Dict[str, List[Dict[str, Any]]],
            params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        在多个周期上运行同一策略
        :param strategy_class: 策略类
        :param data_by_period: {周期名: K线数据} 的字典
        :param params: 策略参数
        :return: 多周期结果
        """
        results = {}
        
        for period, data in data_by_period.items():
            try:
                strategy = strategy_class(**(params or {}))
                engine = BacktestEngine(initial_balance=self.initial_balance)
                result = engine.run(strategy, data)
                results[period] = {
                    'success': True,
                    'data_count': len(data),
                    'statistics': result['statistics']
                }
            except Exception as e:
                results[period] = {'success': False, 'error': str(e)}
        
        return {
            'success': True,
            'periods': list(data_by_period.keys()),
            'results': results
        }
