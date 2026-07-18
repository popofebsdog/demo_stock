#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from stock_screener import run_analysis, scored_records


def main() -> int:
    today = dt.datetime.now(ZoneInfo("Asia/Taipei")).date()
    date, scored, report = run_analysis(today, top=50)
    payload = {
        "date": str(date),
        "top": 50,
        "count": len(scored),
        "records": scored_records(scored, 50),
        "report": report,
        "generated_at": dt.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds"),
    }
    path = Path("static/latest.json")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {path} for {date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
