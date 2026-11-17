"""
Phân tích kỹ thuật tự động.

Sinh ra cho mỗi mã:
  • Vùng Hỗ trợ / Kháng (cluster từ swing points)
  • Trendline hỗ trợ / kháng + số lần chạm
  • Mẫu hình Đỉnh kép / Đáy kép
  • CHECKLIST 4 điều kiện HỘI TỤ vào lệnh (① Phá · ② Retest · ③ Trendline 3 · ④ Mẫu hình),
    từng điều kiện ĐẠT / KHÔNG ĐẠT kèm mức giá cụ thể
  • Setup: Entry / SL / TP / R:R
  • Điểm chất lượng 0–100 để xếp hạng "setup đẹp"
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import setup_state as st_mod
from . import orderflow as of_mod
from . import multi_tf as mtf_mod


# ------------------------------------------------------------ swing & cluster
def _swing_points(df: pd.DataFrame, window: int = 5):
    highs: List[Tuple] = []
    lows: List[Tuple] = []
    if len(df) < window * 2 + 3:
        return highs, lows
    for i in range(window, len(df) - window):
        seg_h = df["high"].iloc[i - window: i + window + 1]
        seg_l = df["low"].iloc[i - window: i + window + 1]
        if df["high"].iloc[i] >= seg_h.max():
            highs.append((df.index[i], float(df["high"].iloc[i])))
        if df["low"].iloc[i] <= seg_l.min():
            lows.append((df.index[i], float(df["low"].iloc[i])))
    return highs, lows


def _cluster(points: List[Tuple], threshold_pct: float = 0.004) -> List[float]:
    if not points:
        return []
    prices = sorted(p for _, p in points)
    clusters: List[float] = []
    current = [prices[0]]
    for p in prices[1:]:
        if abs(p - current[-1]) / max(current[-1], 1e-9) <= threshold_pct:
            current.append(p)
        else:
            clusters.append(sum(current) / len(current))
            current = [p]
    clusters.append(sum(current) / len(current))
    return clusters


# ------------------------------------------------------------------ trendline
def _fit_line(points: List[Tuple], kind: str) -> Optional[Dict]:
    if len(points) < 2:
        return None
    p1, p2 = points[0], points[-1]
    try:
        x1 = pd.Timestamp(p1[0]).value
        x2 = pd.Timestamp(p2[0]).value
    except Exception:
        return None
    if x2 <= x1:
        return None
    return {"kind": kind, "x1": x1, "y1": float(p1[1]), "x2": x2, "y2": float(p2[1]),
            "from": str(p1[0]), "to": str(p2[0])}


def _count_touches(df: pd.DataFrame, line: Optional[Dict], tol: float = 0.004):
    if not line:
        return 0, []
    touches = []
    for ts, row in df.iterrows():
        x = pd.Timestamp(ts).value
        if x < line["x1"] or x > line["x2"]:
            continue
        y = line["y1"] + (line["y2"] - line["y1"]) * (x - line["x1"]) / (line["x2"] - line["x1"])
        price = float(row["low"]) if line["kind"] == "support" else float(row["high"])
        if y <= 0:
            continue
        if abs(price - y) / y <= tol:
            touches.append({"ts": str(ts), "price": round(price, 5), "line": round(y, 5)})
    return len(touches), touches



def _touches_recent(df: pd.DataFrame, line: Optional[Dict], tol: float = 0.004,
                    lookback: int = 12) -> int:
    """Đếm số lần chạm trendline trong `lookback` nến GẦN NHẤT.

    Dùng cho điều kiện ③ "Nay chạm trendline lần thứ 3": lần chạm phải ĐANG
    diễn ra, không phải chạm từ 200 nến trước.
    """
    if not line:
        return 0
    n = len(df)
    if n == 0:
        return 0
    cnt = 0
    for ts, row in df.iloc[-lookback:].iterrows():
        x = pd.Timestamp(ts).value
        if x < line["x1"] or x > line["x2"] or line["x2"] == line["x1"]:
            continue
        y = line["y1"] + (line["y2"] - line["y1"]) * (x - line["x1"]) / (line["x2"] - line["x1"])
        if y <= 0:
            continue
        price = float(row["low"]) if line["kind"] == "support" else float(row["high"])
        if abs(price - y) / y <= tol:
            cnt += 1
    return cnt



# ------------------------------------------------------- liquidity targets
def _liquidity_targets(side: str, close: float, highs: List[Tuple], lows: List[Tuple],
                       atr: float) -> List[float]:
    """Tìm các MỤC TIÊU THANH KHOẢN phía trước — nơi đám đông đặt SL.

    Với BUY  : các ĐỈNH phía trên giá (SL của phe SELL đang nằm trên đỉnh)
    Với SELL : các ĐÁY phía dưới giá  (SL của phe BUY đang nằm dưới đáy)

    MM thường đẩy giá tới đúng các mức này để quét SL trước khi đảo chiều,
    nên đây là mục tiêu TP hợp lý hơn ATR×3 rất nhiều.

    Trả về danh sách đã sắp xếp theo khoảng cách tăng dần (gần -> xa),
    đã lọc bỏ mức quá gần (< 0.4 ATR, nhiễu) và quá xa (> 12 ATR, phi thực tế).
    """
    pool = []
    if side == "BUY":
        pool = [p for _, p in highs if p > close * 1.002]
        pool.sort()
    else:
        pool = [p for _, p in lows if p < close * 0.998]
        pool.sort(reverse=True)

    out: List[float] = []
    for p in pool:
        dist = abs(p - close)
        if dist < atr * 0.4 or dist > atr * 12:
            continue
        # gộp các mức sát nhau (< 0.5 ATR) để không ra 2 mục tiêu trùng
        if out and abs(p - out[-1]) < atr * 0.5:
            continue
        out.append(round(p, 6))
        if len(out) >= 4:
            break
    return out


def _pick_tp(side: str, close: float, sl: float, targets: List[float],
             atr: float) -> Tuple[float, Optional[float], str]:
    """Chọn TP1 / TP2 từ danh sách mục tiêu thanh khoản.

    Yêu cầu: TP1 phải cho R:R >= 1.5 (nếu không đủ thì nới ra ATR).
    Trả về (tp1, tp2, mô tả nguồn).
    """
    risk = abs(close - sl)
    if risk <= 0:
        risk = atr

    usable = [t for t in targets
              if (side == "BUY" and t > close) or (side == "SELL" and t < close)]
    # Lọc mức cho R:R >= 1.5
    usable_ok = [t for t in usable if abs(t - close) / risk >= 1.5]

    if usable_ok:
        tp1 = usable_ok[0]
        tp2 = usable_ok[1] if len(usable_ok) > 1 else None
        src = "Vùng thanh khoản (đỉnh/đáy đám đông đặt SL)"
        return tp1, tp2, src

    # Không có mức thanh khoản nào đủ xa -> nới bằng ATR
    tp1 = close + atr * 3 if side == "BUY" else close - atr * 3
    return tp1, None, "ATR×3 (không tìm thấy vùng thanh khoản phù hợp)"



# ------------------------------------------------------- stop sau râu quét
def _stop_after_sweep(side: str, df: pd.DataFrame, atr: float,
                      struct_level: Optional[float], lookback: int = 12) -> Dict:
    """BƯỚC 7 — Đặt SL SAU RÂU QUÉT (không phải trước vùng S/R).

    Tài liệu: "đặt Stop-Loss sau vùng râu quét".

    Ý nghĩa: MM thường chọc râu qua đỉnh/đáy để quét SL đám đông rồi mới đảo
    chiều. Nếu đặt SL ngay trên đỉnh (BUY) hoặc dưới đáy (SELL) thì bị quét.
    Vì vậy SL phải nằm NGOÀI cực trị gần nhất + một khoảng đệm ATR.

    Trả về {sl, sweep_high, sweep_low, buffer, note}
    """
    if df is None or len(df) < 3:
        ref = struct_level or 0
        return {"sl": ref, "buffer": 0, "note": "Không đủ dữ liệu"}

    seg = df.tail(lookback)
    hi = float(seg["high"].max())
    lo = float(seg["low"].min())
    buf = atr * 0.6          # đệm sau râu quét

    if side == "BUY":
        # SL dưới ĐÁY thấp nhất của lookback (nơi râu quét hay chọc xuống)
        base = lo
        if struct_level and struct_level < base:
            base = float(struct_level)
        sl = base - buf
        return {"sl": sl, "sweep_low": round(lo, 6), "buffer": round(buf, 6),
                "note": (f"SL đặt dưới đáy {round(lo, 6)} một khoảng đệm "
                         f"{round(buf, 6)} (0.6·ATR) — sau vùng râu quét.")}
    else:
        # SL trên ĐỈNH cao nhất của lookback
        base = hi
        if struct_level and struct_level > base:
            base = float(struct_level)
        sl = base + buf
        return {"sl": sl, "sweep_high": round(hi, 6), "buffer": round(buf, 6),
                "note": (f"SL đặt trên đỉnh {round(hi, 6)} một khoảng đệm "
                         f"{round(buf, 6)} (0.6·ATR) — sau vùng râu quét.")}


# ------------------------------------------------------------------- patterns
def detect_patterns(highs, lows, threshold: float = 0.006) -> List[Dict]:
    patterns: List[Dict] = []
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if abs(a[1] - b[1]) / max(a[1], 1e-9) <= threshold:
            mid = min(lows, key=lambda p: abs((b[0] - p[0]).total_seconds())) if lows else None
            patterns.append({"type": "Đỉnh kép (Double Top)", "bias": "SELL",
                             "price": round((a[1] + b[1]) / 2, 5),
                             "neckline": round(mid[1], 5) if mid else None,
                             "points": [{"t": str(a[0]), "p": a[1]}, {"t": str(b[0]), "p": b[1]}]})
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if abs(a[1] - b[1]) / max(a[1], 1e-9) <= threshold:
            mid = min(highs, key=lambda p: abs((b[0] - p[0]).total_seconds())) if highs else None
            patterns.append({"type": "Đáy kép (Double Bottom)", "bias": "BUY",
                             "price": round((a[1] + b[1]) / 2, 5),
                             "neckline": round(mid[1], 5) if mid else None,
                             "points": [{"t": str(a[0]), "p": a[1]}, {"t": str(b[0]), "p": b[1]}]})
    return patterns


# ---------------------------------------------------------------- indicators
def _atr(df: pd.DataFrame, n: int = 14) -> float:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    val = float(tr.rolling(n).mean().iloc[-1])
    if np.isfinite(val) and val > 0:
        return val
    fb = float((high - low).tail(n).mean())
    return fb if np.isfinite(fb) and fb > 0 else float(close.iloc[-1]) * 0.005


def _rsi(df: pd.DataFrame, n: int = 14) -> float:
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    last_loss = float(loss.iloc[-1])
    if last_loss <= 0:
        return 100.0
    rs = float(gain.iloc[-1]) / last_loss
    return float(100 - (100 / (1 + rs)))


def _round(price: float, ref: float) -> float:
    if ref >= 1000:
        return round(price, 2)
    if ref >= 10:
        return round(price, 3)
    if ref >= 1:
        return round(price, 4)
    return round(price, 5)


# ----------------------------------------------------------------- checklist
def _build_checklist(side: str, close: float, sup_below: Optional[float],
                     res_above: Optional[float], res_below: Optional[float],
                     sup_above: Optional[float], sup_tl: Optional[Dict],
                     res_tl: Optional[Dict], sup_touch: int, res_touch: int,
                     e20: float, e50: float, rsi: float, patterns: List[Dict],
                     atr: float, touch_recent: int = 0) -> Tuple[List[Dict], str]:
    """Trả về (danh sách 4 điều kiện HỘI TỤ, tên mô hình).

    Bám đúng lý thuyết "Hội tụ 4 điều kiện" của Market Maker:
      ① Phá vùng Hỗ trợ / Kháng        (Break)
      ② Quay về test lại vùng vừa phá  (Retest)
      ③ Chạm Trendline lần thứ 3       (Trendline 3)
      ④ Chuỗi mẫu hình / cấu trúc đồng thuận (Pattern 3)

    Mỗi điều kiện nêu MỘT SỰ THẬT kiểm chứng được, kèm mức giá cụ thể.
    RSI chỉ hiện trong phần diễn giải, KHÔNG còn là điều kiện riêng.
    """
    items: List[Dict] = []

    def push(ok: bool, text: str, value: str):
        items.append({"ok": bool(ok), "text": text, "value": value})

    if side == "BUY":
        # ---- ①② Phá kháng & test lại (ưu tiên) hoặc test lại hỗ trợ ----
        if res_below and (close - res_below) / close <= 0.025:
            pattern = "Phá vỡ & test lại (Breakout–Retest)"
            push(True,
                 f"① Giá đã phá vùng kháng {_round(res_below, close)}",
                 f"Giá {_round(close, close)} > kháng {_round(res_below, close)}")
            push(True,
                 f"② Quay về test lại vùng {_round(res_below, close)} "
                 f"(kháng cũ → hỗ trợ mới)",
                 f"Cách {round((close - res_below) / close * 100, 2)}% (yêu cầu ≤ 2.5%)")
            touch = sup_touch
            tl = sup_tl
            tl_name = "hỗ trợ"
        else:
            pattern = "Phản ứng tại vùng hỗ trợ (Rejection)"
            zone = sup_below
            if zone:
                d = (close - zone) / close * 100
                push(close > zone * 0.999,
                     f"① Giá chưa đánh thủng hỗ trợ {_round(zone, close)}",
                     f"Giá {_round(close, close)} > {_round(zone, close)}")
                push(d <= 2.5,
                     f"② Giá đang test lại vùng hỗ trợ {_round(zone, close)}",
                     f"Cách {round(d, 2)}% (yêu cầu ≤ 2.5%)")
            else:
                push(False, "① Không tìm thấy vùng hỗ trợ bên dưới giá", "—")
                push(False, "② Không có vùng để test lại", "—")
            touch = sup_touch
            tl = sup_tl
            tl_name = "hỗ trợ"

        # ---- ③ NAY chạm Trendline lần thứ 3 ----
        c3_ok = touch >= 3 and touch_recent >= 1
        push(c3_ok,
             f"③ Nay giá chạm trendline {tl_name} lần thứ 3",
             f"{touch} lần chạm" + (f" · từ {tl['from'][:10]}" if tl else "")
             + f" · {touch_recent} lần trong 12 nến gần nhất"
             + ("" if c3_ok else " (cần ≥ 3 tổng VÀ đang chạm)"))

        # ---- ④ Chuỗi mẫu hình tăng đã hoàn thành (Đáy kép) ----
        pat_ok = any(p["bias"] == "BUY" for p in patterns)
        trend_ok = e20 > e50
        push(pat_ok,
             "④ Chuỗi mẫu hình tăng đã hoàn thành (Đáy kép)",
             ("có Đáy kép ✔" if pat_ok else "chưa có Đáy kép")
             + f" · EMA20 {'>' if trend_ok else '<'} EMA50"
             + f" · RSI {round(rsi, 1)}")

    else:  # SELL
        # ---- ①② Thủng hỗ trợ & test lại (ưu tiên) hoặc test lại kháng ----
        if sup_above and (sup_above - close) / close <= 0.025:
            pattern = "Phá vỡ & test lại (Breakdown–Retest)"
            push(True,
                 f"① Giá đã đánh thủng vùng hỗ trợ {_round(sup_above, close)}",
                 f"Giá {_round(close, close)} < hỗ trợ {_round(sup_above, close)}")
            push(True,
                 f"② Quay về test lại vùng {_round(sup_above, close)} "
                 f"(hỗ trợ cũ → kháng mới)",
                 f"Cách {round((sup_above - close) / close * 100, 2)}% (yêu cầu ≤ 2.5%)")
            touch = res_touch
            tl = res_tl
            tl_name = "kháng"
        else:
            pattern = "Phản ứng tại vùng kháng (Rejection)"
            zone = res_above
            if zone:
                d = (zone - close) / close * 100
                push(close < zone * 1.001,
                     f"① Giá chưa vượt qua kháng {_round(zone, close)}",
                     f"Giá {_round(close, close)} < {_round(zone, close)}")
                push(d <= 2.5,
                     f"② Giá đang test lại vùng kháng {_round(zone, close)}",
                     f"Cách {round(d, 2)}% (yêu cầu ≤ 2.5%)")
            else:
                push(False, "① Không tìm thấy vùng kháng bên trên giá", "—")
                push(False, "② Không có vùng để test lại", "—")
            touch = res_touch
            tl = res_tl
            tl_name = "kháng"

        # ---- ③ NAY chạm Trendline lần thứ 3 ----
        c3_ok = touch >= 3 and touch_recent >= 1
        push(c3_ok,
             f"③ Nay giá chạm trendline {tl_name} lần thứ 3",
             f"{touch} lần chạm" + (f" · từ {tl['from'][:10]}" if tl else "")
             + f" · {touch_recent} lần trong 12 nến gần nhất"
             + ("" if c3_ok else " (cần ≥ 3 tổng VÀ đang chạm)"))

        # ---- ④ Chuỗi mẫu hình giảm đã hoàn thành (Đỉnh kép) ----
        pat_ok = any(p["bias"] == "SELL" for p in patterns)
        trend_ok = e20 < e50
        push(pat_ok,
             "④ Chuỗi mẫu hình giảm đã hoàn thành (Đỉnh kép)",
             ("có Đỉnh kép ✔" if pat_ok else "chưa có Đỉnh kép")
             + f" · EMA20 {'<' if trend_ok else '>'} EMA50"
             + f" · RSI {round(rsi, 1)}")

    return items, pattern


def _candles_since(df: pd.DataFrame, level: Optional[float], side: str) -> int:
    """Số nến kể từ lần cuối giá vượt qua mốc level theo hướng side."""
    if not level:
        return 999
    for i in range(len(df) - 1, max(len(df) - 120, 0), -1):
        c = float(df["close"].iloc[i])
        if (side == "BUY" and c > level * 0.999) or (side == "SELL" and c < level * 1.001):
            return len(df) - 1 - i
    return 999


# -------------------------------------------------------------------- setup
def _mk_setup(side: str, entry: float, sl: float, tp: float, reasons: List[str],
              source: str, checklist: List[Dict]) -> Optional[Dict]:
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk <= 0 or reward <= 0:
        return None
    rr = reward / risk
    passed = sum(1 for c in checklist if c["ok"])
    total = len(checklist)

    # Điểm chất lượng 0–100
    score = rr / 3.0 * 45                     # R:R tối đa 45đ
    score += passed / max(total, 1) * 40      # checklist tối đa 40đ
    score += 15 if source.startswith("Vùng") else 6
    score = max(0.0, min(100.0, score))

    if passed >= 4 and rr >= 2:
        grade = "A+ (Rất đẹp)"
    elif passed >= 3 and rr >= 1.8:
        grade = "A (Đẹp)"
    elif passed >= 3:
        grade = "B (Khá)"
    elif passed >= 2:
        grade = "C (Trung bình)"
    else:
        grade = "D (Yếu)"

    confidence = "Cao" if passed >= 4 else ("Trung bình" if passed >= 3 else "Thấp")

    return {
        "type": side,
        "entry": _round(entry, entry),
        "sl": _round(sl, entry),
        "tp": _round(tp, entry),
        "rr": round(rr, 2),
        "confidence": confidence,
        "source": source,
        "reasons": reasons,
        "checklist": checklist,
        "passed": passed,
        "total": total,
        "score": round(score, 1),
        "grade": grade,
    }


# ------------------------------------------------------------------ analyze
def analyze_symbol(df: pd.DataFrame, symbol: str, interval: str, info: Optional[Dict] = None,
                   locked: Optional[Dict] = None,
                   expiry_bars: int = st_mod.DEFAULT_EXPIRY_BARS,
                   tf_frames: Optional[Dict[str, pd.DataFrame]] = None,
                   df_lower: Optional[pd.DataFrame] = None) -> Dict:
    df = df.copy()
    close = float(df["close"].iloc[-1])
    atr = _atr(df)
    rsi = _rsi(df)

    highs, lows = _swing_points(df, window=5)
    resistances = _cluster(highs)
    supports = _cluster(lows)

    sup_line = _fit_line(lows, "support")
    res_line = _fit_line(highs, "resistance")
    sup_touch, sup_list = _count_touches(df, sup_line)
    res_touch, res_list = _count_touches(df, res_line)
    sup_recent = _touches_recent(df, sup_line)
    res_recent = _touches_recent(df, res_line)
    patterns = detect_patterns(highs, lows)

    ema20 = df["close"].ewm(span=20, adjust=False).mean()
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    e20, e50 = float(ema20.iloc[-1]), float(ema50.iloc[-1])

    # Phân loại vùng S/R theo vị trí tương đối so với giá hiện tại
    sup_below = [s for s in supports if s < close]
    sup_above = [s for s in supports if s >= close]
    res_above = [r for r in resistances if r > close]
    res_below = [r for r in resistances if r <= close]

    sup_near = max(sup_below) if sup_below else None      # hỗ trợ gần nhất bên dưới
    sup_just_above = min(sup_above) if sup_above else None  # hỗ trợ vừa bị thủng
    res_near = min(res_above) if res_above else None      # kháng gần nhất bên trên
    res_just_below = max(res_below) if res_below else None  # kháng vừa bị phá

    setups: List[Dict] = []

    # Mục tiêu thanh khoản phía trước (đỉnh/đáy đám đông đặt SL)
    buy_targets = _liquidity_targets("BUY", close, highs, lows, atr)
    sell_targets = _liquidity_targets("SELL", close, highs, lows, atr)

    def make(side: str, sl: float, tp: float, source: str, reasons: List[str],
             tp2: Optional[float] = None, tp_src: str = "",
             sweep_lvl: Optional[float] = None):
        cl, pattern = _build_checklist(
            side, close, sup_near, res_near, res_just_below, sup_just_above,
            sup_line, res_line, sup_touch, res_touch, e20, e50, rsi, patterns, atr,
            touch_recent=(sup_recent if side == "BUY" else res_recent),
        )
        s_ = _mk_setup(side, close, sl, tp, reasons, source, cl)
        if s_:
            s_["pattern"] = pattern
            s_["tp2"] = _round(tp2, close) if tp2 else None
            s_["tp_source"] = tp_src
            s_["sweep_level"] = _round(sweep_lvl, close) if sweep_lvl else None
            setups.append(s_)

    # ---- BUY: phản ứng tại hỗ trợ ----
    if sup_near and (close - sup_near) / close <= 0.03:
        sw = _stop_after_sweep("BUY", df, atr, sup_near)
        sl = sw["sl"]
        tp1, tp2, tsrc = _pick_tp("BUY", close, sl, buy_targets, atr)
        make("BUY", sl, tp1, "Vùng hỗ trợ", [
            f"Nằm trên hỗ trợ {_round(sup_near, close)} (cách {round((close - sup_near) / close * 100, 2)}%)",
            f"Trendline hỗ trợ bị chạm {sup_touch} lần",
            sw["note"],
            f"RSI {round(rsi, 1)} · ATR {_round(atr, close)}",
        ], tp2, tsrc, sweep_lvl=sw.get("sweep_low"))

    # ---- BUY: phá kháng rồi test lại ----
    if res_just_below and (close - res_just_below) / close <= 0.025:
        sw = _stop_after_sweep("BUY", df, atr, res_just_below)
        sl = sw["sl"]
        tp1, tp2, tsrc = _pick_tp("BUY", close, sl, buy_targets, atr)
        make("BUY", sl, tp1, "Phá kháng & test lại", [
            f"Kháng {_round(res_just_below, close)} vừa bị phá, nay thành hỗ trợ",
            f"Giá đang test lại từ phía trên (cách {round((close - res_just_below) / close * 100, 2)}%)",
            sw["note"],
            f"RSI {round(rsi, 1)} · ATR {_round(atr, close)}",
        ], tp2, tsrc, sweep_lvl=sw.get("sweep_low"))

    # ---- BUY: thuận xu hướng EMA ----
    if e20 > e50 and close > e20:
        sw = _stop_after_sweep("BUY", df, atr, None)
        sl = sw["sl"]
        tp1, tp2, tsrc = _pick_tp("BUY", close, sl, buy_targets, atr)
        make("BUY", sl, tp1, "Xu hướng tăng", [
            "EMA20 > EMA50 (xu hướng tăng)", "Giá đóng cửa trên EMA20",
            sw["note"],
            f"RSI {round(rsi, 1)} · ATR {_round(atr, close)}",
        ], tp2, tsrc, sweep_lvl=sw.get("sweep_low"))

    # ---- SELL: phản ứng tại kháng ----
    if res_near and (res_near - close) / close <= 0.03:
        sw = _stop_after_sweep("SELL", df, atr, res_near)
        sl = sw["sl"]
        tp1, tp2, tsrc = _pick_tp("SELL", close, sl, sell_targets, atr)
        make("SELL", sl, tp1, "Vùng kháng", [
            f"Nằm dưới kháng {_round(res_near, close)} (cách {round((res_near - close) / close * 100, 2)}%)",
            f"Trendline kháng bị chạm {res_touch} lần",
            sw["note"],
            f"RSI {round(rsi, 1)} · ATR {_round(atr, close)}",
        ], tp2, tsrc, sweep_lvl=sw.get("sweep_high"))

    # ---- SELL: thủng hỗ trợ rồi test lại ----
    if sup_just_above and (sup_just_above - close) / close <= 0.025:
        sw = _stop_after_sweep("SELL", df, atr, sup_just_above)
        sl = sw["sl"]
        tp1, tp2, tsrc = _pick_tp("SELL", close, sl, sell_targets, atr)
        make("SELL", sl, tp1, "Thủng hỗ trợ & test lại", [
            f"Hỗ trợ {_round(sup_just_above, close)} vừa bị thủng, nay thành kháng",
            f"Giá đang test lại từ phía dưới (cách {round((sup_just_above - close) / close * 100, 2)}%)",
            sw["note"],
            f"RSI {round(rsi, 1)} · ATR {_round(atr, close)}",
        ], tp2, tsrc, sweep_lvl=sw.get("sweep_high"))

    # ---- SELL: thuận xu hướng EMA ----
    if e20 < e50 and close < e20:
        sw = _stop_after_sweep("SELL", df, atr, None)
        sl = sw["sl"]
        tp1, tp2, tsrc = _pick_tp("SELL", close, sl, sell_targets, atr)
        make("SELL", sl, tp1, "Xu hướng giảm", [
            "EMA20 < EMA50 (xu hướng giảm)", "Giá đóng cửa dưới EMA20",
            sw["note"],
            f"RSI {round(rsi, 1)} · ATR {_round(atr, close)}",
        ], tp2, tsrc, sweep_lvl=sw.get("sweep_high"))

    # ---- Dựng dữ liệu nến TRƯỚC để dùng cho khoá hướng ----
    candles = [
        {"time": int(pd.Timestamp(ts).timestamp()),
         "open": round(float(r["open"]), 6), "high": round(float(r["high"]), 6),
         "low": round(float(r["low"]), 6), "close": round(float(r["close"]), 6)}
        for ts, r in df.iterrows()
    ]

    # ================================================================
    # BƯỚC 1 — XU HƯỚNG ĐA KHUNG (1D → 4H → 1H)
    # ================================================================
    mtf = mtf_mod.combine(tf_frames or {})

    # ================================================================
    # KHOÁ HƯỚNG (hysteresis) — chống đảo hướng mỗi lần refresh
    # ================================================================
    lock_info: Dict = {"locked": False}
    blocked_counter = 0

    if locked:
        rec = st_mod.evaluate(locked, candles, interval, expiry_bars)
        lock_info = st_mod.describe(rec)
        if st_mod.is_locked(rec):
            # Đang bị khoá -> ép hướng cũ, bỏ mọi tín hiệu ngược
            locked_side = rec.get("side")
            opposite = [x for x in setups if x["type"] != locked_side]
            same = [x for x in setups if x["type"] == locked_side]
            if opposite:
                blocked_counter = len(opposite)
                rec["blocked_signals"] = rec.get("blocked_signals", 0) + blocked_counter
            if same:
                same.sort(key=lambda x: x["score"], reverse=True)
                setups = same
            else:
                # Không còn setup cùng hướng -> giữ hướng khoá bằng bản ghi cũ
                setups = []
            lock_info["blocked_now"] = blocked_counter
            lock_info = {**lock_info, **st_mod.describe(rec)}
        else:
            lock_info["just_closed"] = rec.get("state")
            lock_info["closed_event"] = rec.get("event")

    # ---- Chọn 1 hướng nhất quán theo điểm chất lượng ----
    buys = [s for s in setups if s["type"] == "BUY"]
    sells = [s for s in setups if s["type"] == "SELL"]
    best_buy = max(buys, key=lambda x: x["score"]) if buys else None
    best_sell = max(sells, key=lambda x: x["score"]) if sells else None
    if best_buy and best_sell:
        chosen = "BUY" if best_buy["score"] >= best_sell["score"] else "SELL"
        setups = [s for s in setups if s["type"] == chosen]
    setups.sort(key=lambda x: x["score"], reverse=True)
    setups = [s for s in setups if s["rr"] >= 1.2][:3]

    # ================================================================
    # BƯỚC 5 + 6 — ORDER FLOW & VỊ TRÍ MM (áp cho setup cuối cùng)
    # ================================================================
    of_report: Dict = {}
    mtf_check: Dict = {}
    if setups:
        st0 = setups[0]
        side0 = st0["type"]
        lvl = st0.get("sweep_level")
        of_report = of_mod.orderflow_report(df, df_lower, side0, lvl, atr)
        st0["orderflow"] = of_report
        st0["mm_position"] = of_report.get("position")

        # Điều chỉnh điểm theo dòng tiền (Bước 5)
        adj = st0["score"] + of_report.get("score_bonus", 0)
        st0["score"] = round(max(0.0, min(100.0, adj)), 1)

        # Bước 1 — kiểm tra ngược xu hướng khung lớn
        mtf_check = mtf_mod.check_conflict(mtf, side0)
        st0["mtf_status"] = mtf_check
        st0["score"] = round(max(0.0, min(100.0, st0["score"] - mtf_check.get("penalty", 0))), 1)

        # Xếp hạng lại theo điểm mới
        p_, t_ = st0["passed"], st0["total"]
        rr_ = st0["rr"]
        if p_ >= 4 and rr_ >= 2:
            st0["grade"] = "A+ (Rất đẹp)"
        elif p_ >= 3 and rr_ >= 1.8:
            st0["grade"] = "A (Đẹp)"
        elif p_ >= 3:
            st0["grade"] = "B (Khá)"
        elif p_ >= 2:
            st0["grade"] = "C (Trung bình)"
        else:
            st0["grade"] = "D (Yếu)"

        # Ép R:R tối thiểu 1:2 (Bước 7) — nếu không đủ thì đánh dấu
        st0["rr_ok"] = rr_ >= 2.0

    # Không còn setup nào sau khi lọc R:R -> trả về rỗng (không bịa)
    # (giữ nguyên hành vi cũ)

    info = info or {}
    best = setups[0] if setups else None

    return {
        "symbol": symbol,
        "ticker": symbol,
        "name": info.get("name", symbol),
        "cat": info.get("cat", "Khác"),
        "sub": info.get("sub", symbol),
        "unit": info.get("unit", ""),
        "interval": interval,
        "current_price": _round(close, close),
        "atr": _round(atr, close),
        "rsi": round(rsi, 1),
        "ema20": _round(e20, close),
        "ema50": _round(e50, close),
        "supports": [_round(s, close) for s in supports[-2:]],
        "resistances": [_round(r, close) for r in resistances[:2]],
        "support_trendline": _serialize_line(sup_line),
        "resistance_trendline": _serialize_line(res_line),
        "support_touches": sup_touch,
        "resistance_touches": res_touch,
        "support_touch_list": sup_list,
        "resistance_touch_list": res_list,
        "patterns": patterns,
        "setups": setups,
        "score": best["score"] if best else 0,
        "grade": best["grade"] if best else "Không có setup",
        "direction": best["type"] if best else None,
        "lock": lock_info,
        "mtf": mtf,
        "mtf_check": mtf_check,
        "candles": candles,
        "time": int(datetime.now(tz=timezone.utc).timestamp()),
    }


def _serialize_line(line: Optional[Dict]) -> Optional[Dict]:
    if not line:
        return None
    x1, x2, y1, y2 = line["x1"], line["x2"], line["y1"], line["y2"]
    span = x2 - x1
    x_end = x2 + span * 0.35
    y_end = y2 + (y2 - y1) * 0.35
    return {
        "kind": line["kind"], "from": line["from"], "to": line["to"],
        "y1": _round(y1, y1), "y2": _round(y2, y2),
        "x1_ts": int(pd.Timestamp(x1).timestamp()),
        "x2_ts": int(pd.Timestamp(x_end).timestamp()),
        "y_end": _round(y_end, y1),
        "slope_pct": round((y_end - y1) / max(abs(y1), 1e-9) * 100, 2),
    }
