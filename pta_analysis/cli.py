#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
命令行界面工具
提供交互式命令行操作
"""

import argparse
import sys
import os
from typing import Optional

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import TradingSystem
from utils.logger import setup_logger


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        prog='trading-cli',
        description='期货交易辅助系统命令行工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 采集数据
  trading-cli --collect --symbol TEST
  
  # 运行MACD策略回测
  trading-cli --backtest macd --symbol TEST
  
  # 分析数据（模式识别+缠论分析）
  trading-cli --analyze --symbol TEST
  
  # 查看账户状态
  trading-cli --status
  
  # 查看支持的策略
  trading-cli --list-strategies
  
  # 运行多个策略回测并比较
  trading-cli --compare macd ma rsi --symbol TEST
        """
    )
    
    # 主要操作
    parser.add_argument('--collect', action='store_true', help='采集数据')
    parser.add_argument('--backtest', type=str, help='运行回测策略 (macd/ma/kdj/breakout/rsi/bollinger/atr)')
    parser.add_argument('--analyze', action='store_true', help='分析数据（模式识别+缠论分析）')
    parser.add_argument('--status', action='store_true', help='查看账户状态')
    parser.add_argument('--list-strategies', action='store_true', help='列出支持的策略')
    parser.add_argument('--compare', nargs='+', help='比较多个策略')
    
    # 参数
    parser.add_argument('--symbol', type=str, default='TEST', help='合约代码')
    parser.add_argument('--log-level', type=str, default='INFO', help='日志级别 (DEBUG/INFO/WARNING/ERROR)')
    parser.add_argument('--log-file', type=str, help='日志文件路径')
    
    args = parser.parse_args()
    
    # 配置日志
    setup_logger(
        name='trading_cli',
        log_level=args.log_level,
        log_file=args.log_file,
        console_output=True
    )
    
    # 创建交易系统
    system = TradingSystem()
    
    if args.list_strategies:
        print("支持的策略列表:")
        strategies = ['macd', 'ma', 'kdj', 'breakout', 'rsi', 'bollinger', 'atr']
        descriptions = {
            'macd': 'MACD交叉策略 - 基于MACD指标的金叉/死叉信号',
            'ma': '均线交叉策略 - 基于短期/长期均线交叉',
            'kdj': 'KDJ策略 - 基于随机指标的超买超卖信号',
            'breakout': '突破策略 - 基于价格突破的趋势跟随',
            'rsi': 'RSI策略 - 基于相对强弱指标的超买超卖',
            'bollinger': '布林带策略 - 基于布林带通道突破',
            'atr': 'ATR策略 - 基于平均真实波动幅度的突破'
        }
        for strategy in strategies:
            print(f"  {strategy:12} - {descriptions[strategy]}")
        return
    
    if args.collect:
        print(f"正在采集 {args.symbol} 的数据...")
        data = system.collect_data(args.symbol)
        if data:
            processed = system.process_data(data)
            system.store_data(processed)
        print("数据采集完成！")
        return
    
    if args.backtest:
        strategy_name = args.backtest.lower()
        print(f"正在运行 {strategy_name} 策略回测...")
        data = system.load_data(args.symbol)
        if data:
            result = system.run_backtest(strategy_name, data)
            if result:
                print("\n回测完成！")
        else:
            print("没有找到数据，请先采集数据。")
        return
    
    if args.analyze:
        print(f"正在分析 {args.symbol} 的数据...")
        data = system.load_data(args.symbol)
        if data:
            print("\n=== K线模式识别 ===")
            system.analyze_patterns(data)
            print("\n=== 缠论分析 ===")
            system.analyze_chan(data)
        else:
            print("没有找到数据，请先采集数据。")
        return
    
    if args.status:
        print("=== 账户状态 ===")
        system.print_account_status()
        return
    
    if args.compare:
        print(f"正在比较策略: {', '.join(args.compare)}")
        data = system.load_data(args.symbol)
        if not data:
            print("没有找到数据，请先采集数据。")
            return
        
        results = []
        for strategy_name in args.compare:
            print(f"\n运行 {strategy_name} 策略...")
            result = system.run_backtest(strategy_name.lower(), data)
            if result:
                results.append({
                    'strategy': strategy_name,
                    'total_trades': result.get('total_trades', 0),
                    'win_rate': result.get('win_rate', 0),
                    'total_pnl': result.get('total_pnl', 0),
                    'max_drawdown': result.get('max_drawdown', 0),
                    'sharpe_ratio': result.get('sharpe_ratio', 0),
                    'profit_factor': result.get('profit_factor', 0)
                })
        
        # 打印比较结果
        print("\n" + "="*80)
        print("策略比较结果")
        print("="*80)
        print(f"{'策略':<12} {'交易数':<8} {'胜率':<8} {'总盈亏':<12} {'最大回撤':<10} {'夏普比率':<10} {'盈利因子':<10}")
        print("-"*80)
        
        for result in results:
            print(f"{result['strategy']:<12} {result['total_trades']:<8} "
                  f"{result['win_rate']*100:<8.1f}% {result['total_pnl']:<12.2f} "
                  f"{result['max_drawdown']*100:<10.1f}% {result['sharpe_ratio']:<10.2f} "
                  f"{result['profit_factor']:<10.2f}")
        
        print("="*80)
        return
    
    # 如果没有指定参数，显示帮助
    parser.print_help()


if __name__ == '__main__':
    main()
