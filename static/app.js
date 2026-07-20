const form = document.querySelector("#run-form");
const dateInput = document.querySelector("#date");
const button = document.querySelector("#run-button");
const statusEl = document.querySelector("#status");
const bodyEl = document.querySelector("#result-body");
const metricDate = document.querySelector("#metric-date");
const metricCount = document.querySelector("#metric-count");
const metricScore = document.querySelector("#metric-score");
const sendLogBody = document.querySelector("#send-log-body");

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
    renderGroups(payload.groups);
    return;
  }
  bodyEl.innerHTML = renderRows(records);
}

function renderGroups(groups) {
  const labels = [
    ["volume", "成交量前 50"],
    ["gainers", "漲幅前 50"],
    ["losers", "跌幅前 50"],
  ];
  bodyEl.innerHTML = labels.map(([key, label]) => `
    <tr class="group-title"><td colspan="8">${label}</td></tr>
    ${renderRows(groups[key] || [])}
  `).join("");
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
