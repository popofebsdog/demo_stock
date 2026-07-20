const form = document.querySelector("#run-form");
const dateInput = document.querySelector("#date");
const button = document.querySelector("#run-button");
const statusEl = document.querySelector("#status");
const bodyEl = document.querySelector("#result-body");
const metricDate = document.querySelector("#metric-date");
const metricCount = document.querySelector("#metric-count");
const metricScore = document.querySelector("#metric-score");
const sendLogBody = document.querySelector("#send-log-body");
const tabButtons = [...document.querySelectorAll(".tab-button")];
const sortButtons = [...document.querySelectorAll(".sort-button")];
const sortState = document.querySelector("#sort-state");

let activeRows = [];
let activeGroups = null;
let activeGroup = "volume";
let sortKey = "volume";
let sortDirection = "desc";

const groupConfig = {
  volume: { label: "成交量前 50", sortKey: "volume", sortDirection: "desc" },
  gainers: { label: "漲幅前 50", sortKey: "change_pct", sortDirection: "desc" },
  losers: { label: "跌幅前 50", sortKey: "change_pct", sortDirection: "asc" },
};

const sortLabels = {
  symbol: "股票",
  market: "市場",
  score: "分數",
  close: "收盤",
  change_pct: "漲跌幅",
  volume: "成交量",
};

dateInput.valueAsDate = new Date();
loadDateChoices();
loadSendLog();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  button.disabled = true;
  statusEl.textContent = "分析中";
  bodyEl.innerHTML = `<tr class="empty-row"><td colspan="8">正在抓官方行情與計算 K 線訊號...</td></tr>`;

  try {
    const params = new URLSearchParams(new FormData(form));
    const payload = await loadAnalysis(params);
    render(payload);
  } catch (error) {
    statusEl.textContent = "失敗";
    bodyEl.innerHTML = `<tr class="empty-row"><td colspan="8">${escapeHtml(error.message)}</td></tr>`;
  } finally {
    button.disabled = false;
  }
});

tabButtons.forEach((tab) => {
  tab.addEventListener("click", () => {
    if (!activeGroups) return;
    activeGroup = tab.dataset.group;
    const config = groupConfig[activeGroup];
    sortKey = config.sortKey;
    sortDirection = config.sortDirection;
    renderActiveGroup();
  });
});

sortButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const nextKey = button.dataset.sort;
    if (sortKey === nextKey) {
      sortDirection = sortDirection === "desc" ? "asc" : "desc";
    } else {
      sortKey = nextKey;
      sortDirection = defaultDirection(nextKey);
    }
    renderCurrentRows();
  });
});

async function loadAnalysis(params) {
  const requestedDate = params.get("date");
  const apiResponse = await fetch(`api/run?${params.toString()}`);
  if (apiResponse.ok) return apiResponse.json();
  const staticPath = requestedDate ? `data/${requestedDate}.json` : "latest.json";
  let staticResponse = await fetch(staticPath);
  if (!staticResponse.ok) staticResponse = await fetch("latest.json");
  if (staticResponse.ok) {
    const payload = await staticResponse.json();
    payload.staticMode = true;
    if (requestedDate && payload.date !== requestedDate) {
      payload.requestedMissing = requestedDate;
    }
    return payload;
  }
  const errorPayload = await apiResponse.json().catch(() => ({}));
  throw new Error(errorPayload.error || "找不到本機 API，也沒有 GitHub Pages 最新資料");
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
  statusEl.textContent = payload.requestedMissing ? `Pages 無 ${payload.requestedMissing}` : payload.staticMode ? "Pages 靜態資料" : "完成";
  metricDate.textContent = payload.date;
  metricCount.textContent = payload.count.toLocaleString("zh-TW");
  const records = payload.records || [];
  metricScore.textContent = records[0]?.score ?? "--";
  if (payload.groups) {
    activeGroups = payload.groups;
    activeGroup = "volume";
    sortKey = groupConfig.volume.sortKey;
    sortDirection = groupConfig.volume.sortDirection;
    renderActiveGroup();
    return;
  }
  activeGroups = null;
  activeRows = records;
  sortKey = "score";
  sortDirection = "desc";
  updateTabs();
  renderCurrentRows();
}

function renderActiveGroup() {
  activeRows = activeGroups?.[activeGroup] || [];
  updateTabs();
  renderCurrentRows();
}

function renderCurrentRows() {
  const sortedRows = sortRows(activeRows, sortKey, sortDirection);
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

function defaultDirection(key) {
  return ["symbol", "market"].includes(key) ? "asc" : "desc";
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
  const directionLabel = sortDirection === "desc" ? "高到低" : "低到高";
  const groupLabel = activeGroups ? groupConfig[activeGroup].label : "觀察名單";
  sortState.textContent = `${groupLabel} · ${sortLabels[sortKey] || sortKey}：${directionLabel}`;
}

function updateSortButtons() {
  sortButtons.forEach((button) => {
    const selected = button.dataset.sort === sortKey;
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-sort", selected ? (sortDirection === "desc" ? "descending" : "ascending") : "none");
    const baseLabel = sortLabels[button.dataset.sort] || button.textContent.replace(/[▲▼]/g, "").trim();
    const marker = selected ? (sortDirection === "desc" ? "▼" : "▲") : "";
    button.textContent = marker ? `${baseLabel} ${marker}` : baseLabel;
  });
}

function renderRows(rows) {
  return rows.map((row, index) => {
    const change = row.change_pct === null || row.change_pct === undefined ? "--" : `${row.change_pct.toFixed(2)}%`;
    const changeClass = row.change_pct > 0 ? "positive" : row.change_pct < 0 ? "negative" : "";
    const signals = row.reasons.length ? row.reasons.join("；") : "無明顯加分訊號";
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
        <td class="signals">${escapeHtml(signals)}</td>
      </tr>
    `;
  }).join("") || `<tr class="empty-row"><td colspan="8">沒有可用資料。</td></tr>`;
}

async function loadDateChoices() {
  const response = await fetch("dates.json").catch(() => null);
  if (!response?.ok) return;
  const payload = await response.json();
  const dates = payload.dates || [];
  if (!dates.length) return;
  dateInput.value = dates[0];
  dateInput.min = dates[dates.length - 1];
  dateInput.max = dates[0];
  const list = document.createElement("datalist");
  list.id = "available-dates";
  dates.forEach((date) => {
    const option = document.createElement("option");
    option.value = date;
    list.appendChild(option);
  });
  document.body.appendChild(list);
  dateInput.setAttribute("list", "available-dates");
}

function formatNumber(value) {
  return Number(value).toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
