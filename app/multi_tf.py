"""
BƯỚC 1 — Xác định xu hướng DẪN DỤ đa khung (1D → 4H → 1H).

Theo tài liệu "Phân tích Thanh khoản & Market Maker":
    "Dùng cấu trúc đỉnh-đáy, EMA50/200 hoặc Kijun H1/H4 để biết MM đang
     điều phối sóng theo hướng nào nhằm dụ đám đông."

Nguyên tắc: khung lớn là XU HƯỚNG CHỦ, khung nhỏ là ĐIỂM VÀO.
Nếu khung nhỏ ngược khung lớn -> đó thường là nhịp DỤ (dẫn dụ), rủi ro cao.

Module này KHÔNG fetch dữ liệu — nhận vào DataFrame đã có.
"""
from typing import Dict, List, Optional, Tuple

import pandas as pd


# Khung thời gian dùng cho phân tích đa khung, từ lớn -> nhỏ
MTF_ORDER = ["1wk", "1d", "4h"]


def _ema(series: pd.Series, span: int) -> float:
    return float(series.ewm(span=span, adjust=False).mean().iloc[-1])


def _swing_structure(df: pd.DataFrame, window: int = 5) -> Tuple[str, Dict]:
    """Đọc cấu trúc đỉnh-đáy: HH/HL (tăng) hay LH/LL (giảm).

    Trả về ("TANG" | "GIAM" | "NGANG", chi tiết)
    """
    highs: List[Tuple] = []
    lows: List[Tuple] = []
    for i in range(window, len(df) - window):
        h = df["high"].iloc[i - window: i + window + 1]
        l = df["low"].iloc[i - window: i + window + 1]
        if df["high"].iloc[i] >= h.max():
            highs.append(float(df["high"].iloc[i]))
        if df["low"].iloc[i] <= l.min():
            lows.append(float(df["low"].iloc[i]))

    detail = {"n_highs": len(highs), "n_lows": len(lows)}
    if len(highs) < 2 or len(lows) < 2:
        return "NGANG", detail

    hh = highs[-1] > highs[-2]      # Higher High
    hl = lows[-1] > lows[-2]        # Higher Low
    lh = highs[-1] < highs[-2]      # Lower High
    ll = lows[-1] < lows[-2]        # Lower Low

    detail.update({"HH": hh, "HL": hl, "LH": lh, "LL": ll,
                   "last_high": round(highs[-1], 6), "last_low": round(lows[-1], 6)})

    if hh and hl:
        return "TANG", detail
    if lh and ll:
        return "GIAM", detail
    # Trường hợp lẫn lộn -> dùng EMA để phá vỡ thế cân bằng
    e50 = _ema(df["close"], 50)
    e200_span = min(200, max(50, len(df) // 2))
    e200 = _ema(df["close"], e200_span)
    if e50 > e200:
        return "TANG", detail
    if e50 < e200:
        return "GIAM", detail
    return "NGANG", detail


def analyze_one(df: pd.DataFrame, label: str) -> Dict:
    """Phân tích xu hướng một khung."""
    if df is None or df.empty or len(df) < 30:
        return {"tf": label, "trend": "KHONG_DU_DU_LIEU", "strength": 0,
                "ema50": None, "ema200": None, "close": None, "detail": {}}

    close = float(df["close"].iloc[-1])
    e50 = _ema(df["close"], 50)
    e200_span = min(200, max(50, len(df) // 2))
    e200 = _ema(df["close"], e200_span)
    struct, detail = _swing_structure(df)

    # Điểm mạnh xu hướng 0-100
    strength = 0
    if struct == "TANG":
        strength += 40
    elif struct == "GIAM":
        strength += 40
    if e50 > e200:
        strength += 30
    elif e50 < e200:
        strength += 30
    if struct == "TANG" and close > e50:
        strength += 30
    elif struct == "GIAM" and close < e50:
        strength += 30
    strength = min(100, strength)

    return {
        "tf": label,
        "trend": struct,
        "strength": strength,
        "close": round(close, 6),
        "ema50": round(e50, 6),
        "ema200": round(e200, 6),
        "detail": detail,
    }


def combine(frames: Dict[str, Optional[pd.DataFrame]]) -> Dict:
    """Tổng hợp xu hướng nhiều khung.

    frames: {"1d": df, "4h": df, ...} — khung nào không có thì bỏ qua.
    """
    rows = []
    for tf in MTF_ORDER:
        if tf in frames and frames[tf] is not None:
            rows.append(analyze_one(frames[tf], tf))

    if not rows:
        return {"available": False, "frames": [], "alignment": "KHONG_CO",
                "bias": None, "note": "Không lấy được dữ liệu đa khung."}

    trends = [r["trend"] for r in rows if r["trend"] in ("TANG", "GIAM")]
    if not trends:
        return {"available": True, "frames": rows, "alignment": "NGANG",
                "bias": None, "note": "Các khung lớn đều đi ngang — chưa có xu hướng rõ."}

    # --- Đồng thuận ---
    up = sum(1 for t in trends if t == "TANG")
    down = sum(1 for t in trends if t == "GIAM")

    if up == len(trends):
        alignment, bias = "DONG_THUAN_TANG", "BUY"
        note = f"Cả {len(trends)} khung lớn đều TĂNG — xu hướng dẫn dụ là tăng."
    elif down == len(trends):
        alignment, bias = "DONG_THUAN_GIAM", "SELL"
        note = f"Cả {len(trends)} khung lớn đều GIẢM — xu hướng dẫn dụ là giảm."
    elif up > down:
        alignment, bias = "LECH_TANG", "BUY"
        note = (f"{up}/{len(trends)} khung TĂNG — xu hướng chủ yếu tăng nhưng có "
                f"khung ngược. Cẩn thận nhịp dụ.")
    elif down > up:
        alignment, bias = "LECH_GIAM", "SELL"
        note = (f"{down}/{len(trends)} khung GIẢM — xu hướng chủ yếu giảm nhưng có "
                f"khung ngược. Cẩn thận nhịp dụ.")
    else:
        alignment, bias = "MAU_THUAN", None
        note = "Các khung MÂU THUẪN nhau — rất dễ bị dẫn dụ. Nên đứng ngoài."

    return {"available": True, "frames": rows, "alignment": alignment,
            "bias": bias, "note": note}


def check_conflict(mtf: Dict, setup_side: str) -> Dict:
    """Kiểm tra setup có NGƯỢC xu hướng khung lớn không.

    Đây chính là phần "tránh nhịp dẫn dụ" của Bước 1.
    """
    if not mtf or not mtf.get("available"):
        return {"status": "UNKNOWN", "penalty": 0, "note": "Không kiểm tra được đa khung."}

    bias = mtf.get("bias")
    if bias is None:
        return {"status": "NEUTRAL", "penalty": 8,
                "note": "Các khung mâu thuẫn — không rõ MM dẫn dụ hướng nào. Giảm điểm."}

    if bias == setup_side:
        strong = mtf.get("alignment", "").startswith("DONG_THUAN")
        return {"status": "THUAN", "penalty": 0,
                "note": ("Setup THUẬN xu hướng cả 3 khung — đúng hướng MM."
                         if strong else
                         "Setup thuận xu hướng chủ (có khung ngược nhẹ).")}

    return {"status": "NGUOC", "penalty": 25,
            "note": (f"⚠️ Setup NGƯỢC xu hướng khung lớn ({mtf.get('alignment')}). "
                     f"Đây có thể là nhịp DỤ của MM — rủi ro cao.")}
