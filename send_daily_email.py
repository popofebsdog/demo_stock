#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

from stock_screener import load_env_file, send_email


def append_send_log(path: Path, date: str, top: int, recipient: str, sent_at: str) -> None:
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"records": []}
    records = payload.get("records", [])
    records.insert(
        0,
        {
            "date": date,
            "sent_at": sent_at,
            "top": top,
            "recipient": mask_email(recipient),
            "status": "sent",
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
    top = payload.get("top", 50)
    report = payload["report"]
    send_email(f"台股每日自動觀察名單 {date}", report)
    append_send_log(Path("static/send-log.json"), str(date), int(top), os.getenv("EMAIL_TO", ""), payload.get("generated_at", ""))
    print(f"sent daily email for {date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
