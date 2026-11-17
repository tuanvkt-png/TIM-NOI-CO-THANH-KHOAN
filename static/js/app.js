"use strict";

/* ============================================================ state */
const state = {
  chart: null,
  series: null,
  priceLines: [],
  extraSeries: [],
  symbolInfo: {},
  watchlist: [],
  currentSymbol: null,
  scanSeq: 0,
};

const $ = (id) => document.getElementById(id);
const symbolSelect = $("symbolSelect");
const intervalSelect = $("intervalSelect");
const cycleSelect = $("cycleSelect");
const btnScan = $("btnScan");
const btnScanAll = $("btnScanAll");
const btnPretty = $("btnPretty");
const statusBar = $("statusBar");
const setupsList = $("setupsList");
const prettyList = $("prettyList");
const watchList = $("watchList");
const chartInfo = $("chartInfo");
const chartContainer = $("chartContainer");
const assetBadge = $("assetBadge");

function setStatus(msg, kind) {
  statusBar.textContent = msg;
  statusBar.className = "status-bar" + (kind ? " " + kind : "");
}

function fmt(n, digits) {
  if (n === null || n === undefined || n === "") return "–";
  const num = Number(n);
  if (!isFinite(num)) return "–";
  let d = digits;
  if (d === undefined) {
    const a = Math.abs(num);
    d = a >= 1000 ? 2 : a >= 10 ? 3 : a >= 1 ? 4 : 5;
  }
  return num.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

/* ======================================================= chart engine */
function initChart() {
  if (typeof LightweightCharts === "undefined") {
    chartContainer.innerHTML =
      '<div class="chart-error">Không tải được thư viện biểu đồ. Hãy tải lại trang (Ctrl+F5).</div>';
    return false;
  }
  state.chart = LightweightCharts.createChart(chartContainer, {
    layout: { background: { type: "solid", color: "#ffffff" }, textColor: "#1f2937", fontSize: 12 },
    grid: { vertLines: { color: "#eef1f5" }, horzLines: { color: "#eef1f5" } },
    rightPriceScale: { borderColor: "#e5e7eb", scaleMargins: { top: 0.12, bottom: 0.12 } },
    timeScale: { borderColor: "#e5e7eb", timeVisible: true, secondsVisible: false },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    width: chartContainer.clientWidth,
    height: chartContainer.clientHeight || 520,
  });

  state.series = state.chart.addCandlestickSeries({
    upColor: "#16a34a", downColor: "#dc2626",
    wickUpColor: "#16a34a", wickDownColor: "#dc2626", borderVisible: false,
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

/* QUAN TRỌNG: xoá hết overlay CŨ trước khi nạp dữ liệu mới,
   nếu không thang giá sẽ bị kẹt ở vùng giá của mã trước đó. */
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

function addLine(price, color, style, title, width) {
  try {
    state.priceLines.push(state.series.createPriceLine({
      price: Number(price), color, lineWidth: width || 1,
      lineStyle: style, axisLabelVisible: true, title,
    }));
  } catch (e) { console.warn("priceLine lỗi", price, e); }
}

function addTrendline(line, color, title) {
  if (!line || !line.x1_ts) return;
  try {
    const s = state.chart.addLineSeries({
      color, lineWidth: 2, lineStyle: LightweightCharts.LineStyle.Solid,
      priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false, title,
    });
    s.setData([
      { time: line.x1_ts, value: Number(line.y1) },
      { time: line.x2_ts, value: Number(line.y_end) },
    ]);
    state.extraSeries.push(s);
  } catch (e) { console.warn("trendline lỗi", e); }
}

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
    out.push({ time: sec, open: Number(c.open), high: Number(c.high),
               low: Number(c.low), close: Number(c.close) });
  });
  return out;
}

function drawChart(data) {
  if (!state.chart) return;
  const bars = toChartData(data.candles);

  // 1) Xoá overlay cũ TRƯỚC
  clearOverlays();

  // 2) Ép thang giá tự động co giãn lại từ đầu (chống kẹt vùng giá cũ)
  try {
    const ps = state.series.priceScale();
    if (ps && ps.applyOptions) ps.applyOptions({ autoScale: true });
  } catch (e) {}
  try {
    state.chart.priceScale("right").applyOptions({ autoScale: true });
  } catch (e) {}

  if (!bars.length) {
    chartInfo.textContent = "Không có dữ liệu nến để vẽ.";
    return;
  }

  // 3) Nạp dữ liệu mới
  state.series.setData(bars);

  const dashed = LightweightCharts.LineStyle.Dashed;
  const solid = LightweightCharts.LineStyle.Solid;

  (data.supports || []).forEach((p) => addLine(p, "#16a34a", dashed, "Hỗ trợ"));
  (data.resistances || []).forEach((p) => addLine(p, "#dc2626", dashed, "Kháng"));
  if (data.support_trendline)
    addTrendline(data.support_trendline, "#2563eb", `Trendline hỗ trợ (${data.support_touches} lần chạm)`);
  if (data.resistance_trendline)
    addTrendline(data.resistance_trendline, "#f97316", `Trendline kháng (${data.resistance_touches} lần chạm)`);

  (data.setups || []).forEach((s) => {
    addLine(s.entry, "#2563eb", solid, `Entry ${s.type}`, 2);
    addLine(s.sl, "#dc2626", dashed, `SL ${s.type}`);
    addLine(s.tp, "#16a34a", dashed, `TP ${s.type}`);
  });

  // 4) Căn lại khung nhìn + scale
  state.chart.timeScale().fitContent();
  try { state.chart.priceScale("right").applyOptions({ autoScale: true }); } catch (e) {}

  chartInfo.innerHTML =
    `<strong>${data.name}</strong> · ${data.sub} · ${data.interval} · Giá: <strong>${fmt(data.current_price)} ${data.unit || ""}</strong>` +
    ` · RSI ${data.rsi} · ATR ${fmt(data.atr)} · ${bars.length} nến`;
}

/* ========================================================= asset badge */
function renderBadge(data) {
  assetBadge.innerHTML = `
    <span class="badge-cat cat-${(data.cat || "").replace(/\s+/g, "-")}">${data.cat || "—"}</span>
    <span class="badge-name">${data.name || data.symbol}</span>
    <span class="badge-sub">${data.sub || ""}</span>
    <span class="badge-ticker">Yahoo: ${data.ticker || data.symbol}</span>
    <span class="badge-unit">Đơn vị: ${data.unit || "—"}</span>
  `;
}

/* =========================================================== checklist */
function checklistHTML(s) {
  const rows = (s.checklist || []).map((c, i) => `
    <li class="ck-item ${c.ok ? "ok" : "no"}">
      <span class="ck-icon">${c.ok ? "✔" : "✘"}</span>
      <span class="ck-body">
        <span class="ck-text">${i + 1}. ${c.text}</span>
        <span class="ck-value">${c.value}</span>
      </span>
    </li>`).join("");
  return `<ul class="ck-list">${rows}</ul>`;
}

function setupCardHTML(s) {
  const side = s.type === "BUY" ? "buy" : "sell";
  const gradeCls = s.grade.startsWith("A+") ? "gp" : s.grade.startsWith("A") ? "g" :
                   s.grade.startsWith("B") ? "b" : s.grade.startsWith("C") ? "c" : "d";
  return `
    <div class="setup-card ${side}">
      <div class="setup-head">
        <span class="setup-type ${side}">${s.type === "BUY" ? "▲ MUA (BUY)" : "▼ BÁN (SELL)"}</span>
        <span class="grade ${gradeCls}" title="Điểm chất lượng">${s.grade}</span>
      </div>
      <div class="setup-meta">
        <span class="setup-source">${s.source}</span>
        <span class="ck-score">${s.passed}/${s.total} điều kiện · Điểm ${s.score}/100</span>
      </div>
      ${s.pattern ? `<div class="pattern-tag">📐 ${s.pattern}</div>` : ""}
      <table class="setup-table">
        <tr><td>Entry</td><td class="mono">${fmt(s.entry)}</td></tr>
        <tr><td>Stop Loss</td><td class="mono red">${fmt(s.sl)}</td></tr>
        <tr><td>Take Profit</td><td class="mono green">${fmt(s.tp)}</td></tr>
        <tr><td>R:R</td><td class="mono"><strong>1 : ${s.rr}</strong> ${s.rr_ok ? '<span class="rr-ok">✔ ≥1:2</span>' : '<span class="rr-bad">✘ &lt;1:2</span>'}</td></tr>
      </table>
      <div class="ck-title">✅ <span class="step-num">4</span> Hội tụ 4 điều kiện <span class="step-note-inline">(B1 đa khung · B2 phá/retest · B3 trendline · B4 mẫu hình)</span></div>
      ${checklistHTML(s)}
      <ul class="reasons">${(s.reasons || []).map((r) => `<li>${r}</li>`).join("")}</ul>
    </div>`;
}


/* ============ BƯỚC 1 — XU HƯỚNG ĐA KHUNG ============ */
function mtfHTML(data) {
  const m = data.mtf;
  if (!m || !m.available) return "";
  const chip = (t) => t === "TANG" ? "up" : t === "GIAM" ? "down" : "flat";
  const label = (t) => t === "TANG" ? "TĂNG" : t === "GIAM" ? "GIẢM" : "NGANG";
  const rows = (m.frames || []).map((f) => `
    <div class="mtf-row">
      <span class="mtf-tf">${(f.tf||"").toUpperCase()}</span>
      <span class="mtf-trend ${chip(f.trend)}">${label(f.trend)}</span>
      <span class="mtf-bar"><i style="width:${f.strength}%"></i></span>
      <span class="mtf-strength">${f.strength}/100</span>
    </div>`).join("");
  const ck = data.mtf_check || {};
  const cls = ck.status === "THUAN" ? "ok" : ck.status === "NGUOC" ? "bad" : "warn";
  return `
    <div class="step-block">
      <div class="step-head"><span class="step-num">1</span> Xu hướng đa khung (1D → 4H → 1H)</div>
      <div class="mtf-grid">${rows}</div>
      <div class="step-note ${cls}">${m.note || ""}</div>
      ${ck.note ? `<div class="step-note ${cls}"><b>${ck.status}</b> — ${ck.note}</div>` : ""}
    </div>`;
}

/* ============ BƯỚC 5 — ORDER FLOW ============ */
function orderflowHTML(data) {
  const lst = data.setups || [];
  const of = lst[0] && lst[0].orderflow;
  if (!of) return "";
  const v = of.volume || {};
  const kj = of.kijun || {};
  const ch = of.choch || {};
  let volLine = "";
  if (v.available) {
    const cls = v.is_climax ? "bad" : v.is_spike ? "warn" : v.is_dry ? "warn" : "ok";
    volLine = `<div class="of-line ${cls}"><b>Volume</b> ${v.ratio}× trung bình
        ${v.is_climax ? "· 🔥 CỰC ĐẠI" : v.is_spike ? "· ⚡ ĐỘT BIẾN" : v.is_dry ? "· 💤 CẠN" : ""}</div>`;
    (v.signals || []).forEach((x) => {
      volLine += `<div class="of-line sig"><b>${x.label}</b><br><small>${x.detail}</small></div>`;
    });
  } else {
    volLine = `<div class="of-line warn"><b>Volume</b> — ${v.reason || "không có dữ liệu"}</div>`;
  }
  const kjLine = kj.available ? `<div class="of-line ${kj.aligns ? "ok" : "bad"}"><b>Kijun</b> ${kj.detail}</div>` : "";
  const chLine = `<div class="of-line ${ch.bias ? "ok" : "warn"}"><b>CHoCH</b> ${ch.detail || "—"}</div>`;
  return `
    <div class="step-block">
      <div class="step-head"><span class="step-num">5</span> Thanh khoản &amp; Order Flow</div>
      ${volLine}${kjLine}${chLine}
      <div class="step-note ${of.confirmed ? "ok" : "warn"}">
        ${of.verdict} <span class="of-bonus">(điểm ${of.score_bonus > 0 ? "+" : ""}${of.score_bonus})</span>
      </div>
    </div>`;
}

/* ============ BƯỚC 6 — VỊ TRÍ MM ============ */
function mmPosHTML(data) {
  const lst = data.setups || [];
  const pos = lst[0] && lst[0].mm_position;
  if (!pos) return "";
  const cls = pos.confidence === "CAO" ? "ok" : pos.confidence === "TRUNG_BINH" ? "warn" : "bad";
  const notes = (pos.notes || []).map((n) => `<li>${n}</li>`).join("");
  return `
    <div class="step-block">
      <div class="step-head"><span class="step-num">6</span> Vị trí của Market Maker</div>
      <div class="mm-verdict ${cls}">${pos.verdict}</div>
      <div class="mm-sides">
        <span class="side-chip crowd">👥 Đám đông: <b>${pos.crowd_side || "?"}</b></span>
        <span class="side-chip mm">🏦 MM: <b>${pos.mm_side || "chưa rõ"}</b></span>
        <span class="side-chip conf">Tin cậy: <b>${pos.confidence}</b></span>
      </div>
      ${notes ? `<ul class="mm-notes">${notes}</ul>` : ""}
    </div>`;
}

/* ============ TRẠNG THÁI CHU KỲ ============ */
function cycleBannerHTML(data) {
  const L = data.lock || {};
  if (L.locked) {
    const cls = L.side === "BUY" ? "buy" : "sell";
    const blocked = L.blocked_signals || 0;
    return `
      <div class="cycle-banner locked ${cls}">
        <div class="cycle-head">
          <span class="lock-icon">🔒</span>
          <strong>HƯỚNG ĐANG KHOÁ: ${L.side === "BUY" ? "MUA (BUY)" : "BÁN (SELL)"}</strong>
          <span class="cycle-state">${L.state_label || ""}</span>
        </div>
        <div class="cycle-body">
          <span>Mở lúc <b>${L.opened_at ? String(L.opened_at).replace("T"," ").slice(0,16) : "—"}</b>
            · đã qua <b>${L.bars_alive || 0}</b> nến</span>
          <span>Entry <b>${fmt(L.entry)}</b> · SL <b class="red">${fmt(L.sl)}</b>
            · TP1 <b class="green">${fmt(L.tp1)}</b></span>
          ${blocked > 0 ? `<span class="blocked">⛔ Đã bỏ qua <b>${blocked}</b> tín hiệu ngược chiều</span>` : ""}
        </div>
        <div class="cycle-note">Web KHÔNG lật hướng cho tới khi thủng SL, chạm TP1, hoặc hết hạn.</div>
      </div>`;
  }
  if (L.just_closed) {
    const map = {
      DA_CHAM_TP: ["✅", "Chu kỳ trước đã CHẠM MỤC TIÊU", "green"],
      THUNG_SL:   ["❌", "Chu kỳ trước đã THỦNG SL", "red"],
      HET_HAN:    ["⌛", "Chu kỳ trước HẾT HẠN", "gray"],
    };
    const m = map[L.just_closed] || ["•", "Chu kỳ trước đã đóng", "gray"];
    return `
      <div class="cycle-banner closed ${m[2]}">
        <strong>${m[0]} ${m[1]}</strong>
        ${L.closed_event ? `<div class="cycle-note">${L.closed_event}</div>` : ""}
        <div class="cycle-note">Đây là phân tích CHU KỲ MỚI.</div>
      </div>`;
  }
  return "";
}

function renderSetups(data) {
  setupsList.innerHTML = "";
  const setups = data.setups || [];

  const banner = cycleBannerHTML(data);
  if (banner) {
    const b = document.createElement("div");
    b.innerHTML = banner;
    if (b.firstElementChild) setupsList.appendChild(b.firstElementChild);
  }

  [mtfHTML(data), orderflowHTML(data), mmPosHTML(data)].forEach((html) => {
    if (!html) return;
    const d = document.createElement("div");
    d.innerHTML = html;
    if (d.firstElementChild) setupsList.appendChild(d.firstElementChild);
  });

  if (!setups.length) {
    setupsList.innerHTML =
      '<div class="empty">Không có setup đạt điều kiện cho mã này ở khung thời gian đã chọn.<br>Thử đổi sang khung lớn hơn (4h, 1 ngày).</div>';
    return;
  }
  setups.forEach((s) => {
    const wrap = document.createElement("div");
    wrap.innerHTML = setupCardHTML(s);
    setupsList.appendChild(wrap.firstElementChild);
  });

  if (data.patterns && data.patterns.length) {
    const p = document.createElement("div");
    p.className = "pattern-box";
    p.innerHTML = "<strong>Mẫu hình phát hiện:</strong><br>" +
      data.patterns.map((x) => `• ${x.type} @ ${fmt(x.price)} (${x.bias})`).join("<br>");
    setupsList.appendChild(p);
  }
}

/* ============================================================ scanning */
async function scanOne(symbol, interval) {
  const seq = ++state.scanSeq;
  state.currentSymbol = symbol;
  setStatus(`Đang phân tích ${symbol} (${interval})…`, "loading");
  btnScan.disabled = true;
  try {
    const res = await fetch(
      `/api/scan?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}`
    );
    if (seq !== state.scanSeq) return;            // bỏ kết quả về muộn của mã cũ
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const err = await res.json();
        if (err && err.detail) detail = typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail);
      } catch (e) {}
      throw new Error(detail);
    }
    const data = await res.json();
    if (seq !== state.scanSeq) return;

    renderBadge(data);
    drawChart(data);
    renderSetups(data);
    setStatus(`Đã phân tích ${data.name} · ${interval} · ${data.setups.length} setup (${data.grade})`, "ok");
    saveSettings();
  } catch (err) {
    if (seq !== state.scanSeq) return;
    setStatus(`Lỗi: ${err.message}`, "error");
    setupsList.innerHTML = `<div class="empty">Không lấy được dữ liệu cho ${symbol}.<br>${err.message}</div>`;
    console.error(err);
  } finally {
    if (seq === state.scanSeq) btnScan.disabled = false;
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
        row.innerHTML = `<span class="row-name"><strong>${sym}</strong><br><small>${d.name || ""}</small></span>
          <span>${fmt(d.current_price)}</span>
          ${first ? `<span class="badge ${first.type === "BUY" ? "buy" : "sell"}">${first.type} R:R 1:${first.rr}</span>`
                  : '<span class="badge none">Không có setup</span>'}`;
        row.style.cursor = "pointer";
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

/* ==================================================== pretty setups tab */
async function scanPretty() {
  setStatus("Đang quét watchlist để tìm setup đẹp…", "loading");
  btnPretty.disabled = true;
  prettyList.innerHTML = '<div class="empty">Đang quét…</div>';
  try {
    const res = await fetch(`/api/watchlist-scan?interval=${encodeURIComponent(intervalSelect.value)}&only_beautiful=true`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const list = data.results || [];

    if (!list.length) {
      prettyList.innerHTML =
        `<div class="empty">Không có mã nào đạt tiêu chí “setup đẹp” trong watchlist.<br>
         (Yêu cầu: ≥3/5 điều kiện · R:R ≥ 1.5 · Điểm ≥ 55)<br><br>
         Đã quét ${data.scanned} mã · ${data.interval}</div>`;
      setStatus(`Đã quét ${data.scanned} mã — chưa có setup đẹp nào`, "ok");
      return;
    }

    prettyList.innerHTML = `<div class="scan-all-title">⭐ ${list.length} mã có setup đẹp / ${data.scanned} mã · ${data.interval}</div>`;
    list.forEach((r) => {
      const row = document.createElement("div");
      row.className = "pretty-row";
      const side = r.direction === "BUY" ? "buy" : "sell";
      const gradeCls = r.grade.startsWith("A+") ? "gp" : r.grade.startsWith("A") ? "g" :
                       r.grade.startsWith("B") ? "b" : r.grade.startsWith("C") ? "c" : "d";
      row.innerHTML = `
        <div class="pretty-top">
          <span class="pretty-name">${r.name}<br><small>${r.ticker} · ${r.cat}</small></span>
          <span class="grade ${gradeCls}">${r.grade}</span>
        </div>
        <div class="pretty-mid">
          <span class="badge ${side}">${r.direction} · R:R 1:${r.rr}</span>
          <span class="pretty-checks">${r.passed}/${r.total} điều kiện · ${r.score} điểm</span>
        </div>
        <div class="pretty-prices mono">
          E ${fmt(r.entry)} · SL ${fmt(r.sl)} · TP ${fmt(r.tp)}
        </div>`;
      row.addEventListener("click", () => {
        symbolSelect.value = r.ticker;
        scanOne(r.ticker, intervalSelect.value);
        activateTab("setup");
      });
      prettyList.appendChild(row);
    });
    setStatus(`Tìm được ${list.length} mã có setup đẹp`, "ok");
  } catch (err) {
    setStatus(`Lỗi quét setup đẹp: ${err.message}`, "error");
    prettyList.innerHTML = `<div class="empty">Lỗi: ${err.message}</div>`;
  } finally {
    btnPretty.disabled = false;
  }
}

/* ========================================================= watchlist tab */
let allSymbolInfo = [];

function renderWatchlist() {
  watchList.innerHTML = "";
  const groups = {};
  allSymbolInfo.forEach((s) => {
    (groups[s.cat] = groups[s.cat] || []).push(s);
  });
  Object.entries(groups).forEach(([cat, items]) => {
    const h = document.createElement("div");
    h.className = "watch-group-title";
    h.textContent = cat;
    watchList.appendChild(h);
    items.forEach((s) => {
      const row = document.createElement("label");
      row.className = "watch-item" + (state.watchlist.includes(s.t) ? " on" : "");
      row.innerHTML = `
        <input type="checkbox" value="${s.t}" ${state.watchlist.includes(s.t) ? "checked" : ""}>
        <span class="w-name">${s.name}</span>
        <span class="w-sub">${s.sub}</span>`;
      row.querySelector("input").addEventListener("change", (e) => {
        const t = e.target.value;
        if (e.target.checked) {
          if (!state.watchlist.includes(t)) state.watchlist.push(t);
        } else {
          state.watchlist = state.watchlist.filter((x) => x !== t);
        }
        row.classList.toggle("on", e.target.checked);
      });
      watchList.appendChild(row);
    });
  });
}

async function saveWatchlist() {
  try {
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ watchlist: state.watchlist }),
    });
    setStatus(`Đã lưu watchlist (${state.watchlist.length} mã)`, "ok");
  } catch (e) {
    setStatus("Không lưu được watchlist", "error");
  }
}

/* ================================================================ tabs */
function activateTab(name) {
  document.querySelectorAll(".tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab-body").forEach((b) =>
    b.classList.toggle("active", b.id === "tab-" + name));
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
  } catch (e) { console.warn("Không lưu được cài đặt", e); }
}

/* ================================================================ boot */
document.addEventListener("DOMContentLoaded", async () => {
  initChart();

  // Nạp danh sách mã + settings
  try {
    const [rSym, rSet] = await Promise.all([fetch("/api/symbols"), fetch("/api/settings")]);
    if (rSym.ok) {
      const d = await rSym.json();
      allSymbolInfo = d.symbols || [];
      allSymbolInfo.forEach((s) => { state.symbolInfo[s.t] = s; });
    }
    if (rSet.ok) {
      const s = await rSet.json();
      if (s.interval) intervalSelect.value = s.interval;
      if (s.scan_cycle) cycleSelect.value = s.scan_cycle;
      if (s.favorite_symbols && s.favorite_symbols[0]) symbolSelect.value = s.favorite_symbols[0];
      state.watchlist = s.watchlist || s.favorite_symbols || [];
    }
  } catch (e) { console.warn(e); }

  renderWatchlist();

  btnScan.addEventListener("click", () => scanOne(symbolSelect.value, intervalSelect.value));
  btnScanAll.addEventListener("click", scanAll);
  btnPretty.addEventListener("click", scanPretty);
  $("btnWatchSave").addEventListener("click", saveWatchlist);
  $("btnWatchAll").addEventListener("click", () => {
    state.watchlist = allSymbolInfo.map((s) => s.t);
    renderWatchlist();
  });
  symbolSelect.addEventListener("change", () => {
    // Reset hiển thị ngay để người dùng thấy đang chuyển mã
    setStatus(`Đang tải ${symbolSelect.value}…`, "loading");
    setupsList.innerHTML = '<div class="empty">Đang tải…</div>';
    scanOne(symbolSelect.value, intervalSelect.value);
  });
  intervalSelect.addEventListener("change", () => scanOne(symbolSelect.value, intervalSelect.value));
  cycleSelect.addEventListener("change", saveSettings);
  document.querySelectorAll(".tab").forEach((b) =>
    b.addEventListener("click", () => activateTab(b.dataset.tab)));

  // Tự phân tích mã đầu tiên
  scanOne(symbolSelect.value, intervalSelect.value);
});
