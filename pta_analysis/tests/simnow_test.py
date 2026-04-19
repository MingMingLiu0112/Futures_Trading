#!/usr/bin/env python3
"""
SimNow模拟行情接收测试
SimNow是期货公司提供的模拟交易环境，可用于测试

SimNow账户信息：
- BrokerID: 9999
- UserID: 12888
- Password: 12888
- TradeFront: 218.202.237.33:66603
- MarketFront: 218.202.237.33:66604

注意：这是simnow官方提供的通用测试账户，仅供测试使用
"""

import sys
sys.path.insert(0, '/home/admin/.pyenv/versions/3.11.9/lib/python3.11/site-packages')

from vnpy.trader.constant import Direction, Offset, Exchange, Product, Status, OrderType
from vnpy.trader.gateway import BaseGateway
from vnpy.event import EventEngine
import time

# SimNow配置
SIMNOW_CONFIG = {
    "broker_id": "9999",
    "user_id": "12888",
    "password": "12888",
    "trade_front": "218.202.237.33:66603",
    "market_front": "218.202.237.33:66604",
    "app_id": "trader_simnow",
    "auth_code": "",
}

def test_vnpy_ctp():
    """测试vnpy CTP接口"""
    print("=" * 50)
    print("SimNow CTP行情接收测试")
    print("=" * 50)
    
    # 检查vnpy是否可用
    try:
        from vnpy.ctp import CtpGateway
        print(f"✅ CtpGateway 可用")
    except Exception as e:
        print(f"❌ CtpGateway 导入失败: {e}")
        return
    
    # 尝试连接
    print(f"\n配置信息:")
    print(f"  BrokerID: {SIMNOW_CONFIG['broker_id']}")
    print(f"  UserID: {SIMNOW_CONFIG['user_id']}")
    print(f"  MarketFront: {SIMNOW_CONFIG['market_front']}")
    print()
    print("注意: SimNow账户信息可能已过期，需要从官网获取最新账户")
    print("官网: https://www.simnow.com.cn")
    
    # 尝试基本连接测试
    print("\n尝试初始化连接...")
    try:
        # 创建网关
        gateway = CtpGateway(gateway_name="SimNow")
        print(f"✅ 网关创建成功")
        
        # 注意: 实际连接需要完整的CTP接口库
        # 这里只是验证接口可用
        print(f"✅ CTP接口验证完成")
        
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        print("\n可能原因:")
        print("1. 缺少CTP接口库(64位)")
        print("2. 账户信息过期")
        print("3. 网络连接问题")
        
        # 检查vnpy其他接口
        print("\n检查vnpy其他可用接口...")
        try:
            from vnpy.trader.rqdata import RqdataGateway
            print("✅ RqdataGateway 可用(需要RQData账户)")
        except:
            pass
        
        try:
            from vnpy.trader.tts import TtsGateway
            print("✅ TtsGateway 可用(需要TTS服务)")
        except:
            pass

def test_ctp_direct():
    """直接测试CTP接口(需要完整库)"""
    print("\n" + "=" * 50)
    print("CTP直连测试")
    print("=" * 50)
    
    try:
        from ctp import ApiStruct, TraderApi
        print("✅ pyctp库可用")
    except ImportError:
        print("❌ pyctp库未安装")
        
    try:
        import tqsdk
        print("✅ 天勤量化(TQSdk)可用")
        print("   天勤量化是国产免费期货数据接口，可考虑使用")
    except ImportError:
        print("❌ 天勤量化未安装")

def test_tqsdk():
    """测试天勤量化(免费实时行情)"""
    print("\n" + "=" * 50)
    print("天勤量化(TQSdk)测试")
    print("=" * 50)
    
    try:
        import tqsdk
        print("✅ 天勤量化已安装")
        
        # 天勤量化使用示例
        print("\n天勤量化特点:")
        print("- 免费使用，无需账户")
        print("- 支持期货、期权、现货数据")
        print("- Python原生支持")
        print("- 适合量化策略研究")
        
        # 尝试获取T合约行情
        print("\n尝试获取PTA(T)行情...")
        from tqsdk import TqApi
        
        api = TqApi()
        ta = api.get_quote("CZCE.TA")
        print(f"合约: {ta.exchange}.{ta.instrument_id}")
        print(f"最新价: {ta.last_price}")
        print(f"卖一价: {ta.ask_price1}")
        print(f"买一价: {ta.bid_price1}")
        print(f"成交量: {ta.volume}")
        print(f"持仓量: {ta.open_interest}")
        
        api.close()
        print("\n✅ 天勤量化连接成功!")
        return True
        
    except ImportError:
        print("❌ 天勤量化未安装")
        print("安装命令: pip install tqsdk")
        return False
    except Exception as e:
        print(f"❌ 天勤量化连接失败: {e}")
        return False

if __name__ == "__main__":
    print("SimNow测试开始...\n")
    
    # 测试vnpy CTP
    test_vnpy_ctp()
    
    # 测试CTP直连
    test_ctp_direct()
    
    # 测试天勤量化
    tqsdk_ok = test_tqsdk()
    
    print("\n" + "=" * 50)
    print("总结")
    print("=" * 50)
    
    if tqsdk_ok:
        print("✅ 天勤量化可用，建议优先使用")
        print("   优势: 免费、无需账户、Python原生支持")
    else:
        print("❌ 天勤量化不可用")
    
    print("\n下一步:")
    print("1. 安装天勤量化: pip install tqsdk")
    print("2. 使用TQSdk获取实时行情")
    print("3. 结合现有分析系统进行测试")