"""
天勤数据下载工具 - 图形界面版
"""

import os
import sys
from datetime import datetime
from typing import List

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QDateTimeEdit,
    QProgressBar, QTextEdit, QFileDialog, QGroupBox, QCheckBox,
    QMessageBox, QGridLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from vnpy.trader.constant import Exchange, Interval

from tq_data_downloader import TqDataDownloader


class DownloadThread(QThread):
    """
    下载线程，用于在后台执行下载任务
    """
    
    progress_signal = pyqtSignal(float)  # 进度信号
    log_signal = pyqtSignal(str)  # 日志信号
    finished_signal = pyqtSignal(bool)  # 完成信号
    
    def __init__(
        self,
        account: str,
        password: str,
        symbol_list: str,
        dur_sec: int,
        start_dt: datetime,
        end_dt: datetime,
        csv_file_name: str,
        write_mode: str = 'w',
        adj_type: str = None
    ):
        """
        初始化下载线程
        """
        super().__init__()
        self.account = account
        self.password = password
        self.symbol_list = symbol_list
        self.dur_sec = dur_sec
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.csv_file_name = csv_file_name
        self.write_mode = write_mode
        self.adj_type = adj_type
    
    def run(self):
        """
        执行下载任务
        """
        try:
            downloader = TqDataDownloader(self.account, self.password)
            
            # 重定向print输出
            original_print = print
            
            def custom_print(*args, **kwargs):
                msg = ' '.join(map(str, args))
                self.log_signal.emit(msg)
                original_print(*args, **kwargs)
            
            import builtins
            builtins.print = custom_print
            
            # 执行下载
            success = downloader.download_data(
                symbol_list=self.symbol_list,
                dur_sec=self.dur_sec,
                start_dt=self.start_dt,
                end_dt=self.end_dt,
                csv_file_name=self.csv_file_name,
                write_mode=self.write_mode,
                adj_type=self.adj_type
            )
            
            # 恢复print函数
            builtins.print = original_print
            
            self.finished_signal.emit(success)
        except Exception as e:
            self.log_signal.emit(f"下载异常: {str(e)}")
            self.finished_signal.emit(False)


class ImportThread(QThread):
    """
    导入线程，用于在后台执行导入任务
    """
    
    log_signal = pyqtSignal(str)  # 日志信号
    finished_signal = pyqtSignal(bool)  # 完成信号
    
    def __init__(
        self,
        csv_file_path: str,
        symbol: str,
        exchange: Exchange,
        interval: Interval = None
    ):
        """
        初始化导入线程
        """
        super().__init__()
        self.csv_file_path = csv_file_path
        self.symbol = symbol
        self.exchange = exchange
        self.interval = interval
    
    def run(self):
        """
        执行导入任务
        """
        try:
            downloader = TqDataDownloader()
            
            # 重定向print输出
            original_print = print
            
            def custom_print(*args, **kwargs):
                msg = ' '.join(map(str, args))
                self.log_signal.emit(msg)
                original_print(*args, **kwargs)
            
            import builtins
            builtins.print = custom_print
            
            # 执行导入
            success = downloader.import_to_vnpy(
                csv_file_path=self.csv_file_path,
                symbol=self.symbol,
                exchange=self.exchange,
                interval=self.interval
            )
            
            # 恢复print函数
            builtins.print = original_print
            
            self.finished_signal.emit(success)
        except Exception as e:
            self.log_signal.emit(f"导入异常: {str(e)}")
            self.finished_signal.emit(False)


class TqDataDownloaderGUI(QMainWindow):
    """
    天勤数据下载工具图形界面
    """
    
    def __init__(self):
        """
        初始化界面
        """
        super().__init__()
        self.init_ui()
        self.download_thread = None
        self.import_thread = None
    
    def init_ui(self):
        """
        初始化界面组件
        """
        # 设置窗口标题和大小
        self.setWindowTitle("天勤数据下载工具")
        self.resize(800, 700)
        
        # 设置主布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # 标题标签
        title_label = QLabel("天勤数据下载工具")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 1. 登录信息组
        login_group = QGroupBox("登录信息")
        login_layout = QHBoxLayout()
        
        login_layout.addWidget(QLabel("天勤账号:"))
        self.account_edit = QLineEdit()
        login_layout.addWidget(self.account_edit)
        
        login_layout.addWidget(QLabel("密码:"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        login_layout.addWidget(self.password_edit)
        
        login_group.setLayout(login_layout)
        main_layout.addWidget(login_group)
        
        # 2. 合约信息组
        contract_group = QGroupBox("合约信息")
        contract_layout = QGridLayout()
        
        # 合约代码
        contract_layout.addWidget(QLabel("合约代码:"), 0, 0)
        self.symbol_edit = QLineEdit()
        self.symbol_edit.setPlaceholderText("如: SHFE.cu2305")
        contract_layout.addWidget(self.symbol_edit, 0, 1)
        
        # 交易所
        contract_layout.addWidget(QLabel("交易所:"), 0, 2)
        self.exchange_combo = QComboBox()
        for exchange in Exchange:
            self.exchange_combo.addItem(exchange.value, exchange)
        contract_layout.addWidget(self.exchange_combo, 0, 3)
        
        # 周期选择
        contract_layout.addWidget(QLabel("数据周期:"), 1, 0)
        self.interval_combo = QComboBox()
        self.interval_map = {
            "tick": 0,
            "1分钟": 60,
            "5分钟": 300,
            "15分钟": 900,
            "30分钟": 1800,
            "1小时": 3600,
            "2小时": 7200,
            "4小时": 14400,
            "日线": 86400
        }
        for name in self.interval_map:
            self.interval_combo.addItem(name, self.interval_map[name])
        contract_layout.addWidget(self.interval_combo, 1, 1)
        
        contract_group.setLayout(contract_layout)
        main_layout.addWidget(contract_group)
        
        # 3. 时间范围组
        time_group = QGroupBox("时间范围")
        time_layout = QHBoxLayout()
        
        time_layout.addWidget(QLabel("起始时间:"))
        self.start_time_edit = QDateTimeEdit()
        self.start_time_edit.setDateTime(datetime.now().replace(hour=0, minute=0, second=0))
        self.start_time_edit.setCalendarPopup(True)
        self.start_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        time_layout.addWidget(self.start_time_edit)
        
        time_layout.addWidget(QLabel("结束时间:"))
        self.end_time_edit = QDateTimeEdit()
        self.end_time_edit.setDateTime(datetime.now().replace(hour=23, minute=59, second=59))
        self.end_time_edit.setCalendarPopup(True)
        self.end_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        time_layout.addWidget(self.end_time_edit)
        
        time_group.setLayout(time_layout)
        main_layout.addWidget(time_group)
        
        # 4. 输出设置组
        output_group = QGroupBox("输出设置")
        output_layout = QGridLayout()
        
        # 保存路径
        output_layout.addWidget(QLabel("保存路径:"), 0, 0)
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("选择保存文件路径")
        output_layout.addWidget(self.output_path_edit, 0, 1)
        
        browse_button = QPushButton("浏览")
        browse_button.clicked.connect(self.browse_file)
        output_layout.addWidget(browse_button, 0, 2)
        
        # 写入模式
        output_layout.addWidget(QLabel("写入模式:"), 1, 0)
        self.write_mode_combo = QComboBox()
        self.write_mode_combo.addItem("覆盖 (w)", "w")
        self.write_mode_combo.addItem("追加 (a)", "a")
        output_layout.addWidget(self.write_mode_combo, 1, 1)
        
        output_group.setLayout(output_layout)
        main_layout.addWidget(output_group)
        
        # 5. 导入设置组
        import_group = QGroupBox("导入设置")
        import_layout = QGridLayout()
        
        # 是否导入到数据库
        self.import_check = QCheckBox("导入到VNPY数据库")
        import_layout.addWidget(self.import_check, 0, 0, 1, 2)
        
        # VNPY合约代码
        import_layout.addWidget(QLabel("VNPY合约代码:"), 1, 0)
        self.vnpy_symbol_edit = QLineEdit()
        self.vnpy_symbol_edit.setPlaceholderText("如: cu2305")
        import_layout.addWidget(self.vnpy_symbol_edit, 1, 1)
        
        import_group.setLayout(import_layout)
        main_layout.addWidget(import_group)
        
        # 6. 操作按钮组
        button_layout = QHBoxLayout()
        
        self.download_button = QPushButton("开始下载")
        self.download_button.clicked.connect(self.start_download)
        button_layout.addWidget(self.download_button)
        
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.cancel_download)
        self.cancel_button.setEnabled(False)
        button_layout.addWidget(self.cancel_button)
        
        exit_button = QPushButton("退出")
        exit_button.clicked.connect(self.close)
        button_layout.addWidget(exit_button)
        
        main_layout.addLayout(button_layout)
        
        # 7. 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)
        
        # 8. 日志输出
        log_group = QGroupBox("日志输出")
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        log_layout.addWidget(self.log_text)
        
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)
        
        # 调整布局间距
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
    
    def browse_file(self):
        """
        浏览文件路径
        """
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "选择保存文件",
            os.getcwd(),
            "CSV Files (*.csv);;All Files (*)"
        )
        if file_path:
            self.output_path_edit.setText(file_path)
    
    def start_download(self):
        """
        开始下载
        """
        # 验证输入
        if not self.validate_input():
            return
        
        # 获取参数
        account = self.account_edit.text().strip()
        password = self.password_edit.text().strip()
        symbol = self.symbol_edit.text().strip()
        dur_sec = self.interval_combo.currentData()
        start_dt = self.start_time_edit.dateTime().toPyDateTime()
        end_dt = self.end_time_edit.dateTime().toPyDateTime()
        output_path = self.output_path_edit.text().strip()
        write_mode = self.write_mode_combo.currentData()
        
        # 禁用按钮
        self.download_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        
        # 清空日志
        self.log_text.clear()
        self.progress_bar.setValue(0)
        
        # 记录开始时间
        self.log(f"开始下载数据...")
        self.log(f"合约: {symbol}")
        self.log(f"周期: {self.interval_combo.currentText()}")
        self.log(f"时间范围: {start_dt} 到 {end_dt}")
        self.log(f"保存路径: {output_path}")
        
        # 创建下载线程
        self.download_thread = DownloadThread(
            account=account,
            password=password,
            symbol_list=symbol,
            dur_sec=dur_sec,
            start_dt=start_dt,
            end_dt=end_dt,
            csv_file_name=output_path,
            write_mode=write_mode
        )
        
        # 连接信号
        self.download_thread.progress_signal.connect(self.update_progress)
        self.download_thread.log_signal.connect(self.log)
        self.download_thread.finished_signal.connect(self.download_finished)
        
        # 启动线程
        self.download_thread.start()
    
    def cancel_download(self):
        """
        取消下载
        """
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.terminate()
            self.download_thread.wait()
            self.log("下载已取消")
            self.reset_ui()
    
    def download_finished(self, success: bool):
        """
        下载完成处理
        """
        if success:
            self.log("下载完成！")
            
            # 检查是否需要导入到数据库
            if self.import_check.isChecked():
                self.start_import()
            else:
                self.reset_ui()
        else:
            self.log("下载失败！")
            self.reset_ui()
    
    def start_import(self):
        """
        开始导入到数据库
        """
        # 获取参数
        output_path = self.output_path_edit.text().strip()
        vnpy_symbol = self.vnpy_symbol_edit.text().strip()
        exchange = self.exchange_combo.currentData()
        
        # 确定周期
        interval_str = self.interval_combo.currentText()
        interval = None
        if interval_str != "tick":
            interval_map = {
                "1分钟": "1m",
                "5分钟": "5m",
                "15分钟": "15m",
                "30分钟": "30m",
                "1小时": "1h",
                "2小时": "2h",
                "4小时": "4h",
                "日线": "d"
            }
            interval = Interval(interval_map[interval_str])
        
        self.log("开始导入到VNPY数据库...")
        
        # 创建导入线程
        self.import_thread = ImportThread(
            csv_file_path=output_path,
            symbol=vnpy_symbol,
            exchange=exchange,
            interval=interval
        )
        
        # 连接信号
        self.import_thread.log_signal.connect(self.log)
        self.import_thread.finished_signal.connect(self.import_finished)
        
        # 启动线程
        self.import_thread.start()
    
    def import_finished(self, success: bool):
        """
        导入完成处理
        """
        if success:
            self.log("导入数据库完成！")
        else:
            self.log("导入数据库失败！")
        
        self.reset_ui()
    
    def update_progress(self, progress: float):
        """
        更新进度条
        """
        self.progress_bar.setValue(int(progress))
    
    def log(self, message: str):
        """
        记录日志
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        # 自动滚动到底部
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
    
    def validate_input(self) -> bool:
        """
        验证输入参数
        
        Returns:
            是否验证通过
        """
        # 验证合约代码
        symbol = self.symbol_edit.text().strip()
        if not symbol:
            QMessageBox.warning(self, "警告", "请输入合约代码")
            return False
        
        # 验证保存路径
        output_path = self.output_path_edit.text().strip()
        if not output_path:
            QMessageBox.warning(self, "警告", "请选择保存路径")
            return False
        
        # 验证导入设置
        if self.import_check.isChecked():
            vnpy_symbol = self.vnpy_symbol_edit.text().strip()
            if not vnpy_symbol:
                QMessageBox.warning(self, "警告", "请输入VNPY合约代码")
                return False
        
        # 验证时间范围
        start_dt = self.start_time_edit.dateTime().toPyDateTime()
        end_dt = self.end_time_edit.dateTime().toPyDateTime()
        if start_dt > end_dt:
            QMessageBox.warning(self, "警告", "起始时间不能大于结束时间")
            return False
        
        return True
    
    def reset_ui(self):
        """
        重置UI状态
        """
        self.download_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress_bar.setValue(0)
    
    def closeEvent(self, event):
        """
        关闭窗口事件
        """
        # 确保线程已停止
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.terminate()
            self.download_thread.wait()
        
        if self.import_thread and self.import_thread.isRunning():
            self.import_thread.terminate()
            self.import_thread.wait()
        
        event.accept()


def main():
    """
    主函数
    """
    app = QApplication(sys.argv)
    window = TqDataDownloaderGUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
