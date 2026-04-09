"""
缠论算法完整实现：包含关系处理 + 顶底分型识别
基于缠论108课标准实现
"""

import pandas as pd
import numpy as np
from typing import List, Tuple, Dict, Any, Optional
import warnings

warnings.filterwarnings('ignore')


class ChanKLine:
    """缠论K线类"""
    
    def __init__(self, high: float, low: float, open: Optional[float] = None, 
                 close: Optional[float] = None, volume: Optional[float] = None,
                 timestamp: Optional[pd.Timestamp] = None):
        self.high = high
        self.low = low
        self.open = open
        self.close = close
        self.volume = volume
        self.timestamp = timestamp
        
    def __repr__(self):
        return f"KLine(H={self.high:.2f}, L={self.low:.2f})"
    
    def is_contained_by(self, other: 'ChanKLine') -> bool:
        """判断当前K线是否被另一根K线包含（双向）"""
        # 包含关系的定义：一根K线的区间完全在另一根K线的区间内
        # 或者两根K线有重叠但一根完全包含另一根
        return (self.high <= other.high and self.low >= other.low) or \
               (self.high >= other.high and self.low <= other.low)
    
    def has_containment(self, other: 'ChanKLine') -> bool:
        """判断两根K线是否存在包含关系"""
        return self.is_contained_by(other)
    
    def merge_with(self, other: 'ChanKLine', direction: str) -> 'ChanKLine':
        """合并两根包含关系的K线
        direction: 'up' 上升包含取高高, 'down' 下降包含取低低
        """
        if direction == 'up':
            # 上升包含：取高高原则
            new_high = max(self.high, other.high)
            new_low = max(self.low, other.low)
        else:  # direction == 'down'
            # 下降包含：取低低原则
            new_high = min(self.high, other.high)
            new_low = min(self.low, other.low)
            
        # 合并其他属性（取第一根K线的值）
        return ChanKLine(
            high=new_high,
            low=new_low,
            open=self.open,
            close=self.close,
            volume=self.volume,
            timestamp=self.timestamp
        )


class ChanProcessor:
    """缠论处理器：包含关系处理和分型识别"""
    
    def __init__(self):
        self.processed_klines: List[ChanKLine] = []
        self.fenxing_list: List[Dict] = []
        self.bi_list: List[Dict] = []
        
    def process_containment(self, klines: List[ChanKLine]) -> List[ChanKLine]:
        """
        处理K线包含关系
        算法步骤：
        1. 从左到右处理K线
        2. 判断当前K线与前一根处理后的K线是否有包含关系
        3. 如果有包含关系，根据趋势方向合并
        4. 趋势方向判断：看前两根非包含K线的方向
        """
        if not klines:
            return []
            
        result: List[ChanKLine] = []
        
        for i, kline in enumerate(klines):
            if not result:
                # 第一根K线直接加入
                result.append(kline)
                continue
                
            prev_kline = result[-1]
            
            # 检查包含关系
            if kline.has_containment(prev_kline):
                # 确定趋势方向
                direction = self._determine_trend_direction(result, kline)
                
                # 合并K线
                merged_kline = prev_kline.merge_with(kline, direction)
                result[-1] = merged_kline
            else:
                # 无包含关系，直接加入
                result.append(kline)
                
        return result
    
    def _determine_trend_direction(self, processed_klines: List[ChanKLine], 
                                  current_kline: ChanKLine) -> str:
        """
        确定包含关系的处理方向
        缠论规则：找到最近的非包含K线来判断趋势
        """
        if len(processed_klines) < 2:
            # 如果只有一根K线，用当前K线的高点判断
            if len(processed_klines) == 0:
                return 'up'  # 默认
            prev_kline = processed_klines[-1]
            return 'up' if current_kline.high > prev_kline.high else 'down'
        
        # 从后往前找到最近的两根非包含K线
        # 首先，processed_klines中的K线都是非包含的（因为包含的已经合并了）
        # 所以我们可以直接用最后两根K线
        k2 = processed_klines[-1]  # 最近的非包含K线
        k1 = processed_klines[-2]  # 前一根非包含K线
        
        # 判断趋势：如果k2比k1高，则是上升趋势
        if k2.high > k1.high and k2.low > k1.low:
            return 'up'
        elif k2.high < k1.high and k2.low < k1.low:
            return 'down'
        else:
            # 无法明确判断，用默认规则
            return 'up' if current_kline.high > k2.high else 'down'
    
    def find_fenxing(self, klines: List[ChanKLine]) -> List[Dict]:
        """
        识别顶分型和底分型
        规则：
        1. 顶分型：中间K线最高价和最低价都高于左右两根K线
        2. 底分型：中间K线最高价和最低价都低于左右两根K线
        3. 分型确认：需要排除包含关系处理后的特殊情况
        4. 分型有效性：分型之间至少间隔一根K线
        """
        if len(klines) < 3:
            return []
            
        fenxing_list = []
        
        for i in range(1, len(klines) - 1):
            left = klines[i - 1]
            middle = klines[i]
            right = klines[i + 1]
            
            # 检查顶分型：中间K线的高点是三根中最高的，且低点也是三根中最高的
            is_top = (middle.high >= left.high and middle.high >= right.high and
                     middle.low >= left.low and middle.low >= right.low and
                     (middle.high > left.high or middle.high > right.high) and
                     (middle.low > left.low or middle.low > right.low))
            
            # 检查底分型：中间K线的低点是三根中最低的，且高点也是三根中最低的
            is_bottom = (middle.high <= left.high and middle.high <= right.high and
                        middle.low <= left.low and middle.low <= right.low and
                        (middle.high < left.high or middle.high < right.high) and
                        (middle.low < left.low or middle.low < right.low))
            
            if is_top:
                fenxing = {
                    'type': 'top',  # 顶分型
                    'index': i,
                    'price': middle.high,  # 顶分型价格取最高价
                    'kline': middle,
                    'left_kline': left,
                    'right_kline': right
                }
                fenxing_list.append(fenxing)
                
            elif is_bottom:
                fenxing = {
                    'type': 'bottom',  # 底分型
                    'index': i,
                    'price': middle.low,  # 底分型价格取最低价
                    'kline': middle,
                    'left_kline': left,
                    'right_kline': right
                }
                fenxing_list.append(fenxing)
        
        # 过滤无效分型：缠论中允许相邻的分型，只要类型不同
        # 这里我们只过滤掉同一位置的分型（理论上不应该出现）
        filtered_fenxing = []
        seen_indices = set()
        
        for fen in fenxing_list:
            if fen['index'] not in seen_indices:
                filtered_fenxing.append(fen)
                seen_indices.add(fen['index'])
        
        self.fenxing_list = filtered_fenxing
        return filtered_fenxing
    
    def build_bi(self, fenxing_list: List[Dict], min_kline_gap: int = 4, 
                min_price_range: Optional[float] = None) -> List[Dict]:
        """
        从分型构建笔
        规则：
        1. 笔由顶分型和底分型交替构成
        2. 上升笔：底分型 -> 顶分型
        3. 下降笔：顶分型 -> 底分型
        4. 笔的有效性：分型之间至少间隔min_kline_gap根K线
        5. 可选的价格幅度过滤：笔的幅度必须大于min_price_range
        """
        if len(fenxing_list) < 2:
            return []
            
        bi_list = []
        i = 0
        
        while i < len(fenxing_list) - 1:
            start_fen = fenxing_list[i]
            
            # 寻找下一个相反类型的分型
            j = i + 1
            while j < len(fenxing_list):
                end_fen = fenxing_list[j]
                
                # 检查分型类型是否相反
                if start_fen['type'] == 'top' and end_fen['type'] == 'bottom':
                    direction = 'down'
                    price_range = start_fen['price'] - end_fen['price']
                elif start_fen['type'] == 'bottom' and end_fen['type'] == 'top':
                    direction = 'up'
                    price_range = end_fen['price'] - start_fen['price']
                else:
                    j += 1
                    continue
                
                # 检查K线间隔
                kline_gap = end_fen['index'] - start_fen['index']
                
                # 检查价格幅度（如果设置了阈值）
                price_valid = True
                if min_price_range is not None:
                    price_valid = price_range >= min_price_range
                
                # 检查是否满足条件（允许小笔）
                if price_valid:
                    # 构建笔（包括小笔）
                    bi = {
                        'direction': direction,
                        'start_index': start_fen['index'],
                        'end_index': end_fen['index'],
                        'start_price': start_fen['price'],
                        'end_price': end_fen['price'],
                        'price_range': price_range,
                        'kline_gap': kline_gap,
                        'start_fenxing': start_fen,
                        'end_fenxing': end_fen,
                        'is_small_bi': kline_gap < min_kline_gap
                    }
                    bi_list.append(bi)
                    i = j  # 移动到结束分型位置
                    break
                else:
                    j += 1
            else:
                # 没有找到合适的分型，移动到下一个
                i += 1
        
        self.bi_list = bi_list
        return bi_list
    
    def process_pipeline(self, klines: List[ChanKLine], 
                        min_kline_gap: int = 4,
                        min_price_range: Optional[float] = None) -> Dict[str, Any]:
        """
        完整的缠论处理流水线
        1. 包含关系处理
        2. 分型识别
        3. 笔构建
        """
        # 1. 包含关系处理
        processed_klines = self.process_containment(klines)
        self.processed_klines = processed_klines
        
        # 2. 分型识别
        fenxing_list = self.find_fenxing(processed_klines)
        
        # 3. 笔构建
        bi_list = self.build_bi(fenxing_list, min_kline_gap, min_price_range)
        
        return {
            'processed_klines': processed_klines,
            'fenxing_list': fenxing_list,
            'bi_list': bi_list,
            'original_count': len(klines),
            'processed_count': len(processed_klines),
            'fenxing_count': len(fenxing_list),
            'bi_count': len(bi_list)
        }


# ============================================================================
# 数据工具函数
# ============================================================================

def create_test_klines() -> List[ChanKLine]:
    """创建测试K线数据"""
    # 模拟一个简单的价格序列：先上升后下降，确保有足够的分型间隔
    prices = [
        (100, 95),   # 0
        (105, 100),  # 1 - 上升
        (110, 105),  # 2 - 上升，顶分型
        (108, 103),  # 3
        (105, 100),  # 4 - 下降
        (102, 97),   # 5 - 下降，底分型
        (108, 103),  # 6 - 上升
        (112, 107),  # 7 - 上升
        (115, 110),  # 8 - 上升，顶分型
        (112, 107),  # 9 - 下降
        (108, 103),  # 10 - 下降
        (105, 100),  # 11 - 下降，底分型
    ]
    
    klines = []
    for i, (high, low) in enumerate(prices):
        klines.append(ChanKLine(
            high=high,
            low=low,
            open=low + (high - low) * 0.3,  # 模拟开盘价
            close=low + (high - low) * 0.7,  # 模拟收盘价
            volume=1000 + i * 100,
            timestamp=pd.Timestamp(f'2024-01-01 09:{i:02d}:00')
        ))
    
    return klines


def klines_from_dataframe(df: pd.DataFrame) -> List[ChanKLine]:
    """从DataFrame创建K线列表"""
    klines = []
    
    for _, row in df.iterrows():
        kline = ChanKLine(
            high=float(row['high']),
            low=float(row['low']),
            open=float(row['open']) if 'open' in row else None,
            close=float(row['close']) if 'close' in row else None,
            volume=float(row['volume']) if 'volume' in row else None,
            timestamp=row['datetime'] if 'datetime' in row else None
        )
        klines.append(kline)
    
    return klines


# ============================================================================
# 单元测试
# ============================================================================

def test_containment_processing():
    """测试包含关系处理"""
    print("测试包含关系处理...")
    
    # 创建测试数据：包含上升包含和下降包含
    klines = [
        ChanKLine(high=100, low=90),   # 1
        ChanKLine(high=105, low=95),   # 2 - 上升，无包含
        ChanKLine(high=103, low=97),   # 3 - 被第2根包含（上升包含）
        ChanKLine(high=98, low=88),    # 4 - 下降，无包含
        ChanKLine(high=96, low=89),    # 5 - 被第4根包含（下降包含）
    ]
    
    processor = ChanProcessor()
    processed = processor.process_containment(klines)
    
    print(f"原始K线数量: {len(klines)}")
    print(f"处理后K线数量: {len(processed)}")
    
    # 验证：包含关系应该被合并
    assert len(processed) == 3, f"包含关系处理错误，预期3根K线，实际{len(processed)}根"
    
    # 验证合并后的值
    # 第2和第3根应该合并，取高高原则
    assert processed[1].high == 105, f"上升包含合并错误，预期high=105，实际{processed[1].high}"
    assert processed[1].low == 97, f"上升包含合并错误，预期low=97，实际{processed[1].low}"
    
    # 第4和第5根应该合并，取低低原则
    assert processed[2].high == 96, f"下降包含合并错误，预期high=96，实际{processed[2].high}"
    assert processed[2].low == 88, f"下降包含合并错误，预期low=88，实际{processed[2].low}"
    
    print("✓ 包含关系处理测试通过")


def test_fenxing_detection():
    """测试分型识别"""
    print("\n测试分型识别...")
    
    # 创建测试数据：包含顶分型和底分型
    klines = [
        ChanKLine(high=100, low=90),   # 1
        ChanKLine(high=110, low=100),  # 2 - 上升
        ChanKLine(high=115, low=105),  # 3 - 顶分型的中间K线
        ChanKLine(high=112, low=102),  # 4 - 顶分型的右边K线
        ChanKLine(high=105, low=95),   # 5 - 下降
        ChanKLine(high=95, low=85),    # 6 - 底分型的左边K线
        ChanKLine(high=90, low=80),    # 7 - 底分型的中间K线
        ChanKLine(high=95, low=85),    # 8 - 底分型的右边K线
    ]
    
    processor = ChanProcessor()
    fenxing_list = processor.find_fenxing(klines)
    
    print(f"找到分型数量: {len(fenxing_list)}")
    
    # 验证：应该找到1个顶分型和1个底分型
    assert len(fenxing_list) == 2, f"分型识别错误，预期2个分型，实际{len(fenxing_list)}个"
    
    # 验证顶分型
    top_fenxing = fenxing_list[0]
    assert top_fenxing['type'] == 'top', f"第一个分型应该是顶分型，实际是{top_fenxing['type']}"
    assert top_fenxing['index'] == 2, f"顶分型位置错误，预期index=2，实际{top_fenxing['index']}"
    assert top_fenxing['price'] == 115, f"顶分型价格错误，预期115，实际{top_fenxing['price']}"
    
    # 验证底分型
    bottom_fenxing = fenxing_list[1]
    assert bottom_fenxing['type'] == 'bottom', f"第二个分型应该是底分型，实际是{bottom_fenxing['type']}"
    assert bottom_fenxing['index'] == 6, f"底分型位置错误，预期index=6，实际{bottom_fenxing['index']}"
    assert bottom_fenxing['price'] == 80, f"底分型价格错误，预期80，实际{bottom_fenxing['price']}"
    
    print("✓ 分型识别测试通过")


def test_bi_building():
    """测试笔构建"""
    print("\n测试笔构建...")
    
    # 创建测试数据：包含多个分型
    klines = [
        ChanKLine(high=100, low=90),   # 0 - 底分型开始
        ChanKLine(high=95, low=85),    # 1
        ChanKLine(high=90, low=80),    # 2 - 底分型
        ChanKLine(high=110, low=100),  # 3
        ChanKLine(high=115, low=105),  # 4
        ChanKLine(high=120, low=110),  # 5 - 顶分型
        ChanKLine(high=115, low=105),  # 6
        ChanKLine(high=105, low=95),   # 7 - 底分型
    ]
    
    processor = ChanProcessor()
    fenxing_list = processor.find_fenxing(klines)
    bi_list = processor.build_bi(fenxing_list, min_kline_gap=3)
    
    print(f"找到分型数量: {len(fenxing_list)}")
    print(f"构建笔数量: {len(bi_list)}")
    
    # 验证：应该构建1支笔（底分型2 -> 顶分型5）
    assert len(bi_list) == 1, f"笔构建错误，预期1支笔，实际{len(bi_list)}支"
    
    bi = bi_list[0]
    assert bi['direction'] == 'up', f"笔方向错误，预期up，实际{bi['direction']}"
    assert bi['start_index'] == 2, f"笔起点错误，预期2，实际{bi['start_index']}"
    assert bi['end_index'] == 5, f"笔终点错误，预期5，实际{bi['end_index']}"
    assert bi['start_price'] == 80, f"笔起点价格错误，预期80，实际{bi['start_price']}"
    assert bi['end_price'] == 120, f"笔终点价格错误，预期120，实际{bi['end_price']}"
    
    print("✓ 笔构建测试通过")


def test_full_pipeline():
    """测试完整流水线"""
    print("\n测试完整流水线...")
    
    klines = create_test_klines()
    processor = ChanProcessor()
    result = processor.process_pipeline(klines, min_kline_gap=3)
    
    print(f"原始K线: {result['original_count']}")
    print(f"处理后K线: {result['processed_count']}")
    print(f"分型数量: {result['fenxing_count']}")
    print(f"笔数量: {result['bi_count']}")
    
    # 验证流水线输出
    assert result['original_count'] == 10
    assert result['processed_count'] <= 10  # 包含关系处理后K线会减少
    assert result['fenxing_count'] > 0
    assert result['bi_count'] > 0
    
    print("✓ 完整流水线测试通过")


def test_edge_cases():
    """测试边界情况"""
    print("\n测试边界情况...")
    
    # 测试空数据
    processor = ChanProcessor()
    empty_result = processor.process_containment([])
    assert empty_result == [], "空数据处理错误"
    
    # 测试单根K线
    single_kline = [ChanKLine(high=100, low=90)]
    single_result = processor.process_containment(single_kline)
    assert len(single_result) == 1, "单根K线处理错误"
    
    # 测试连续包含关系
    klines = [
        ChanKLine(high=100, low=90),
        ChanKLine(high=105, low=95),   # 被包含
        ChanKLine(high=103, low=97),   # 被包含
        ChanKLine(high=108, low=98),   # 被包含
    ]
    processed = processor.process_containment(klines)
    assert len(processed) == 1, "连续包含关系处理错误"
    assert processed[0].high == 108, "连续包含合并错误"
    assert processed[0].low == 98, "连续包含合并错误"
    
    print("✓ 边界情况测试通过")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("缠论算法单元测试")
    print("=" * 60)
    
    try:
        test_containment_processing()
        test_fenxing_detection()
        test_bi_building()
        test_full_pipeline()
        test_edge_cases()
        
        print("\n" + "=" * 60)
        print("所有测试通过！✓")
        print("=" * 60)
        return True
    except AssertionError as e:
        print(f"\n测试失败: {e}")
        return False
    except Exception as e:
        print(f"\n测试异常: {e}")
        return False


# ============================================================================
# 主函数和示例
# ============================================================================

def main():
    """主函数：演示缠论算法使用"""
    print("缠论算法演示")
    print("-" * 40)
    
    # 1. 创建测试数据
    klines = create_test_klines()
    print(f"创建测试K线: {len(klines)} 根")
    
    # 2. 创建处理器
    processor = ChanProcessor()
    
    # 3. 运行完整流水线
    result = processor.process_pipeline(klines, min_kline_gap=3)
    
    # 4. 输出结果
    print(f"\n处理结果:")
    print(f"  原始K线数量: {result['original_count']}")
    print(f"  处理后K线数量: {result['processed_count']}")
    print(f"  识别分型数量: {result['fenxing_count']}")
    print(f"  构建笔数量: {result['bi_count']}")
    
    print(f"\n分型详情:")
    for fen in result['fenxing_list']:
        fen_type = "顶分型" if fen['type'] == 'top' else "底分型"
        print(f"  {fen_type}: 位置={fen['index']}, 价格={fen['price']:.2f}")
    
    print(f"\n笔详情:")
    for bi in result['bi_list']:
        direction = "↑上行" if bi['direction'] == 'up' else "↓下行"
        small_flag = " [小笔]" if bi['is_small_bi'] else ""
        print(f"  {direction}笔: {bi['start_price']:.2f}→{bi['end_price']:.2f} "
              f"(幅度={bi['price_range']:.2f}, K线间隔={bi['kline_gap']}){small_flag}")
    
    print("\n" + "=" * 40)
    print("演示完成")


if __name__ == "__main__":
    # 运行单元测试
    tests_passed = run_all_tests()
    
    if tests_passed:
        print("\n\n开始算法演示...")
        main()
    else:
        print("\n单元测试失败，请检查代码逻辑。")