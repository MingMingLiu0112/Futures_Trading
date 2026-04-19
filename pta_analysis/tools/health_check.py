#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
健康检查脚本 - 定时执行，监控服务状态
"""
import sys
sys.path.insert(0, '/app')

import json
import traceback
from datetime import datetime

def check_mysql():
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(
            "mysql+pymysql://pta:pta_pass_2025@localhost:3306/pta_analysis?charset=utf8mb4",
            pool_size=2, pool_recycle=1800
        )
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).fetchone()
        engine.dispose()
        return True, "MySQL 正常"
    except Exception as e:
        return False, f"MySQL 异常: {e}"

def check_redis():
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0)
        r.ping()
        r.close()
        return True, "Redis 正常"
    except Exception as e:
        return False, f"Redis 异常: {e}"

def check_akshare():
    try:
        import akshare as ak
        # 简单测试一个接口
        df = ak.futures_spot_price(exchange="CZCE", symbol="TA")
        return True, f"AKShare 正常 (TA数据: {len(df)} 条)"
    except Exception as e:
        return False, f"AKShare 异常: {e}"

def check_vnpy():
    try:
        import vnpy
        from vnpy.ctp import CtpGateway
        return True, f"vnpy {vnpy.__version__} 正常"
    except Exception as e:
        return False, f"vnpy 异常: {e}"

def check_tqsdk():
    try:
        import tqsdk
        return True, f"tqsdk 正常"
    except Exception as e:
        return False, f"tqsdk 异常: {e}"

def main():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results = {}
    all_ok = True

    checks = [
        ("MySQL", check_mysql),
        ("Redis", check_redis),
        ("AKShare", check_akshare),
        ("vnpy", check_vnpy),
        ("TQSdk", check_tqsdk),
    ]

    for name, func in checks:
        try:
            ok, msg = func()
            results[name] = {"status": "up" if ok else "down", "message": msg}
            if not ok:
                all_ok = False
        except Exception as e:
            results[name] = {"status": "error", "message": str(e)}
            all_ok = False

    log_entry = {
        "timestamp": timestamp,
        "overall": "healthy" if all_ok else "degraded",
        "checks": results
    }

    log_file = "/app/logs/health_check.log"
    try:
        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    except:
        pass

    # 打印摘要
    status_icon = "✅" if all_ok else "⚠️"
    print(f"{status_icon} [{timestamp}] 健康检查: {'全部正常' if all_ok else '部分异常'}")
    for name, result in results.items():
        icon = "✅" if result["status"] == "up" else "❌"
        print(f"  {icon} {name}: {result['message']}")

    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
