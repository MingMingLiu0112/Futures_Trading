"""
期权合约验证脚本
用于验证期权链的完整性和正确性
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vnpy.gateway.tqsdk.option_parser import OptionContractParser
from vnpy.trader.constant import Exchange


def load_contracts(file_path: str = "tqsdk_contracts.json"):
    """
    加载合约配置文件
    """
    full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), file_path)
    with open(full_path, "r", encoding="utf-8") as f:
        return json.load(f)


def analyze_option_contracts(contracts):
    """
    分析期权合约，构建期权链
    """
    portfolios = {}
    
    for contract_info in contracts:
        symbol = contract_info.get("symbol")
        exchange_str = contract_info.get("exchange")
        
        if not symbol or not exchange_str:
            continue
        
        try:
            exchange = Exchange(exchange_str)
        except:
            continue
        
        if not OptionContractParser.is_option_contract(symbol, exchange):
            continue
        
        option_info = OptionContractParser.parse_option_info(symbol, exchange)
        if not option_info:
            continue
        
        portfolio = option_info.get("option_portfolio")
        expiry = option_info.get("option_expiry")
        strike = option_info.get("option_strike")
        option_type = option_info.get("option_type")
        underlying = option_info.get("option_underlying")
        
        if not portfolio:
            continue
        
        if portfolio not in portfolios:
            portfolios[portfolio] = {
                "name": portfolio,
                "underlying": underlying,
                "chains": {}
            }
        
        expiry_key = expiry.strftime("%Y-%m") if expiry else "unknown"
        if expiry_key not in portfolios[portfolio]["chains"]:
            portfolios[portfolio]["chains"][expiry_key] = {
                "expiry": expiry,
                "strikes": set(),
                "calls": {},
                "puts": {}
            }
        
        chain = portfolios[portfolio]["chains"][expiry_key]
        chain["strikes"].add(strike)
        
        if option_type.value == "看涨期权":
            chain["calls"][strike] = {
                "symbol": symbol,
                "exchange": exchange_str,
                "name": contract_info.get("name", ""),
                "size": contract_info.get("size", 1),
                "price_tick": contract_info.get("price_tick", 0.01)
            }
        else:
            chain["puts"][strike] = {
                "symbol": symbol,
                "exchange": exchange_str,
                "name": contract_info.get("name", ""),
                "size": contract_info.get("size", 1),
                "price_tick": contract_info.get("price_tick", 0.01)
            }
    
    return portfolios


def print_portfolio_summary(portfolios):
    """
    打印期权组合摘要
    """
    print("=" * 80)
    print("期权组合摘要")
    print("=" * 80)
    
    total_portfolios = len(portfolios)
    total_chains = 0
    total_options = 0
    
    for portfolio_name, portfolio_data in sorted(portfolios.items()):
        print(f"\n期权产品: {portfolio_name}")
        print(f"  标的物: {portfolio_data['underlying']}")
        print(f"  期权链数量: {len(portfolio_data['chains'])}")
        
        for expiry_key, chain_data in sorted(portfolio_data['chains'].items()):
            total_chains += 1
            strikes = sorted(chain_data['strikes'])
            num_calls = len(chain_data['calls'])
            num_puts = len(chain_data['puts'])
            total_options += num_calls + num_puts
            
            print(f"\n  期权链: {expiry_key}")
            print(f"    到期日: {chain_data['expiry']}")
            print(f"    行权价数量: {len(strikes)}")
            if strikes:
                print(f"    行权价范围: {strikes[0]} ~ {strikes[-1]}")
            print(f"    看涨期权: {num_calls} 个")
            print(f"    看跌期权: {num_puts} 个")
    
    print("\n" + "=" * 80)
    print(f"总计: {total_portfolios} 个期权产品, {total_chains} 条期权链, {total_options} 个期权合约")
    print("=" * 80)


def validate_option_chains(portfolios):
    """
    验证期权链的完整性
    """
    print("\n" + "=" * 80)
    print("期权链完整性验证")
    print("=" * 80)
    
    issues = []
    
    for portfolio_name, portfolio_data in sorted(portfolios.items()):
        for expiry_key, chain_data in sorted(portfolio_data['chains'].items()):
            strikes = sorted(chain_data['strikes'])
            calls = chain_data['calls']
            puts = chain_data['puts']
            
            for strike in strikes:
                if strike not in calls:
                    issues.append(f"{portfolio_name} {expiry_key}: 行权价 {strike} 缺少看涨期权")
                if strike not in puts:
                    issues.append(f"{portfolio_name} {expiry_key}: 行权价 {strike} 缺少看跌期权")
    
    if issues:
        print("\n发现问题:")
        for issue in issues:
            print(f"  ⚠️  {issue}")
    else:
        print("\n✓ 所有期权链完整，每个行权价都有对应的看涨和看跌期权")
    
    print("=" * 80)


def print_t_type_quote_structure(portfolios):
    """
    打印T型报价结构
    """
    print("\n" + "=" * 80)
    print("T型报价结构示例")
    print("=" * 80)
    
    for portfolio_name, portfolio_data in sorted(portfolios.items()):
        if len(portfolio_data['chains']) == 0:
            continue
        
        print(f"\n期权产品: {portfolio_name}")
        
        for expiry_key, chain_data in sorted(list(portfolio_data['chains'].items())[:1]):
            strikes = sorted(chain_data['strikes'])
            
            if len(strikes) == 0:
                continue
            
            print(f"\n  期权链: {expiry_key}")
            print(f"  {'行权价':<15} {'看涨期权':<30} {'看跌期权':<30}")
            print(f"  {'-'*15} {'-'*30} {'-'*30}")
            
            for strike in strikes:
                call_symbol = chain_data['calls'].get(strike, {}).get('symbol', 'N/A')
                put_symbol = chain_data['puts'].get(strike, {}).get('symbol', 'N/A')
                
                print(f"  {strike:<15.2f} {call_symbol:<30} {put_symbol:<30}")
            
            print(f"\n  ✓ T型报价可用于期权模块的T型报价窗口")
            break
        
        if len(portfolio_data['chains']) > 0:
            break
    
    print("=" * 80)


def main():
    """
    主函数
    """
    print("加载合约配置文件...")
    contracts = load_contracts()
    
    print(f"共加载 {len(contracts)} 个合约")
    
    print("\n分析期权合约...")
    portfolios = analyze_option_contracts(contracts)
    
    print_portfolio_summary(portfolios)
    validate_option_chains(portfolios)
    print_t_type_quote_structure(portfolios)
    
    print("\n✓ 验证完成！期权模块现在可以使用完整的期权组合和期权链。")


if __name__ == "__main__":
    main()
