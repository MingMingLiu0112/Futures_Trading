#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
参数优化模块
提供网格搜索和参数优化功能
"""

from typing import List, Dict, Any, Callable, Optional, Tuple
from itertools import product
import copy


class ParameterGrid:
    """参数网格定义"""
    
    def __init__(self, params: Dict[str, List[Any]]):
        """
        初始化参数网格
        :param params: 参数名到参数值列表的映射
                      例如: {'fast_period': [12, 26], 'slow_period': [9, 12]}
        """
        self.params = params
        self.param_names = list(params.keys())
        self.param_values = list(params.values())
    
    def __iter__(self):
        """遍历所有参数组合"""
        for values in product(*self.param_values):
            yield dict(zip(self.param_names, values))
    
    def __len__(self) -> int:
        """返回参数组合总数"""
        result = 1
        for values in self.param_values:
            result *= len(values)
        return result


class GridOptimizer:
    """网格搜索优化器"""
    
    def __init__(self, 
                 objective: str = 'total_return',
                 mode: str = 'max',
                 top_n: int = 5):
        """
        初始化优化器
        :param objective: 优化目标指标（支持任何 statistics 中的字段）
        :param mode: 优化模式，'max' 或 'min'
        :param top_n: 返回前N个最佳参数组合
        """
        self.objective = objective
        self.mode = mode
        self.top_n = top_n
        self.results: List[Dict[str, Any]] = []
    
    def optimize(self, 
                 backtest_func: Callable,
                 param_grid: ParameterGrid,
                 strategy_class,
                 data: List[Dict[str, Any]],
                 fixed_params: Optional[Dict[str, Any]] = None,
                 initial_balance: float = 100000.0) -> Dict[str, Any]:
        """
        执行网格搜索优化
        :param backtest_func: 回测函数，签名为 (strategy_class, data, params, initial_balance) -> dict
        :param param_grid: 参数网格
        :param strategy_class: 策略类
        :param data: K线数据
        :param fixed_params: 固定参数（不参与优化）
        :param initial_balance: 初始资金
        :return: 优化结果
        """
        self.results = []
        total_combinations = len(param_grid)
        
        print(f"[参数优化] 开始网格搜索，共 {total_combinations} 种参数组合...")
        
        fixed_params = fixed_params or {}
        
        for i, params in enumerate(param_grid):
            # 合并固定参数和可变参数
            full_params = {**fixed_params, **params}
            
            try:
                # 运行回测
                result = backtest_func(strategy_class, data, full_params, initial_balance)
                
                # 提取目标指标
                stats = result.get('statistics', {})
                objective_value = stats.get(self.objective, 0.0)
                
                # 保存结果
                self.results.append({
                    'params': params,
                    'full_params': full_params,
                    'objective': objective_value,
                    'statistics': stats,
                    'total_trades': stats.get('total_trades', 0),
                    'win_rate': stats.get('win_rate', 0),
                    'max_drawdown': stats.get('max_drawdown', 0),
                    'sharpe_ratio': stats.get('sharpe_ratio', 0),
                    'final_balance': stats.get('final_balance', initial_balance),
                    'result': result
                })
                
                # 进度显示
                if (i + 1) % 10 == 0 or (i + 1) == total_combinations:
                    print(f"[参数优化] 进度: {i + 1}/{total_combinations}")
                    
            except Exception as e:
                print(f"[参数优化] 参数组合 {params} 执行失败: {e}")
                continue
        
        # 排序
        self.results = self._sort_results()
        
        # 生成报告
        return self._generate_report()
    
    def _sort_results(self) -> List[Dict[str, Any]]:
        """对结果排序"""
        reverse = (self.mode == 'max')
        return sorted(self.results, key=lambda x: x['objective'], reverse=reverse)
    
    def _generate_report(self) -> Dict[str, Any]:
        """生成优化报告"""
        if not self.results:
            return {
                'success': False,
                'error': '没有成功的参数组合',
                'total_combinations': 0,
                'best_params': None,
                'results': []
            }
        
        best = self.results[0]
        top_results = self.results[:self.top_n]
        
        return {
            'success': True,
            'objective': self.objective,
            'mode': self.mode,
            'total_combinations': len(self.results),
            'best_params': best['params'],
            'best_objective': best['objective'],
            'best_statistics': best['statistics'],
            'top_params': [r['params'] for r in top_results],
            'top_objectives': [r['objective'] for r in top_results],
            'results': top_results
        }


def run_backtest_for_optimization(strategy_class,
                                   data: List[Dict[str, Any]],
                                   params: Dict[str, Any],
                                   initial_balance: float = 100000.0) -> Dict[str, Any]:
    """
    用于参数优化的回测函数
    被 GridOptimizer 调用
    """
    from .backtest_engine import BacktestEngine

    # 创建策略实例 - 使用 params 作为单个参数传入
    strategy = strategy_class(params=params)

    # 创建回测引擎
    engine = BacktestEngine(initial_balance=initial_balance)

    # 运行回测
    result = engine.run(strategy, data)

    return result


class WalkForwardOptimizer:
    """Walk-Forward 优化器（样本内优化 + 样本外验证）"""
    
    def __init__(self,
                 train_ratio: float = 0.7,
                 n_splits: int = 3,
                 objective: str = 'total_return'):
        """
        初始化 Walk-Forward 优化器
        :param train_ratio: 训练集比例
        :param n_splits: 分割次数
        :param objective: 优化目标
        """
        self.train_ratio = train_ratio
        self.n_splits = n_splits
        self.objective = objective
    
    def optimize(self,
                backtest_func: Callable,
                param_grid: ParameterGrid,
                strategy_class,
                data: List[Dict[str, Any]],
                fixed_params: Optional[Dict[str, Any]] = None,
                initial_balance: float = 100000.0) -> Dict[str, Any]:
        """
        执行 Walk-Forward 优化
        """
        n = len(data)
        train_size = int(n * self.train_ratio)
        
        results = []
        
        for i in range(self.n_splits):
            # 计算训练集和测试集范围
            train_end = train_size + int((n - train_size) * i / self.n_splits)
            test_start = train_end
            test_end = train_end + int((n - train_size) / self.n_splits)
            
            if test_end > n:
                test_end = n
            
            train_data = data[:train_end]
            test_data = data[test_start:test_end]
            
            print(f"[Walk-Forward] Split {i+1}/{self.n_splits}: "
                  f"Train=[0:{train_end}], Test=[{test_start}:{test_end}]")
            
            # 在训练集上优化
            optimizer = GridOptimizer(objective=self.objective, mode='max', top_n=1)
            train_result = optimizer.optimize(
                backtest_func, param_grid, strategy_class, train_data,
                fixed_params, initial_balance
            )
            
            if not train_result['success']:
                continue
            
            # 使用最佳参数在测试集上验证
            best_params = train_result['best_params']
            full_params = {**(fixed_params or {}), **best_params}
            
            test_backtest = backtest_func(
                strategy_class, test_data, full_params, initial_balance
            )
            
            train_stats = train_result['best_statistics']
            test_stats = test_backtest.get('statistics', {})
            
            results.append({
                'split': i + 1,
                'train_params': best_params,
                'train_stats': train_stats,
                'test_stats': test_stats,
                'train_objective': train_stats.get(self.objective, 0),
                'test_objective': test_stats.get(self.objective, 0),
            })
        
        # 计算平均表现
        if results:
            avg_train = sum(r['train_objective'] for r in results) / len(results)
            avg_test = sum(r['test_objective'] for r in results) / len(results)
            
            return {
                'success': True,
                'n_splits': self.n_splits,
                'avg_train_objective': avg_train,
                'avg_test_objective': avg_test,
                'stability': avg_test / avg_train if avg_train != 0 else 0,
                'results': results
            }
        
        return {'success': False, 'error': 'No valid results'}
