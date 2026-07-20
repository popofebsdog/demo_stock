#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import argparse
from pathlib import Path
from zoneinfo import ZoneInfo

from stock_screener import apply_ai_reviews, ranked_group_records, records_for_ai_review, review_records_with_openai, run_analysis, scored_records


def build_payload(requested: dt.date) -> dict[str, object]:
    date, scored, report = run_analysis(requested, top=50)
    groups = ranked_group_records(scored, 50)
    payload = {
        "date": str(date),
        "top": 50,
        "count": len(scored),
        "records": scored_records(scored, 50),
        "groups": groups,
        "report": report,
        "generated_at": dt.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds"),
    }
    reviews = review_records_with_openai(records_for_ai_review(groups, 20))
    return apply_ai_reviews(payload, reviews)


def write_payload(payload: dict[str, object]) -> Path:
    date = str(payload["date"])
    data_dir = Path("static/data")
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{date}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    Path("static/latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_dates() -> None:
    dates = sorted((p.stem for p in Path("static/data").glob("*.json")), reverse=True)
    payload = {
        "dates": dates,
        "latest": dates[0] if dates else None,
        "generated_at": dt.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds"),
    }
    Path("static/dates.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate static GitHub Pages data")
    parser.add_argument("--date", help="latest requested date, default: today in Asia/Taipei")
    parser.add_argument("--backfill", type=int, default=1, help="calendar days to walk backward")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    today = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(ZoneInfo("Asia/Taipei")).date()
    seen: set[str] = set()
    for offset in range(max(args.backfill, 1)):
        requested = today - dt.timedelta(days=offset)
        payload = build_payload(requested)
        date = str(payload["date"])
        if date in seen:
            continue
        seen.add(date)
        path = write_payload(payload)
        print(f"wrote {path} for {date}")
    write_dates()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
