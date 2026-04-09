"""
示例：使用天勤数据下载工具的公共函数
"""

from datetime import datetime, date
from tq_data_downloader import download_tq_data, import_tq_data_to_vnpy


if __name__ == "__main__":
    # 1. 下载数据示例
    print("=== 下载数据示例 ===")
    
    # 设置参数
    symbol = "SHFE.cu2305"  # 合约代码
    start_dt = date(2023, 1, 1)  # 起始日期
    end_dt = date(2023, 1, 10)  # 结束日期
    dur_sec = 60  # 1分钟线
    output_file = "cu2305_1min.csv"  # 输出文件名
    
    # 调用下载函数
    success = download_tq_data(
        symbol_list=symbol,
        dur_sec=dur_sec,
        start_dt=start_dt,
        end_dt=end_dt,
        csv_file_name=output_file
    )
    
    if success:
        print(f"数据下载成功，保存到: {output_file}")
        
        # 2. 导入到VNPY数据库示例
        print("\n=== 导入到VNPY数据库示例 ===")
        
        vnpy_symbol = "cu2305"  # VNPY合约代码
        exchange = "SHFE"  # 交易所
        interval = "1m"  # 周期
        
        # 调用导入函数
        import_success = import_tq_data_to_vnpy(
            csv_file_path=output_file,
            symbol=vnpy_symbol,
            exchange=exchange,
            interval=interval
        )
        
        if import_success:
            print("数据导入到VNPY数据库成功")
        else:
            print("数据导入到VNPY数据库失败")
    else:
        print("数据下载失败")
