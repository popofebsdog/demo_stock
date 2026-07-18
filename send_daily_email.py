#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from stock_screener import load_env_file, run_analysis, send_email


def main() -> int:
    load_env_file()
    today = dt.datetime.now(ZoneInfo("Asia/Taipei")).date()
    date, _scored, report = run_analysis(today, top=50)
    send_email(f"台股每日自動觀察名單 {date}", report)
    print(f"sent daily email for {date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
