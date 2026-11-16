"""
Phân tích kỹ thuật tự động.

Sinh ra cho mỗi mã:
  • Vùng Hỗ trợ / Kháng (cluster từ swing points)
  • Trendline hỗ trợ / kháng + số lần chạm
  • Mẫu hình Đỉnh kép / Đáy kép
  • CHECKLIST 4 điều kiện vào lệnh (từng điều kiện ĐẠT / KHÔNG ĐẠT, kèm mức giá cụ thể)
  • Setup: Entry / SL / TP / R:R
  • Điểm chất lượng 0–100 để xếp hạng "setup đẹp"
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


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
                     atr: float) -> Tuple[List[Dict], str]:
    """Trả về (danh sách điều kiện, tên mô hình).

    Mỗi điều kiện nêu MỘT SỰ THẬT có thể kiểm chứng được, kèm mức giá cụ thể.
    Hỗ trợ 2 mô hình:
      • "Phá vỡ & test lại"  – giá đã phá một vùng rồi quay lại kiểm tra
      • "Phản ứng tại vùng"  – giá đang nằm sát vùng S/R và bị từ chối
    """
    items: List[Dict] = []

    def push(ok: bool, text: str, value: str):
        items.append({"ok": bool(ok), "text": text, "value": value})

    if side == "BUY":
        # Ưu tiên mô hình phá vỡ & test lại nếu có kháng đã bị phá nằm ngay dưới giá
        if res_below and (close - res_below) / close <= 0.025:
            pattern = "Phá vỡ & test lại (Breakout–Retest)"
            push(True,
                 f"Giá đã phá vùng kháng {_round(res_below, close)}",
                 f"Giá {_round(close, close)} > kháng {_round(res_below, close)}")
            push(True,
                 f"Giá quay về test lại vùng {_round(res_below, close)} từ phía trên (kháng cũ → hỗ trợ mới)",
                 f"Cách {round((close - res_below) / close * 100, 2)}% (yêu cầu ≤ 2.5%)")
            zone = res_below
            touch = sup_touch
            tl = sup_tl
            tl_name = "hỗ trợ"
        else:
            pattern = "Phản ứng tại vùng hỗ trợ (Rejection)"
            zone = sup_below
            if zone:
                d = (close - zone) / close * 100
                push(d <= 2.5,
                     f"Giá nằm sát vùng hỗ trợ {_round(zone, close)}",
                     f"Cách {round(d, 2)}% (yêu cầu ≤ 2.5%)")
                push(close > zone * 0.999,
                     f"Giá chưa đánh thủng hỗ trợ {_round(zone, close)}",
                     f"Giá {_round(close, close)} > {_round(zone, close)}")
            else:
                push(False, "Không tìm thấy vùng hỗ trợ bên dưới giá", "—")
                push(False, "Không có hỗ trợ để giữ giá", "—")
            touch = sup_touch
            tl = sup_tl
            tl_name = "hỗ trợ"

        push(touch >= 2,
             f"Trendline {tl_name} được tôn trọng ({touch} lần chạm)",
             f"{touch} lần chạm" + (f" · từ {tl['from'][:10]}" if tl else ""))

        trend_ok = e20 > e50
        pat_ok = any(p["bias"] == "BUY" for p in patterns)
        push(trend_ok or pat_ok,
             "Đồng thuận xu hướng tăng (EMA20 > EMA50) hoặc mẫu hình Đáy kép",
             f"EMA20 {'>' if trend_ok else '<'} EMA50"
             + (" · có Đáy kép" if pat_ok else "")
             + f" · RSI {round(rsi, 1)}")

        push(rsi < 72, "RSI chưa rơi vào vùng quá mua (còn dư địa tăng)",
             f"RSI {round(rsi, 1)} < 72")

    else:  # SELL
        # Ưu tiên mô hình phá vỡ & test lại nếu có hỗ trợ đã bị thủng nằm ngay trên giá
        if sup_above and (sup_above - close) / close <= 0.025:
            pattern = "Phá vỡ & test lại (Breakdown–Retest)"
            push(True,
                 f"Giá đã đánh thủng vùng hỗ trợ {_round(sup_above, close)}",
                 f"Giá {_round(close, close)} < hỗ trợ {_round(sup_above, close)}")
            push(True,
                 f"Giá quay về test lại vùng {_round(sup_above, close)} từ phía dưới (hỗ trợ cũ → kháng mới)",
                 f"Cách {round((sup_above - close) / close * 100, 2)}% (yêu cầu ≤ 2.5%)")
            touch = res_touch
            tl = res_tl
            tl_name = "kháng"
        else:
            pattern = "Phản ứng tại vùng kháng (Rejection)"
            zone = res_above
            if zone:
                d = (zone - close) / close * 100
                push(d <= 2.5,
                     f"Giá nằm sát vùng kháng {_round(zone, close)}",
                     f"Cách {round(d, 2)}% (yêu cầu ≤ 2.5%)")
                push(close < zone * 1.001,
                     f"Giá chưa vượt qua kháng {_round(zone, close)}",
                     f"Giá {_round(close, close)} < {_round(zone, close)}")
            else:
                push(False, "Không tìm thấy vùng kháng bên trên giá", "—")
                push(False, "Không có kháng để chặn giá", "—")
            touch = res_touch
            tl = res_tl
            tl_name = "kháng"

        push(touch >= 2,
             f"Trendline {tl_name} được tôn trọng ({touch} lần chạm)",
             f"{touch} lần chạm" + (f" · từ {tl['from'][:10]}" if tl else ""))

        trend_ok = e20 < e50
        pat_ok = any(p["bias"] == "SELL" for p in patterns)
        push(trend_ok or pat_ok,
             "Đồng thuận xu hướng giảm (EMA20 < EMA50) hoặc mẫu hình Đỉnh kép",
             f"EMA20 {'<' if trend_ok else '>'} EMA50"
             + (" · có Đỉnh kép" if pat_ok else "")
             + f" · RSI {round(rsi, 1)}")

        push(rsi > 28, "RSI chưa rơi vào vùng quá bán (còn dư địa giảm)",
             f"RSI {round(rsi, 1)} > 28")

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
def analyze_symbol(df: pd.DataFrame, symbol: str, interval: str, info: Optional[Dict] = None) -> Dict:
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

    def make(side: str, sl: float, tp: float, source: str, reasons: List[str]):
        cl, pattern = _build_checklist(
            side, close, sup_near, res_near, res_just_below, sup_just_above,
            sup_line, res_line, sup_touch, res_touch, e20, e50, rsi, patterns, atr,
        )
        s = _mk_setup(side, close, sl, tp, reasons, source, cl)
        if s:
            s["pattern"] = pattern
            setups.append(s)

    # ---- BUY: phản ứng tại hỗ trợ ----
    if sup_near and (close - sup_near) / close <= 0.03:
        sl = sup_near - atr * 0.75
        tp = close + max(atr * 3, (close - sl) * 2)
        make("BUY", sl, tp, "Vùng hỗ trợ", [
            f"Nằm trên hỗ trợ {_round(sup_near, close)} (cách {round((close - sup_near) / close * 100, 2)}%)",
            f"Trendline hỗ trợ bị chạm {sup_touch} lần",
            f"RSI {round(rsi, 1)} · ATR {_round(atr, close)}",
        ])

    # ---- BUY: phá kháng rồi test lại ----
    if res_just_below and (close - res_just_below) / close <= 0.025:
        sl = min(res_just_below - atr * 0.5, close - atr * 1.2)
        tp = close + max(atr * 3, (close - sl) * 2)
        make("BUY", sl, tp, "Phá kháng & test lại", [
            f"Kháng {_round(res_just_below, close)} vừa bị phá, nay thành hỗ trợ",
            f"Giá đang test lại từ phía trên (cách {round((close - res_just_below) / close * 100, 2)}%)",
            f"RSI {round(rsi, 1)} · ATR {_round(atr, close)}",
        ])

    # ---- BUY: thuận xu hướng EMA ----
    if e20 > e50 and close > e20:
        sl = min(close - atr * 1.5, float(df["low"].tail(10).min()))
        tp = close + atr * 3
        make("BUY", sl, tp, "Xu hướng tăng", [
            "EMA20 > EMA50 (xu hướng tăng)", "Giá đóng cửa trên EMA20",
            f"RSI {round(rsi, 1)} · ATR {_round(atr, close)}",
        ])

    # ---- SELL: phản ứng tại kháng ----
    if res_near and (res_near - close) / close <= 0.03:
        sl = res_near + atr * 0.75
        tp = close - max(atr * 3, (sl - close) * 2)
        make("SELL", sl, tp, "Vùng kháng", [
            f"Nằm dưới kháng {_round(res_near, close)} (cách {round((res_near - close) / close * 100, 2)}%)",
            f"Trendline kháng bị chạm {res_touch} lần",
            f"RSI {round(rsi, 1)} · ATR {_round(atr, close)}",
        ])

    # ---- SELL: thủng hỗ trợ rồi test lại ----
    if sup_just_above and (sup_just_above - close) / close <= 0.025:
        sl = max(sup_just_above + atr * 0.5, close + atr * 1.2)
        tp = close - max(atr * 3, (sl - close) * 2)
        make("SELL", sl, tp, "Thủng hỗ trợ & test lại", [
            f"Hỗ trợ {_round(sup_just_above, close)} vừa bị thủng, nay thành kháng",
            f"Giá đang test lại từ phía dưới (cách {round((sup_just_above - close) / close * 100, 2)}%)",
            f"RSI {round(rsi, 1)} · ATR {_round(atr, close)}",
        ])

    # ---- SELL: thuận xu hướng EMA ----
    if e20 < e50 and close < e20:
        sl = max(close + atr * 1.5, float(df["high"].tail(10).max()))
        tp = close - atr * 3
        make("SELL", sl, tp, "Xu hướng giảm", [
            "EMA20 < EMA50 (xu hướng giảm)", "Giá đóng cửa dưới EMA20",
            f"RSI {round(rsi, 1)} · ATR {_round(atr, close)}",
        ])

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

    # ---- Nến cho chart ----
    candles = [
        {"time": int(pd.Timestamp(ts).timestamp()),
         "open": round(float(r["open"]), 6), "high": round(float(r["high"]), 6),
         "low": round(float(r["low"]), 6), "close": round(float(r["close"]), 6)}
        for ts, r in df.iterrows()
    ]

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
