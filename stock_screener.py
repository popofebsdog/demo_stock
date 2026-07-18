#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import email.message
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
    if lower >= max(real_body * 2, total * 0.35) and upper <= total * 0.25:
        patterns.append("錘子線")
    if real_body >= total * 0.75 and is_red(last):
        patterns.append("大紅K")
    if real_body >= total * 0.75 and is_green(last):
        patterns.append("大綠K")

    if len(candles) >= 2:
        prev = candles[-2]
        if is_green(prev) and is_red(last) and last.open < prev.close and last.close > prev.open:
            patterns.append("陽包陰")
        if is_red(prev) and is_green(last) and last.open > prev.close and last.close < prev.open:
            patterns.append("陰包陽")
        midpoint = (prev.open + prev.close) / 2
        if is_green(prev) and is_red(last) and last.open < prev.low and last.close > midpoint:
            patterns.append("曙光初現")
        if is_red(prev) and is_green(last) and last.open > prev.high and last.close < midpoint:
            patterns.append("烏雲罩頂")

    if len(candles) >= 3:
        a, b, c = candles[-3:]
        if is_green(a) and body(b) <= candle_range(b) * 0.35 and is_red(c) and c.close > (a.open + a.close) / 2:
            patterns.append("晨星")
        if is_red(a) and body(b) <= candle_range(b) * 0.35 and is_green(c) and c.close < (a.open + a.close) / 2:
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
        lines.append(f"{idx:02d}. {c.symbol} {c.name} [{c.market}] 分數 {item.score} 收 {c.close:g} 漲跌 {pct} 量 {c.volume:,}")
        lines.append(f"    {reasons}")
    if not rows:
        lines.append("沒有可用資料。")
    return "\n".join(lines)


def scored_records(scored: Iterable[ScoredStock], max_rows: int = 20) -> list[dict[str, object]]:
    rows = sorted(scored, key=lambda item: (item.score, item.candle.volume), reverse=True)
    records: list[dict[str, object]] = []
    for item in rows[:max_rows]:
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


def cache_path(market: str, date: dt.date) -> Path:
    return CACHE_DIR / f"{market}_{date:%Y%m%d}.json"


def get_json(url: str, params: dict[str, str], cache_file: Path) -> object:
    CACHE_DIR.mkdir(exist_ok=True)
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
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
        if change not in (None, 0):
            previous_close = float(close) - float(change)
        change_pct = ((float(close) - previous_close) / previous_close * 100) if previous_close else None
        candles.append(Candle(date, symbol, str(row[name_i]).strip(), market, float(open_), float(high), float(low), float(close), int(volume), change_pct))
    return candles


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


def send_email(subject: str, body_text: str) -> None:
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


def run_analysis(requested: dt.date, top: int = 20) -> tuple[dt.date, list[ScoredStock], str]:
    date, rows = previous_trading_day(requested)
    candidates = pick_ranked_candidates(rows)
    histories = history_for_symbols({c.symbol for c in candidates}, date)
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
