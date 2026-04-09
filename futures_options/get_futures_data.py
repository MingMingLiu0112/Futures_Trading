def get_futures_daily(symbol: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    使用AKShare获取期货日线数据
    symbol格式: 如 'M2509' 表示豆粕2509, 'M' 表示豆粕主力
    """
    try:
        import akshare as ak
        import pandas as pd
        from datetime import datetime, timedelta
        
        # 解析合约 - 去掉数字只保留品种代码
        contract_code = symbol.upper()
        base_symbol = ''.join([c for c in contract_code if not c.isdigit()]) or contract_code
        
        print(f"正在获取 {symbol} ({base_symbol}) 数据...")
        
        # 获取数据
        df = pd.DataFrame()
        
        # 方法1: 新浪期货日线 - 使用品种代码
        try:
            df = ak.futures_zh_daily_sina(symbol=base_symbol)
            print(f"✅ 新浪数据: {len(df)}条")
        except Exception as e1:
            print(f"新浪方法失败: {e1}")
        
        # 方法2: 大商所期货
        if df.empty:
            try:
                df = ak.futures_daily_sina(symbol=base_symbol)
                print(f"✅ 大商所数据: {len(df)}条")
            except Exception as e2:
                print(f"大商所方法失败: {e2}")
        
        # 方法3: 东财期货历史
        if df.empty:
            try:
                df = ak.futures_zh_history(symbol="dalian")
                if not df.empty and 'symbol' in df.columns:
                    df = df[df['symbol'].str.contains(base_symbol, na=False)]
                print(f"✅ 东财历史数据: {len(df)}条")
            except Exception as e3:
                print(f"东财历史方法失败: {e3}")
        
        if df.empty:
            print(f"⚠️ {symbol} 所有数据源均失败")
            return pd.DataFrame()
        
        # 统一列名
        rename_map = {
            '日期': 'date', 'date': 'date', 'trade_date': 'date',
            '开盘': 'open', 'open': 'open',
            '最高': 'high', 'high': 'high',
            '最低': 'low', 'low': 'low',
            '收盘': 'close', 'close': 'close',
            '成交量': 'volume', 'volume': 'volume',
            '持仓量': 'position', 'position': 'position'
        }
        df = df.rename(columns=rename_map)
        
        # 转换日期
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df = df.sort_values('date')
        
        # 确保数值类型
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 取最近60天
        if len(df) > 60:
            df = df.tail(60)
        
        print(f"   最终数据: {len(df)}条")
        return df
        
    except Exception as e:
        print(f"获取期货数据失败: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()
