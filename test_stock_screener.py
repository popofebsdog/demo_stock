import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from send_daily_email import append_send_log, mask_email
from stock_screener import (
    Candle,
    build_report,
    candlestick_patterns,
    parse_number,
    pick_ranked_candidates,
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

    def test_candlestick_patterns_detects_bullish_engulfing_and_hammer(self):
        candles = [
            Candle("2026-07-16", "2330", "台積電", "TWSE", 100, 101, 94, 96, 1000, -4),
            Candle("2026-07-17", "2330", "台積電", "TWSE", 95, 106, 70, 105, 3000, 9.38),
        ]

        patterns = candlestick_patterns(candles)

        self.assertIn("陽包陰", patterns)
        self.assertIn("錘子線", patterns)

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

    def test_scored_records_are_json_ready(self):
        item = score_stock([Candle("2026-07-17", "2330", "台積電", "TWSE", 100, 110, 99, 108, 5000, 8)])

        records = scored_records([item])

        self.assertEqual(records[0]["symbol"], "2330")
        self.assertIsInstance(records[0]["reasons"], list)

    def test_append_send_log_masks_recipient(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "send-log.json"
            append_send_log(path, "2026-07-17", 50, "dearbibi@hotmail.com", "2026-07-18T15:30:00+08:00")

            text = path.read_text(encoding="utf-8")
            self.assertIn("de***@hotmail.com", text)
            self.assertNotIn("dearbibi@hotmail.com", text)
            self.assertEqual(mask_email("a@example.com"), "a***@example.com")


if __name__ == "__main__":
    unittest.main()
