"""
天勤数据下载工具
支持通过公共函数调用和单独运行
"""

import os
import csv
import argparse
from datetime import datetime, date
from typing import List, Dict, Any, Union
from contextlib import closing

from tqsdk import TqApi, TqAuth
from tqsdk.tools import DataDownloader

from vnpy.trader.object import BarData, TickData
from vnpy.trader.constant import Exchange, Interval

# 尝试导入数据库管理器，如果失败则禁用数据库功能
try:
    from vnpy.trader.database import database_manager
    DATABASE_AVAILABLE = True
except ImportError:
    database_manager = None
    DATABASE_AVAILABLE = False


class TqDataDownloader:
    """
    天勤数据下载器
    """
    
    def __init__(self, account: str = "", password: str = ""):
        """
        初始化下载器
        
        Args:
            account: 天勤账号
            password: 天勤密码
        """
        self.account = account
        self.password = password
        self.api = None
    
    def download_data(
        self,
        symbol_list: Union[str, List[str]],
        dur_sec: int,
        start_dt: Union[date, datetime],
        end_dt: Union[date, datetime],
        csv_file_name: str,
        write_mode: str = 'w',
        adj_type: str = None
    ) -> bool:
        """
        下载数据到CSV文件
        
        Args:
            symbol_list: 合约代码列表
            dur_sec: 数据周期（秒），0为tick数据
            start_dt: 起始时间
            end_dt: 结束时间
            csv_file_name: 输出文件名
            write_mode: 写入模式
            adj_type: 复权类型
            
        Returns:
            是否下载成功
        """
        try:
            # 创建API实例
            if self.account and self.password:
                self.api = TqApi(auth=TqAuth(self.account, self.password))
            else:
                self.api = TqApi()
            
            # 创建下载任务
            downloader = DataDownloader(
                api=self.api,
                symbol_list=symbol_list,
                dur_sec=dur_sec,
                start_dt=start_dt,
                end_dt=end_dt,
                csv_file_name=csv_file_name,
                write_mode=write_mode,
                adj_type=adj_type
            )
            
            # 执行下载
            with closing(self.api):
                while not downloader.is_finished():
                    self.api.wait_update()
                    progress = downloader.get_progress()
                    print(f"下载进度: {progress:.2f}%")
            
            print(f"\n数据下载完成，保存到: {csv_file_name}")
            return True
        except Exception as e:
            print(f"下载失败: {str(e)}")
            return False
    
    def import_to_vnpy(
        self,
        csv_file_path: str,
        symbol: str,
        exchange: Exchange,
        interval: Interval = None
    ) -> bool:
        """
        导入CSV数据到VNPY数据库
        
        Args:
            csv_file_path: CSV文件路径
            symbol: 合约代码
            exchange: 交易所
            interval: K线周期（tick数据不需要）
            
        Returns:
            是否导入成功
        """
        # 检查数据库功能是否可用
        if not DATABASE_AVAILABLE:
            print("数据库功能不可用，请确保已正确安装VNPY数据库模块")
            return False
        
        try:
            # 读取CSV文件
            with open(csv_file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            
            if not rows:
                print("CSV文件为空")
                return False
            
            # 判断数据类型：tick数据或K线数据
            is_tick = 'last_price' in rows[0] and 'bid_price1' in rows[0]
            
            if is_tick:
                # 导入tick数据
                tick_list = []
                for row in rows:
                    tick = TickData(
                        symbol=symbol,
                        exchange=exchange,
                        datetime=datetime.strptime(row['datetime'], '%Y-%m-%d %H:%M:%S.%f'),
                        name=symbol,
                        volume=int(float(row.get('volume', 0))),
                        turnover=float(row.get('turnover', 0)),
                        open_interest=int(float(row.get('open_interest', 0))),
                        last_price=float(row['last_price']),
                        limit_up=float(row.get('upper_limit', 0)),
                        limit_down=float(row.get('lower_limit', 0)),
                        open_price=float(row.get('open', 0)),
                        high_price=float(row.get('high', 0)),
                        low_price=float(row.get('low', 0)),
                        pre_close=float(row.get('pre_close', 0)),
                        bid_price_1=float(row.get('bid_price1', 0)),
                        bid_volume_1=int(float(row.get('bid_volume1', 0))),
                        ask_price_1=float(row.get('ask_price1', 0)),
                        ask_volume_1=int(float(row.get('ask_volume1', 0))),
                        bid_price_2=float(row.get('bid_price2', 0)),
                        bid_volume_2=int(float(row.get('bid_volume2', 0))),
                        ask_price_2=float(row.get('ask_price2', 0)),
                        ask_volume_2=int(float(row.get('ask_volume2', 0))),
                        bid_price_3=float(row.get('bid_price3', 0)),
                        bid_volume_3=int(float(row.get('bid_volume3', 0))),
                        ask_price_3=float(row.get('ask_price3', 0)),
                        ask_volume_3=int(float(row.get('ask_volume3', 0))),
                        bid_price_4=float(row.get('bid_price4', 0)),
                        bid_volume_4=int(float(row.get('bid_volume4', 0))),
                        ask_price_4=float(row.get('ask_price4', 0)),
                        ask_volume_4=int(float(row.get('ask_volume4', 0))),
                        bid_price_5=float(row.get('bid_price5', 0)),
                        bid_volume_5=int(float(row.get('bid_volume5', 0))),
                        ask_price_5=float(row.get('ask_price5', 0)),
                        ask_volume_5=int(float(row.get('ask_volume5', 0))),
                        gateway_name="TQSDK"
                    )
                    tick_list.append(tick)
                
                # 批量插入数据库
                database_manager.save_tick_data(tick_list)
                print(f"成功导入 {len(tick_list)} 条tick数据")
            else:
                # 导入K线数据
                if not interval:
                    print("导入K线数据需要指定interval参数")
                    return False
                
                bar_list = []
                for row in rows:
                    bar = BarData(
                        symbol=symbol,
                        exchange=exchange,
                        datetime=datetime.strptime(row['datetime'], '%Y-%m-%d %H:%M:%S'),
                        interval=interval,
                        volume=int(float(row.get('volume', 0))),
                        turnover=float(row.get('turnover', 0)),
                        open_interest=int(float(row.get('open_interest', 0))),
                        open_price=float(row['open']),
                        high_price=float(row['high']),
                        low_price=float(row['low']),
                        close_price=float(row['close']),
                        gateway_name="TQSDK"
                    )
                    bar_list.append(bar)
                
                # 批量插入数据库
                database_manager.save_bar_data(bar_list)
                print(f"成功导入 {len(bar_list)} 条K线数据")
            
            return True
        except Exception as e:
            print(f"导入数据库失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return False


def download_tq_data(
    symbol_list: Union[str, List[str]],
    dur_sec: int,
    start_dt: Union[date, datetime],
    end_dt: Union[date, datetime],
    csv_file_name: str,
    account: str = "",
    password: str = "",
    write_mode: str = 'w',
    adj_type: str = None
) -> bool:
    """
    公共函数：下载天勤数据
    
    Args:
        symbol_list: 合约代码列表，格式如"SHFE.cu2305"或["SHFE.cu2305", "SHFE.cu2306"]
        dur_sec: 数据周期（秒），0为tick数据
        start_dt: 起始时间，支持date或datetime对象
        end_dt: 结束时间，支持date或datetime对象
        csv_file_name: 输出CSV文件名
        account: 天勤账号（可选）
        password: 天勤密码（可选）
        write_mode: 写入模式，默认为'w'（覆盖）
        adj_type: 复权类型，默认为None
        
    Returns:
        是否下载成功
    """
    downloader = TqDataDownloader(account, password)
    return downloader.download_data(
        symbol_list=symbol_list,
        dur_sec=dur_sec,
        start_dt=start_dt,
        end_dt=end_dt,
        csv_file_name=csv_file_name,
        write_mode=write_mode,
        adj_type=adj_type
    )


def import_tq_data_to_vnpy(
    csv_file_path: str,
    symbol: str,
    exchange: str,
    interval: str = None
) -> bool:
    """
    公共函数：导入天勤数据到VNPY数据库
    
    Args:
        csv_file_path: CSV文件路径
        symbol: 合约代码，如"cu2305"
        exchange: 交易所，如"SHFE"
        interval: K线周期，如"1m"、"1h"、"d"（tick数据不需要）
        
    Returns:
        是否导入成功
    """
    # 转换交易所枚举
    try:
        exchange_enum = Exchange[exchange]
    except KeyError:
        print(f"不支持的交易所: {exchange}")
        return False
    
    # 转换周期枚举（如果提供）
    interval_enum = None
    if interval:
        try:
            interval_enum = Interval(interval)
        except ValueError:
            print(f"不支持的周期: {interval}")
            return False
    
    downloader = TqDataDownloader()
    return downloader.import_to_vnpy(
        csv_file_path=csv_file_path,
        symbol=symbol,
        exchange=exchange_enum,
        interval=interval_enum
    )


def main():
    """
    命令行入口
    """
    parser = argparse.ArgumentParser(description='天勤数据下载工具')
    
    # 下载参数
    parser.add_argument('--account', type=str, default="", help='天勤账号')
    parser.add_argument('--password', type=str, default="", help='天勤密码')
    parser.add_argument('--symbol', type=str, required=True, help='合约代码，如SHFE.cu2305')
    parser.add_argument('--start', type=str, required=True, help='起始时间，格式：YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DD')
    parser.add_argument('--end', type=str, required=True, help='结束时间，格式：YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DD')
    parser.add_argument('--interval', type=str, required=True, help='数据周期，如tick、1m、5m、1h、d')
    parser.add_argument('--output', type=str, required=True, help='输出CSV文件名')
    parser.add_argument('--mode', type=str, default='w', help='写入模式，w为覆盖，a为追加')
    
    # 导入参数
    parser.add_argument('--import', action='store_true', help='是否导入到VNPY数据库')
    parser.add_argument('--vnpy-symbol', type=str, help='VNPY合约代码，如cu2305')
    parser.add_argument('--exchange', type=str, help='交易所，如SHFE')
    
    args = parser.parse_args()
    
    # 解析周期
    interval_map = {
        'tick': 0,
        '1m': 60,
        '5m': 300,
        '15m': 900,
        '30m': 1800,
        '1h': 3600,
        '2h': 7200,
        '4h': 14400,
        'd': 86400,
        'w': 604800,
        'M': 2592000
    }
    
    dur_sec = interval_map.get(args.interval)
    if dur_sec is None:
        print(f"不支持的周期: {args.interval}")
        return
    
    # 解析时间
    try:
        # 尝试解析带时间的格式
        start_dt = datetime.strptime(args.start, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        # 尝试解析仅日期格式
        start_dt = date.fromisoformat(args.start)
    
    try:
        # 尝试解析带时间的格式
        end_dt = datetime.strptime(args.end, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        # 尝试解析仅日期格式
        end_dt = date.fromisoformat(args.end)
    
    # 执行下载
    downloader = TqDataDownloader(args.account, args.password)
    success = downloader.download_data(
        symbol_list=args.symbol,
        dur_sec=dur_sec,
        start_dt=start_dt,
        end_dt=end_dt,
        csv_file_name=args.output,
        write_mode=args.mode
    )
    
    # 执行导入（如果指定）
    if success and getattr(args, 'import'):
        if not args.vnpy_symbol or not args.exchange:
            print("导入数据库需要指定 --vnpy-symbol 和 --exchange 参数")
            return
        
        # 转换VNPY周期
        vnpy_interval = None
        if args.interval != 'tick':
            vnpy_interval = Interval(args.interval)
        
        # 转换交易所
        try:
            exchange_enum = Exchange[args.exchange]
        except KeyError:
            print(f"不支持的交易所: {args.exchange}")
            return
        
        downloader.import_to_vnpy(
            csv_file_path=args.output,
            symbol=args.vnpy_symbol,
            exchange=exchange_enum,
            interval=vnpy_interval
        )


if __name__ == "__main__":
    main()
