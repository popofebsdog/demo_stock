const form = document.querySelector("#run-form");
const dateInput = document.querySelector("#date");
const button = document.querySelector("#run-button");
const statusEl = document.querySelector("#status");
const bodyEl = document.querySelector("#result-body");
const metricDate = document.querySelector("#metric-date");
const metricCount = document.querySelector("#metric-count");
const metricScore = document.querySelector("#metric-score");

dateInput.valueAsDate = new Date();

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
  const apiResponse = await fetch(`api/run?${params.toString()}`);
  if (apiResponse.ok) return apiResponse.json();
  const staticResponse = await fetch("latest.json");
  if (staticResponse.ok) {
    const payload = await staticResponse.json();
    payload.staticMode = true;
    return payload;
  }
  const errorPayload = await apiResponse.json().catch(() => ({}));
  throw new Error(errorPayload.error || "找不到本機 API，也沒有 GitHub Pages 最新資料");
}

function render(payload) {
  statusEl.textContent = payload.staticMode ? "Pages 最新資料" : "完成";
  metricDate.textContent = payload.date;
  metricCount.textContent = payload.count.toLocaleString("zh-TW");
  metricScore.textContent = payload.records[0]?.score ?? "--";
  bodyEl.innerHTML = payload.records.map((row, index) => {
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
  }).join("");
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
