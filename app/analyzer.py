"""
Phân tích kỹ thuật tự động:
- Swing highs/lows -> vùng Hỗ trợ / Kháng (cluster)
- Trendline hỗ trợ (nối đáy) & kháng (nối đỉnh) + đếm số lần chạm
- Mẫu hình Double Top / Double Bottom
- Setup chuẩn: Entry / SL / TP / R:R (từ vùng S/R và từ xu hướng EMA + ATR)
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ---------------------------------------------------------------- swing points
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


# ------------------------------------------------------------------- trendline
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
    return {
        "kind": kind,
        "x1": x1, "y1": float(p1[1]),
        "x2": x2, "y2": float(p2[1]),
        "from": str(p1[0]), "to": str(p2[0]),
    }


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


# --------------------------------------------------------------------- patterns
def detect_patterns(highs: List[Tuple], lows: List[Tuple], threshold: float = 0.006) -> List[Dict]:
    patterns: List[Dict] = []
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if abs(a[1] - b[1]) / max(a[1], 1e-9) <= threshold:
            mid = min(lows, key=lambda p: abs((b[0] - p[0]).total_seconds())) if lows else None
            patterns.append({
                "type": "Đỉnh kép (Double Top)",
                "bias": "SELL",
                "price": round((a[1] + b[1]) / 2, 5),
                "neckline": round(mid[1], 5) if mid else None,
                "points": [{"t": str(a[0]), "p": a[1]}, {"t": str(b[0]), "p": b[1]}],
            })
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if abs(a[1] - b[1]) / max(a[1], 1e-9) <= threshold:
            mid = min(highs, key=lambda p: abs((b[0] - p[0]).total_seconds())) if highs else None
            patterns.append({
                "type": "Đáy kép (Double Bottom)",
                "bias": "BUY",
                "price": round((a[1] + b[1]) / 2, 5),
                "neckline": round(mid[1], 5) if mid else None,
                "points": [{"t": str(a[0]), "p": a[1]}, {"t": str(b[0]), "p": b[1]}],
            })
    return patterns


# ----------------------------------------------------------------- indicators
def _atr(df: pd.DataFrame, n: int = 14) -> float:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    val = float(tr.rolling(n).mean().iloc[-1])
    return val if np.isfinite(val) and val > 0 else float((high - low).tail(n).mean())


def _round(price: float, ref: float) -> float:
    if ref >= 1000:
        return round(price, 2)
    if ref >= 10:
        return round(price, 3)
    if ref >= 1:
        return round(price, 4)
    return round(price, 5)


def _mk_setup(side: str, entry: float, sl: float, tp: float, reasons: List[str], source: str) -> Optional[Dict]:
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk <= 0 or reward <= 0:
        return None
    rr = reward / risk
    return {
        "type": side,
        "entry": _round(entry, entry),
        "sl": _round(sl, entry),
        "tp": _round(tp, entry),
        "rr": round(rr, 2),
        "confidence": "Cao" if rr >= 2.5 else ("Trung bình" if rr >= 1.8 else "Thấp"),
        "source": source,
        "reasons": reasons,
    }


# --------------------------------------------------------------------- analyze
def analyze_symbol(df: pd.DataFrame, symbol: str, interval: str) -> Dict:
    df = df.copy()
    close = float(df["close"].iloc[-1])
    atr = _atr(df)

    highs, lows = _swing_points(df, window=5)
    resistances = _cluster(highs)
    supports = _cluster(lows)

    sup_line = _fit_line(lows, "support")
    res_line = _fit_line(highs, "resistance")
    sup_touch, sup_list = _count_touches(df, sup_line)
    res_touch, res_list = _count_touches(df, res_line)
    patterns = detect_patterns(highs, lows)

    setups: List[Dict] = []

    # 1) Setup từ vùng hỗ trợ / kháng
    below = [s for s in supports if s < close]
    above = [r for r in resistances if r > close]

    if below:
        sup = max(below)
        dist = (close - sup) / close
        if dist <= 0.015:
            entry = close
            sl = sup - atr * 0.75
            tp = entry + max(atr * 3, (entry - sl) * 2)
            s = _mk_setup(
                "BUY", entry, sl, tp,
                [
                    f"Giá đang nằm trên vùng hỗ trợ {_round(sup, close)}",
                    f"Cách hỗ trợ {round(dist * 100, 2)}%",
                    f"Trendline hỗ trợ bị chạm {sup_touch} lần",
                ],
                "Vùng hỗ trợ",
            )
            if s:
                setups.append(s)

    if above:
        res = min(above)
        dist = (res - close) / close
        if dist <= 0.015:
            entry = close
            sl = res + atr * 0.75
            tp = entry - max(atr * 3, (sl - entry) * 2)
            s = _mk_setup(
                "SELL", entry, sl, tp,
                [
                    f"Giá đang nằm dưới vùng kháng {_round(res, close)}",
                    f"Cách kháng {round(dist * 100, 2)}%",
                    f"Trendline kháng bị chạm {res_touch} lần",
                ],
                "Vùng kháng",
            )
            if s:
                setups.append(s)

    # 2) Setup theo xu hướng EMA + ATR (luôn có để người dùng tham khảo)
    ema20 = df["close"].ewm(span=20, adjust=False).mean()
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    e20, e50 = float(ema20.iloc[-1]), float(ema50.iloc[-1])

    if e20 > e50 and close > e20:
        sl = min(close - atr * 1.5, float(df["low"].tail(10).min()))
        tp = close + atr * 3
        s = _mk_setup(
            "BUY", close, sl, tp,
            ["EMA20 > EMA50 (xu hướng tăng)", "Giá đóng cửa trên EMA20", f"ATR14 = {_round(atr, close)}"],
            "Xu hướng tăng",
        )
        if s:
            setups.append(s)
    elif e20 < e50 and close < e20:
        sl = max(close + atr * 1.5, float(df["high"].tail(10).max()))
        tp = close - atr * 3
        s = _mk_setup(
            "SELL", close, sl, tp,
            ["EMA20 < EMA50 (xu hướng giảm)", "Giá đóng cửa dưới EMA20", f"ATR14 = {_round(atr, close)}"],
            "Xu hướng giảm",
        )
        if s:
            setups.append(s)

    # Chỉ giữ MỘT hướng nhất quán (BUY hoặc SELL) để tránh tín hiệu mâu thuẫn.
    buys = [s for s in setups if s["type"] == "BUY"]
    sells = [s for s in setups if s["type"] == "SELL"]
    best_buy = max(buys, key=lambda x: x["rr"]) if buys else None
    best_sell = max(sells, key=lambda x: x["rr"]) if sells else None

    if best_buy and best_sell:
        chosen = "BUY" if best_buy["rr"] >= best_sell["rr"] else "SELL"
        setups = [s for s in setups if s["type"] == chosen]
    elif not best_buy and not best_sell and e20 != e50:
        chosen = "BUY" if e20 > e50 else "SELL"
        setups = [s for s in setups if s["type"] == chosen]

    # Ưu tiên setup chất lượng cao lên đầu, tối đa 3
    setups.sort(key=lambda x: x["rr"], reverse=True)
    setups = [s for s in setups if s["rr"] >= 1.2][:3]

    now_ts = int(datetime.now(tz=timezone.utc).timestamp())
    candles = []
    for ts, row in df.iterrows():
        candles.append({
            "time": int(pd.Timestamp(ts).timestamp()),
            "open": round(float(row["open"]), 6),
            "high": round(float(row["high"]), 6),
            "low": round(float(row["low"]), 6),
            "close": round(float(row["close"]), 6),
        })

    return {
        "symbol": symbol,
        "interval": interval,
        "current_price": _round(close, close),
        "atr": _round(atr, close),
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
        "candles": candles,
        "time": now_ts,
    }


def _serialize_line(line: Optional[Dict]) -> Optional[Dict]:
    if not line:
        return None
    # Kéo dài trendline về tương lai ~ 30 nến để người dùng thấy hướng đi
    x1, x2, y1, y2 = line["x1"], line["x2"], line["y1"], line["y2"]
    span = x2 - x1
    x_end = x2 + span * 0.35
    y_end = y2 + (y2 - y1) * 0.35
    return {
        "kind": line["kind"],
        "from": line["from"],
        "to": line["to"],
        "y1": _round(y1, y1),
        "y2": _round(y2, y2),
        "x1_ts": int(pd.Timestamp(x1).timestamp()),
        "x2_ts": int(pd.Timestamp(x_end).timestamp()),
        "y_end": _round(y_end, y1),
        "slope_pct": round((y_end - y1) / max(abs(y1), 1e-9) * 100, 2),
    }