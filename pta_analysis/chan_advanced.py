#!/usr/bin/env python3
"""
高级缠论分析模块
提供完整的缠论分析功能：笔、线段、中枢、分型识别
"""

import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class ChanAdvancedAnalyzer:
    """高级缠论分析器"""
    
    def __init__(self):
        self.data_cache = {}
        
    def get_kline_data(self, symbol: str = "TA", period: str = "1d") -> pd.DataFrame:
        """获取K线数据"""
        cache_key = f"{symbol}_{period}"
        
        if cache_key in self.data_cache:
            return self.data_cache[cache_key]
        
        try:
            # 尝试从本地文件获取数据
            data_path = os.path.join(os.path.dirname(__file__), "data", "ta509_alternating.csv")
            if not os.path.exists(data_path):
                data_path = os.path.join(os.path.dirname(__file__), "data", "ta509_varied.csv")
            if not os.path.exists(data_path):
                data_path = os.path.join(os.path.dirname(__file__), "data", "ta509_daily.csv")
                
            # print(f"尝试读取数据文件: {data_path}")
            # print(f"文件存在: {os.path.exists(data_path)}")
            
            if os.path.exists(data_path):
                df = pd.read_csv(data_path)
                # print(f"读取到 {len(df)} 行数据")
                # print(f"列名: {df.columns.tolist()}")
                
                if 'datetime' in df.columns:
                    df['datetime'] = pd.to_datetime(df['datetime'])
                    df = df.sort_values('datetime')
                    # print(f"时间范围: {df['datetime'].min()} 到 {df['datetime'].max()}")
                    
                    # 根据period过滤数据
                    # 由于数据是2024年的，我们调整过滤逻辑
                    if period == "1d":
                        # 返回所有数据
                        pass
                    elif period == "3d":
                        # 返回最后3天的数据
                        if len(df) > 3:
                            df = df.tail(3)
                    elif period == "1w":
                        # 返回最后7天的数据
                        if len(df) > 7:
                            df = df.tail(7)
                    elif period == "1m":
                        # 返回最后30天的数据
                        if len(df) > 30:
                            df = df.tail(30)
                    
                    # print(f"过滤后数据: {len(df)} 行")
                    self.data_cache[cache_key] = df
                    return df
                else:
                    # print("错误: 数据文件缺少datetime列")
                    pass
            else:
                # print(f"数据文件不存在: {data_path}")
                pass
        except Exception as e:
            print(f"获取K线数据失败: {e}")
        
        # 返回空DataFrame
        return pd.DataFrame(columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
    
    def process_baohan(self, kline_df: pd.DataFrame) -> List[Tuple[float, float]]:
        """
        处理K线包含关系
        返回处理后的K线列表 [(high, low), ...]
        """
        if kline_df.empty:
            return []
        
        rows = kline_df[['high', 'low']].values.tolist()
        result = []
        
        i = 0
        while i < len(rows):
            if len(result) == 0:
                result.append(rows[i])
                i += 1
                continue
            
            h1, l1 = result[-1]
            h2, l2 = rows[i]
            
            # 判断包含关系
            has_contain = (h2 <= h1 and l2 >= l1) or (h2 >= h1 and l2 <= l1)
            
            if not has_contain:
                result.append(rows[i])
                i += 1
                continue
            
            # 判断趋势
            if l2 > l1:
                # 上升趋势 - 高高原则
                new_h = max(h1, h2)
                new_l = max(l1, l2)
            else:
                # 下降趋势 - 低低原则
                new_h = min(h1, h2)
                new_l = min(l1, l2)
            
            result[-1] = (new_h, new_l)
            i += 1
        
        return result
    
    def find_fenxing(self, klist: List[Tuple[float, float]]) -> List[Dict]:
        """
        识别顶分型和底分型
        返回分型列表
        """
        n = len(klist)
        fenxing_list = []
        
        for i in range(1, n - 1):
            h_prev, l_prev = klist[i - 1]
            h_curr, l_curr = klist[i]
            h_next, l_next = klist[i + 1]
            
            # 顶分型
            if h_curr > h_prev and h_curr > h_next and l_curr > l_prev and l_curr > l_next:
                fenxing_list.append({
                    'type': 'top',
                    'index': i,
                    'price': h_curr,
                    'kline_index': i
                })
            # 底分型
            elif h_curr < h_prev and h_curr < h_next and l_curr < l_prev and l_curr < l_next:
                fenxing_list.append({
                    'type': 'bottom',
                    'index': i,
                    'price': l_curr,
                    'kline_index': i
                })
        
        return fenxing_list
    
    def build_bi(self, fenxing_list: List[Dict], klist: List[Tuple[float, float]]) -> List[Dict]:
        """
        构建笔
        返回笔列表
        """
        if len(fenxing_list) < 2:
            return []
        
        bi_list = []
        i = 0
        

        
        while i < len(fenxing_list) - 1:
            start_fx = fenxing_list[i]
            end_fx = fenxing_list[i + 1]
            
            # 笔的规则：底分型 + 顶分型 = 上升笔，顶分型 + 底分型 = 下降笔
            if start_fx['type'] == 'bottom' and end_fx['type'] == 'top':
                # 上升笔
                direction = 'up'
                start_price = start_fx['price']
                end_price = end_fx['price']
                start_idx = start_fx['index']
                end_idx = end_fx['index']
                
                # 检查笔的有效性（至少包含3根K线）
                if end_idx - start_idx >= 2:
                    change_pct = (end_price - start_price) / start_price * 100
                    bi_list.append({
                        'direction': direction,
                        'start_index': start_idx,
                        'end_index': end_idx,
                        'start_price': round(start_price, 2),
                        'end_price': round(end_price, 2),
                        'change_pct': round(change_pct, 2),
                        'length': end_idx - start_idx + 1,
                        'duration': f"{end_idx - start_idx + 1}根K线"
                    })
                    i += 2  # 跳过已使用的分型
                else:
                    i += 1  # 无效笔，跳过起始分型
            
            elif start_fx['type'] == 'top' and end_fx['type'] == 'bottom':
                # 下降笔
                direction = 'down'
                start_price = start_fx['price']
                end_price = end_fx['price']
                start_idx = start_fx['index']
                end_idx = end_fx['index']
                
                # 检查笔的有效性
                if end_idx - start_idx >= 2:
                    change_pct = (end_price - start_price) / start_price * 100
                    bi_list.append({
                        'direction': direction,
                        'start_index': start_idx,
                        'end_index': end_idx,
                        'start_price': round(start_price, 2),
                        'end_price': round(end_price, 2),
                        'change_pct': round(change_pct, 2),
                        'length': end_idx - start_idx + 1,
                        'duration': f"{end_idx - start_idx + 1}根K线"
                    })
                    i += 2
                else:
                    i += 1
            else:
                i += 1  # 不匹配的分型组合
        return bi_list
    
    def build_xd(self, bi_list: List[Dict]) -> List[Dict]:
        """
        构建线段
        返回线段列表
        """
        if len(bi_list) < 3:
            print(f"笔数量不足 ({len(bi_list)})，无法构建线段")
            return []
        
        xd_list = []
        i = 0
        

        
        while i < len(bi_list) - 2:
            # 线段需要至少3笔
            bi1 = bi_list[i]
            bi2 = bi_list[i + 1]
            bi3 = bi_list[i + 2]
            
            # 检查是否形成线段（简化版：至少3笔，方向相同）
            if (bi1['direction'] == bi2['direction'] and 
                bi2['direction'] == bi3['direction']):
                
                # 确定线段方向（与奇数笔方向相同）
                direction = bi1['direction']
                
                # 线段包含的笔范围
                start_bi_idx = i
                end_bi_idx = i + 2
                
                # 尝试扩展线段
                j = i + 3
                while j < len(bi_list):
                    if bi_list[j]['direction'] == direction:
                        end_bi_idx = j
                        j += 2  # 跳过相反方向的笔
                    else:
                        break
                
                # 创建线段
                start_bi = bi_list[start_bi_idx]
                end_bi = bi_list[end_bi_idx]
                
                if direction == 'up':
                    start_price = start_bi['start_price']
                    end_price = end_bi['end_price']
                else:
                    start_price = start_bi['start_price']
                    end_price = end_bi['end_price']
                
                change_pct = (end_price - start_price) / start_price * 100
                
                xd_list.append({
                    'direction': direction,
                    'start_bi_index': start_bi_idx,
                    'end_bi_index': end_bi_idx,
                    'bi_count': end_bi_idx - start_bi_idx + 1,
                    'start_price': round(start_price, 2),
                    'end_price': round(end_price, 2),
                    'change_pct': round(change_pct, 2),
                    'length': f"{end_bi_idx - start_bi_idx + 1}笔",
                    'bi_range': f"{start_bi_idx+1}-{end_bi_idx+1}"
                })
                
                i = end_bi_idx + 1  # 移动到下一线段
            else:
                i += 1
        return xd_list
    
    def find_zhongshu(self, xd_list: List[Dict], bi_list: List[Dict]) -> List[Dict]:
        """
        识别中枢
        返回中枢列表
        """
        if len(xd_list) < 3:
            return []
        
        zhongshu_list = []
        
        for i in range(len(xd_list) - 2):
            # 中枢需要至少3个重叠的线段
            xd1 = xd_list[i]
            xd2 = xd_list[i + 1]
            xd3 = xd_list[i + 2]
            
            # 检查线段方向（应该上下交替）
            if (xd1['direction'] != xd2['direction'] and 
                xd2['direction'] != xd3['direction']):
                
                # 计算价格重叠区间
                prices = []
                for xd in [xd1, xd2, xd3]:
                    prices.extend([xd['start_price'], xd['end_price']])
                
                overlap_high = min(max(xd1['start_price'], xd1['end_price']),
                                  max(xd2['start_price'], xd2['end_price']),
                                  max(xd3['start_price'], xd3['end_price']))
                
                overlap_low = max(min(xd1['start_price'], xd1['end_price']),
                                 min(xd2['start_price'], xd2['end_price']),
                                 min(xd3['start_price'], xd3['end_price']))
                
                # 检查是否有有效重叠
                if overlap_low < overlap_high:
                    zhongshu_list.append({
                        'index': len(zhongshu_list) + 1,
                        'start_xd_index': i,
                        'end_xd_index': i + 2,
                        'high': round(overlap_high, 2),
                        'low': round(overlap_low, 2),
                        'center': round((overlap_high + overlap_low) / 2, 2),
                        'height': round(overlap_high - overlap_low, 2),
                        'xd_count': 3,
                        'range': f"{round(overlap_low, 2)}-{round(overlap_high, 2)}"
                    })
        
        return zhongshu_list
    
    def analyze_trend(self, bi_list: List[Dict], xd_list: List[Dict]) -> Dict:
        """分析趋势"""
        if not bi_list:
            return {
                'trend': 'neutral',
                'trend_text': '震荡',
                'trend_strength': '弱',
                'key_levels': '无'
            }
        
        # 分析最近3笔的方向
        recent_bi = bi_list[-3:] if len(bi_list) >= 3 else bi_list
        up_count = sum(1 for bi in recent_bi if bi['direction'] == 'up')
        down_count = sum(1 for bi in recent_bi if bi['direction'] == 'down')
        
        if up_count > down_count:
            trend = 'up'
            trend_text = '上升'
        elif down_count > up_count:
            trend = 'down'
            trend_text = '下降'
        else:
            trend = 'neutral'
            trend_text = '震荡'
        
        # 趋势强度
        if len(recent_bi) >= 2:
            strength = '强' if abs(recent_bi[-1]['change_pct']) > 1.0 else '中等'
        else:
            strength = '弱'
        
        # 关键位置
        key_levels = []
        if bi_list:
            # 最近笔的高低点
            recent_prices = [bi['start_price'] for bi in recent_bi] + [bi['end_price'] for bi in recent_bi]
            key_levels.append(f"支撑: {min(recent_prices):.2f}")
            key_levels.append(f"阻力: {max(recent_prices):.2f}")
        
        return {
            'trend': trend,
            'trend_text': trend_text,
            'trend_strength': strength,
            'key_levels': ', '.join(key_levels) if key_levels else '无'
        }
    
    def generate_signals(self, bi_list: List[Dict], xd_list: List[Dict], 
                        zhongshu_list: List[Dict]) -> List[Dict]:
        """生成交易信号"""
        signals = []
        
        if not bi_list:
            return signals
        
        # 获取最新笔
        latest_bi = bi_list[-1]
        
        # 笔结束信号
        if latest_bi['direction'] == 'up' and latest_bi['change_pct'] > 1.0:
            signals.append({
                'type': 'buy',
                'text': f"上升笔结束，涨幅{latest_bi['change_pct']}%",
                'icon': 'arrow-up',
                'time': datetime.now().strftime("%H:%M:%S")
            })
        elif latest_bi['direction'] == 'down' and latest_bi['change_pct'] < -1.0:
            signals.append({
                'type': 'sell',
                'text': f"下降笔结束，跌幅{abs(latest_bi['change_pct'])}%",
                'icon': 'arrow-down',
                'time': datetime.now().strftime("%H:%M:%S")
            })
        
        # 线段突破信号
        if len(xd_list) >= 2:
            latest_xd = xd_list[-1]
            prev_xd = xd_list[-2]
            
            if (latest_xd['direction'] == 'up' and 
                latest_xd['end_price'] > prev_xd['end_price']):
                signals.append({
                    'type': 'buy',
                    'text': f"线段突破前高{prev_xd['end_price']:.2f}",
                    'icon': 'chart-line',
                    'time': datetime.now().strftime("%H:%M:%S")
                })
            elif (latest_xd['direction'] == 'down' and 
                  latest_xd['end_price'] < prev_xd['end_price']):
                signals.append({
                    'type': 'sell',
                    'text': f"线段跌破前低{prev_xd['end_price']:.2f}",
                    'icon': 'chart-line',
                    'time': datetime.now().strftime("%H:%M:%S")
                })
        
        # 中枢相关信号
        if zhongshu_list:
            latest_zs = zhongshu_list[-1]
            current_price = latest_bi['end_price'] if bi_list else 0
            
            if current_price > latest_zs['high']:
                signals.append({
                    'type': 'buy',
                    'text': f"突破中枢上沿{latest_zs['high']:.2f}",
                    'icon': 'door-open',
                    'time': datetime.now().strftime("%H:%M:%S")
                })
            elif current_price < latest_zs['low']:
                signals.append({
                    'type': 'sell',
                    'text': f"跌破中枢下沿{latest_zs['low']:.2f}",
                    'icon': 'door-closed',
                    'time': datetime.now().strftime("%H:%M:%S")
                })
        
        return signals
    
    def generate_suggestion(self, analysis: Dict) -> Dict:
        """生成操作建议"""
        trend = analysis.get('trend', 'neutral')
        signals = analysis.get('signals', [])
        
        if not signals:
            return {
                'signal': '观望',
                'signal_type': 'neutral',
                'suggestion': '等待明确信号',
                'risk_level': '低'
            }
        
        # 检查是否有买卖信号
        buy_signals = [s for s in signals if s['type'] == 'buy']
        sell_signals = [s for s in signals if s['type'] == 'sell']
        
        if buy_signals and trend == 'up':
            return {
                'signal': '买入',
                'signal_type': 'buy',
                'suggestion': '上升趋势确认，可考虑买入',
                'risk_level': '中等'
            }
        elif sell_signals and trend == 'down':
            return {
                'signal': '卖出',
                'signal_type': 'sell',
                'suggestion': '下降趋势确认，可考虑卖出',
                'risk_level': '中等'
            }
        elif buy_signals:
            return {
                'signal': '谨慎买入',
                'signal_type': 'buy',
                'suggestion': '有买入信号但趋势不明，谨慎操作',
                'risk_level': '高'
            }
        elif sell_signals:
            return {
                'signal': '谨慎卖出',
                'signal_type': 'sell',
                'suggestion': '有卖出信号但趋势不明，谨慎操作',
                'risk_level': '高'
            }
        else:
            return {
                'signal': '观望',
                'signal_type': 'neutral',
                'suggestion': '等待明确信号',
                'risk_level': '低'
            }
    
    def analyze(self, symbol: str = "TA", period: str = "1d") -> Dict:
        """执行完整的缠论分析"""
        try:
            # 获取K线数据
            kline_df = self.get_kline_data(symbol, period)
            if kline_df.empty:
                return {
                    'success': False,
                    'error': '无K线数据',
                    'timestamp': datetime.now().isoformat()
                }
            
            # 处理包含关系
            klist = self.process_baohan(kline_df)
            
            # 识别分型
            fenxing_list = self.find_fenxing(klist)
            
            # 构建笔
            bi_list = self.build_bi(fenxing_list, klist)
            
            # 构建线段
            xd_list = self.build_xd(bi_list)
            
            # 识别中枢
            zhongshu_list = self.find_zhongshu(xd_list, bi_list)
            
            # 分析趋势
            trend_analysis = self.analyze_trend(bi_list, xd_list)
            
            # 生成信号
            signals = self.generate_signals(bi_list, xd_list, zhongshu_list)
            
            # 生成建议
            suggestion = self.generate_suggestion({
                'trend': trend_analysis['trend'],
                'signals': signals
            })
            
            # 准备K线数据用于图表
            klines_for_chart = []
            for idx, row in kline_df.iterrows():
                klines_for_chart.append({
                    'time': row['datetime'].isoformat() if hasattr(row['datetime'], 'isoformat') else str(row['datetime']),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': float(row['volume']) if 'volume' in row else 0
                })
            
            # 准备分型数据
            fenxing_for_chart = []
            for fx in fenxing_list:
                if fx['kline_index'] < len(klines_for_chart):
                    kline = klines_for_chart[fx['kline_index']]
                    fenxing_for_chart.append({
                        'type': fx['type'],
                        'time': kline['time'],
                        'price': fx['price'],
                        'index': fx['index']
                    })
            
            # 返回完整结果
            return {
                'success': True,
                'symbol': symbol,
                'period': period,
                'timestamp': datetime.now().isoformat(),
                'summary': {
                    'bi_count': len(bi_list),
                    'xd_count': len(xd_list),
                    'zhongshu_count': len(zhongshu_list),
                    'fenxing_count': len(fenxing_list)
                },
                'klines': klines_for_chart[-100:],  # 只返回最近100根K线
                'fenxing_list': fenxing_for_chart,
                'bi_list': bi_list,
                'xd_list': xd_list,
                'zhongshu_list': zhongshu_list,
                'signals': signals,
                'analysis': {
                    **trend_analysis,
                    **suggestion,
                    'current_zhongshu': zhongshu_list[-1]['range'] if zhongshu_list else '无',
                    'zhongshu_range': zhongshu_list[-1]['range'] if zhongshu_list else 'N/A'
                }
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

# 全局分析器实例
_analyzer = ChanAdvancedAnalyzer()

def get_chan_advanced_analysis(symbol: str = "TA", period: str = "1d") -> Dict:
    """获取高级缠论分析（外部调用接口）"""
    return _analyzer.analyze(symbol, period)

if __name__ == "__main__":
    # 测试代码
    result = get_chan_advanced_analysis("TA", "1d")
    print(json.dumps(result, indent=2, ensure_ascii=False))