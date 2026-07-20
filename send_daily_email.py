#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from stock_screener import (
    apply_ai_reviews,
    build_grouped_records_html_report,
    build_grouped_records_report,
    load_env_file,
    records_for_ai_review,
    review_records_with_openai,
    send_email,
)


def append_send_log(path: Path, date: str, top: int, recipient: str, sent_at: str, status: str = "sent") -> None:
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"records": []}
    records = payload.get("records", [])
    records.insert(
        0,
        {
            "date": date,
            "sent_at": sent_at,
            "top": top,
            "recipient": mask_email(recipient),
            "status": status,
        },
    )
    payload["records"] = records[:30]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def mask_email(email: str) -> str:
    if "@" not in email:
        return "***"
    name, domain = email.split("@", 1)
    visible = name[:2] if len(name) > 2 else name[:1]
    return f"{visible}***@{domain}"


def main() -> int:
    load_env_file()
    payload = json.loads(Path("static/latest.json").read_text(encoding="utf-8"))
    date = payload["date"]
    today = dt.datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()
    top = 20
    if str(date) != today:
        append_send_log(Path("static/send-log.json"), str(date), int(top), os.getenv("EMAIL_TO", ""), payload.get("generated_at", ""), status="skipped-stale")
        print(f"skip daily email: latest data is {date}, today is {today}")
        return 0
    groups = payload.get("groups", {})
    if isinstance(groups, dict) and not payload.get("ai_review"):
        payload = apply_ai_reviews(payload, review_records_with_openai(records_for_ai_review(groups, top)))
        groups = payload.get("groups", {})
    if not isinstance(groups, dict):
        raise RuntimeError("missing grouped records in static/latest.json")
    report = build_grouped_records_report(str(date), groups, max_rows=top)
    html_report = build_grouped_records_html_report(str(date), groups, max_rows=top)
    send_email(f"台股每日自動觀察名單 {date}", report, html_report)
    append_send_log(Path("static/send-log.json"), str(date), int(top), os.getenv("EMAIL_TO", ""), payload.get("generated_at", ""))
    print(f"sent daily email for {date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
