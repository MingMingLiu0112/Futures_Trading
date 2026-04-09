"""
期货期权分析模块

Usage:
    from futures_options import FuturesOptionsAnalyzer
    from futures_options.push.feishu import init_pusher, send_report
    
    # 初始化
    analyzer = FuturesOptionsAnalyzer(
        symbol="CU",
        iv_history=[...],
        put_iv=24.5,
        call_iv=22.3
    )
    
    # 分析
    result = analyzer.analyze(futures_data)
    
    # 推送
    from futures_options.push.feishu import init_pusher, send_report
    init_pusher("YOUR_WEBHOOK_URL")
    send_report(result)
"""

from .analyzer import FuturesOptionsAnalyzer

__version__ = "0.1.0"
__all__ = ["FuturesOptionsAnalyzer"]
