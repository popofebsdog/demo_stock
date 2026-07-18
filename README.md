# 台股隔日觀察名單

這是一個台股隔日觀察名單自動化系統：每天抓證交所 TWSE 和櫃買 TPEx 公開行情，取前一交易日的成交量 Top 100、漲幅 Top 100、跌幅 Top 100，套用 MA / MACD / RSI / 成交量 / K 線型態規則，輸出隔天觀察名單，並在 15:30 自動寄出 Email。

## 這個系統解決什麼

短線選股最花時間的地方不是看一檔股票，而是每天從上千檔台股裡先縮小範圍。這個系統把人工流程自動化：

- 自動抓官方行情，不用手動複製排行資料。
- 先聚焦有成交量、強勢漲幅、弱勢跌幅的活躍標的。
- 把 K 線圖片裡的判斷流程轉成固定分數，降低憑感覺選股。
- 每天產出可追蹤的 TXT / CSV / 網頁名單，方便隔天開盤前複盤。
- 可接 Email 排程，在台灣時間 15:30 收到隔天觀察名單。

這不是自動下單，也不是保證獲利模型；它解決的是「每天快速整理候選股」和「用一致規則篩掉雜訊」。

## 系統 Pipeline

這個系統分成兩條 pipeline：

- 每日自動寄信 pipeline：每個台股交易日台灣時間 15:20 先更新最新交易日資料，15:30 自動寄出前 50 筆觀察名單。這條線不需要人工挑日期、不需要按按鈕。
- 日常查詢 pipeline：網站提供日期和筆數查詢，給你臨時回看某一天的分析結果，或在動態主機上即時重跑指定日期。

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

- `.github/workflows/update-watchlist.yml` 每個台股交易日台灣時間 15:20 觸發，更新最新交易日資料。
- `.github/workflows/send-daily-email.yml` 每個台股交易日台灣時間 15:30 讀取最新資料並自動寄出前 50 筆觀察名單。
- `generate_static_data.py` 會跑完整分析流程並輸出 `static/data/YYYY-MM-DD.json`、`static/latest.json`、`static/dates.json`。
- Pages 網頁可挑已產生的日期，讀取對應 JSON 顯示名單。
- 本機開發時，網頁優先呼叫 `/api/run`，可以按日期即時重跑。

注意：private repo 是否能啟用 GitHub Pages 取決於 GitHub 帳號/組織方案。如果 GitHub 回覆 `Your current plan does not support GitHub Pages for this repository`，代表 repo 可以維持 private，但 Pages 無法啟用；可改成 public repo、升級方案，或改部署到 Vercel / Netlify。

## 動態部署

如果要在正式網址上「挑任意日期即時重跑」，需要能執行 Python 的動態主機，例如 Render、Railway、Fly.io 或 Heroku。這個 repo 已經包含：

- `render.yaml`：Render Blueprint 設定。
- `Procfile`：Railway / Heroku 類平台可用的啟動命令。
- `requirements.txt`：Python 依賴。
- `demo_server.py`：會讀平台提供的 `PORT`，並提供 `/api/run` 和 `/api/health`。

Render 部署流程：

1. 到 Render 建立 Web Service。
2. 連接 GitHub repo `popofebsdog/demo_stock`。
3. Render 會讀 `render.yaml`。
4. 部署完成後打開 Render URL，就可以在網頁上挑日期即時跑分析。

## 每日 15:30 自動寄信

正式的零人力寄信由 GitHub Actions 負責：

- 15:20：`.github/workflows/update-watchlist.yml` 更新 `static/latest.json`。
- 15:30：`.github/workflows/send-daily-email.yml` 讀取 `static/latest.json` 並寄出 Email。

寄信 workflow 執行：

```bash
python send_daily_email.py
```

這個腳本不重新爬資料，只寄出 15:20 產生好的前 50 筆觀察名單，讓寄信步驟更穩定。

需要在 GitHub repo 的 `Settings > Secrets and variables > Actions` 新增：

```text
SMTP_HOST
SMTP_PORT
SMTP_USER
SMTP_PASSWORD
EMAIL_FROM
EMAIL_TO
```

寄信成功後，workflow 會更新 `static/send-log.json`，前端會顯示最近寄送紀錄。

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
