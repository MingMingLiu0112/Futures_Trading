"""
PX 外盘亚洲 CFR 中国收盘价 — 抓取脚本（best-effort）

策略：依次尝试多个免费源；任意一个成功就采纳并写盘，全部失败保留上次成功记录。
本脚本只负责写 data/fundamental/px_external_scrape.json，不直接进入报告。
合并/谁最新用谁由 macro.px_external_source.merge_pick_winner 统一处理。

使用方法：
  python3 -m macro.px_external_scraper              # 跑一次
  python3 -m macro.px_external_scraper --show      # 跑一次并打印结果
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

from macro.px_external_source import (
    PRICE_MAX, PRICE_MIN, SCRAPE_PATH, load_scrape, save_scrape,
)

PROXY = "http://127.0.0.1:7890"  # 本地代理（外网必须走代理）

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Upgrade-Insecure-Requests": "1",
}

# 常见 PX 价格段落正则：例如 "亚洲PX收 1166.33 美元/吨 CFR中国"
PX_RE = re.compile(
    r"(?:亚洲\s*)?PX[\u4e00-\u9fa5]{0,6}?[\s\S]{0,40}?(\d{3,4}(?:\.\d+)?)\s*(?:美元|USD|\$)",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


def _http_get(url: str, timeout: int = 10) -> Tuple[int, str]:
    if requests is None:
        return 0, ''
    try:
        r = requests.get(
            url, headers=HEADERS,
            proxies={"http": PROXY, "https": PROXY},
            timeout=timeout, allow_redirects=True,
        )
        return r.status_code, r.text or ''
    except Exception as e:  # pragma: no cover
        return 0, f"ERR: {e!r}"


def _try_100ppi() -> Optional[Dict[str, Any]]:
    """尝试 100ppi.com 主页/列表/详情（已知大多 404，但每天源可能变）。"""
    urls = [
        "http://www.100ppi.com/",
        "http://www.100ppi.com/web/price/",
        "http://www.100ppi.com/sf/",
    ]
    for url in urls:
        code, body = _http_get(url)
        if code != 200 or not body:
            continue
        # 1) 价格
        m = PX_RE.search(body)
        if m:
            try:
                price = float(m.group(1))
                if PRICE_MIN <= price <= PRICE_MAX:
                    dm = DATE_RE.search(body) or DATE_RE.search(url) or None
                    return {
                        'px_asia_close_usd': price,
                        'date': dm.group(1) if dm else datetime.now().strftime('%Y-%m-%d'),
                        'source': f"100ppi:{url.split('/')[-1] or 'home'}",
                        'note': m.group(0)[:80],
                    }
            except ValueError:
                pass
    return None


def _try_goodsfu() -> Optional[Dict[str, Any]]:
    """尝试同花顺 goodsfu.10jqka.com.cn（可能无 PX）。"""
    url = "https://goodsfu.10jqka.com.cn/web/price/detail-PX"
    code, body = _http_get(url, timeout=8)
    if code != 200 or not body:
        return None
    m = PX_RE.search(body)
    if m:
        try:
            price = float(m.group(1))
            if PRICE_MIN <= price <= PRICE_MAX:
                dm = DATE_RE.search(body)
                return {
                    'px_asia_close_usd': price,
                    'date': dm.group(1) if dm else datetime.now().strftime('%Y-%m-%d'),
                    'source': 'goodsfu:PX',
                    'note': m.group(0)[:80],
                }
        except ValueError:
            pass
    return None


SOURCES = [_try_100ppi, _try_goodsfu]


def fetch() -> Dict[str, Any]:
    """依次尝试源；任一成功即写盘并返回；全部失败则保留上次成功记录并标记 failed。"""
    errors: List[str] = []
    for fn in SOURCES:
        try:
            rec = fn()
        except Exception as e:  # pragma: no cover
            rec = None
            errors.append(f"{fn.__name__}: {e!r}")
        if rec:
            rec['status'] = 'ok'
            rec['error'] = ''
            return save_scrape(rec)

    # 全部失败：保留上次（如果有），否则写一条 failed 占位
    last = load_scrape() or {}
    if last.get('px_asia_close_usd'):
        last = dict(last)
        last['status'] = 'failed'
        last['error'] = '今日所有源抓取失败，保留上次成功记录 | ' + ' | '.join(errors)
        last['fetched_at'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        return save_scrape(last)
    return save_scrape({
        'px_asia_close_usd': 0,
        'date': '',
        'source': 'scraper',
        'status': 'failed',
        'error': '全部源失败 | ' + ' | '.join(errors),
        'note': '尚未抓取到 PX 外盘数据',
    })


def main() -> int:
    started = time.time()
    rec = fetch()
    print(json.dumps({
        'elapsed_sec': round(time.time() - started, 2),
        'result': rec,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
