#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from stock_screener import load_env_file, run_analysis, scored_records


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"


class DemoHandler(BaseHTTPRequestHandler):
    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        self.serve_file(parsed.path, include_body=False)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"ok": True})
            return
        if parsed.path == "/api/run":
            self.handle_run(parsed.query)
            return
        self.serve_file(parsed.path)

    def handle_run(self, query: str) -> None:
        params = parse_qs(query)
        date_text = params.get("date", [""])[0]
        top_text = params.get("top", ["20"])[0]
        try:
            requested = dt.date.fromisoformat(date_text) if date_text else dt.date.today()
            top = min(max(int(top_text), 1), 50)
            date, scored, report = run_analysis(requested, top)
            payload = {
                "date": str(date),
                "top": top,
                "count": len(scored),
                "records": scored_records(scored, top),
                "report": report,
            }
            self.send_json(payload)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def serve_file(self, path: str, include_body: bool = True) -> None:
        if path in {"", "/"}:
            file_path = STATIC / "index.html"
        elif path.startswith("/images/"):
            file_path = ROOT / Path(path).name
        else:
            file_path = STATIC / path.removeprefix("/")
        try:
            file_path = file_path.resolve()
            allowed_static = file_path.is_relative_to(STATIC.resolve())
            allowed_image = file_path.parent == ROOT.resolve() and file_path.suffix.lower() in {".jpg", ".jpeg", ".png"}
            allowed = allowed_static or allowed_image
            if not allowed or not file_path.exists() or not file_path.is_file():
                self.send_error(404)
                return
            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if include_body:
                self.wfile.write(data)
        except OSError:
            self.send_error(404)

    def send_json(self, payload: dict[str, object], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> int:
    load_env_file()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), DemoHandler)
    print(f"Demo running at http://{host}:{port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
