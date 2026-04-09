"""
天勤数据服务模块
"""

from datetime import timedelta, datetime
from typing import Optional, List
from collections.abc import Callable
import traceback
from pandas import DataFrame

from vnpy.trader.datafeed import BaseDatafeed
from vnpy.trader.object import HistoryRequest, BarData, TickData
from vnpy.trader.constant import Interval
from vnpy.trader.utility import ZoneInfo

# Interval映射表 - 使用字符串key以便兼容不同版本的vnpy
INTERVAL_VT2TQ: dict = {
    "MINUTE": 60,
    "HOUR": 60 * 60,
    "DAILY": 60 * 60 * 24,
    "WEEKLY": 60 * 60 * 24 * 7,
    "MINUTE_5": 300,
    "MINUTE_15": 900,
    "MINUTE_30": 1800,
    "HOUR_2": 60 * 60 * 2,
    "HOUR_4": 60 * 60 * 4,
    "MONTHLY": 60 * 60 * 24 * 30
}

CHINA_TZ = ZoneInfo("Asia/Shanghai")


def _get_interval_seconds(interval: Interval) -> int:
    """获取Interval对应的秒数，兼容不同版本vnpy"""
    interval_str = str(interval).split('.')[-1]
    return INTERVAL_VT2TQ.get(interval_str, 60)


class TqSdkDatafeed(BaseDatafeed):
    """
    天勤数据服务类，用于查询历史行情数据
    """

    def __init__(self) -> None:
        """
        初始化
        """
        self.api = None
        self.inited = False

    def init(self, output: Callable = print) -> bool:
        """
        初始化数据服务连接
        """
        try:
            from tqsdk import TqApi, TqAuth
            from vnpy.trader.setting import SETTINGS
            if not self.inited:
                self.api = TqApi(auth=TqAuth(SETTINGS["datafeed.username"], SETTINGS["datafeed.password"]))
                self.inited = True
                output("天勤数据服务初始化成功")
                return True
        except Exception as ex:
            output(f"天勤数据服务初始化失败: {ex}")
            return False

    def query_history(self, req: HistoryRequest) -> Optional[List[BarData]]:
        """
        查询历史K线数据
        """
        if not self.api:
            return []

        try:
            from tqsdk import tqsdk_timestamp_to_datetime
            
            duration_seconds = _get_interval_seconds(req.interval)
            
            ts = self.api.get_kline_serial(
                req.symbol,
                duration_seconds=duration_seconds,
                data_length=min(req.end - req.start, 1000000) if req.end else 1000,
                end_datetime=req.end
            )
            
            data: List[BarData] = []
            for i in range(len(ts)):
                dt = ts.iloc[i]["datetime"]
                if isinstance(dt, (int, float)):
                    dt = datetime.fromtimestamp(dt / 1e9)
                
                bar = BarData(
                    symbol=req.symbol,
                    exchange=req.exchange,
                    datetime=dt,
                    interval=req.interval,
                    volume=ts.iloc[i]["volume"],
                    turnover=0,
                    open_interest=ts.iloc[i].get("close_oi", 0),
                    open_price=ts.iloc[i]["open"],
                    high_price=ts.iloc[i]["high"],
                    low_price=ts.iloc[i]["low"],
                    close_price=ts.iloc[i]["close"],
                    gateway_name="TQSDK"
                )
                data.append(bar)
            
            return data
            
        except Exception as ex:
            traceback.print_exc()
            return []

    def close(self) -> None:
        """
        关闭连接
        """
        if self.api:
            self.api = None
            self.inited = False
