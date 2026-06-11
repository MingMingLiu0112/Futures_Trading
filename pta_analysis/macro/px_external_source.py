
"""
PX 外盘亚洲 CFR 中国收盘价数据源（人工 + 抓取双路径，谁最新用谁）

数据源结构（统一 schema）:
{
  "px_asia_close_usd": 905.67,        # 必填
  "date": "2026-06-10",                # 必填：价格级别对应的交易日（"最新"指它）
  "fetched_at": "2026-06-11T13:00:00", # 抓取/录入时间（仅用于新鲜度诊断，不参与排名）
  "source": "manual:生意社" | "scraper:...",
  "note": "...",
  "status": "ok" | "failed",           # 仅 scraper 用
  "error": ""                          # 仅 scraper 用
}

"最新" = 级别数据（price level）的 trade_date 越新越好：
  - 即便 905 是 6/10 抓取的，但它的 trade_date 是 6/8；
  - 1166 trade_date 是 6/9；
  - 6/9 > 6/8 → 选 1166；fetched_at 不参与排序。
  
Merge 规则：
  1. 过滤：price 必须在 [500, 2000]，date 必须能解析
  2. 排序：trade_date DESC（仅此一项）
  3. 并列：manual 优先（人工录入更受信任）
  4. 没候选 → None
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPE_PATH = os.path.join(WORKSPACE, 'data', 'fundamental', 'px_external_scrape.json')

# 合理价区间（USD/吨 CFR 中国），用于防呆
PRICE_MIN = 500.0
PRICE_MAX = 2000.0

# 不同来源的价格级别新鲜度容忍（小时）— 同样基于 trade_date，不是 fetched_at
# 1166 trade_date=6/9，今天 6/11 → age=2 天，仍可用
# 老于 7 天的 trade_date 一律视为"价格已无代表性"，拒绝
LEVEL_FRESHNESS_HOURS = {
    'manual': 7 * 24,
    'scraper': 7 * 24,
    'text': 3 * 24,   # 文本正则没有明确 date，宽容度更低
}


def _parse_dt(value: Any) -> Optional[datetime]:
    """把字符串/datetime 解析成 datetime；解析失败返回 None。"""
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if not s:
        return None
    # 兼容 "YYYY-MM-DD HH:MM:SS" 和 ISO "YYYY-MM-DDTHH:MM:SS"
    for fmt in (
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d',
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _is_valid_record(rec: Dict[str, Any], source_kind: str) -> bool:
    """有效性：价格合理 + trade_date 可解析 + 价格级别仍在新鲜度窗口内。

    注意：freshness 是基于 **trade_date vs NOW**（价格级别的实时性），
    不是 fetched_at vs NOW（数据抓取延迟）。
    """
    if not isinstance(rec, dict):
        return False
    try:
        price = float(rec.get('px_asia_close_usd') or rec.get('price') or 0)
    except (TypeError, ValueError):
        return False
    if not (PRICE_MIN <= price <= PRICE_MAX):
        return False
    trade_dt = _parse_dt(rec.get('date'))
    if trade_dt is None:
        return False
    # 价格级别距今的新鲜度（基于 trade_date）
    level_age_hours = (datetime.now() - trade_dt).total_seconds() / 3600
    gate = LEVEL_FRESHNESS_HOURS.get(source_kind, 7 * 24)
    if level_age_hours > gate:
        return False
    # 防呆：fetched_at 不能远早于 trade_date（数据完整性）
    fetched_dt = _parse_dt(rec.get('fetched_at'))
    if fetched_dt is not None:
        skew = (fetched_dt - trade_dt).total_seconds() / 3600
        if skew < -24 or skew > 14 * 24:
            return False
    return True


def load_scrape(path: str = SCRAPE_PATH) -> Optional[Dict[str, Any]]:
    """读抓取文件；不存在或损坏返回 None。"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_scrape(data: Dict[str, Any], path: str = SCRAPE_PATH) -> Dict[str, Any]:
    """原子写：先写 .tmp 再 rename。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = dict(data or {})
    data.setdefault('fetched_at', datetime.now().strftime('%Y-%m-%dT%H:%M:%S'))
    data.setdefault('source', 'scraper')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return data


def collect_candidates(
    manual_macro: Optional[Dict[str, Any]] = None,
    scrape: Optional[Dict[str, Any]] = None,
    text_extracted: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    收集三路候选（人工 dict / 抓取 dict / 正则文本 dict），过滤、附加 source_kind。
    每个候选标准化为：
      {
        'px_asia_close_usd', 'date', 'fetched_at', 'source', 'source_text', 'source_kind'
      }
    """
    out: List[Dict[str, Any]] = []

    # 1) 人工 dict
    if isinstance(manual_macro, dict):
        pe = manual_macro.get('px_external') if isinstance(manual_macro.get('px_external'), dict) else manual_macro
        if isinstance(pe, dict):
            try:
                price = float(pe.get('px_asia_close_usd') or pe.get('price') or 0)
            except (TypeError, ValueError):
                price = 0
            if price:
                out.append({
                    'px_asia_close_usd': price,
                    'date': pe.get('date') or manual_macro.get('as_of_date') or '',
                    'fetched_at': pe.get('fetched_at') or manual_macro.get('updated_at') or '',
                    'source': f"manual:{pe.get('source', '人工')}",
                    'source_text': pe.get('note', ''),
                    'source_kind': 'manual',
                })

    # 2) 抓取 dict
    if isinstance(scrape, dict) and scrape.get('status') != 'failed':
        try:
            price = float(scrape.get('px_asia_close_usd') or 0)
        except (TypeError, ValueError):
            price = 0
        if price:
            out.append({
                'px_asia_close_usd': price,
                'date': scrape.get('date', ''),
                'fetched_at': scrape.get('fetched_at', ''),
                'source': f"scraper:{scrape.get('source', 'auto')}",
                'source_text': scrape.get('note', scrape.get('error', '')),
                'source_kind': 'scraper',
            })

    # 3) 文本正则 dict（无 date 时回退到 updated_at 当日）
    if isinstance(text_extracted, dict) and text_extracted.get('px_asia_close_usd'):
        out.append({
            'px_asia_close_usd': float(text_extracted['px_asia_close_usd']),
            'date': text_extracted.get('date', ''),
            'fetched_at': text_extracted.get('fetched_at', ''),
            'source': text_extracted.get('source', 'text:regex'),
            'source_text': text_extracted.get('source_text', ''),
            'source_kind': 'text',
        })

    return out


def merge_pick_winner(
    manual_macro: Optional[Dict[str, Any]] = None,
    scrape: Optional[Dict[str, Any]] = None,
    text_extracted: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    选最新一条：**trade_date DESC**（"最新"=价格级别最新），并列时 manual 优先。
    fetched_at 不参与排序（它只用于诊断和有效性的完整性检查）。

    返回 (winner, all_valid_candidates)。
    """
    candidates = collect_candidates(manual_macro, scrape, text_extracted)
    valid: List[Dict[str, Any]] = []
    for c in candidates:
        if not _is_valid_record(c, c['source_kind']):
            continue
        c['_trade_dt'] = _parse_dt(c.get('date'))
        valid.append(c)

    if not valid:
        return None, []

    def sort_key(c: Dict[str, Any]):
        # trade_date 是唯一排序键；并列时 manual 优先
        kind_rank = 0 if c['source_kind'] == 'manual' else 1
        return (c['_trade_dt'], -kind_rank)

    valid.sort(key=sort_key, reverse=True)
    return valid[0], valid


def format_winner(winner: Dict[str, Any]) -> Dict[str, Any]:
    """把赢家候选序列化成下游需要的 result 字段。"""
    return {
        'px_asia_close_usd': float(winner['px_asia_close_usd']),
        'date': winner.get('date', ''),
        'fetched_at': winner.get('fetched_at', ''),
        'source': winner.get('source', ''),
        'source_text': winner.get('source_text', ''),
        'source_kind': winner.get('source_kind', ''),
    }
