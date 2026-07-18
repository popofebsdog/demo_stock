# Taiwan Stock Screener Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a daily Taiwan stock screener that ranks prior-trading-day volume/gainers/losers, applies candlestick and technical rules, and emails the next-day watchlist.

**Architecture:** A single Python stdlib script fetches TWSE/TPEx public data, caches daily quotes, scores candidates, renders a text report, and optionally sends SMTP email. Tests cover parsing, candidate selection, candlestick rules, indicators, and report generation.

**Tech Stack:** Python 3.11 standard library, TWSE public JSON, TPEx public JSON, SMTP.

## Global Constraints

- Market: Taiwan stocks, TWSE + TPEx.
- Notification: Email only.
- Schedule target: Taiwan time 15:30.
- Secrets must come from environment variables, never source files.
- Keep implementation small; no database or web app for the first version.

---

### Task 1: Core Rules

**Files:**
- Create: `stock_screener.py`
- Create: `test_stock_screener.py`

**Interfaces:**
- Produces: `Candle`, `pick_ranked_candidates`, `candlestick_patterns`, `score_stock`, `build_report`

- [x] Write failing unittest cases for number parsing, top-100 selection, candlestick signals, RSI/MACD scoring, and report text.
- [x] Run `python3 -m unittest -v` and verify missing-code failures.
- [x] Implement minimal core functions.
- [x] Run `python3 -m unittest -v` and verify pass.

### Task 2: Data Fetching and Email CLI

**Files:**
- Modify: `stock_screener.py`
- Create: `README.md`
- Create: `.env.example`

**Interfaces:**
- Produces CLI: `python3 stock_screener.py --date YYYY-MM-DD --send-email`

- [x] Add TWSE/TPEx fetchers with JSON parsing and local cache.
- [x] Add SMTP sending using `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO`.
- [x] Add README usage and macOS launchd schedule example for 15:30 Asia/Taipei.
- [x] Run tests and a no-email dry run.
