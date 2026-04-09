"""
缠论分析API - 基于chan.py
"""
from flask import Blueprint, jsonify, request, current_app
import sys
import os
import json
import time

bp = Blueprint('chan_api', __name__)

# 全局chan.py分析器（延迟初始化）
_chan_analyzer = None

def get_chan_analyzer():
    """获取或创建chan.py分析器（单例）"""
    global _chan_analyzer
    if _chan_analyzer is not None:
        return _chan_analyzer

    chan_path = '/app/chan_py'
    if chan_path not in sys.path:
        sys.path.insert(0, chan_path)

    from Common.CEnum import KL_TYPE
    from Chan import CChan
    from ChanConfig import CChanConfig
    from KLine.KLine_List import CKLine_List

    # Patch chan.py买卖点bug
    if not hasattr(get_chan_analyzer, '_patched'):
        get_chan_analyzer._patched = True
        try:
            _orig = CKLine_List.cal_seg_and_zs
            def _patched_fn(self):
                if not self.step_calculation:
                    self.bi_list.try_add_virtual_bi(self.lst[-1])
                from KLine.KLine_List import cal_seg, update_zs_in_seg
                self.last_sure_seg_start_bi_idx = cal_seg(self.bi_list, self.seg_list, self.last_sure_seg_start_bi_idx)
                self.zs_list.cal_bi_zs(self.bi_list, self.seg_list)
                update_zs_in_seg(self.bi_list, self.seg_list, self.zs_list)
                self.last_sure_segseg_start_bi_idx = cal_seg(self.seg_list, self.segseg_list, self.last_sure_segseg_start_bi_idx)
                self.segzs_list.cal_bi_zs(self.seg_list, self.segseg_list)
                update_zs_in_seg(self.seg_list, self.segseg_list, self.segzs_list)
            CKLine_List.cal_seg_and_zs = _patched_fn
            print("[chan] 买卖点bug已patch")
        except Exception as e:
            print(f"[chan] Patch失败: {e}")

    class PTAAnalyzer:
        def __init__(self):
            self.cache = {}
            self.cache_ttl = 300  # 5分钟缓存

        def analyze(self, period='1min'):
            # 检查缓存
            cache_key = f"pta_{period}"
            if cache_key in self.cache:
                cached = self.cache[cache_key]
                if time.time() - cached['ts'] < self.cache_ttl:
                    return cached['data']

            # 加载akshare数据
            import akshare as ak
            period_map = {
                '1min': ('TA0', '1'), '5min': ('TA0', '5'),
                '15min': ('TA0', '15'), '30min': ('TA0', '30'),
                '60min': ('TA0', '60'), '1day': ('TA0', '1day'),
            }
            sym, per = period_map.get(period, ('TA0', '1'))

            if per == '1day':
                df = ak.futures_zh_daily_sina(symbol=sym)
            else:
                df = ak.futures_zh_minute_sina(symbol=sym, period=per)

            df = df.sort_values('datetime').tail(1500).reset_index(drop=True)

            # 创建PTA数据源
            from DataAPI.pta import CPTADataFeed

            # 执行chan.py缠论分析
            kl_type_map = {
                '1min': KL_TYPE.K_1M, '5min': KL_TYPE.K_5M,
                '15min': KL_TYPE.K_15M, '30min': KL_TYPE.K_30M,
                '60min': KL_TYPE.K_60M, '1day': KL_TYPE.K_DAY,
            }
            kl_type = kl_type_map.get(period, KL_TYPE.K_1M)

            chan = CChan(
                code='PTA', begin_time=None, end_time=None,
                data_src='custom:pta.CPTADataFeed',
                lv_list=[kl_type], config=CChanConfig()
            )
            for _ in chan.load(): pass
            kl = chan[0]

            # 提取K线
            klines = []
            for klu in kl:
                raw = klu.lst[0] if klu.lst else None
                klines.append({
                    'idx': klu.idx,
                    'time': str(klu.time_begin),
                    'open': raw.close if raw else klu.close,
                    'high': klu.high,
                    'low': klu.low,
                    'close': raw.close if raw else klu.close,
                    'volume': raw.volume if raw else 0
                })

            # 提取笔（关键修复：用lst[-1].close）
            from Common.CEnum import BI_DIR
            bi_list = []
            for b in kl.bi_list:
                is_up = b.dir == BI_DIR.UP
                begin_price = b.begin_klc.lst[-1].close
                end_price = b.end_klc.lst[-1].close
                bi_list.append({
                    'idx': b.idx,
                    'dir': 'up' if is_up else 'down',
                    'begin': b.begin_klc.idx,
                    'end': b.end_klc.idx,
                    'begin_val': begin_price,
                    'end_val': end_price,
                    'is_sure': b.is_sure
                })

            # 提取线段
            seg_list = []
            for s in kl.seg_list:
                is_up = s.dir.value == 'BI_DIR.UP'
                beg = s.start_bi.idx if hasattr(s, 'start_bi') and s.start_bi else 0
                end = s.end_bi.idx if hasattr(s, 'end_bi') and s.end_bi else 0
                beg_val = s.start_bi.begin_klc.lst[-1].close if hasattr(s, 'start_bi') and s.start_bi else 0
                end_val = s.end_bi.end_klc.lst[-1].close if hasattr(s, 'end_bi') and s.end_bi else 0
                seg_list.append({
                    'idx': s.idx, 'dir': 'up' if is_up else 'down',
                    'begin': beg, 'end': end,
                    'begin_val': beg_val, 'end_val': end_val,
                    'is_sure': s.is_sure
                })

            # 提取中枢
            zs_list = []
            for z in kl.zs_list:
                zs_list.append({
                    'idx': z.idx if hasattr(z, 'idx') else len(zs_list),
                    'low': z.low, 'high': z.high,
                    'mid': z.mid if hasattr(z, 'mid') else (z.low + z.high) / 2,
                    'begin': z.begin.idx if hasattr(z.begin, 'idx') else 0,
                    'end': z.end.idx if hasattr(z.end, 'idx') else 0,
                    'is_sure': z.is_sure
                })

            # 提取买卖点
            bs_list = []
            for bp in kl.bs_list:
                bs_list.append({
                    'idx': bp.idx,
                    'type': str(bp.type),
                    'price': bp.price,
                    'bi_idx': bp.bi_idx if hasattr(bp, 'bi_idx') else 0
                })

            current_price = klines[-1]['close'] if klines else 0
            first_price = klines[0]['close'] if klines else current_price
            change = current_price - first_price
            change_pct = (change / first_price * 100) if first_price else 0

            # ECharts可视化数据
            bi_markline = []
            for b in bi_list:
                color = '#f23645' if b['dir'] == 'up' else '#089981'
                bi_markline.append({
                    'xAxis': b['begin'], 'yAxis': b['begin_val'],
                    'xAxis2': b['end'], 'yAxis2': b['end_val'],
                    'lineStyle': {'color': color, 'width': 2},
                    'label': {'show': True, 'formatter': f"{'↑' if b['dir']=='up' else '↓'}{b['idx']}", 'color': color}
                })

            seg_markline = []
            for s in seg_list:
                seg_markline.append({
                    'xAxis': s['begin'], 'yAxis': s['begin_val'],
                    'xAxis2': s['end'], 'yAxis2': s['end_val'],
                    'lineStyle': {'color': '#ffd93d', 'width': 3},
                    'label': {'show': True, 'formatter': f"S{s['idx']}", 'color': '#ffd93d'}
                })

            zs_markarea = []
            for z in zs_list:
                zs_markarea.append({
                    'xAxis': z['begin'], 'xAxis2': z['end'],
                    'yAxis': z['low'], 'yAxis2': z['high'],
                    'itemStyle': {'color': 'rgba(233,69,96,0.1)', 'borderColor': '#e94560', 'borderWidth': 1, 'borderType': 'dashed'}
                })

            bs_scatter = []
            for bp in bs_list:
                color = '#ff6b6b' if 'buy' in bp['type'] else '#6bcb77'
                bs_scatter.append({
                    'value': [bp.get('bi_idx', 0), bp['price']],
                    'symbol': 'circle', 'symbolSize': 12,
                    'itemStyle': {'color': color}
                })

            result = {
                'period': period,
                'klines': klines,
                'bi': bi_list,
                'seg': seg_list,
                'zs': zs_list,
                'bs': bs_list,
                'current_price': round(current_price, 2),
                'change': round(change, 2),
                'change_pct': round(change_pct, 2),
                'echarts': {
                    'bi_markline': bi_markline,
                    'seg_markline': seg_markline,
                    'zs_markarea': zs_markarea,
                    'bs_scatter': bs_scatter,
                },
                'stats': {
                    'bi_count': len(bi_list),
                    'seg_count': len(seg_list),
                    'zs_count': len(zs_list),
                    'bs_count': len(bs_list),
                    'current_price': round(current_price, 2),
                    'change': round(change, 2),
                    'change_pct': round(change_pct, 2),
                }
            }

            # 缓存结果
            self.cache[cache_key] = {'data': result, 'ts': time.time()}
            return result

    _chan_analyzer = PTAAnalyzer()
    return _chan_analyzer


@bp.route('/analysis')
def analysis():
    """缠论完整分析"""
    period = request.args.get('period', '1min')
    try:
        analyzer = get_chan_analyzer()
        result = analyzer.analyze(period)
        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'period': period})


@bp.route('/status')
def chan_status():
    """缠论模块状态"""
    return jsonify({
        'status': 'running',
        'engine': 'chan.py',
        'features': [
            '笔计算 (Bi)',
            '线段计算 (Seg)',
            '中枢计算 (ZS)',
            '买卖点识别 (BS)',
            'ECharts数据导出'
        ]
    })
