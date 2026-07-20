import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from send_daily_email import append_send_log, mask_email
from stock_screener import (
    Candle,
    build_grouped_report,
    build_html_report,
    build_report,
    candlestick_patterns,
    parse_number,
    parse_quote_table,
    pick_ranked_candidates,
    ranked_group_records,
    run_analysis,
    scored_records,
    score_stock,
)


class StockScreenerTest(unittest.TestCase):
    def test_parse_number_handles_market_strings(self):
        self.assertEqual(parse_number("1,234,567"), 1234567)
        self.assertEqual(parse_number("+3.21%"), 3.21)
        self.assertIsNone(parse_number("--"))

    def test_pick_ranked_candidates_deduplicates_three_top_lists(self):
        rows = [
            Candle("2026-07-17", "1001", "A", "TWSE", 10, 11, 9, 11, 300, 10),
            Candle("2026-07-17", "1002", "B", "TWSE", 10, 10, 8, 8, 500, -20),
            Candle("2026-07-17", "1003", "C", "TPEx", 10, 10.5, 9, 10.5, 400, 5),
        ]

        picked = pick_ranked_candidates(rows, limit=1)

        self.assertEqual([row.symbol for row in picked], ["1002", "1001"])

    def test_parse_quote_table_applies_twse_minus_sign_to_change_pct(self):
        fields = ["證券代號", "證券名稱", "成交股數", "開盤價", "最高價", "最低價", "收盤價", "漲跌(+/-)", "漲跌價差"]
        rows = [["2330", "台積電", "1,000", "100.00", "101.00", "98.00", "99.00", "<p style= color:green>-</p>", "1.00"]]

        parsed = parse_quote_table("2026-07-17", "TWSE", fields, rows)

        self.assertAlmostEqual(parsed[0].change_pct, -1.0)

    def test_candlestick_patterns_detects_bullish_engulfing_and_hammer(self):
        candles = [
            Candle("2026-07-13", "2330", "台積電", "TWSE", 106, 107, 104, 105, 1000, -1),
            Candle("2026-07-14", "2330", "台積電", "TWSE", 105, 106, 101, 102, 1000, -3),
            Candle("2026-07-15", "2330", "台積電", "TWSE", 102, 103, 99, 100, 1000, -2),
            Candle("2026-07-16", "2330", "台積電", "TWSE", 101, 102, 97, 98, 1000, -2),
            Candle("2026-07-17", "2330", "台積電", "TWSE", 97, 103, 96, 102, 3000, 4.08),
        ]

        patterns = candlestick_patterns(candles)

        self.assertIn("陽包陰", patterns)

    def test_candlestick_patterns_require_reversal_context(self):
        candles = [
            Candle("2026-07-15", "2330", "台積電", "TWSE", 100, 103, 99, 102, 1000, 2),
            Candle("2026-07-16", "2330", "台積電", "TWSE", 101, 102, 97, 98, 1000, -3),
            Candle("2026-07-17", "2330", "台積電", "TWSE", 97, 103, 96, 102, 3000, 4.08),
        ]

        patterns = candlestick_patterns(candles)

        self.assertNotIn("陽包陰", patterns)

    def test_candlestick_patterns_detects_hammer_after_downtrend(self):
        candles = [
            Candle("2026-07-13", "2330", "台積電", "TWSE", 108, 109, 105, 106, 1000, -1),
            Candle("2026-07-14", "2330", "台積電", "TWSE", 106, 107, 102, 103, 1000, -3),
            Candle("2026-07-15", "2330", "台積電", "TWSE", 103, 104, 99, 100, 1000, -3),
            Candle("2026-07-16", "2330", "台積電", "TWSE", 100, 101, 96, 97, 1000, -3),
            Candle("2026-07-17", "2330", "台積電", "TWSE", 95, 97, 90, 96, 3000, -1),
        ]

        patterns = candlestick_patterns(candles)

        self.assertIn("錘子線", patterns)

    def test_candlestick_patterns_detects_stars_with_long_first_body(self):
        morning = [
            Candle("2026-07-13", "2330", "台積電", "TWSE", 112, 113, 109, 110, 1000, -1),
            Candle("2026-07-14", "2330", "台積電", "TWSE", 110, 111, 105, 106, 1000, -4),
            Candle("2026-07-15", "2330", "台積電", "TWSE", 106, 107, 99, 100, 1000, -6),
            Candle("2026-07-16", "2330", "台積電", "TWSE", 99, 100, 98, 99.5, 1000, -0.5),
            Candle("2026-07-17", "2330", "台積電", "TWSE", 100, 105, 99, 104, 3000, 4.5),
        ]
        evening = [
            Candle("2026-07-13", "2330", "台積電", "TWSE", 98, 101, 97, 100, 1000, 2),
            Candle("2026-07-14", "2330", "台積電", "TWSE", 100, 105, 99, 104, 1000, 4),
            Candle("2026-07-15", "2330", "台積電", "TWSE", 104, 111, 103, 110, 1000, 6),
            Candle("2026-07-16", "2330", "台積電", "TWSE", 110, 112, 109, 110.5, 1000, 0.5),
            Candle("2026-07-17", "2330", "台積電", "TWSE", 110, 111, 104, 106, 3000, -4.1),
        ]

        self.assertIn("晨星", candlestick_patterns(morning))
        self.assertIn("黃昏星", candlestick_patterns(evening))

    def test_score_stock_rewards_bullish_volume_and_trend(self):
        candles = [
            Candle(f"2026-06-{day:02d}", "2330", "台積電", "TWSE", 100 + (day % 5), 102 + (day % 5), 99 + (day % 5), 101 + (day % 5), 1000 + day, 1)
            for day in range(1, 26)
        ]
        candles[-1] = Candle("2026-06-25", "2330", "台積電", "TWSE", 101, 112, 100, 111, 5000, 9.9)

        scored = score_stock(candles)

        self.assertGreaterEqual(scored.score, 3)
        self.assertTrue(any("MA20" in reason for reason in scored.reasons))
        self.assertTrue(any("放量" in reason for reason in scored.reasons))

    def test_build_report_contains_ranked_watchlist(self):
        candles = [
            Candle("2026-07-17", "2330", "台積電", "TWSE", 100, 110, 99, 108, 5000, 8),
            Candle("2026-07-17", "2317", "鴻海", "TWSE", 50, 52, 49, 51, 3000, 2),
        ]

        report = build_report("2026-07-17", [score_stock([c]) for c in candles])

        self.assertIn("台股隔日觀察名單", report)
        self.assertIn("2330 台積電", report)

    def test_build_html_report_contains_table(self):
        item = score_stock([Candle("2026-07-17", "2330", "台積電", "TWSE", 100, 110, 99, 108, 5000, 8)])

        html = build_html_report("2026-07-17", [item])

        self.assertIn("<table", html)
        self.assertIn("2330", html)
        self.assertIn("台積電", html)
        self.assertIn("分數", html)

    def test_build_grouped_report_contains_three_rankings(self):
        scored = [
            score_stock([Candle("2026-07-17", "1001", "A", "TWSE", 10, 11, 9, 11, 300, 10)]),
            score_stock([Candle("2026-07-17", "1002", "B", "TWSE", 10, 10, 8, 8, 500, -20)]),
        ]

        report = build_grouped_report("2026-07-17", scored, max_rows=1)

        self.assertIn("成交量前段班", report)
        self.assertIn("漲幅前段班", report)
        self.assertIn("跌幅前段班", report)
        self.assertEqual(report.count("01."), 3)

    def test_ranked_group_records_splits_volume_gainers_and_losers(self):
        scored = [
            score_stock([Candle("2026-07-17", "1001", "A", "TWSE", 10, 11, 9, 11, 300, 10)]),
            score_stock([Candle("2026-07-17", "1002", "B", "TWSE", 10, 10, 8, 8, 500, -20)]),
            score_stock([Candle("2026-07-17", "1003", "C", "TPEx", 10, 10.5, 9, 10.5, 400, 5)]),
        ]

        groups = ranked_group_records(scored, 2)

        self.assertEqual([r["symbol"] for r in groups["volume"]], ["1002", "1003"])
        self.assertEqual([r["symbol"] for r in groups["gainers"]], ["1001", "1003"])
        self.assertEqual([r["symbol"] for r in groups["losers"]], ["1002", "1003"])

    def test_run_analysis_requires_requested_date_data(self):
        with patch("stock_screener.fetch_market", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "沒有當日官方交易資料"):
                run_analysis(__import__("datetime").date(2026, 7, 20))

    def test_scored_records_are_json_ready(self):
        item = score_stock([Candle("2026-07-17", "2330", "台積電", "TWSE", 100, 110, 99, 108, 5000, 8)])

        records = scored_records([item])

        self.assertEqual(records[0]["symbol"], "2330")
        self.assertIsInstance(records[0]["reasons"], list)

    def test_append_send_log_masks_recipient(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "send-log.json"
            append_send_log(path, "2026-07-17", 50, "dear.user@example.com", "2026-07-18T15:30:00+08:00", status="skipped-stale")

            text = path.read_text(encoding="utf-8")
            self.assertIn("de***@example.com", text)
            self.assertIn("skipped-stale", text)
            self.assertNotIn("dear.user@example.com", text)
            self.assertEqual(mask_email("a@example.com"), "a***@example.com")


if __name__ == "__main__":
    unittest.main()
