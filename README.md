# 台股隔日觀察名單

這是一個台股隔日觀察名單 demo 系統：每天抓證交所 TWSE 和櫃買 TPEx 公開行情，取前一交易日的成交量 Top 100、漲幅 Top 100、跌幅 Top 100，套用 MA / MACD / RSI / 成交量 / K 線型態規則，輸出隔天觀察名單，並可寄 Email。

## 這個系統解決什麼

短線選股最花時間的地方不是看一檔股票，而是每天從上千檔台股裡先縮小範圍。這個系統把人工流程自動化：

- 自動抓官方行情，不用手動複製排行資料。
- 先聚焦有成交量、強勢漲幅、弱勢跌幅的活躍標的。
- 把 K 線圖片裡的判斷流程轉成固定分數，降低憑感覺選股。
- 每天產出可追蹤的 TXT / CSV / 網頁名單，方便隔天開盤前複盤。
- 可接 Email 排程，在台灣時間 15:30 收到隔天觀察名單。

這不是自動下單，也不是保證獲利模型；它解決的是「每天快速整理候選股」和「用一致規則篩掉雜訊」。

## 使用

啟動本機 demo 系統：

```bash
python3 demo_server.py
```

打開：

```text
http://127.0.0.1:8000
```

## GitHub Pages 模式

GitHub Pages 只能提供靜態檔，不能直接執行 Python 爬蟲。這個 repo 另外提供 Pages 版本：

- `.github/workflows/update-watchlist.yml` 每個台股交易日台灣時間 15:30 觸發。
- `generate_static_data.py` 會跑完整分析流程並輸出 `static/latest.json`。
- Pages 網頁讀取 `latest.json` 顯示最新名單。
- 本機開發時，網頁優先呼叫 `/api/run`，可以按日期即時重跑。

先測試產生報告：

```bash
python3 stock_screener.py --date 2026-07-17
```

會產生：

```text
watchlist_YYYYMMDD.txt
watchlist_YYYYMMDD.csv
```

寄 Email 前，建立 `.env`：

```bash
cp .env.example .env
```

再把 `.env` 裡的帳號、app password、收件人改成你的資料。寄送：

```bash
python3 stock_screener.py --send-email
```

Gmail 要使用「應用程式密碼」，不要用登入密碼。

## 每天 15:30 自動執行

macOS 可用 `launchd`。建立 `~/Library/LaunchAgents/com.demo-stock.screener.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.demo-stock.screener</string>
  <key>WorkingDirectory</key>
  <string>/Users/lanyanlin/Desktop/demo_stock</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Library/Frameworks/Python.framework/Versions/3.11/bin/python3</string>
    <string>/Users/lanyanlin/Desktop/demo_stock/stock_screener.py</string>
    <string>--send-email</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>15</integer>
    <key>Minute</key>
    <integer>30</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/lanyanlin/Desktop/demo_stock/screener.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/lanyanlin/Desktop/demo_stock/screener.err</string>
</dict>
</plist>
```

載入：

```bash
launchctl load ~/Library/LaunchAgents/com.demo-stock.screener.plist
```

## 策略規則

候選池先由三個排行榜合併去重：

- 成交量 Top 100
- 漲幅 Top 100
- 跌幅 Top 100

分數規則：

- `+1` 收盤站上 MA20。
- `+1` MACD 柱狀體比前一日轉強。
- `+1` RSI 介於 40-70。
- `+1` 紅 K 且成交量大於近 5 日均量 1.5 倍。
- `+2` 出現多方 K 線：錘子線、陽包陰、曙光初現、晨星、大紅K。
- `-1` RSI 大於等於 80，視為過熱。
- `-2` 出現空方 K 線：陰包陽、烏雲罩頂、黃昏星、大綠K。

排序方式：

- 分數高者優先。
- 同分時成交量高者優先。

這是觀察名單，不是買賣建議。
