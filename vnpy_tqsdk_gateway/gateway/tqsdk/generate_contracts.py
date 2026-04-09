"""
天勤网关合约JSON文件自动生成工具

功能：
1. 从天勤API查询所有可用合约
2. 根据交易所和品种分类
3. 自动生成期货合约
4. 自动生成期权链（期权组合）
5. 支持多个交易所
6. 支持期权产品名称映射

使用方法：
1. 确保天勤网关已连接
2. 运行此脚本自动生成合约文件
3. 将生成的文件保存到 tqsdk_contracts.json
"""

import json
import os
import argparse
from datetime import datetime
from typing import List, Dict, Any

try:
    from tqsdk import TqApi, TqAuth
except ImportError:
    print("错误: 未安装 tqsdk 库")
    print("请先安装: pip install tqsdk")
    exit(1)


# 品种名称映射字典
PRODUCT_NAME_MAPPING = {
    # 上海期货交易所（SHFE）及上期能源
    "cu": "铜",
    "al": "铝",
    "zn": "锌",
    "pb": "铅",
    "ni": "镍",
    "sn": "锡",
    "au": "黄金",
    "ag": "白银",
    "rb": "螺纹钢",
    "hc": "热轧卷板",
    "bu": "石油沥青",
    "ru": "天然橡胶",
    "sp": "纸浆",
    "ss": "不锈钢",
    "wr": "线材",
    "fu": "燃料油",
    "ao": "氧化铝",
    "ad": "铸造铝合金",
    "op": "胶版印刷纸",
    "br": "丁二烯橡胶",
    "sc": "原油",
    "lu": "低硫燃料油",
    "nr": "20号胶",
    "bc": "国际铜",
    "ec": "集运指数（欧线）",
    
    # 郑州商品交易所（ZCE）
    "WH": "强麦",
    "PM": "普麦",
    "CF": "棉花",
    "SR": "白糖",
    "OI": "菜籽油",
    "RS": "油菜籽",
    "RM": "菜籽粕",
    "RI": "早籼稻",
    "LR": "晚籼稻",
    "JR": "粳稻",
    "TA": "PTA",
    "MA": "甲醇",
    "SA": "纯碱",
    "UR": "尿素",
    "PF": "短纤",
    "SF": "硅铁",
    "SM": "锰硅",
    "ZC": "动力煤",
    "PK": "花生",
    "CJ": "红枣",
    "AP": "苹果",
    "CY": "棉纱",
    "FG": "玻璃",
    
    # 大连商品交易所（DCE）
    "c": "玉米",
    "cs": "玉米淀粉",
    "a": "黄大豆1号",
    "b": "黄大豆2号",
    "m": "豆粕",
    "y": "豆油",
    "p": "棕榈油",
    "jd": "鸡蛋",
    "lh": "生猪",
    "l": "聚乙烯",
    "pp": "聚丙烯",
    "v": "聚氯乙烯",
    "eb": "苯乙烯",
    "eg": "乙二醇",
    "pg": "液化石油气",
    "j": "焦炭",
    "jm": "焦煤",
    "i": "铁矿石",
    "bb": "胶合板",
    "fb": "纤维板",
    
    # 中国金融期货交易所（CFFEX）
    "IF": "沪深300股指期货",
    "IH": "上证50股指期货",
    "IC": "中证500股指期货",
    "IM": "中证1000股指期货",
    "IO": "沪深300股指期权",
    "HO": "上证50股指期权",
    "MO": "中证1000股指期权",
    "TS": "2年期国债期货",
    "TF": "5年期国债期货",
    "T": "10年期国债期货",
    "TL": "30年期国债期货",
    
    # 广州期货交易所（GFEX）
    "si": "工业硅",
    "lc": "碳酸锂",
    "pg": "多晶硅"
}

OPTION_PORTFOLIO_MAPPING = {
    "ETF期权": {
        "510050": "510050_O",
        "159919": "159919_O"
    },
    "股指期权": {
        "IF": "IO",
        "IH": "HO",
        "IM": "MO"
    },
    "商品期权": {
        "i": "i_o",
        "cu": "cu_o",
        "sc": "sc_o",
        "SR": "SR",
        "CF": "CF_O",
        "m": "m_o",
        "y": "y_o",
        "c": "c_o",
        "V": "V_O"
    }
}


FUTURES_CONFIG = {
    "CFFEX": {
        "IF": {"name": "沪深300期货", "size": 300, "price_tick": 0.2, "option_portfolio": "IO"},
        "IH": {"name": "上证50期货", "size": 300, "price_tick": 0.2, "option_portfolio": "HO"},
        "IM": {"name": "中证1000期货", "size": 200, "price_tick": 0.2, "option_portfolio": "MO"},
        "IC": {"name": "中证500期货", "size": 200, "price_tick": 0.2, "option_portfolio": "CO"}
    },
    "SHFE": {
        "cu": {"name": "铜期货", "size": 5, "price_tick": 10, "option_portfolio": "cu_o"},
        "au": {"name": "黄金期货", "size": 1000, "price_tick": 0.02, "option_portfolio": "au_o"},
        "rb": {"name": "螺纹钢期货", "size": 10, "price_tick": 1, "option_portfolio": "rb_o"},
        "ru": {"name": "天然橡胶期货", "size": 10, "price_tick": 5, "option_portfolio": "ru_o"},
        "ni": {"name": "镍期货", "size": 1, "price_tick": 10, "option_portfolio": "ni_o"},
        "zn": {"name": "锌期货", "size": 5, "price_tick": 5, "option_portfolio": "zn_o"},
        "pb": {"name": "铅期货", "size": 5, "price_tick": 5, "option_portfolio": "pb_o"},
        "al": {"name": "铝期货", "size": 5, "price_tick": 5, "option_portfolio": "al_o"},
        "sn": {"name": "锡期货", "size": 1, "price_tick": 10, "option_portfolio": "sn_o"},
        "hc": {"name": "热轧卷板期货", "size": 10, "price_tick": 1, "option_portfolio": "hc_o"},
        "ss": {"name": "不锈钢期货", "size": 5, "price_tick": 5, "option_portfolio": "ss_o"},
        "sp": {"name": "纸浆期货", "size": 10, "price_tick": 2, "option_portfolio": "sp_o"}
    },
    "DCE": {
        "m": {"name": "豆粕期货", "size": 10, "price_tick": 0.5, "option_portfolio": "m_o"},
        "y": {"name": "豆油期货", "size": 10, "price_tick": 2, "option_portfolio": "y_o"},
        "c": {"name": "玉米期货", "size": 10, "price_tick": 1, "option_portfolio": "c_o"},
        "i": {"name": "铁矿石期货", "size": 100, "price_tick": 0.5, "option_portfolio": "i_o"},
        "j": {"name": "焦炭期货", "size": 100, "price_tick": 1, "option_portfolio": "j_o"},
        "jm": {"name": "焦煤期货", "size": 60, "price_tick": 0.5, "option_portfolio": "jm_o"},
        "a": {"name": "豆一期货", "size": 10, "price_tick": 1, "option_portfolio": "a_o"},
        "b": {"name": "豆二期货", "size": 10, "price_tick": 1, "option_portfolio": "b_o"},
        "p": {"name": "棕榈油期货", "size": 10, "price_tick": 2, "option_portfolio": "p_o"},
        "l": {"name": "聚乙烯期货", "size": 5, "price_tick": 5, "option_portfolio": "l_o"},
        "v": {"name": "聚氯乙烯期货", "size": 5, "price_tick": 5, "option_portfolio": "V_O"},
        "pp": {"name": "聚丙烯期货", "size": 5, "price_tick": 1, "option_portfolio": "pp_o"},
        "eb": {"name": "苯乙烯期货", "size": 5, "price_tick": 5, "option_portfolio": "eb_o"},
        "eg": {"name": "乙二醇期货", "size": 10, "price_tick": 1, "option_portfolio": "eg_o"},
        "rr": {"name": "粳米期货", "size": 5, "price_tick": 1, "option_portfolio": "rr_o"}
    },
    "CZCE": {
        "SR": {"name": "白糖期货", "size": 10, "price_tick": 1, "option_portfolio": "SR"},
        "CF": {"name": "棉花期货", "size": 5, "price_tick": 5, "option_portfolio": "CF_O"},
        "TA": {"name": "PTA期货", "size": 5, "price_tick": 2, "option_portfolio": "TA_O"},
        "MA": {"name": "甲醇期货", "size": 10, "price_tick": 1, "option_portfolio": "MA_O"},
        "FG": {"name": "玻璃期货", "size": 20, "price_tick": 1, "option_portfolio": "FG_O"},
        "RM": {"name": "菜粕期货", "size": 10, "price_tick": 1, "option_portfolio": "RM_O"},
        "OI": {"name": "菜油期货", "size": 10, "price_tick": 2, "option_portfolio": "OI_O"},
        "ZC": {"name": "红枣期货", "size": 5, "price_tick": 5, "option_portfolio": "ZC_O"},
        "AP": {"name": "苹果期货", "size": 10, "price_tick": 1, "option_portfolio": "AP_O"},
        "CF": {"name": "棉花期货", "size": 5, "price_tick": 5, "option_portfolio": "CF_O"},
        "CY": {"name": "棉纱期货", "size": 5, "price_tick": 5, "option_portfolio": "CY_O"},
        "JR": {"name": "粳稻期货", "size": 20, "price_tick": 1, "option_portfolio": "JR_O"},
        "LR": {"name": "晚籼稻期货", "size": 20, "price_tick": 1, "option_portfolio": "LR_O"},
        "RS": {"name": "菜籽期货", "size": 10, "price_tick": 1, "option_portfolio": "RS_O"},
        "SF": {"name": "硅铁期货", "size": 5, "price_tick": 2, "option_portfolio": "SF_O"},
        "SM": {"name": "锰硅期货", "size": 5, "price_tick": 2, "option_portfolio": "SM_O"},
        "UR": {"name": "尿素期货", "size": 20, "price_tick": 1, "option_portfolio": "UR_O"}
    },
    "INE": {
        "sc": {"name": "原油期货", "size": 1000, "price_tick": 0.1, "option_portfolio": "sc_o"},
        "lu": {"name": "低硫燃料油期货", "size": 10, "price_tick": 1, "option_portfolio": "lu_o"},
        "fu": {"name": "燃料油期货", "size": 10, "price_tick": 1, "option_portfolio": "fu_o"},
        "nr": {"name": "20号胶期货", "size": 10, "price_tick": 5, "option_portfolio": "nr_o"}
    }
}


OPTION_STRIKE_CONFIG = {
    "IF": {"base": 4000, "step": 50, "count": 5},
    "IH": {"base": 2500, "step": 50, "count": 5},
    "IM": {"base": 6000, "step": 100, "count": 5},
    "IC": {"base": 5000, "step": 100, "count": 5},
    "cu": {"base": 70000, "step": 1000, "count": 5},
    "au": {"base": 500, "step": 10, "count": 5},
    "rb": {"base": 3500, "step": 100, "count": 5},
    "ru": {"base": 15000, "step": 500, "count": 5},
    "ni": {"base": 120000, "step": 2000, "count": 5},
    "zn": {"base": 25000, "step": 500, "count": 5},
    "pb": {"base": 15000, "step": 500, "count": 5},
    "al": {"base": 20000, "step": 500, "count": 5},
    "sn": {"base": 200000, "step": 5000, "count": 5},
    "hc": {"base": 3500, "step": 100, "count": 5},
    "ss": {"base": 15000, "step": 500, "count": 5},
    "sp": {"base": 5500, "step": 100, "count": 5},
    "m": {"base": 3000, "step": 50, "count": 5},
    "y": {"base": 8000, "step": 100, "count": 5},
    "c": {"base": 2200, "step": 50, "count": 5},
    "i": {"base": 800, "step": 20, "count": 5},
    "j": {"base": 2000, "step": 50, "count": 5},
    "jm": {"base": 1200, "step": 30, "count": 5},
    "a": {"base": 5000, "step": 100, "count": 5},
    "b": {"base": 5000, "step": 100, "count": 5},
    "p": {"base": 8000, "step": 100, "count": 5},
    "l": {"base": 8000, "step": 200, "count": 5},
    "v": {"base": 4400, "step": 200, "count": 5},
    "pp": {"base": 8000, "step": 200, "count": 5},
    "eb": {"base": 8000, "step": 200, "count": 5},
    "eg": {"base": 4000, "step": 100, "count": 5},
    "rr": {"base": 3000, "step": 50, "count": 5},
    "SR": {"base": 6000, "step": 100, "count": 5},
    "CF": {"base": 11000, "step": 200, "count": 5},
    "TA": {"base": 5000, "step": 100, "count": 5},
    "MA": {"base": 2500, "step": 50, "count": 5},
    "FG": {"base": 1500, "step": 50, "count": 5},
    "RM": {"base": 2500, "step": 50, "count": 5},
    "OI": {"base": 8000, "step": 100, "count": 5},
    "ZC": {"base": 10000, "step": 200, "count": 5},
    "AP": {"base": 8000, "step": 200, "count": 5},
    "CY": {"base": 20000, "step": 500, "count": 5},
    "JR": {"base": 3000, "step": 50, "count": 5},
    "LR": {"base": 3000, "step": 50, "count": 5},
    "RS": {"base": 6000, "step": 100, "count": 5},
    "SF": {"base": 7000, "step": 200, "count": 5},
    "SM": {"base": 7000, "step": 200, "count": 5},
    "UR": {"base": 2000, "step": 50, "count": 5},
    "sc": {"base": 500, "step": 10, "count": 5},
    "lu": {"base": 2500, "step": 50, "count": 5},
    "fu": {"base": 2000, "step": 50, "count": 5},
    "nr": {"base": 15000, "step": 500, "count": 5}
}


def query_all_contracts(api: TqApi) -> List[Dict[str, Any]]:
    """
    从天勤API查询所有可用合约
    
    Args:
        api: 天勤API对象
        
    Returns:
        合约列表
    """
    contracts = []
    
    try:
        print("正在查询天勤API合约列表...")
        
        # 定义主要期货交易所
        exchanges = ['SHFE', 'DCE', 'CZCE', 'CFFEX', 'INE']
        
        # 使用query_quotes获取所有期货合约
        print("正在查询期货合约...")
        future_quotes = api.query_quotes(ins_class="FUTURE", expired=False)
        print(f"查询到 {len(future_quotes)} 个期货合约")
        
        # 处理期货合约
        futures = []
        for quote in future_quotes:
            if isinstance(quote, str):
                # 解析合约代码，格式：交易所.合约代码
                parts = quote.split(".")
                if len(parts) == 2:
                    exchange = parts[0]
                    symbol = parts[1]
                    
                    # 跳过不在主要交易所的合约
                    if exchange not in exchanges:
                        continue
                    
                    # 提取基础品种代码
                    base_symbol = None
                    # 尝试匹配1-3个字符的品种代码
                    for i in range(3, 0, -1):
                        if len(symbol) > i:
                            test_symbol = symbol[:i]
                            if test_symbol in PRODUCT_NAME_MAPPING:
                                base_symbol = test_symbol
                                break
                    
                    # 如果没有找到，尝试使用完整symbol
                    if not base_symbol:
                        base_symbol = symbol
                    
                    # 获取品种名称
                    product_name = PRODUCT_NAME_MAPPING.get(base_symbol, f"{base_symbol}期货")
                    
                    # 构建期货合约信息
                    contract_info = {
                        'symbol': symbol,
                        'exchange': exchange,
                        'name': f"{product_name}{symbol[-4:]}",
                        'class': 'FUTURE',
                        'size': 1,  # 默认值，后续会使用FUTURES_CONFIG中的配置
                        'price_tick': 0.01,  # 默认值，后续会使用FUTURES_CONFIG中的配置
                        'min_volume': 1
                    }
                    
                    contracts.append(contract_info)
                    futures.append(quote)  # 保存完整的合约代码用于查询期权
        
        print(f"处理完成 {len(futures)} 个期货合约")
        
        # 获取所有期权合约
        print("正在查询期权合约...")
        
        # 使用query_quotes获取所有期权合约
        option_quotes = api.query_quotes(ins_class="OPTION", expired=False)
        print(f"查询到 {len(option_quotes)} 个期权合约")
        
        # 处理期权合约
        for quote in option_quotes:
            if isinstance(quote, str):
                # 解析合约代码，格式：交易所.合约代码
                parts = quote.split(".")
                if len(parts) == 2:
                    exchange = parts[0]
                    symbol = parts[1]
                    
                    # 跳过不在主要交易所的合约
                    if exchange not in exchanges:
                        continue
                    
                    # 提取基础品种代码
                    base_symbol = None
                    # 尝试匹配1-3个字符的品种代码
                    for i in range(3, 0, -1):
                        if len(symbol) > i:
                            test_symbol = symbol[:i]
                            if test_symbol in PRODUCT_NAME_MAPPING:
                                base_symbol = test_symbol
                                break
                    
                    # 如果没有找到，尝试使用完整symbol
                    if not base_symbol:
                        base_symbol = symbol
                    
                    # 获取品种名称
                    product_name = PRODUCT_NAME_MAPPING.get(base_symbol, f"{base_symbol}期权")
                    
                    # 构建期权合约信息
                    contract_info = {
                        'symbol': symbol,
                        'exchange': exchange,
                        'name': f"{product_name}{symbol[-4:]}",
                        'class': 'OPTION',
                        'option_type': 'CALL' if 'C' in symbol else 'PUT',
                        'strike_price': 0,  # 默认值，后续会使用生成逻辑
                        'underlying_instrument_id': '',  # 默认值，后续会使用生成逻辑
                        'size': 1,  # 默认值
                        'price_tick': 0.01,  # 默认值
                        'min_volume': 1
                    }
                    
                    contracts.append(contract_info)
        
        print(f"共查询到 {len(contracts)} 个合约")
        
    except Exception as e:
        print(f"查询合约失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return []
    
    return contracts


def generate_futures_contracts(contracts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    生成期货合约配置
    
    Args:
        contracts: 原始合约列表
        
    Returns:
        期货合约列表
    """
    futures = []
    
    # 缓存已处理的合约，避免重复
    processed_contracts = set()
    
    for contract in contracts:
        try:
            symbol = contract.get('symbol', '')
            exchange = contract.get('exchange', '')
            
            # 跳过无效合约
            if not symbol or not exchange:
                continue
            
            # 生成唯一标识符
            contract_key = f"{exchange}.{symbol}"
            if contract_key in processed_contracts:
                continue
            
            # 只处理期货合约，跳过期权合约
            if 'C' in symbol and 'P' in symbol:
                continue
            if '-' in symbol and ('C' in symbol or 'P' in symbol):
                continue
            
            # 提取基础品种代码
            # 支持不同格式：如 "IF2305"、"i2305"、"sc2305"等
            base_symbol = None
            # 尝试匹配1-3个字符的品种代码
            for i in range(3, 0, -1):
                if len(symbol) > i:
                    test_symbol = symbol[:i]
                    if test_symbol in PRODUCT_NAME_MAPPING:
                        base_symbol = test_symbol
                        break
            
            # 如果没有找到，尝试使用完整symbol（适用于指数等）
            if not base_symbol:
                base_symbol = symbol
            
            # 获取品种名称
            product_name = PRODUCT_NAME_MAPPING.get(base_symbol, f"{base_symbol}合约")
            
            # 使用API返回的完整合约信息
            if contract.get('class') == 'FUTURE':
                futures.append({
                    'symbol': symbol,
                    'exchange': exchange,
                    'name': f"{product_name}{symbol[-4:]}",
                    'class': 'FUTURE',
                    'size': contract.get('size', 1),
                    'price_tick': contract.get('price_tick', 0.01),
                    'min_volume': contract.get('min_volume', 1),
                    'max_volume': contract.get('max_volume', None),
                    'create_date': contract.get('create_date', None),
                    'expire_date': contract.get('expire_date', None),
                    'product_id': base_symbol,
                    'product_name': product_name
                })
                processed_contracts.add(contract_key)
            elif 'class' not in contract:  # 兼容旧格式或API返回不完整的情况
                # 使用FUTURES_CONFIG中的配置补充信息
                if exchange in FUTURES_CONFIG:
                    # 提取基础品种代码
                    base_symbol = None
                    for underlying in FUTURES_CONFIG[exchange]:
                        if symbol.startswith(underlying):
                            base_symbol = underlying
                            break
                    
                    if base_symbol:
                        config = FUTURES_CONFIG[exchange][base_symbol]
                        product_name = PRODUCT_NAME_MAPPING.get(base_symbol, config['name'])
                        futures.append({
                            'symbol': symbol,
                            'exchange': exchange,
                            'name': f"{product_name}{symbol[-4:]}",
                            'class': 'FUTURE',
                            'size': config['size'],
                            'price_tick': config['price_tick'],
                            'min_volume': 1
                        })
                        processed_contracts.add(contract_key)
        except Exception as e:
            print(f"处理期货合约 {contract} 时出错: {str(e)}")
            continue
    
    return futures


def generate_option_chain(underlying: str, month_year: str, exchange: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    自动生成期权链（期权组合）
    
    Args:
        underlying: 标的物代码
        month_year: 到期月份
        exchange: 交易所
        config: 期权配置
        
    Returns:
        期权合约列表
    """
    options = []
    
    if underlying not in OPTION_STRIKE_CONFIG:
        return options
    
    strike_config = OPTION_STRIKE_CONFIG[underlying]
    base_strike = strike_config['base']
    strike_step = strike_config['step']
    strike_count = strike_config['count']
    
    # 获取品种名称
    product_name = PRODUCT_NAME_MAPPING.get(underlying, f"{underlying}期权")
    
    # 生成看涨和看跌期权
    for cp_type in ['C', 'P']:
        option_type = 'CALL' if cp_type == 'C' else 'PUT'
        option_type_name = "看涨期权" if cp_type == 'C' else "看跌期权"
        
        # 生成不同行权价的期权合约
        for i in range(strike_count):
            strike = base_strike + i * strike_step
            
            # 根据交易所规则生成不同格式的期权合约代码
            if exchange in ['DCE', 'SHFE', 'INE']:
                # 大连商品交易所、上海期货交易所、上海国际能源交易中心
                # 格式：{underlying}{month_year}-{cp_type}-{strike}
                option_symbol = f"{underlying}{month_year}-{cp_type}-{int(strike)}"
            elif exchange == 'CZCE':
                # 郑州商品交易所
                # 格式：{underlying}{month_year}{cp_type}{strike}
                option_symbol = f"{underlying}{month_year}{cp_type}{int(strike)}"
            elif exchange == 'CFFEX':
                # 中国金融期货交易所
                # 格式：{option_portfolio}{month_year}-{cp_type}-{strike}
                option_symbol = f"{config['option_portfolio']}{month_year}-{cp_type}-{int(strike)}"
            else:
                # 默认格式
                option_symbol = f"{underlying}{month_year}-{cp_type}-{int(strike)}"
            
            # 构建期权合约信息，确保符合天勤网关要求
            options.append({
                'symbol': option_symbol,
                'exchange': exchange,
                'name': f"{product_name}{month_year} {option_type_name} {int(strike)}",
                'class': 'OPTION',
                'option_type': option_type,
                'strike_price': strike,
                'underlying_instrument_id': f"{exchange}.{underlying}{month_year}",
                'size': config['size'],
                'price_tick': config['price_tick'],
                'min_volume': 1,
                'max_volume': None,
                'create_date': None,
                'expire_date': None,
                'product_id': underlying,
                'product_name': product_name
            })
    
    return options


def generate_option_contracts(contracts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    生成期权合约配置（自动生成期权链）
    
    Args:
        contracts: 原始合约列表
        
    Returns:
        期权合约列表
    """
    options = []
    
    # 缓存已处理的期权合约，避免重复
    processed_options = set()
    
    # 首先使用API返回的实际期权合约
    has_api_options = False
    for contract in contracts:
        try:
            # 只处理期权合约
            if contract.get('class') == 'OPTION':
                has_api_options = True
                symbol = contract.get('symbol', '')
                exchange = contract.get('exchange', '')
                
                # 跳过无效合约
                if not symbol or not exchange:
                    continue
                
                # 生成唯一标识符
                option_key = f"{exchange}.{symbol}"
                if option_key in processed_options:
                    continue
                
                # 提取基础品种代码
                base_symbol = None
                # 尝试匹配1-3个字符的品种代码
                for i in range(3, 0, -1):
                    if len(symbol) > i:
                        test_symbol = symbol[:i]
                        if test_symbol in PRODUCT_NAME_MAPPING:
                            base_symbol = test_symbol
                            break
                
                # 如果没有找到，尝试使用完整symbol
                if not base_symbol:
                    base_symbol = symbol
                
                # 获取品种名称
                product_name = PRODUCT_NAME_MAPPING.get(base_symbol, f"{base_symbol}期权")
                
                # 使用API返回的完整期权合约信息
                options.append({
                    'symbol': symbol,
                    'exchange': exchange,
                    'name': contract.get('name', f"{product_name}{symbol[-4:]}"),
                    'class': 'OPTION',
                    'option_type': contract.get('option_type', ''),
                    'strike_price': contract.get('strike_price', 0),
                    'underlying_instrument_id': contract.get('underlying_instrument_id', ''),
                    'size': contract.get('size', 1),
                    'price_tick': contract.get('price_tick', 0.01),
                    'min_volume': contract.get('min_volume', 1),
                    'max_volume': contract.get('max_volume', None),
                    'create_date': contract.get('create_date', None),
                    'expire_date': contract.get('expire_date', None),
                    'product_id': contract.get('product_id', base_symbol),
                    'product_name': contract.get('product_name', product_name)
                })
                processed_options.add(option_key)
        except Exception as e:
            print(f"处理期权合约 {contract} 时出错: {str(e)}")
            continue
    
    if has_api_options:
        print(f"从API获取到 {len(options)} 个实际期权合约")
    else:
        print("未从API获取到期权合约，使用内置配置生成...")
        # 如果API没有返回期权合约，使用原有的生成逻辑作为备用
        
        # 先从合约列表中提取有效的期货合约作为标的物
        valid_futures = []
        for contract in contracts:
            if contract.get('class') == 'FUTURE':
                valid_futures.append(contract)
        
        # 如果没有获取到有效期货合约，使用默认配置
        if not valid_futures:
            for exchange, futures in FUTURES_CONFIG.items():
                for underlying, config in futures.items():
                    for month in ['03', '04', '05', '06', '07', '08', '09', '10', '11', '12']:
                        month_year = f"26{month}"
                        
                        option_chain = generate_option_chain(underlying, month_year, exchange, config)
                        options.extend(option_chain)
        else:
            # 使用实际的期货合约生成期权链
            print(f"使用 {len(valid_futures)} 个期货合约作为标的物生成期权链")
            
            for future in valid_futures:
                try:
                    symbol = future.get('symbol', '')
                    exchange = future.get('exchange', '')
                    
                    # 提取基础品种代码（如 "i2305" -> "i"）
                    base_symbol = None
                    for underlying in FUTURES_CONFIG.get(exchange, {}):
                        if symbol.startswith(underlying):
                            base_symbol = underlying
                            break
                    
                    if base_symbol and exchange in FUTURES_CONFIG:
                        config = FUTURES_CONFIG[exchange][base_symbol]
                        
                        # 提取到期月份（如 "i2305" -> "2305"）
                        # 支持不同格式：如 "IF2305"、"i2305"、"sc2305"等
                        import re
                        month_match = re.search(r'\d{4}$', symbol)
                        if month_match:
                            month_year = month_match.group()
                            
                            option_chain = generate_option_chain(base_symbol, month_year, exchange, config)
                            options.extend(option_chain)
                except Exception as e:
                    print(f"为期货合约 {future.get('symbol', '')} 生成期权链时出错: {str(e)}")
                    continue
    
    return options


def save_contracts_to_json(contracts: List[Dict[str, Any]], filepath: str) -> bool:
    """
    保存合约列表到JSON文件
    
    Args:
        contracts: 合约列表
        filepath: 文件路径
        
    Returns:
        是否保存成功
    """
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(contracts, f, ensure_ascii=False, indent=4)
        print(f"合约文件已保存到: {filepath}")
        print(f"共保存 {len(contracts)} 个合约")
        return True
    except Exception as e:
        print(f"保存文件失败: {str(e)}")
        return False


def generate_contracts_dict(account: str = "16740529999", password: str = "19841228") -> List[Dict[str, Any]]:
    """
    生成合约字典，可直接在网关中引用
    
    Args:
        account: 天勤账号
        password: 天勤密码
        
    Returns:
        合约字典列表
    """
    try:
        # 创建API对象
        api = TqApi(auth=TqAuth(account, password))
        
        # 从天勤API查询合约列表
        all_contracts = query_all_contracts(api)
        
        # 如果没有从API获取到合约，使用内置配置生成
        if not all_contracts:
            print("未查询到合约，使用内置配置生成...")
            all_contracts = []
            
            # 获取当前年份的后两位，用于生成合约月份
            current_year = datetime.now().year % 100
            
            for exchange, futures in FUTURES_CONFIG.items():
                for underlying, config in futures.items():
                    for month in ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12']:
                        symbol = f"{underlying}{current_year}{month}"
                        all_contracts.append({
                            'symbol': symbol,
                            'exchange': exchange,
                            'name': config['name'],
                            'class': 'FUTURE',
                            'size': config['size'],
                            'price_tick': config['price_tick'],
                            'min_volume': 1
                        })
        
        # 生成期货合约配置
        futures = generate_futures_contracts(all_contracts)
        
        # 自动生成期权链配置
        options = generate_option_contracts(all_contracts)
        
        # 合并合约
        all_contracts = futures + options
        
        # 去重处理
        unique_contracts = []
        processed_contracts = set()
        for contract in all_contracts:
            contract_key = f"{contract.get('exchange', '')}.{contract.get('symbol', '')}"
            if contract_key not in processed_contracts:
                unique_contracts.append(contract)
                processed_contracts.add(contract_key)
        
        return unique_contracts
    except Exception as e:
        print(f"生成合约字典失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return []
    finally:
        # 确保API资源被释放
        try:
            api.close()
        except:
            pass


def get_contracts_dict(account: str = "16740529999", password: str = "19841228") -> List[Dict[str, Any]]:
    """
    获取合约字典，优先从文件加载，失败则生成
    
    Args:
        account: 天勤账号
        password: 天勤密码
        
    Returns:
        合约字典列表
    """
    import os
    
    # 尝试从文件加载
    contracts_file = os.path.join(os.path.dirname(__file__), "tqsdk_contracts.json")
    if os.path.exists(contracts_file):
        try:
            with open(contracts_file, "r", encoding="utf-8") as f:
                contracts = json.load(f)
            print(f"从文件加载了 {len(contracts)} 个合约")
            return contracts
        except Exception as e:
            print(f"从文件加载合约失败: {str(e)}")
    
    # 文件加载失败，生成新合约
    print("从文件加载合约失败，正在生成新合约...")
    return generate_contracts_dict(account, password)


def main():
    """
    主函数
    """
    parser = argparse.ArgumentParser(description='天勤网关合约JSON文件自动生成工具')
    parser.add_argument('--account', type=str, required=False, help='天勤账号')
    parser.add_argument('--password', type=str, required=False, help='天勤密码')
    parser.add_argument('--output', type=str, required=False, help='输出文件路径')
    args = parser.parse_args()
    
    print("=" * 60)
    print("天勤网关合约JSON文件自动生成工具")
    print("=" * 60)
    
    try:
        # 使用默认账号密码或从命令行参数获取
        account = args.account if args.account else "16740529999"
        password = args.password if args.password else "19841228"
        
        print(f"\n使用账号: {account}")
        print(f"使用密码: {password}")
        
        # 生成合约字典
        unique_contracts = generate_contracts_dict(account, password)
        
        print(f"\n2. 生成期货合约配置...")
        print(f"   生成 {len([c for c in unique_contracts if c['class'] == 'FUTURE'])} 个期货合约")
        
        print(f"\n3. 自动生成期权链配置...")
        print(f"   生成 {len([c for c in unique_contracts if c['class'] == 'OPTION'])} 个期权合约")
        
        print(f"\n4. 保存合约配置文件...")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_file = args.output if args.output else os.path.join(script_dir, 'tqsdk_contracts.json')
        
        if save_contracts_to_json(unique_contracts, output_file):
            print(f"\n✅ 合约文件生成成功！")
            print(f"\n文件路径: {output_file}")
            
            # 统计期货和期权数量
            futures_count = len([c for c in unique_contracts if c['class'] == 'FUTURE'])
            options_count = len([c for c in unique_contracts if c['class'] == 'OPTION'])
            
            print(f"\n期货合约: {futures_count} 个")
            print(f"期权合约: {options_count} 个")
            print(f"去重后合约总数: {len(unique_contracts)} 个")
            
            # 按交易所统计
            print(f"\n按交易所统计:")
            exchange_stats = {}
            for contract in unique_contracts:
                exchange = contract.get('exchange', '')
                if exchange not in exchange_stats:
                    exchange_stats[exchange] = {'futures': 0, 'options': 0}
                
                if contract.get('class') == 'FUTURE':
                    exchange_stats[exchange]['futures'] += 1
                elif contract.get('class') == 'OPTION':
                    exchange_stats[exchange]['options'] += 1
            
            for exchange, stats in sorted(exchange_stats.items()):
                print(f"  {exchange}: 期货 {stats['futures']} 个, 期权 {stats['options']} 个")
            
            # 支持的期权产品
            print(f"\n支持的期权产品:")
            for option_type, mappings in OPTION_PORTFOLIO_MAPPING.items():
                products = ', '.join(mappings.values())
                print(f"  {option_type}: {products}")
            
            print(f"\n✅ 合约生成完成！")
        else:
            print(f"\n❌ 合约文件生成失败！")
    
    except KeyboardInterrupt:
        print(f"\n\n❌ 操作被用户中断")
    except Exception as e:
        print(f"\n\n❌ 发生错误: {str(e)}")
        import traceback
        traceback.print_exc()
        print(f"\n请检查:")
        print(f"1. 天勤API账号密码是否正确")
        print(f"2. 网络连接是否正常")
        print(f"3. 天勤SDK版本是否兼容")
        print(f"\n使用方法:")
        print(f"  python generate_contracts.py --account <天勤账号> --password <天勤密码> [--output <输出文件路径>]")
    finally:
        print(f"\n程序执行完成")


if __name__ == "__main__":
    main()
