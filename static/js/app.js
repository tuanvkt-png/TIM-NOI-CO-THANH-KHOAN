"use strict";

const state = { chart: null, series: null, priceLines: [], extraSeries: [] };

const $ = (id) => document.getElementById(id);
const symbolSelect = $("symbolSelect");
const intervalSelect = $("intervalSelect");
const cycleSelect = $("cycleSelect");
const btnScan = $("btnScan");
const btnScanAll = $("btnScanAll");
const statusBar = $("statusBar");
const setupsList = $("setupsList");
const chartInfo = $("chartInfo");
const chartContainer = $("chartContainer");

function setStatus(msg, kind) {
  statusBar.textContent = msg;
  statusBar.className = "status-bar" + (kind ? " " + kind : "");
}

function fmt(n) {
  if (n === null || n === undefined) return "–";
  const num = Number(n);
  if (!isFinite(num)) return "–";
  return num.toLocaleString("en-US", { maximumFractionDigits: 5 });
}

/* ------------------------------------------------------------ chart setup */
function initChart() {
  if (typeof LightweightCharts === "undefined") {
    chartContainer.innerHTML =
      '<div class="chart-error">Không tải được thư viện biểu đồ. Hãy tải lại trang (Ctrl+F5).</div>';
    return false;
  }
  state.chart = LightweightCharts.createChart(chartContainer, {
    layout: {
      background: { type: "solid", color: "#ffffff" },
      textColor: "#1f2937",
      fontSize: 12,
    },
    grid: { vertLines: { color: "#eef1f5" }, horzLines: { color: "#eef1f5" } },
    rightPriceScale: { borderColor: "#e5e7eb", scaleMargins: { top: 0.1, bottom: 0.1 } },
    timeScale: { borderColor: "#e5e7eb", timeVisible: true, secondsVisible: false },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    width: chartContainer.clientWidth,
    height: chartContainer.clientHeight || 520,
  });

  state.series = state.chart.addCandlestickSeries({
    upColor: "#16a34a",
    downColor: "#dc2626",
    wickUpColor: "#16a34a",
    wickDownColor: "#dc2626",
    borderVisible: false,
  });

  const ro = new ResizeObserver(() => {
    if (!state.chart) return;
    state.chart.applyOptions({
      width: chartContainer.clientWidth,
      height: chartContainer.clientHeight || 520,
    });
  });
  ro.observe(chartContainer);
  return true;
}

function clearOverlays() {
  state.priceLines.forEach((l) => {
    try { state.series.removePriceLine(l); } catch (e) {}
  });
  state.priceLines = [];
  state.extraSeries.forEach((s) => {
    try { state.chart.removeSeries(s); } catch (e) {}
  });
  state.extraSeries = [];
}

/* Vẽ trendline dạng đường chéo thật (kéo dài về tương lai) */
function addTrendline(line, color, title) {
  if (!line || !line.x1_ts) return;
  try {
    const s = state.chart.addLineSeries({
      color,
      lineWidth: 2,
      lineStyle: LightweightCharts.LineStyle.Solid,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      title,
    });
    s.setData([
      { time: line.x1_ts, value: Number(line.y1) },
      { time: line.x2_ts, value: Number(line.y_end) },
    ]);
    state.extraSeries.push(s);
  } catch (e) {
    console.warn("Không vẽ được trendline", e);
  }
}

function addLine(price, color, style, title, width) {
  try {
    const line = state.series.createPriceLine({
      price: Number(price),
      color,
      lineWidth: width || 1,
      lineStyle: style,
      axisLabelVisible: true,
      title,
    });
    state.priceLines.push(line);
  } catch (e) {
    console.warn("Không vẽ được đường giá", price, e);
  }
}

/* yfinance/pandas có thể trả time dạng ISO -> phải đổi sang Unix giây */
function toChartData(candles) {
  const out = [];
  let last = 0;
  (candles || []).forEach((c) => {
    let sec = null;
    if (typeof c.time === "number") {
      sec = c.time > 1e11 ? Math.floor(c.time / 1000) : Math.floor(c.time);
    } else {
      const parsed = Date.parse(String(c.time).replace(" ", "T"));
      if (!isNaN(parsed)) sec = Math.floor(parsed / 1000);
    }
    if (!sec || sec <= last) return;
    last = sec;
    out.push({
      time: sec,
      open: Number(c.open),
      high: Number(c.high),
      low: Number(c.low),
      close: Number(c.close),
    });
  });
  return out;
}

function drawChart(data) {
  if (!state.chart) return;
  const bars = toChartData(data.candles);
  if (!bars.length) {
    chartInfo.textContent = "Không có dữ liệu nến để vẽ.";
    return;
  }
  state.series.setData(bars);
  clearOverlays();

  const dashed = LightweightCharts.LineStyle.Dashed;
  const solid = LightweightCharts.LineStyle.Solid;

  (data.supports || []).forEach((p) => addLine(p, "#16a34a", dashed, "Hỗ trợ"));
  (data.resistances || []).forEach((p) => addLine(p, "#dc2626", dashed, "Kháng"));

  if (data.support_trendline) {
    addTrendline(data.support_trendline, "#2563eb", `Trendline hỗ trợ (${data.support_touches} lần chạm)`);
  }
  if (data.resistance_trendline) {
    addTrendline(data.resistance_trendline, "#f97316", `Trendline kháng (${data.resistance_touches} lần chạm)`);
  }

  (data.setups || []).forEach((s) => {
    addLine(s.entry, "#2563eb", solid, `Entry ${s.type}`, 2);
    addLine(s.sl, "#dc2626", dashed, `SL ${s.type}`);
    addLine(s.tp, "#16a34a", dashed, `TP ${s.type}`);
  });

  state.chart.timeScale().fitContent();
  chartInfo.innerHTML =
    `<strong>${data.symbol}</strong> · ${data.interval} · Giá hiện tại: <strong>${fmt(data.current_price)}</strong>` +
    ` · ATR14: ${fmt(data.atr)} · ${bars.length} nến`;
}

/* ---------------------------------------------------------------- setups */
function renderSetups(data) {
  setupsList.innerHTML = "";
  const setups = data.setups || [];

  if (!setups.length) {
    setupsList.innerHTML =
      '<div class="empty">Không có setup đạt điều kiện cho mã này ở khung thời gian đã chọn.</div>';
    return;
  }

  setups.forEach((s) => {
    const side = s.type === "BUY" ? "buy" : "sell";
    const confCls = s.confidence === "Cao" ? "cao" : s.confidence === "Trung bình" ? "tb" : "thap";
    const card = document.createElement("div");
    card.className = `setup-card ${side}`;
    card.innerHTML = `
      <div class="setup-head">
        <span class="setup-type ${side}">${s.type === "BUY" ? "▲ MUA (BUY)" : "▼ BÁN (SELL)"}</span>
        <span class="setup-conf ${confCls}">${s.confidence}</span>
      </div>
      <div class="setup-source">${s.source || ""}</div>
      <table class="setup-table">
        <tr><td>Entry</td><td class="mono">${fmt(s.entry)}</td></tr>
        <tr><td>Stop Loss</td><td class="mono red">${fmt(s.sl)}</td></tr>
        <tr><td>Take Profit</td><td class="mono green">${fmt(s.tp)}</td></tr>
        <tr><td>R:R</td><td class="mono"><strong>1 : ${s.rr}</strong></td></tr>
      </table>
      <ul class="reasons">${(s.reasons || []).map((r) => `<li>${r}</li>`).join("")}</ul>
    `;
    setupsList.appendChild(card);
  });

  if (data.patterns && data.patterns.length) {
    const p = document.createElement("div");
    p.className = "pattern-box";
    p.innerHTML =
      "<strong>Mẫu hình phát hiện:</strong><br>" +
      data.patterns.map((x) => `• ${x.type} @ ${fmt(x.price)} (${x.bias})`).join("<br>");
    setupsList.appendChild(p);
  }
}

/* ------------------------------------------------------------------ fetch */
async function scanOne(symbol, interval) {
  setStatus(`Đang phân tích ${symbol} (${interval})…`, "loading");
  btnScan.disabled = true;
  try {
    const url = `/api/scan?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}`;
    const res = await fetch(url);
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const err = await res.json();
        if (err && err.detail) detail = typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail);
      } catch (e) {}
      throw new Error(detail);
    }
    const data = await res.json();
    drawChart(data);
    renderSetups(data);
    setStatus(`Đã phân tích ${symbol} · ${interval} · ${data.setups.length} setup`, "ok");
  } catch (err) {
    setStatus(`Lỗi: ${err.message}`, "error");
    setupsList.innerHTML = `<div class="empty">Không lấy được dữ liệu cho ${symbol}.<br>${err.message}</div>`;
    console.error(err);
  } finally {
    btnScan.disabled = false;
  }
}

async function scanAll() {
  setStatus("Đang quét tất cả mã (có thể mất 30–60 giây)…", "loading");
  btnScanAll.disabled = true;
  try {
    const res = await fetch(`/api/scan-all?interval=${encodeURIComponent(intervalSelect.value)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const results = await res.json();

    const entries = Object.entries(results);
    setupsList.innerHTML = `<div class="scan-all-title">Kết quả quét ${entries.length} mã · ${intervalSelect.value}</div>`;
    entries.forEach(([sym, d]) => {
      const row = document.createElement("div");
      row.className = "scan-row";
      if (d.error) {
        row.innerHTML = `<strong>${sym}</strong> — <span class="red">${d.error}</span>`;
      } else {
        const first = (d.setups || [])[0];
        row.innerHTML = `<strong>${sym}</strong> · ${fmt(d.current_price)}
          ${first ? `<span class="badge ${first.type === "BUY" ? "buy" : "sell"}">${first.type} R:R 1:${first.rr}</span>` : '<span class="badge none">Không có setup</span>'}`;
        row.style.cursor = "pointer";
        row.title = "Bấm để xem chi tiết";
        row.addEventListener("click", () => {
          symbolSelect.value = sym;
          scanOne(sym, intervalSelect.value);
        });
      }
      setupsList.appendChild(row);
    });
    setStatus(`Đã quét xong ${entries.length} mã`, "ok");
  } catch (err) {
    setStatus(`Lỗi quét tất cả: ${err.message}`, "error");
  } finally {
    btnScanAll.disabled = false;
  }
}

async function saveSettings() {
  try {
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        favorite_symbols: [symbolSelect.value],
        interval: intervalSelect.value,
        scan_cycle: cycleSelect.value,
        auto_scan: cycleSelect.value !== "manual",
      }),
    });
  } catch (e) {
    console.warn("Không lưu được cài đặt", e);
  }
}

/* ------------------------------------------------------------------- boot */
document.addEventListener("DOMContentLoaded", async () => {
  initChart();

  btnScan.addEventListener("click", () => {
    saveSettings();
    scanOne(symbolSelect.value, intervalSelect.value);
  });
  btnScanAll.addEventListener("click", scanAll);
  symbolSelect.addEventListener("change", () => scanOne(symbolSelect.value, intervalSelect.value));
  intervalSelect.addEventListener("change", () => scanOne(symbolSelect.value, intervalSelect.value));

  try {
    const r = await fetch("/api/settings");
    if (r.ok) {
      const s = await r.json();
      if (s.interval) intervalSelect.value = s.interval;
      if (s.scan_cycle) cycleSelect.value = s.scan_cycle;
      if (s.favorite_symbols && s.favorite_symbols[0]) symbolSelect.value = s.favorite_symbols[0];
    }
  } catch (e) {}

  scanOne(symbolSelect.value, intervalSelect.value);
});