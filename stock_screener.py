#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import email.message
import html
import http.client
import json
import os
import smtplib
import ssl
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


CACHE_DIR = Path(".cache")
TWSE_URL = "https://www.twse.com.tw/exchangeReport/MI_INDEX"
TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"


@dataclass(frozen=True)
class Candle:
    date: str
    symbol: str
    name: str
    market: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    change_pct: float | None = None


@dataclass(frozen=True)
class ScoredStock:
    candle: Candle
    score: int
    reasons: tuple[str, ...]
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class AIReview:
    decision: str
    risk_level: str
    summary: str
    flags: tuple[str, ...] = ()


def parse_number(value: object) -> float | int | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if text in {"", "--", "---", "除權息"}:
        return None
    text = text.replace("+", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def pick_ranked_candidates(rows: Iterable[Candle], limit: int = 100) -> list[Candle]:
    usable = [row for row in rows if row.close > 0 and row.volume > 0]
    ranked_lists = [
        sorted(usable, key=lambda row: row.volume, reverse=True)[:limit],
        sorted((r for r in usable if r.change_pct is not None), key=lambda row: row.change_pct or 0, reverse=True)[:limit],
        sorted((r for r in usable if r.change_pct is not None), key=lambda row: row.change_pct or 0)[:limit],
    ]
    seen: set[str] = set()
    picked: list[Candle] = []
    for ranked in ranked_lists:
        for row in ranked:
            if row.symbol not in seen:
                seen.add(row.symbol)
                picked.append(row)
    return picked


def sma(values: list[float], days: int) -> float | None:
    if len(values) < days:
        return None
    return sum(values[-days:]) / days


def ema(values: list[float], days: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (days + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append(value * alpha + out[-1] * (1 - alpha))
    return out


def macd_histogram(closes: list[float]) -> list[float]:
    if len(closes) < 26:
        return []
    fast = ema(closes, 12)
    slow = ema(closes, 26)
    dif = [a - b for a, b in zip(fast, slow)]
    signal = ema(dif, 9)
    return [a - b for a, b in zip(dif, signal)]


def rsi(closes: list[float], days: int = 14) -> float | None:
    if len(closes) <= days:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for prev, cur in zip(closes[-days - 1 : -1], closes[-days:]):
        diff = cur - prev
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / days
    avg_loss = sum(losses) / days
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def body(candle: Candle) -> float:
    return abs(candle.close - candle.open)


def candle_range(candle: Candle) -> float:
    return max(candle.high - candle.low, 0.0001)


def is_red(candle: Candle) -> bool:
    return candle.close > candle.open


def is_green(candle: Candle) -> bool:
    return candle.close < candle.open


def is_long_body(candle: Candle, min_ratio: float = 0.55) -> bool:
    return body(candle) >= candle_range(candle) * min_ratio


def is_small_body(candle: Candle, max_ratio: float = 0.35) -> bool:
    return body(candle) <= candle_range(candle) * max_ratio


def has_downtrend(candles: list[Candle], lookback: int = 5) -> bool:
    sample = candles[-lookback:]
    if len(sample) < 3:
        return False
    lower_closes = sum(cur.close < prev.close for prev, cur in zip(sample, sample[1:]))
    return sample[-1].close < sample[0].close and lower_closes >= len(sample) // 2


def has_uptrend(candles: list[Candle], lookback: int = 5) -> bool:
    sample = candles[-lookback:]
    if len(sample) < 3:
        return False
    higher_closes = sum(cur.close > prev.close for prev, cur in zip(sample, sample[1:]))
    return sample[-1].close > sample[0].close and higher_closes >= len(sample) // 2


def candlestick_patterns(candles: list[Candle]) -> tuple[str, ...]:
    if not candles:
        return ()
    last = candles[-1]
    patterns: list[str] = []
    real_body = body(last)
    total = candle_range(last)
    upper = last.high - max(last.open, last.close)
    lower = min(last.open, last.close) - last.low

    if real_body <= total * 0.12:
        patterns.append("十字星")
    if has_downtrend(candles[:-1]) and is_small_body(last) and lower >= real_body * 2 and lower >= total * 0.35 and upper <= total * 0.25:
        patterns.append("錘子線")
    if real_body >= total * 0.75 and is_red(last):
        patterns.append("大紅K")
    if real_body >= total * 0.75 and is_green(last):
        patterns.append("大綠K")

    if len(candles) >= 2:
        prev = candles[-2]
        bullish_context = has_downtrend(candles[:-1])
        bearish_context = has_uptrend(candles[:-1])
        if bullish_context and is_green(prev) and is_red(last) and body(last) > body(prev) and last.open < prev.close and last.close > prev.open:
            patterns.append("陽包陰")
        if bearish_context and is_red(prev) and is_green(last) and body(last) > body(prev) and last.open > prev.close and last.close < prev.open:
            patterns.append("陰包陽")
        midpoint = (prev.open + prev.close) / 2
        if bullish_context and is_green(prev) and is_long_body(prev) and is_red(last) and last.open < prev.low and midpoint < last.close < prev.open:
            patterns.append("曙光初現")
        if bearish_context and is_red(prev) and is_long_body(prev) and is_green(last) and last.open > prev.high and prev.open < last.close < midpoint:
            patterns.append("烏雲罩頂")

    if len(candles) >= 3:
        a, b, c = candles[-3:]
        if has_downtrend(candles[:-2]) and is_green(a) and is_long_body(a) and is_small_body(b) and is_red(c) and c.close > (a.open + a.close) / 2:
            patterns.append("晨星")
        if has_uptrend(candles[:-2]) and is_red(a) and is_long_body(a) and is_small_body(b) and is_green(c) and c.close < (a.open + a.close) / 2:
            patterns.append("黃昏星")
    return tuple(dict.fromkeys(patterns))


def score_stock(candles: list[Candle]) -> ScoredStock:
    if not candles:
        raise ValueError("candles must not be empty")
    candles = sorted(candles, key=lambda c: c.date)
    last = candles[-1]
    closes = [c.close for c in candles]
    volumes = [c.volume for c in candles]
    patterns = candlestick_patterns(candles)
    score = 0
    reasons: list[str] = []

    ma20 = sma(closes, 20)
    if ma20 and last.close >= ma20:
        score += 1
        reasons.append(f"站上MA20({ma20:.2f})")

    hist = macd_histogram(closes)
    if len(hist) >= 2 and hist[-1] > hist[-2]:
        score += 1
        reasons.append("MACD動能轉強")

    current_rsi = rsi(closes)
    if current_rsi is not None:
        if 40 <= current_rsi <= 70:
            score += 1
            reasons.append(f"RSI健康({current_rsi:.1f})")
        elif current_rsi >= 80:
            score -= 1
            reasons.append(f"RSI過熱({current_rsi:.1f})")

    avg_volume = sum(volumes[-6:-1]) / min(len(volumes) - 1, 5) if len(volumes) > 1 else 0
    if avg_volume and last.volume >= avg_volume * 1.5 and is_red(last):
        score += 1
        reasons.append("上漲放量")

    bullish = {"錘子線", "陽包陰", "曙光初現", "晨星", "大紅K"}
    bearish = {"陰包陽", "烏雲罩頂", "黃昏星", "大綠K"}
    good_patterns = [p for p in patterns if p in bullish]
    bad_patterns = [p for p in patterns if p in bearish]
    if good_patterns:
        score += 2
        reasons.append("多方K線:" + "、".join(good_patterns))
    if bad_patterns:
        score -= 2
        reasons.append("空方K線:" + "、".join(bad_patterns))

    return ScoredStock(last, score, tuple(reasons), patterns)


def build_report(date: str, scored: Iterable[ScoredStock], max_rows: int = 20) -> str:
    rows = sorted(scored, key=lambda item: (item.score, item.candle.volume), reverse=True)
    lines = [
        f"台股隔日觀察名單 {date}",
        "資料來源：TWSE / TPEx 公開資料；僅供研究，不是投資建議。",
        "",
    ]
    for idx, item in enumerate(rows[:max_rows], 1):
        c = item.candle
        pct = "--" if c.change_pct is None else f"{c.change_pct:.2f}%"
        reasons = "；".join(item.reasons) if item.reasons else "無明顯加分訊號"
        lines.append(f"{idx:02d}. {c.symbol} {c.name} [{c.market}] 分數 {item.score} 收 {c.close:g} 漲跌幅 {pct} 量 {c.volume:,}")
        lines.append(f"    {reasons}")
    if not rows:
        lines.append("沒有可用資料。")
    return "\n".join(lines)


def build_grouped_report(date: str, scored: Iterable[ScoredStock], max_rows: int = 20) -> str:
    groups = ranked_groups(scored, max_rows)
    sections = [
        ("成交量前段班", groups["volume"]),
        ("漲幅前段班", groups["gainers"]),
        ("跌幅前段班", groups["losers"]),
    ]
    lines = [
        f"台股每日自動觀察名單 {date}",
        f"每張表列前 {max_rows} 筆。資料來源：TWSE / TPEx 公開資料；僅供研究，不是投資建議。",
        "",
    ]
    for title, rows in sections:
        lines.append(title)
        if not rows:
            lines.append("沒有可用資料。")
            lines.append("")
            continue
        for idx, item in enumerate(rows, 1):
            c = item.candle
            pct = "--" if c.change_pct is None else f"{c.change_pct:.2f}%"
            reasons = "；".join(item.reasons) if item.reasons else "無明顯加分訊號"
            lines.append(f"{idx:02d}. {c.symbol} {c.name} [{c.market}] 分數 {item.score} 收 {c.close:g} 漲跌幅 {pct} 量 {c.volume:,}")
            lines.append(f"    {reasons}")
        lines.append("")
    return "\n".join(lines).rstrip()


def build_html_report(date: str, scored: Iterable[ScoredStock], max_rows: int = 50) -> str:
    rows = sorted(scored, key=lambda item: (item.score, item.candle.volume), reverse=True)[:max_rows]
    body_rows = []
    for idx, item in enumerate(rows, 1):
        c = item.candle
        pct = "--" if c.change_pct is None else f"{c.change_pct:.2f}%"
        reasons = "；".join(item.reasons) if item.reasons else "無明顯加分訊號"
        body_rows.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td><strong>{html.escape(c.symbol)}</strong><br>{html.escape(c.name)}</td>"
            f"<td>{html.escape(c.market)}</td>"
            f"<td><strong>{item.score}</strong></td>"
            f"<td>{c.close:g}</td>"
            f"<td>{html.escape(pct)}</td>"
            f"<td>{c.volume:,}</td>"
            f"<td>{html.escape(reasons)}</td>"
            "</tr>"
        )
    if not body_rows:
        body_rows.append('<tr><td colspan="8">沒有可用資料</td></tr>')
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans TC", sans-serif; color: #17211b; }}
    .note {{ color: #65726c; font-size: 13px; }}
    table {{ border-collapse: collapse; width: 100%; max-width: 1100px; }}
    th, td {{ border: 1px solid #d8ded7; padding: 8px 10px; text-align: left; vertical-align: top; font-size: 13px; }}
    th {{ background: #eef2ee; }}
    td:nth-child(1), td:nth-child(4), td:nth-child(5), td:nth-child(6), td:nth-child(7) {{ white-space: nowrap; }}
  </style>
</head>
<body>
  <h2>台股每日自動觀察名單 {html.escape(date)}</h2>
  <p class="note">資料來源：TWSE / TPEx 公開資料；僅供研究，不是投資建議。</p>
  <table>
    <thead>
      <tr>
        <th>排名</th>
        <th>股票</th>
        <th>市場</th>
        <th>分數</th>
        <th>收盤</th>
        <th>漲跌幅</th>
        <th>成交量</th>
        <th>訊號</th>
      </tr>
    </thead>
    <tbody>
      {''.join(body_rows)}
    </tbody>
  </table>
</body>
</html>"""


def scored_records(scored: Iterable[ScoredStock], max_rows: int = 20) -> list[dict[str, object]]:
    rows = sorted(scored, key=lambda item: (item.score, item.candle.volume), reverse=True)
    return scored_records_from_rows(rows[:max_rows])


def scored_records_from_rows(rows: Iterable[ScoredStock]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for item in rows:
        c = item.candle
        records.append(
            {
                "symbol": c.symbol,
                "name": c.name,
                "market": c.market,
                "score": item.score,
                "close": c.close,
                "change_pct": c.change_pct,
                "volume": c.volume,
                "reasons": list(item.reasons),
                "patterns": list(item.patterns),
            }
        )
    return records


def ai_review_record(review: AIReview | dict[str, object] | None) -> dict[str, object] | None:
    if review is None:
        return None
    if isinstance(review, AIReview):
        return {
            "decision": review.decision,
            "risk_level": review.risk_level,
            "summary": review.summary,
            "flags": list(review.flags),
        }
    return {
        "decision": str(review.get("decision", "未覆核")),
        "risk_level": str(review.get("risk_level", "unknown")),
        "summary": str(review.get("summary", "")),
        "flags": list(review.get("flags") or []),
    }


def enrich_records_with_ai_reviews(records: list[dict[str, object]], reviews: dict[str, AIReview | dict[str, object]]) -> list[dict[str, object]]:
    enriched = []
    for record in records:
        row = dict(record)
        review = ai_review_record(reviews.get(str(row.get("symbol", ""))))
        if review:
            row["ai_review"] = review
        enriched.append(row)
    return enriched


def records_for_ai_review(groups: dict[str, list[dict[str, object]]], max_rows: int = 20) -> list[dict[str, object]]:
    by_symbol: dict[str, dict[str, object]] = {}
    for key in ("volume", "gainers", "losers"):
        for record in groups.get(key, [])[:max_rows]:
            by_symbol.setdefault(str(record.get("symbol", "")), record)
    return list(by_symbol.values())


def apply_ai_reviews(payload: dict[str, object], reviews: dict[str, AIReview | dict[str, object]]) -> dict[str, object]:
    if not reviews:
        return payload
    if isinstance(payload.get("records"), list):
        payload["records"] = enrich_records_with_ai_reviews(payload["records"], reviews)  # type: ignore[arg-type]
    groups = payload.get("groups")
    if isinstance(groups, dict):
        payload["groups"] = {
            key: enrich_records_with_ai_reviews(value, reviews) if isinstance(value, list) else value
            for key, value in groups.items()
        }
    payload["ai_review"] = {
        "enabled": True,
        "count": len(reviews),
        "model": os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
    }
    return payload


def review_records_with_openai(records: list[dict[str, object]], model: str | None = None) -> dict[str, AIReview]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not records:
        return {}
    model = model or os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
    request_body = {
        "model": model,
        "store": False,
        "input": [
            {
                "role": "developer",
                "content": (
                    "你是台股技術分析覆核員。只根據輸入的規則分數、價量、漲跌幅與訊號做覆核。"
                    "不要提供買賣指令，不要臆測新聞或基本面。"
                    "decision 只能是：通過、保留觀察、排除。risk_level 只能是：low、medium、high。"
                    "summary 用繁體中文，最多 36 字。flags 最多 3 個。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"records": compact_records_for_ai(records)}, ensure_ascii=False),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "stock_ai_reviews",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "reviews": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "symbol": {"type": "string"},
                                    "decision": {"type": "string", "enum": ["通過", "保留觀察", "排除"]},
                                    "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                                    "summary": {"type": "string"},
                                    "flags": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                                },
                                "required": ["symbol", "decision", "risk_level", "summary", "flags"],
                            },
                        }
                    },
                    "required": ["reviews"],
                },
            }
        },
    }
    data = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60, context=ssl_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"skip AI review: {exc}", file=sys.stderr)
        return {}
    parsed = parse_openai_json_output(payload)
    reviews: dict[str, AIReview] = {}
    for item in parsed.get("reviews", []):
        symbol = str(item.get("symbol", ""))
        if not symbol:
            continue
        reviews[symbol] = AIReview(
            decision=str(item.get("decision", "保留觀察")),
            risk_level=str(item.get("risk_level", "medium")),
            summary=str(item.get("summary", ""))[:80],
            flags=tuple(str(flag)[:24] for flag in item.get("flags", [])[:3]),
        )
    return reviews


def compact_records_for_ai(records: list[dict[str, object]]) -> list[dict[str, object]]:
    compact = []
    for record in records:
        compact.append(
            {
                "symbol": record.get("symbol"),
                "name": record.get("name"),
                "market": record.get("market"),
                "score": record.get("score"),
                "close": record.get("close"),
                "change_pct": record.get("change_pct"),
                "volume": record.get("volume"),
                "reasons": record.get("reasons", []),
                "patterns": record.get("patterns", []),
            }
        )
    return compact


def parse_openai_json_output(payload: dict[str, object]) -> dict[str, object]:
    if isinstance(payload.get("output_text"), str):
        return json.loads(payload["output_text"])  # type: ignore[arg-type]
    for item in payload.get("output", []):  # type: ignore[union-attr]
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                return json.loads(content["text"])
    return {"reviews": []}


def ranked_groups(scored: Iterable[ScoredStock], max_rows: int = 50) -> dict[str, list[ScoredStock]]:
    rows = list(scored)
    with_pct = [row for row in rows if row.candle.change_pct is not None]
    return {
        "volume": sorted(rows, key=lambda item: item.candle.volume, reverse=True)[:max_rows],
        "gainers": sorted(with_pct, key=lambda item: item.candle.change_pct or 0, reverse=True)[:max_rows],
        "losers": sorted(with_pct, key=lambda item: item.candle.change_pct or 0)[:max_rows],
    }


def ranked_group_records(scored: Iterable[ScoredStock], max_rows: int = 50) -> dict[str, list[dict[str, object]]]:
    return {name: scored_records_from_rows(rows) for name, rows in ranked_groups(scored, max_rows).items()}


def build_grouped_html_report(date: str, scored: Iterable[ScoredStock], max_rows: int = 20) -> str:
    groups = ranked_groups(scored, max_rows)
    sections = [
        ("成交量前段班", groups["volume"]),
        ("漲幅前段班", groups["gainers"]),
        ("跌幅前段班", groups["losers"]),
    ]
    tables = "\n".join(f"<h3>{html.escape(title)}</h3>{html_table(rows)}" for title, rows in sections)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans TC", sans-serif; color: #17211b; }}
    .note {{ color: #65726c; font-size: 13px; }}
    h3 {{ margin-top: 24px; }}
    table {{ border-collapse: collapse; width: 100%; max-width: 1100px; margin-bottom: 18px; }}
    th, td {{ border: 1px solid #d8ded7; padding: 8px 10px; text-align: left; vertical-align: top; font-size: 13px; }}
    th {{ background: #eef2ee; }}
    td:nth-child(1), td:nth-child(4), td:nth-child(5), td:nth-child(6), td:nth-child(7) {{ white-space: nowrap; }}
  </style>
</head>
<body>
  <h2>台股每日自動觀察名單 {html.escape(date)}</h2>
  <p class="note">每張表列前 {max_rows} 筆。資料來源：TWSE / TPEx 公開資料；僅供研究，不是投資建議。</p>
  {tables}
</body>
</html>"""


def build_grouped_records_report(date: str, groups: dict[str, list[dict[str, object]]], max_rows: int = 20) -> str:
    sections = [
        ("成交量前段班", groups.get("volume", [])),
        ("漲幅前段班", groups.get("gainers", [])),
        ("跌幅前段班", groups.get("losers", [])),
    ]
    lines = [
        f"台股每日自動觀察名單 {date}",
        f"每張表列前 {max_rows} 筆。資料來源：TWSE / TPEx 公開資料；僅供研究，不是投資建議。",
        "",
    ]
    for title, rows in sections:
        lines.append(title)
        if not rows:
            lines.append("沒有可用資料。")
            lines.append("")
            continue
        for idx, record in enumerate(rows[:max_rows], 1):
            pct = "--" if record.get("change_pct") is None else f"{float(record.get('change_pct')):.2f}%"
            reasons = "；".join(record.get("reasons") or []) or "無明顯加分訊號"
            review = ai_review_record(record.get("ai_review"))
            review_text = ""
            if review:
                review_text = f" AI覆核 {review['decision']} / {review['risk_level']}：{review['summary']}"
            lines.append(
                f"{idx:02d}. {record.get('symbol')} {record.get('name')} [{record.get('market')}] "
                f"分數 {record.get('score')} 收 {float(record.get('close') or 0):g} 漲跌幅 {pct} 量 {int(record.get('volume') or 0):,}{review_text}"
            )
            lines.append(f"    {reasons}")
        lines.append("")
    return "\n".join(lines).rstrip()


def build_grouped_records_html_report(date: str, groups: dict[str, list[dict[str, object]]], max_rows: int = 20) -> str:
    sections = [
        ("成交量前段班", groups.get("volume", [])),
        ("漲幅前段班", groups.get("gainers", [])),
        ("跌幅前段班", groups.get("losers", [])),
    ]
    tables = "\n".join(f"<h3>{html.escape(title)}</h3>{html_records_table(rows[:max_rows])}" for title, rows in sections)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans TC", sans-serif; color: #17211b; }}
    .note {{ color: #65726c; font-size: 13px; }}
    h3 {{ margin-top: 24px; }}
    table {{ border-collapse: collapse; width: 100%; max-width: 1280px; margin-bottom: 18px; }}
    th, td {{ border: 1px solid #d8ded7; padding: 8px 10px; text-align: left; vertical-align: top; font-size: 13px; }}
    th {{ background: #eef2ee; }}
    td:nth-child(1), td:nth-child(4), td:nth-child(5), td:nth-child(6), td:nth-child(7), td:nth-child(8) {{ white-space: nowrap; }}
  </style>
</head>
<body>
  <h2>台股每日自動觀察名單 {html.escape(date)}</h2>
  <p class="note">每張表列前 {max_rows} 筆。AI 覆核只做風險提示與訊號檢查，不是投資建議。</p>
  {tables}
</body>
</html>"""


def html_records_table(rows: list[dict[str, object]]) -> str:
    body_rows = []
    for idx, record in enumerate(rows, 1):
        pct = "--" if record.get("change_pct") is None else f"{float(record.get('change_pct')):.2f}%"
        reasons = "；".join(record.get("reasons") or []) or "無明顯加分訊號"
        review = ai_review_record(record.get("ai_review"))
        review_label = "未覆核"
        review_summary = ""
        if review:
            review_label = f"{review['decision']} / {review['risk_level']}"
            review_summary = str(review["summary"])
        body_rows.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td><strong>{html.escape(str(record.get('symbol', '')))}</strong><br>{html.escape(str(record.get('name', '')))}</td>"
            f"<td>{html.escape(str(record.get('market', '')))}</td>"
            f"<td><strong>{int(record.get('score') or 0)}</strong></td>"
            f"<td>{float(record.get('close') or 0):g}</td>"
            f"<td>{html.escape(pct)}</td>"
            f"<td>{int(record.get('volume') or 0):,}</td>"
            f"<td><strong>{html.escape(review_label)}</strong><br>{html.escape(review_summary)}</td>"
            f"<td>{html.escape(reasons)}</td>"
            "</tr>"
        )
    if not body_rows:
        body_rows.append('<tr><td colspan="9">沒有可用資料</td></tr>')
    return f"""<table>
    <thead>
      <tr>
        <th>排名</th>
        <th>股票</th>
        <th>市場</th>
        <th>分數</th>
        <th>收盤</th>
        <th>漲跌幅</th>
        <th>成交量</th>
        <th>AI覆核</th>
        <th>訊號</th>
      </tr>
    </thead>
    <tbody>
      {''.join(body_rows)}
    </tbody>
  </table>"""


def html_table(rows: Iterable[ScoredStock]) -> str:
    body_rows = []
    for idx, item in enumerate(rows, 1):
        c = item.candle
        pct = "--" if c.change_pct is None else f"{c.change_pct:.2f}%"
        reasons = "；".join(item.reasons) if item.reasons else "無明顯加分訊號"
        body_rows.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td><strong>{html.escape(c.symbol)}</strong><br>{html.escape(c.name)}</td>"
            f"<td>{html.escape(c.market)}</td>"
            f"<td><strong>{item.score}</strong></td>"
            f"<td>{c.close:g}</td>"
            f"<td>{html.escape(pct)}</td>"
            f"<td>{c.volume:,}</td>"
            f"<td>{html.escape(reasons)}</td>"
            "</tr>"
        )
    if not body_rows:
        body_rows.append('<tr><td colspan="8">沒有可用資料</td></tr>')
    return f"""<table>
    <thead>
      <tr>
        <th>排名</th>
        <th>股票</th>
        <th>市場</th>
        <th>分數</th>
        <th>收盤</th>
        <th>漲跌幅</th>
        <th>成交量</th>
        <th>訊號</th>
      </tr>
    </thead>
    <tbody>
      {''.join(body_rows)}
    </tbody>
  </table>"""


def cache_path(market: str, date: dt.date) -> Path:
    return CACHE_DIR / f"{market}_{date:%Y%m%d}.json"


def get_json(url: str, params: dict[str, str], cache_file: Path) -> object:
    CACHE_DIR.mkdir(exist_ok=True)
    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if has_market_data(cached):
            return cached
        cache_file.unlink(missing_ok=True)
    full_url = url + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(full_url, headers={"User-Agent": "demo-stock-screener/1.0"})
    context = ssl_context()
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=30, context=context) as response:
                data = json.loads(response.read().decode("utf-8-sig"))
            break
        except (http.client.IncompleteRead, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt == 1:
                raise
            time.sleep(1.5)
    else:
        raise last_error or RuntimeError("download failed")
    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    time.sleep(0.2)
    return data


def has_market_data(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    tables = data.get("tables")
    if isinstance(tables, list) and any(isinstance(table, dict) and table.get("data") for table in tables):
        return True
    if data.get("data"):
        return True
    if data.get("aaData"):
        return True
    stat = str(data.get("stat", "")).lower()
    return stat == "ok"


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def fetch_twse(date: dt.date) -> list[Candle]:
    data = get_json(TWSE_URL, {"response": "json", "date": f"{date:%Y%m%d}", "type": "ALLBUT0999"}, cache_path("twse", date))
    fields = data.get("fields9") or data.get("fields") or []
    rows = data.get("data9") or data.get("data") or []
    for table in data.get("tables", []):
        table_fields = table.get("fields", [])
        if any("證券代號" in str(field) for field in table_fields):
            fields = table_fields
            rows = table.get("data", [])
            break
    return parse_quote_table(str(date), "TWSE", fields, rows)


def fetch_tpex(date: dt.date) -> list[Candle]:
    roc_year = date.year - 1911
    data = get_json(TPEX_URL, {"date": f"{roc_year}/{date:%m/%d}", "response": "json"}, cache_path("tpex", date))
    fields = data.get("fields") or data.get("tables", [{}])[0].get("fields", [])
    rows = data.get("tables", [{}])[0].get("data") or data.get("data") or []
    return parse_quote_table(str(date), "TPEx", fields, rows)


def parse_quote_table(date: str, market: str, fields: list[str], rows: list[list[object]]) -> list[Candle]:
    def idx(*names: str) -> int | None:
        for name in names:
            for i, field in enumerate(fields):
                if name in str(field):
                    return i
        return None

    symbol_i = idx("證券代號", "代號")
    name_i = idx("證券名稱", "名稱")
    volume_i = idx("成交股數", "成交股數/單位數", "成交股數 ")
    open_i = idx("開盤")
    high_i = idx("最高")
    low_i = idx("最低")
    close_i = idx("收盤")
    sign_i = idx("漲跌(+/-)")
    change_i = idx("漲跌價差", "漲跌")
    required = [symbol_i, name_i, volume_i, open_i, high_i, low_i, close_i]
    if any(i is None for i in required):
        return []

    candles: list[Candle] = []
    for row in rows:
        if not isinstance(row, list) or len(row) <= max(i for i in required if i is not None):
            continue
        symbol = str(row[symbol_i]).strip()
        if not (symbol.isdigit() and len(symbol) == 4):
            continue
        open_ = parse_number(row[open_i])
        high = parse_number(row[high_i])
        low = parse_number(row[low_i])
        close = parse_number(row[close_i])
        volume = parse_number(row[volume_i])
        if None in {open_, high, low, close, volume}:
            continue
        previous_close = None
        change = parse_number(row[change_i]) if change_i is not None and change_i < len(row) else None
        if change is not None and sign_i is not None and sign_i < len(row):
            change = float(change) * parse_twse_sign(row[sign_i])
        if change not in (None, 0):
            previous_close = float(close) - float(change)
        change_pct = ((float(close) - previous_close) / previous_close * 100) if previous_close else None
        candles.append(Candle(date, symbol, str(row[name_i]).strip(), market, float(open_), float(high), float(low), float(close), int(volume), change_pct))
    return candles


def parse_twse_sign(value: object) -> int:
    text = str(value)
    if "-" in text or "green" in text.lower():
        return -1
    return 1


def fetch_market(date: dt.date) -> list[Candle]:
    return fetch_twse(date) + fetch_tpex(date)


def previous_trading_day(today: dt.date) -> tuple[dt.date, list[Candle]]:
    day = today
    for _ in range(10):
        rows = fetch_market(day)
        if rows:
            return day, rows
        day -= dt.timedelta(days=1)
    raise RuntimeError("找不到最近交易日資料")


def market_day(date: dt.date) -> tuple[dt.date, list[Candle]]:
    rows = fetch_market(date)
    if not rows:
        raise RuntimeError(f"{date} 沒有當日官方交易資料")
    return date, rows


def history_for_symbols(symbols: set[str], end: dt.date, days: int = 45) -> dict[str, list[Candle]]:
    history = {symbol: [] for symbol in symbols}
    day = end - dt.timedelta(days=days * 2)
    while day <= end:
        if day.weekday() >= 5:
            day += dt.timedelta(days=1)
            continue
        try:
            rows = fetch_market(day)
        except Exception as exc:
            print(f"skip {day}: {exc}", file=sys.stderr)
            day += dt.timedelta(days=1)
            continue
        for row in rows:
            if row.symbol in history:
                history[row.symbol].append(row)
        day += dt.timedelta(days=1)
    return {symbol: candles[-days:] for symbol, candles in history.items() if candles}


def send_email(subject: str, body_text: str, body_html: str | None = None) -> None:
    host = require_env("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = require_env("SMTP_USER")
    password = require_env("SMTP_PASSWORD")
    sender = os.getenv("EMAIL_FROM", user)
    recipients = [part.strip() for part in require_env("EMAIL_TO").split(",") if part.strip()]

    msg = email.message.EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls(context=context)
            smtp.login(user, password)
            smtp.send_message(msg)


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"missing environment variable: {name}")
    return value


def load_env_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def write_csv(path: Path, scored: list[ScoredStock]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "name", "market", "score", "close", "change_pct", "volume", "reasons", "patterns"])
        for item in sorted(scored, key=lambda s: (s.score, s.candle.volume), reverse=True):
            c = item.candle
            writer.writerow([c.symbol, c.name, c.market, item.score, c.close, c.change_pct, c.volume, "；".join(item.reasons), "；".join(item.patterns)])


def run_analysis(requested: dt.date, top: int = 20, history_days: int = 45, allow_previous: bool = False) -> tuple[dt.date, list[ScoredStock], str]:
    date, rows = previous_trading_day(requested) if allow_previous else market_day(requested)
    candidates = pick_ranked_candidates(rows)
    histories = history_for_symbols({c.symbol for c in candidates}, date, days=history_days)
    scored = [score_stock(histories.get(c.symbol, [c])) for c in candidates]
    report = build_report(str(date), scored, top)
    return date, scored, report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Taiwan stock daily screener")
    parser.add_argument("--date", help="analysis date, default: latest available before/equal today, format YYYY-MM-DD")
    parser.add_argument("--send-email", action="store_true", help="send report by SMTP email")
    parser.add_argument("--top", type=int, default=20, help="report rows")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    args = parse_args(argv or sys.argv[1:])
    requested = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    date, scored, report = run_analysis(requested, args.top)
    out = Path(f"watchlist_{date:%Y%m%d}.txt")
    out.write_text(report, encoding="utf-8")
    write_csv(Path(f"watchlist_{date:%Y%m%d}.csv"), scored)
    print(report)
    if args.send_email:
        send_email(f"台股隔日觀察名單 {date}", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
