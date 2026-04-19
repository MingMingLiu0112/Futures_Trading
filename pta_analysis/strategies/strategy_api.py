#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期货期权策略API
提供杀期权阶段识别、期权墙识别、PCR计算、缠论与期权共振信号的HTTP API

Flask API: http://47.100.97.88:8424
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import warnings
import pandas as pd

from pta_option_strategy import (
    PTAOptionStrategy,
    KillOptionStageDetector,
    OptionWallDetector,
    PCRMonitor,
    IVAnalyzer,
    OptionStructureAnalyzer,
    ResonanceSignalGenerator,
    get_pta_option_data,
    get_pta_expiry_dates,
    MarketRegime,
    SignalDirection
)

app = Flask(__name__)
CORS(app)

# 全局策略实例
_strategy = None


def get_strategy():
    """获取策略实例（延迟初始化）"""
    global _strategy
    if _strategy is None:
        _strategy = PTAOptionStrategy(fp=7000)
    return _strategy


# ==================== 主策略API ====================

@app.route('/api/strategy/full_analysis', methods=['GET'])
def full_analysis():
    """完整一体化分析API
    
    Query Parameters:
        trade_date: 交易日期 (YYYYMMDD格式，默认今日)
        
    Returns:
        JSON: 完整分析结果
    """
    try:
        trade_date = request.args.get('trade_date', None)
        
        # 获取期权数据
        option_df = get_pta_option_data(trade_date)
        
        # 获取缠论分析结果
        from chan_core_wrapper import get_chan_result
        chan_result = get_chan_result(period='5min')
        
        if not chan_result.get('success'):
            return jsonify({
                'success': False,
                'error': '缠论分析失败'
            }), 500
        
        # 获取到期日期
        expiry_dates = get_pta_expiry_dates(months=2)
        
        # 执行完整分析
        strategy = get_strategy()
        result = strategy.get_full_analysis(option_df, chan_result, expiry_dates)
        
        return jsonify(result)
    
    except Exception as e:
        warnings.warn(f"分析失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/strategy/report', methods=['GET'])
def get_report():
    """获取格式化分析报告
    
    Query Parameters:
        trade_date: 交易日期 (YYYYMMDD格式，默认今日)
        format: 输出格式 (json/markdown，默认markdown)
        
    Returns:
        格式化报告
    """
    try:
        trade_date = request.args.get('trade_date', None)
        output_format = request.args.get('format', 'markdown')
        
        # 获取期权数据
        option_df = get_pta_option_data(trade_date)
        
        # 获取缠论分析结果
        from chan_core_wrapper import get_chan_result
        chan_result = get_chan_result(period='5min')
        
        if not chan_result.get('success'):
            return jsonify({
                'success': False,
                'error': '缠论分析失败'
            }), 500
        
        # 获取到期日期
        expiry_dates = get_pta_expiry_dates(months=2)
        
        # 执行完整分析
        strategy = get_strategy()
        result = strategy.get_full_analysis(option_df, chan_result, expiry_dates)
        
        if output_format == 'json':
            return jsonify(result)
        else:
            report = strategy.generate_report(result)
            return jsonify({
                'success': True,
                'report': report
            })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ==================== 单独的分析API ====================

@app.route('/api/strategy/kill_option_stage', methods=['GET'])
def kill_option_stage():
    """杀期权阶段识别API
    
    Query Parameters:
        trade_date: 交易日期 (YYYYMMDD格式，默认今日)
        
    Returns:
        JSON: 杀期权阶段识别结果
    """
    try:
        trade_date = request.args.get('trade_date', None)
        option_df = get_pta_option_data(trade_date)
        expiry_dates = get_pta_expiry_dates(months=2)
        
        detector = KillOptionStageDetector()
        result = detector.detect(option_df, expiry_dates)
        
        return jsonify({
            'success': True,
            'is_active': result.is_active,
            'near_expiry': result.near_expiry,
            'expiry_date': result.expiry_date,
            'days_to_expiry': result.days_to_expiry,
            'wall_clarity': round(result.wall_clarity, 2),
            'has_option_wall': result.has_option_wall,
            'confidence': round(result.confidence, 2)
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/strategy/option_walls', methods=['GET'])
def option_walls():
    """期权墙识别API
    
    Query Parameters:
        trade_date: 交易日期 (YYYYMMDD格式，默认今日)
        fp: ATM行权价 (默认7000)
        
    Returns:
        JSON: 期权墙识别结果
    """
    try:
        trade_date = request.args.get('trade_date', None)
        fp = float(request.args.get('fp', 7000))
        
        option_df = get_pta_option_data(trade_date)
        
        detector = OptionWallDetector()
        result = detector.detect(option_df, fp)
        
        # 转换OptionWall为字典
        def wall_to_dict(wall):
            return {
                'strike': wall.strike,
                'option_type': wall.option_type,
                'oi': wall.oi,
                'vol': wall.vol,
                'iv': wall.iv,
                'position': wall.position,
                'density_ratio': round(wall.density_ratio, 2),
                'is_wall': wall.is_wall
            }
        
        return jsonify({
            'success': True,
            'fp': result['fp'],
            'floor_walls': [wall_to_dict(w) for w in result['floor_walls']],
            'ceil_walls': [wall_to_dict(w) for w in result['ceil_walls']],
            'total_floor_oi': result['total_floor_oi'],
            'total_ceil_oi': result['total_ceil_oi']
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/strategy/pcr', methods=['GET'])
def pcr_analysis():
    """PCR指标计算API
    
    Query Parameters:
        trade_date: 交易日期 (YYYYMMDD格式，默认今日)
        
    Returns:
        JSON: PCR计算结果
    """
    try:
        trade_date = request.args.get('trade_date', None)
        option_df = get_pta_option_data(trade_date)
        
        monitor = PCRMonitor()
        result = monitor.calculate(option_df)
        
        return jsonify({
            'success': True,
            'position_pcr': result['position_pcr'],
            'volume_pcr': result['volume_pcr'],
            'total_call_vol': result['total_call_vol'],
            'total_put_vol': result['total_put_vol'],
            'total_call_oi': result['total_call_oi'],
            'total_put_oi': result['total_put_oi'],
            'signal': result['signal'].value,
            'label': result['label']
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/strategy/iv_skew', methods=['GET'])
def iv_skew_analysis():
    """IV曲线分析API
    
    Query Parameters:
        trade_date: 交易日期 (YYYYMMDD格式，默认今日)
        fp: ATM行权价 (默认7000)
        
    Returns:
        JSON: IV曲线分析结果
    """
    try:
        trade_date = request.args.get('trade_date', None)
        fp = float(request.args.get('fp', 7000))
        
        option_df = get_pta_option_data(trade_date)
        
        analyzer = IVAnalyzer()
        result = analyzer.analyze(option_df, fp)
        
        return jsonify({
            'success': True,
            'call_iv': result['call_iv'],
            'put_iv': result['put_iv'],
            'iv_diff': result['iv_diff'],
            'skew': result['skew'].value,
            'label': result['label']
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/strategy/resonance', methods=['GET'])
def resonance_signal():
    """缠论与期权共振信号API
    
    Query Parameters:
        trade_date: 交易日期 (YYYYMMDD格式，默认今日)
        
    Returns:
        JSON: 共振信号结果
    """
    try:
        trade_date = request.args.get('trade_date', None)
        
        # 获取期权数据
        option_df = get_pta_option_data(trade_date)
        
        # 获取缠论分析结果
        from chan_core_wrapper import get_chan_result
        chan_result = get_chan_result(period='5min')
        
        if not chan_result.get('success'):
            return jsonify({
                'success': False,
                'error': '缠论分析失败'
            }), 500
        
        # 获取到期日期
        expiry_dates = get_pta_expiry_dates(months=2)
        
        # 分析期权结构
        option_analyzer = OptionStructureAnalyzer(fp=7000)
        option_structure, kill_stage = option_analyzer.analyze(option_df, expiry_dates)
        
        # 生成共振信号
        resonance_generator = ResonanceSignalGenerator(option_analyzer)
        regime = MarketRegime.KILL_OPTION if kill_stage.is_active else MarketRegime.CALM
        
        bs_points = chan_result.get('bs_data', [])
        current_price = chan_result.get('stats', {}).get('current_price', 0)
        
        signal = resonance_generator.generate(
            bs_points, current_price, option_structure, kill_stage, regime
        )
        
        return jsonify({
            'success': True,
            'direction': signal.direction.value,
            'confidence': round(signal.confidence, 2),
            'regime': signal.regime.value,
            '共振依据': signal.共振依据,
            'risk_level': signal.risk_level,
            'action': signal.action
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ==================== 健康检查 ====================

@app.route('/api/strategy/health', methods=['GET'])
def health():
    """健康检查"""
    return jsonify({
        'status': 'ok',
        'service': 'pta_option_strategy'
    })


if __name__ == '__main__':
    print("=" * 60)
    print("PTA期货期权策略API")
    print("=" * 60)
    app.run(host='0.0.0.0', port=8425, debug=False)
