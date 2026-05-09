#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测报告导出模块
支持导出Excel格式的回测报告
"""

import os
import io
from datetime import datetime
from typing import Dict, Any, List, Optional

# 尝试导入 openpyxl，如果不可用则使用 xlsxwriter
try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    from openpyxl.utils import get_column_letter
    EXPORT_LIBRARY = 'openpyxl'
except ImportError:
    try:
        import xlsxwriter
        EXPORT_LIBRARY = 'xlsxwriter'
    except ImportError:
        EXPORT_LIBRARY = None


class BacktestExporter:
    """回测报告导出器"""

    def __init__(self, result: Dict[str, Any]):
        """
        初始化导出器
        :param result: 回测结果字典
        """
        self.result = result
        self.statistics = result.get('statistics', {})
        self.trades = result.get('trades', [])
        self.equity_curve = result.get('equity_curve', [])
        self.trade_entries = result.get('trade_entries', [])

    def to_excel(self, filepath: Optional[str] = None) -> bytes:
        """
        导出为Excel文件
        :param filepath: 保存路径，如果为None则返回bytes
        :return: Excel文件bytes或保存路径
        """
        if EXPORT_LIBRARY == 'openpyxl':
            return self._export_openpyxl(filepath)
        elif EXPORT_LIBRARY == 'xlsxwriter':
            return self._export_xlsxwriter(filepath)
        else:
            raise ImportError("需要安装 openpyxl 或 xlsxwriter 库来导出Excel")

    def _export_openpyxl(self, filepath: Optional[str] = None) -> bytes:
        """使用 openpyxl 导出"""
        wb = Workbook()
        
        # 样式定义
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        # 1. 概要 sheet
        ws_summary = wb.active
        ws_summary.title = "回测概要"
        self._write_summary_sheet(ws_summary, header_font, header_fill, thin_border)
        
        # 2. 绩效指标 sheet
        ws_metrics = wb.create_sheet("绩效指标")
        self._write_metrics_sheet(ws_metrics, header_font, header_fill, thin_border)
        
        # 3. 交易明细 sheet
        ws_trades = wb.create_sheet("交易明细")
        self._write_trades_sheet(ws_trades, header_font, header_fill, thin_border)
        
        # 4. 权益曲线 sheet
        ws_equity = wb.create_sheet("权益曲线")
        self._write_equity_sheet(ws_equity, header_font, header_fill, thin_border)
        
        # 保存
        if filepath:
            wb.save(filepath)
            return filepath.encode() if isinstance(filepath, str) else filepath
        else:
            buffer = io.BytesIO()
            wb.save(buffer)
            return buffer.getvalue()

    def _export_xlsxwriter(self, filepath: Optional[str] = None) -> bytes:
        """使用 xlsxwriter 导出"""
        if filepath:
            workbook = xlsxwriter.Workbook(filepath)
        else:
            workbook = xlsxwriter.Workbook(io.BytesIO())
        
        # 1. 概要 sheet
        ws_summary = workbook.add_worksheet("回测概要")
        self._write_summary_xlsxwriter(workbook, ws_summary)
        
        # 2. 绩效指标 sheet
        ws_metrics = workbook.add_worksheet("绩效指标")
        self._write_metrics_xlsxwriter(workbook, ws_metrics)
        
        # 3. 交易明细 sheet
        ws_trades = workbook.add_worksheet("交易明细")
        self._write_trades_xlsxwriter(workbook, ws_trades)
        
        # 4. 权益曲线 sheet
        ws_equity = workbook.add_worksheet("权益曲线")
        self._write_equity_xlsxwriter(workbook, ws_equity)
        
        workbook.close()
        
        if filepath:
            return filepath.encode() if isinstance(filepath, str) else filepath
        else:
            buffer = workbook
            return buffer
        
    def _write_summary_sheet(self, ws, header_font, header_fill, thin_border):
        """写入概要 sheet"""
        # 标题
        ws['A1'] = '回测报告'
        ws['A1'].font = Font(bold=True, size=16)
        ws.merge_cells('A1:C1')
        
        # 基本信息
        ws['A3'] = '项目'
        ws['B3'] = '值'
        for cell in [ws['A3'], ws['B3']]:
            cell.font = header_font
            cell.fill = header_fill
        
        info = [
            ('策略名称', self.result.get('strategy_name', 'N/A')),
            ('初始资金', f"{self.result.get('initial_balance', 0):,.2f}"),
            ('最终权益', f"{self.result.get('final_balance', 0):,.2f}"),
            ('总收益率', f"{self.statistics.get('total_return', 0):.2f}%"),
            ('交易次数', self.statistics.get('total_trades', 0)),
            ('生成时间', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        ]
        
        for i, (label, value) in enumerate(info, start=4):
            ws[f'A{i}'] = label
            ws[f'B{i}'] = value
        
        # 设置列宽
        ws.column_dimensions['A'].width = 15
        ws.column_dimensions['B'].width = 20

    def _write_metrics_sheet(self, ws, header_font, header_fill, thin_border):
        """写入绩效指标 sheet"""
        ws['A1'] = '绩效指标'
        ws['A1'].font = Font(bold=True, size=14)
        
        ws['A3'] = '指标名称'
        ws['B3'] = '数值'
        ws['C3'] = '说明'
        for cell in [ws['A3'], ws['B3'], ws['C3']]:
            cell.font = header_font
            cell.fill = header_fill
        
        metrics = [
            ('总交易次数', self.statistics.get('total_trades', 0), '总执行交易数'),
            ('盈利次数', self.statistics.get('win_count', 0), '盈利交易数量'),
            ('亏损次数', self.statistics.get('loss_count', 0), '亏损交易数量'),
            ('胜率', f"{self.statistics.get('win_rate', 0):.2f}%", '盈利交易/总交易'),
            ('平均盈利', f"{self.statistics.get('avg_win', 0):.2f}", '平均盈利金额'),
            ('平均亏损', f"{self.statistics.get('avg_loss', 0):.2f}", '平均亏损金额'),
            ('盈亏比', self.statistics.get('profit_factor', 0), '平均盈利/平均亏损'),
            ('总盈亏', f"{self.statistics.get('total_pnl', 0):.2f}", '总盈利-总亏损'),
            ('年化收益率', f"{self.statistics.get('annual_return', 0):.2f}%", '年化收益'),
            ('日均盈亏', f"{self.statistics.get('daily_pnl', 0):.2f}", '日均盈亏金额'),
            ('最大回撤', f"{self.statistics.get('max_drawdown', 0):.2f}", '最大回撤金额'),
            ('最大回撤率', f"{self.statistics.get('max_drawdown_pct', 0):.2f}%", '最大回撤比例'),
            ('夏普比率', self.statistics.get('sharpe_ratio', 0), '风险调整收益'),
            ('索提诺比率', self.statistics.get('sortino_ratio', 0), '下行风险调整收益'),
            ('卡尔玛比率', self.statistics.get('calmar_ratio', 0), '年化收益/最大回撤'),
            ('最大连续亏损', self.statistics.get('max_consecutive_losses', 0), '最大连续亏损次数'),
            ('最大连续盈利', self.statistics.get('max_consecutive_wins', 0), '最大连续盈利次数'),
            ('止损次数', self.statistics.get('stop_loss_count', 0), '触发止损次数'),
            ('止盈次数', self.statistics.get('take_profit_count', 0), '触发止盈次数'),
            ('主动平仓次数', self.statistics.get('close_count', 0), '信号平仓次数'),
        ]
        
        for i, (name, value, desc) in enumerate(metrics, start=4):
            ws[f'A{i}'] = name
            ws[f'B{i}'] = value
            ws[f'C{i}'] = desc
        
        ws.column_dimensions['A'].width = 18
        ws.column_dimensions['B'].width = 15
        ws.column_dimensions['C'].width = 25

    def _write_trades_sheet(self, ws, header_font, header_fill, thin_border):
        """写入交易明细 sheet"""
        ws['A1'] = '交易明细'
        ws['A1'].font = Font(bold=True, size=14)
        
        headers = ['交易ID', '方向', '入场时间', '入场价格', '出场时间', '出场价格', 
                   '数量', '盈亏', '盈亏%', '止损', '止盈', '出场原因', '入场Bar', '出场Bar']
        
        for col, header in enumerate(headers, start=1):
            cell = ws.cell(row=3, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
        
        for row, trade in enumerate(self.trades, start=4):
            ws.cell(row=row, column=1, value=trade.get('trade_id', ''))
            ws.cell(row=row, column=2, value='多' if trade.get('direction') == 'long' else '空')
            ws.cell(row=row, column=3, value=trade.get('entry_time', ''))
            ws.cell(row=row, column=4, value=trade.get('entry_price', 0))
            ws.cell(row=row, column=5, value=trade.get('exit_time', ''))
            ws.cell(row=row, column=6, value=trade.get('exit_price', 0))
            ws.cell(row=row, column=7, value=trade.get('quantity', 1))
            ws.cell(row=row, column=8, value=trade.get('pnl', 0))
            ws.cell(row=row, column=9, value=f"{trade.get('pnl_pct', 0):.2f}%")
            ws.cell(row=row, column=10, value=trade.get('stop_loss', ''))
            ws.cell(row=row, column=11, value=trade.get('take_profit', ''))
            ws.cell(row=row, column=12, value=trade.get('exit_reason', ''))
            ws.cell(row=row, column=13, value=trade.get('entry_bar_index', -1))
            ws.cell(row=row, column=14, value=trade.get('exit_bar_index', -1))
            
            # 盈亏着色
            pnl = trade.get('pnl', 0)
            if pnl > 0:
                ws.cell(row=row, column=8).font = Font(color="00B050")  # 绿色
            elif pnl < 0:
                ws.cell(row=row, column=8).font = Font(color="FF0000")  # 红色
        
        # 设置列宽
        for col in range(1, 15):
            ws.column_dimensions[get_column_letter(col)].width = 14

    def _write_equity_sheet(self, ws, header_font, header_fill, thin_border):
        """写入权益曲线 sheet"""
        ws['A1'] = '权益曲线'
        ws['A1'].font = Font(bold=True, size=14)
        
        headers = ['时间', '余额', '持仓状态', '价格']
        
        for col, header in enumerate(headers, start=1):
            cell = ws.cell(row=3, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
        
        for row, point in enumerate(self.equity_curve, start=4):
            ws.cell(row=row, column=1, value=point.get('time', ''))
            ws.cell(row=row, column=2, value=point.get('balance', 0))
            ws.cell(row=row, column=3, value=point.get('position', ''))
            ws.cell(row=row, column=4, value=point.get('price', 0))
        
        ws.column_dimensions['A'].width = 20
        ws.column_dimensions['B'].width = 15
        ws.column_dimensions['C'].width = 12
        ws.column_dimensions['D'].width = 12

    # ========== xlsxwriter 导出方法 ==========
    
    def _write_summary_xlsxwriter(self, workbook, ws):
        """写入概要 sheet (xlsxwriter)"""
        title_format = workbook.add_format({'bold': True, 'font_size': 16})
        header_format = workbook.add_format({'bold': True, 'font_color': 'white', 
                                            'bg_color': '#4472C4'})
        
        ws.write('A1', '回测报告', title_format)
        ws.merge_cells('A1:C1')
        
        ws.write('A3', '项目')
        ws.write('B3', '值')
        ws.write('A3', '项目', header_format)
        ws.write('B3', '值', header_format)
        
        info = [
            ('策略名称', self.result.get('strategy_name', 'N/A')),
            ('初始资金', f"{self.result.get('initial_balance', 0):,.2f}"),
            ('最终权益', f"{self.result.get('final_balance', 0):,.2f}"),
            ('总收益率', f"{self.statistics.get('total_return', 0):.2f}%"),
            ('交易次数', self.statistics.get('total_trades', 0)),
            ('生成时间', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        ]
        
        for i, (label, value) in enumerate(info, start=4):
            ws.write(f'A{i}', label)
            ws.write(f'B{i}', value)
        
        ws.set_column('A:A', 15)
        ws.set_column('B:B', 20)

    def _write_metrics_xlsxwriter(self, workbook, ws):
        """写入绩效指标 sheet (xlsxwriter)"""
        title_format = workbook.add_format({'bold': True, 'font_size': 14})
        header_format = workbook.add_format({'bold': True, 'font_color': 'white', 
                                            'bg_color': '#4472C4'})
        
        ws.write('A1', '绩效指标', title_format)
        
        ws.write('A3', '指标名称')
        ws.write('B3', '数值')
        ws.write('C3', '说明')
        for col in ['A3', 'B3', 'C3']:
            ws.write(col, col, header_format)
        
        metrics = [
            ('总交易次数', self.statistics.get('total_trades', 0), '总执行交易数'),
            ('盈利次数', self.statistics.get('win_count', 0), '盈利交易数量'),
            ('亏损次数', self.statistics.get('loss_count', 0), '亏损交易数量'),
            ('胜率', f"{self.statistics.get('win_rate', 0):.2f}%", '盈利交易/总交易'),
            ('平均盈利', f"{self.statistics.get('avg_win', 0):.2f}", '平均盈利金额'),
            ('平均亏损', f"{self.statistics.get('avg_loss', 0):.2f}", '平均亏损金额'),
            ('盈亏比', self.statistics.get('profit_factor', 0), '平均盈利/平均亏损'),
            ('总盈亏', f"{self.statistics.get('total_pnl', 0):.2f}", '总盈利-总亏损'),
            ('年化收益率', f"{self.statistics.get('annual_return', 0):.2f}%", '年化收益'),
            ('日均盈亏', f"{self.statistics.get('daily_pnl', 0):.2f}", '日均盈亏金额'),
            ('最大回撤', f"{self.statistics.get('max_drawdown', 0):.2f}", '最大回撤金额'),
            ('最大回撤率', f"{self.statistics.get('max_drawdown_pct', 0):.2f}%", '最大回撤比例'),
            ('夏普比率', self.statistics.get('sharpe_ratio', 0), '风险调整收益'),
            ('索提诺比率', self.statistics.get('sortino_ratio', 0), '下行风险调整收益'),
            ('卡尔玛比率', self.statistics.get('calmar_ratio', 0), '年化收益/最大回撤'),
        ]
        
        for i, (name, value, desc) in enumerate(metrics, start=4):
            ws.write(f'A{i}', name)
            ws.write(f'B{i}', value)
            ws.write(f'C{i}', desc)
        
        ws.set_column('A:A', 18)
        ws.set_column('B:B', 15)
        ws.set_column('C:C', 25)

    def _write_trades_xlsxwriter(self, workbook, ws):
        """写入交易明细 sheet (xlsxwriter)"""
        title_format = workbook.add_format({'bold': True, 'font_size': 14})
        header_format = workbook.add_format({'bold': True, 'font_color': 'white', 
                                            'bg_color': '#4472C4'})
        green_format = workbook.add_format({'font_color': '00B050'})
        red_format = workbook.add_format({'font_color': 'FF0000'})
        
        ws.write('A1', '交易明细', title_format)
        
        headers = ['交易ID', '方向', '入场时间', '入场价格', '出场时间', '出场价格', 
                   '数量', '盈亏', '盈亏%', '止损', '止盈', '出场原因']
        
        for col, header in enumerate(headers, start=0):
            ws.write(3, col, header, header_format)
        
        for row, trade in enumerate(self.trades, start=4):
            ws.write(row, 0, trade.get('trade_id', ''))
            ws.write(row, 1, '多' if trade.get('direction') == 'long' else '空')
            ws.write(row, 2, trade.get('entry_time', ''))
            ws.write(row, 3, trade.get('entry_price', 0))
            ws.write(row, 4, trade.get('exit_time', ''))
            ws.write(row, 5, trade.get('exit_price', 0))
            ws.write(row, 6, trade.get('quantity', 1))
            
            pnl = trade.get('pnl', 0)
            if pnl > 0:
                ws.write(row, 7, pnl, green_format)
            elif pnl < 0:
                ws.write(row, 7, pnl, red_format)
            else:
                ws.write(row, 7, pnl)
                
            ws.write(row, 8, f"{trade.get('pnl_pct', 0):.2f}%")
            ws.write(row, 9, trade.get('stop_loss', ''))
            ws.write(row, 10, trade.get('take_profit', ''))
            ws.write(row, 11, trade.get('exit_reason', ''))
        
        for col_width in [14, 8, 20, 12, 20, 12, 8, 12, 10, 10, 10, 12]:
            pass  # 已通过下面的方式设置
        ws.set_column(0, 0, 14)
        ws.set_column(1, 1, 8)
        ws.set_column(2, 2, 20)
        ws.set_column(3, 3, 12)
        ws.set_column(4, 4, 20)
        ws.set_column(5, 5, 12)
        ws.set_column(6, 6, 8)
        ws.set_column(7, 7, 12)
        ws.set_column(8, 8, 10)
        ws.set_column(9, 9, 10)
        ws.set_column(10, 10, 10)
        ws.set_column(11, 11, 12)

    def _write_equity_xlsxwriter(self, workbook, ws):
        """写入权益曲线 sheet (xlsxwriter)"""
        title_format = workbook.add_format({'bold': True, 'font_size': 14})
        header_format = workbook.add_format({'bold': True, 'font_color': 'white', 
                                            'bg_color': '#4472C4'})
        
        ws.write('A1', '权益曲线', title_format)
        
        headers = ['时间', '余额', '持仓状态', '价格']
        for col, header in enumerate(headers, start=0):
            ws.write(3, col, header, header_format)
        
        for row, point in enumerate(self.equity_curve, start=4):
            ws.write(row, 0, point.get('time', ''))
            ws.write(row, 1, point.get('balance', 0))
            ws.write(row, 2, point.get('position', ''))
            ws.write(row, 3, point.get('price', 0))
        
        ws.set_column('A:A', 20)
        ws.set_column('B:B', 15)
        ws.set_column('C:C', 12)
        ws.set_column('D:D', 12)

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典格式"""
        return {
            'summary': {
                'strategy_name': self.result.get('strategy_name', 'N/A'),
                'initial_balance': self.result.get('initial_balance', 0),
                'final_balance': self.result.get('final_balance', 0),
                'total_return': self.statistics.get('total_return', 0),
                'total_trades': self.statistics.get('total_trades', 0),
            },
            'statistics': self.statistics,
            'trades': self.trades,
            'equity_curve': self.equity_curve,
        }

    def to_json_string(self) -> str:
        """导出为JSON字符串"""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
