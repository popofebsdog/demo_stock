const form = document.querySelector("#run-form");
const dateInput = document.querySelector("#date");
const button = document.querySelector("#run-button");
const buttonLabel = document.querySelector("#run-button-label");
const statusEl = document.querySelector("#status");
const bodyEl = document.querySelector("#result-body");
const metricDate = document.querySelector("#metric-date");
const metricCount = document.querySelector("#metric-count");
const metricScore = document.querySelector("#metric-score");
const sendLogBody = document.querySelector("#send-log-body");
const modeHint = document.querySelector("#mode-hint");
const tabButtons = [...document.querySelectorAll(".tab-button")];
const sortButtons = [...document.querySelectorAll(".sort-button")];
const sortState = document.querySelector("#sort-state");

let activeRows = [];
let activeGroups = null;
let activeGroup = "volume";
let localCrawlerMode = false;
let scoreSortDirection = null;

const groupConfig = {
  volume: { label: "成交量前 50" },
  gainers: { label: "漲幅前 50" },
  losers: { label: "跌幅前 50" },
};

dateInput.valueAsDate = new Date();
initApp();
loadSendLog();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  button.disabled = true;
  statusEl.textContent = "分析中";
  bodyEl.innerHTML = `<tr class="empty-row"><td colspan="9">正在抓官方行情與計算 K 線訊號...</td></tr>`;

  try {
    const payload = localCrawlerMode ? await runLocalCrawler(new URLSearchParams(new FormData(form))) : await loadLatestStatic();
    render(payload);
  } catch (error) {
    statusEl.textContent = "失敗";
    clearResults();
    bodyEl.innerHTML = `<tr class="empty-row"><td colspan="9">${escapeHtml(error.message)}</td></tr>`;
  } finally {
    button.disabled = false;
  }
});

tabButtons.forEach((tab) => {
  tab.addEventListener("click", () => {
    if (!activeGroups) return;
    activeGroup = tab.dataset.group;
    scoreSortDirection = null;
    renderActiveGroup();
  });
});

sortButtons.forEach((button) => {
  button.addEventListener("click", () => {
    scoreSortDirection = scoreSortDirection === "desc" ? "asc" : "desc";
    renderCurrentRows();
  });
});

async function initApp() {
  localCrawlerMode = await hasLocalApi();
  if (localCrawlerMode) {
    setLocalCrawlerMode();
    return;
  }
  setStaticMode();
  try {
    render(await loadLatestStatic());
  } catch (error) {
    statusEl.textContent = "無資料";
    clearResults();
    bodyEl.innerHTML = `<tr class="empty-row"><td colspan="9">${escapeHtml(error.message)}</td></tr>`;
  }
}

async function hasLocalApi() {
  const response = await fetch("api/health", { cache: "no-store" }).catch(() => null);
  if (!response?.ok) return false;
  const payload = await response.json().catch(() => ({}));
  return payload.ok === true;
}

function setLocalCrawlerMode() {
  statusEl.textContent = "本機爬蟲模式";
  modeHint.textContent = "本機端可自由選日期，會即時連 TWSE / TPEx 抓資料。";
  button.disabled = false;
  buttonLabel.textContent = "跑本機爬蟲";
  dateInput.disabled = false;
  dateInput.removeAttribute("list");
  dateInput.removeAttribute("min");
  dateInput.max = new Date().toISOString().slice(0, 10);
}

function setStaticMode() {
  statusEl.textContent = "GitHub Pages 靜態模式";
  modeHint.textContent = "線上端不做即時爬蟲，只顯示排程產出的最新結果與寄送紀錄。";
  button.disabled = false;
  buttonLabel.textContent = "載入最新結果";
  dateInput.disabled = true;
  dateInput.removeAttribute("list");
  dateInput.removeAttribute("min");
  dateInput.removeAttribute("max");
}

async function runLocalCrawler(params) {
  const response = await fetch(`api/run?${params.toString()}`, { cache: "no-store" });
  if (response.ok) return response.json();
  const errorPayload = await response.json().catch(() => ({}));
  throw new Error(errorPayload.error || "本機爬蟲失敗，請確認日期是否有交易資料。");
}

async function loadLatestStatic() {
  const response = await fetch("latest.json", { cache: "no-store" });
  if (!response.ok) throw new Error("找不到最新靜態資料。");
  const payload = await response.json();
  payload.staticMode = true;
  const today = taipeiToday();
  if (payload.date !== today) {
    throw new Error(`最新靜態資料是 ${payload.date}，不是今天 ${today}，所以不顯示舊資料。`);
  }
  return payload;
}

async function loadSendLog() {
  const response = await fetch("send-log.json").catch(() => null);
  if (!response?.ok) {
    sendLogBody.textContent = "尚無寄送紀錄";
    return;
  }
  const payload = await response.json();
  const records = payload.records || [];
  if (!records.length) {
    sendLogBody.textContent = "尚無寄送紀錄";
    return;
  }
  sendLogBody.innerHTML = records.slice(0, 5).map((record) => `
    <div class="send-log-item">
      <strong>${escapeHtml(record.date)}</strong>
      <span>${escapeHtml(record.status)} · 前 ${record.top} 筆 · ${escapeHtml(record.recipient)}</span>
      <time>${escapeHtml(record.sent_at)}</time>
    </div>
  `).join("");
}

function render(payload) {
  statusEl.textContent = payload.staticMode ? "GitHub Pages 靜態模式" : "本機爬蟲完成";
  metricDate.textContent = payload.date;
  if (payload.date) dateInput.value = payload.date;
  metricCount.textContent = payload.count.toLocaleString("zh-TW");
  const records = payload.records || [];
  metricScore.textContent = records[0]?.score ?? "--";
  if (payload.groups) {
    activeGroups = payload.groups;
    activeGroup = "volume";
    scoreSortDirection = null;
    renderActiveGroup();
    return;
  }
  activeGroups = null;
  activeRows = records;
  scoreSortDirection = null;
  updateTabs();
  renderCurrentRows();
}

function clearResults() {
  activeGroups = null;
  activeRows = [];
  scoreSortDirection = null;
  metricDate.textContent = "--";
  metricCount.textContent = "--";
  metricScore.textContent = "--";
  updateTabs();
  renderCurrentRows();
}

function renderActiveGroup() {
  activeRows = activeGroups?.[activeGroup] || [];
  updateTabs();
  renderCurrentRows();
}

function renderCurrentRows() {
  const sortedRows = scoreSortDirection ? sortRows(activeRows, "score", scoreSortDirection) : activeRows;
  bodyEl.innerHTML = renderRows(sortedRows);
  updateSortState();
  updateSortButtons();
}

function sortRows(rows, key, direction) {
  const multiplier = direction === "desc" ? -1 : 1;
  return [...rows].sort((a, b) => compareValues(a[key], b[key]) * multiplier);
}

function compareValues(a, b) {
  const emptyA = a === null || a === undefined || a === "";
  const emptyB = b === null || b === undefined || b === "";
  if (emptyA && emptyB) return 0;
  if (emptyA) return 1;
  if (emptyB) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), "zh-Hant-u-co-zhuyin", { numeric: true });
}

function updateTabs() {
  tabButtons.forEach((tab) => {
    const selected = Boolean(activeGroups) && tab.dataset.group === activeGroup;
    tab.classList.toggle("is-active", selected);
    tab.setAttribute("aria-selected", selected ? "true" : "false");
    tab.disabled = !activeGroups;
  });
}

function updateSortState() {
  const groupLabel = activeGroups ? groupConfig[activeGroup].label : "觀察名單";
  if (!scoreSortDirection) {
    sortState.textContent = `${groupLabel} · 原排行榜順序`;
    return;
  }
  const directionLabel = scoreSortDirection === "desc" ? "高到低" : "低到高";
  sortState.textContent = `${groupLabel} · 分數：${directionLabel}`;
}

function updateSortButtons() {
  sortButtons.forEach((button) => {
    const selected = Boolean(scoreSortDirection);
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-sort", selected ? (scoreSortDirection === "desc" ? "descending" : "ascending") : "none");
    const baseLabel = "分數";
    const marker = selected ? (scoreSortDirection === "desc" ? "▼" : "▲") : "";
    button.textContent = marker ? `${baseLabel} ${marker}` : baseLabel;
  });
}

function renderRows(rows) {
  return rows.map((row, index) => {
    const change = row.change_pct === null || row.change_pct === undefined ? "--" : `${row.change_pct.toFixed(2)}%`;
    const changeClass = row.change_pct > 0 ? "positive" : row.change_pct < 0 ? "negative" : "";
    const signals = row.reasons.length ? row.reasons.join("；") : "無明顯加分訊號";
    const aiReview = row.ai_review;
    const aiLabel = aiReview ? `${aiReview.decision} / ${aiReview.risk_level}` : "未覆核";
    const aiSummary = aiReview?.summary || "";
    return `
      <tr>
        <td class="rank">${String(index + 1).padStart(2, "0")}</td>
        <td>
          <span class="stock-name">${escapeHtml(row.name)}</span>
          <span class="stock-code">${escapeHtml(row.symbol)}</span>
        </td>
        <td>${escapeHtml(row.market)}</td>
        <td><span class="score">${row.score}</span></td>
        <td>${formatNumber(row.close)}</td>
        <td class="${changeClass}">${change}</td>
        <td>${formatNumber(row.volume)}</td>
        <td class="ai-review">
          <span class="ai-decision">${escapeHtml(aiLabel)}</span>
          <span>${escapeHtml(aiSummary)}</span>
        </td>
        <td class="signals">${escapeHtml(signals)}</td>
      </tr>
    `;
  }).join("") || `<tr class="empty-row"><td colspan="9">沒有可用資料。</td></tr>`;
}

function formatNumber(value) {
  return Number(value).toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}

function taipeiToday() {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const get = (type) => parts.find((part) => part.type === type)?.value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
