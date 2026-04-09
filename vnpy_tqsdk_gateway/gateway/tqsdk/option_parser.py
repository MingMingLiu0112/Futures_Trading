"""
天勤网关期权支持增强模块
为期权模块提供必要的期权合约信息解析和字段映射功能
"""
import re
from datetime import datetime
from typing import Dict, Optional, Tuple

from vnpy.trader.constant import Product, Exchange, OptionType
from vnpy.trader.object import ContractData


class OptionContractParser:
    """
    期权合约信息解析器
    
    支持不同交易所的期权合约命名规则：
    - CFFEX: IO2605-C-4500 (股指期权)
    - SHFE: cu2605C60000 (商品期权)
    - DCE: m2605C3000 (商品期权)
    - CZCE: SR605C6000 (商品期权，注意月份格式)
    """

    @staticmethod
    def is_option_contract(symbol: str, exchange: Exchange) -> bool:
        """
        判断是否为期权合约
        
        Args:
            symbol: 合约代码
            exchange: 交易所
            
        Returns:
            bool: 是否为期权合约
        """
        if exchange == Exchange.CFFEX:
            return symbol.startswith("IO") or symbol.startswith("HO") or symbol.startswith("MO")
        elif exchange == Exchange.SHFE:
            return "C" in symbol or "P" in symbol
        elif exchange == Exchange.DCE:
            return ("C" in symbol or "P" in symbol) and "-" in symbol
        elif exchange == Exchange.CZCE:
            return "C" in symbol or "P" in symbol
        return False

    @staticmethod
    def parse_option_info(symbol: str, exchange: Exchange) -> Dict:
        """
        解析期权合约信息
        
        Args:
            symbol: 合约代码
            exchange: 交易所
            
        Returns:
            Dict: 包含期权信息的字典
                {
                    "option_type": OptionType,
                    "option_strike": float,
                    "option_underlying": str,
                    "option_portfolio": str,
                    "option_expiry": datetime,
                    "option_index": str
                }
        """
        if exchange == Exchange.CFFEX:
            return OptionContractParser._parse_cffex_option(symbol)
        elif exchange == Exchange.SHFE:
            return OptionContractParser._parse_shfe_option(symbol)
        elif exchange == Exchange.DCE:
            return OptionContractParser._parse_dce_option(symbol)
        elif exchange == Exchange.CZCE:
            return OptionContractParser._parse_czce_option(symbol)
        else:
            return {}

    @staticmethod
    def _parse_cffex_option(symbol: str) -> Dict:
        """
        解析中金所股指期权合约
        
        格式: IO2605-C-4500 或 HO2605-P-4500
        - IO: 沪深300股指期权
        - HO: 上证50股指期权
        - MO: 中证1000股指期权
        - 2605: 2026年5月到期
        - C/P: 看涨/看跌
        - 4500: 行权价
        """
        pattern = r"^(IO|HO|MO)(\d{4})-([CP])-(\d+(?:\.\d+)?)$"
        match = re.match(pattern, symbol, re.IGNORECASE)
        
        if not match:
            return {}
        
        portfolio_code, month_year, cp_type, strike = match.groups()
        
        option_type = OptionType.CALL if cp_type == "C" else OptionType.PUT
        option_strike = float(strike)
        
        year = int("20" + month_year[:2])
        month = int(month_year[2:4])
        option_expiry = datetime(year, month, 15)
        
        underlying_symbol = f"{portfolio_code}{month_year}"
        
        return {
            "option_type": option_type,
            "option_strike": option_strike,
            "option_underlying": underlying_symbol,
            "option_portfolio": portfolio_code.lower(),
            "option_expiry": option_expiry,
            "option_index": str(int(option_strike))
        }

    @staticmethod
    def _parse_shfe_option(symbol: str) -> Dict:
        """
        解析上期所商品期权合约
        
        格式: cu2605C60000 或 au2605P400
        - cu/au: 标的物代码
        - 2605: 2026年5月到期
        - C/P: 看涨/看跌
        - 60000: 行权价
        """
        pattern = r"^([a-z]+)(\d{4})([CP])(\d+(?:\.\d+)?)$"
        match = re.match(pattern, symbol, re.IGNORECASE)
        
        if not match:
            return {}
        
        underlying_code, month_year, cp_type, strike = match.groups()
        
        option_type = OptionType.CALL if cp_type.upper() == "C" else OptionType.PUT
        option_strike = float(strike)
        
        year = int("20" + month_year[:2])
        month = int(month_year[2:4])
        option_expiry = datetime(year, month, 15)
        
        underlying_symbol = f"{underlying_code.upper()}{month_year}"
        portfolio_code = f"{underlying_code.lower()}_o"
        
        return {
            "option_type": option_type,
            "option_strike": option_strike,
            "option_underlying": underlying_symbol,
            "option_portfolio": portfolio_code,
            "option_expiry": option_expiry,
            "option_index": str(option_strike)
        }

    @staticmethod
    def _parse_dce_option(symbol: str) -> Dict:
        """
        解析大商所商品期权合约
        
        格式: v2603-C-4400 或 v2603-P-4400
        - v: 标的物代码
        - 2603: 2026年3月到期
        - C/P: 看涨/看跌
        - 4400: 行权价
        """
        pattern = r"^([a-zA-Z]+)(\d{4})-([CP])-(\d+(?:\.\d+)?)$"
        match = re.match(pattern, symbol, re.IGNORECASE)
        
        if not match:
            return {}
        
        underlying_code, month_year, cp_type, strike = match.groups()
        
        option_type = OptionType.CALL if cp_type.upper() == "C" else OptionType.PUT
        option_strike = float(strike)
        
        year = int("20" + month_year[:2])
        month = int(month_year[2:4])
        option_expiry = datetime(year, month, 15)
        
        underlying_symbol = f"{underlying_code.upper()}{month_year}"
        portfolio_code = f"{underlying_code.lower()}_o"
        
        return {
            "option_type": option_type,
            "option_strike": option_strike,
            "option_underlying": underlying_symbol,
            "option_portfolio": portfolio_code,
            "option_expiry": option_expiry,
            "option_index": str(int(option_strike))
        }

    @staticmethod
    def _parse_czce_option(symbol: str) -> Dict:
        """
        解析郑商所商品期权合约
        
        格式: SR605C6000 或 MA605P3000
        - SR/MA: 标的物代码
        - 605: 2026年5月到期（年份省略20）
        - C/P: 看涨/看跌
        - 6000: 行权价
        """
        pattern = r"^([A-Z]+)(\d{3})([CP])(\d+(?:\.\d+)?)$"
        match = re.match(pattern, symbol)
        
        if not match:
            return {}
        
        underlying_code, month_code, cp_type, strike = match.groups()
        
        option_type = OptionType.CALL if cp_type == "C" else OptionType.PUT
        option_strike = float(strike)
        
        # 修复年份解析 - 正确处理2020年后的年份
        # 月份代码格式：605表示2026年5月（第一位6表示2026年）
        year_digit = int(month_code[:1])
        year = 2020 + year_digit
        month = int(month_code[1:3])
        option_expiry = datetime(year, month, 15)
        
        underlying_symbol = f"{underlying_code}{month_code}"
        portfolio_code = f"{underlying_code.lower()}_o"
        
        return {
            "option_type": option_type,
            "option_strike": option_strike,
            "option_underlying": underlying_symbol,
            "option_portfolio": portfolio_code,
            "option_expiry": option_expiry,
            "option_index": str(option_strike)
        }

    @staticmethod
    def create_option_contract(
        symbol: str,
        exchange: Exchange,
        name: str,
        size: float,
        pricetick: float,
        min_volume: float,
        gateway_name: str
    ) -> Optional[ContractData]:
        """
        创建期权合约数据对象
        
        Args:
            symbol: 合约代码
            exchange: 交易所
            name: 合约名称
            size: 合约乘数
            pricetick: 最小价格变动
            min_volume: 最小委托量
            gateway_name: 网关名称
            
        Returns:
            ContractData: 期权合约数据对象，如果解析失败则返回None
        """
        if not OptionContractParser.is_option_contract(symbol, exchange):
            return None
        
        option_info = OptionContractParser.parse_option_info(symbol, exchange)
        if not option_info:
            return None
        
        contract = ContractData(
            symbol=symbol,
            exchange=exchange,
            name=name,
            product=Product.OPTION,
            size=size,
            pricetick=pricetick,
            min_volume=min_volume,
            gateway_name=gateway_name,
            option_strike=option_info.get("option_strike"),
            option_underlying=option_info.get("option_underlying"),
            option_type=option_info.get("option_type"),
            option_expiry=option_info.get("option_expiry"),
            option_portfolio=option_info.get("option_portfolio"),
            option_index=option_info.get("option_index")
        )
        
        return contract


def enhance_load_contracts_with_option_support(
    load_contracts_func,
    gateway_name: str
) -> None:
    """
    增强合约加载函数，添加期权支持
    
    Args:
        load_contracts_func: 原始的合约加载函数
        gateway_name: 网关名称
    """
    def wrapper(contracts_data):
        for contract_info in contracts_data:
            symbol = contract_info.get("symbol")
            exchange_str = contract_info.get("exchange")
            
            if not symbol or not exchange_str:
                continue
            
            exchange = Exchange(exchange_str)
            vt_symbol = f"{symbol}.{exchange.value}"
            
            name = contract_info.get("name", symbol)
            size = contract_info.get("size", 1)
            pricetick = contract_info.get("price_tick", 0.01)
            min_volume = contract_info.get("min_volume", 1)
            
            if OptionContractParser.is_option_contract(symbol, exchange):
                contract = OptionContractParser.create_option_contract(
                    symbol=symbol,
                    exchange=exchange,
                    name=name,
                    size=size,
                    pricetick=pricetick,
                    min_volume=min_volume,
                    gateway_name=gateway_name
                )
                if contract:
                    yield contract
            else:
                contract = ContractData(
                    symbol=symbol,
                    exchange=exchange,
                    name=name,
                    product=Product.FUTURES,
                    size=size,
                    pricetick=pricetick,
                    min_volume=min_volume,
                    gateway_name=gateway_name
                )
                yield contract
    
    return wrapper
