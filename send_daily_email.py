#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

from stock_screener import build_grouped_html_report, build_grouped_report, load_env_file, send_email


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
    top = 20
    scored = records_to_scored_like(flatten_group_records(payload))
    report = build_grouped_report(str(date), scored, max_rows=top)
    html_report = build_grouped_html_report(str(date), scored, max_rows=top)
    send_email(f"台股每日自動觀察名單 {date}", report, html_report)
    append_send_log(Path("static/send-log.json"), str(date), int(top), os.getenv("EMAIL_TO", ""), payload.get("generated_at", ""))
    print(f"sent daily email for {date}")
    return 0


def flatten_group_records(payload: dict[str, object]) -> list[dict[str, object]]:
    groups = payload.get("groups")
    if not isinstance(groups, dict):
        return list(payload.get("records", []))
    by_symbol: dict[str, dict[str, object]] = {}
    for group in groups.values():
        if not isinstance(group, list):
            continue
        for record in group:
            if isinstance(record, dict):
                by_symbol[str(record.get("symbol", ""))] = record
    return list(by_symbol.values())


def records_to_scored_like(records: list[dict[str, object]]) -> list[object]:
    from types import SimpleNamespace

    scored = []
    for record in records:
        candle = SimpleNamespace(
            symbol=str(record.get("symbol", "")),
            name=str(record.get("name", "")),
            market=str(record.get("market", "")),
            close=float(record.get("close") or 0),
            change_pct=record.get("change_pct"),
            volume=int(record.get("volume") or 0),
        )
        scored.append(
            SimpleNamespace(
                candle=candle,
                score=int(record.get("score") or 0),
                reasons=tuple(record.get("reasons") or []),
            )
        )
    return scored


if __name__ == "__main__":
    raise SystemExit(main())
