"""
BƯỚC 5 & 6 — Đọc THANH KHOẢN & ORDER FLOW, xác định VỊ TRÍ CỦA MM.

Tài liệu "Phân tích Thanh khoản & Market Maker" — Phần 5 & 6:
    Bước 5: "Quan sát dấu hiệu hấp thụ, quét SL và chuyển dịch dòng lệnh
             tại đúng điểm chạm lần 3 (Tick Volume / Real Volume /
             M5–M15 CHoCH / Kijun)."
    Bước 6: "Đám đông 90% SELL ở TH1 -> MM ở phía BUY. Đám đông 90% BUY ở
             TH2 -> MM ở phía SELL."

GIỚI HẠN DỮ LIỆU (Yahoo Finance free)
-------------------------------------
Có     : OHLCV (volume tổng hợp) — đủ để phát hiện hấp thụ & quét SL
Có     : nhiều khung thời gian — đủ để đọc CHoCH trên khung nhỏ
KHÔNG có: Level-2 / bid-ask / delta thật -> không làm được footprint

Vì vậy module này dùng 3 chỉ báo THAY THẾ đáng tin:
    1. VOLUME SPIKE + CLIMAX  -> phát hiện hấp thụ / quét SL
    2. KIJUN (Ichimoku)       -> xác nhận xu hướng, điểm cân bằng
    3. CHoCH (Change of Character) -> đổi cấu trúc trên khung nhỏ
"""
from typing import Dict, List, Optional, Tuple

import pandas as pd


# ------------------------------------------------------------------ volume
def _last_closed_index(vol: pd.Series) -> int:
    """Tìm nến ĐÃ ĐÓNG gần nhất.

    Yahoo trả volume = 0 cho nến đang chạy (chưa đóng cửa), nên phải lùi
    lại để lấy nến có volume thật. Nếu tất cả đều 0 -> trả về cuối.
    """
    for i in range(len(vol) - 1, max(-1, len(vol) - 8), -1):
        if float(vol.iloc[i]) > 0:
            return i
    return len(vol) - 1


def volume_profile(df: pd.DataFrame, lookback: int = 20) -> Dict:
    """So sánh volume nến ĐÃ ĐÓNG gần nhất với trung bình `lookback` nến."""
    if df is None or df.empty or "volume" not in df.columns:
        return {"available": False, "reason": "Không có cột volume"}

    vol = df["volume"].astype(float)
    # Bỏ các nến volume = 0 ở đầu (Yahoo để trống) để trung bình không bị kéo xuống
    nz = vol[vol > 0]
    if len(nz) < 5:
        return {"available": False,
                "reason": "Mã này không có dữ liệu volume (vd: Forex spot)"}

    idx = _last_closed_index(vol)
    # Trung bình trên các nến có volume thật, không tính nến 0
    window = vol.iloc[max(0, idx - lookback + 1): idx + 1]
    window = window[window > 0]
    if len(window) == 0:
        return {"available": False, "reason": "Không có nến nào có volume"}

    avg = float(window.mean())
    cur = float(vol.iloc[idx])
    prev = float(vol.iloc[idx - 1]) if idx >= 1 else cur
    ratio = cur / avg if avg > 0 else 0.0

    o = float(df["open"].iloc[idx]); c = float(df["close"].iloc[idx])
    h = float(df["high"].iloc[idx]); l = float(df["low"].iloc[idx])
    rng = h - l
    body = abs(c - o)
    body_ratio = body / rng if rng > 0 else 0
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    return {
        "available": True,
        "avg": round(avg, 2),
        "current": round(cur, 2),
        "ratio": round(ratio, 2),
        "prev": round(prev, 2),
        "body_ratio": round(body_ratio, 3),
        "range": round(rng, 6),
        "upper_wick": round(upper_wick, 6),
        "lower_wick": round(lower_wick, 6),
        "is_spike": ratio >= 1.8,          # volume đột biến
        "is_climax": ratio >= 2.5,          # volume cực đại (thường là đỉnh/đáy)
        "is_dry": ratio <= 0.5,             # volume cạn (thiếu lực)
        "bar_index": idx,
        "bars_ago": len(vol) - 1 - idx,
    }


def detect_volume_signals(df: pd.DataFrame, side: str) -> Dict:
    """Phát hiện HẤP THỤ và QUÉT SL từ hành vi volume + nến.

    HẤP THỤ (Absorption): volume LỚN nhưng giá đi RẤT ÍT
        -> có lực đối ứng hấp thụ hết lệnh đám đông => MM đang đứng đó.
    QUÉT SL (Stop Hunt): volume đột biến + RÂU DÀI một phía + giá quay lại
        -> giá chọc qua vùng SL rồi bị đẩy ngược => MM vừa quét xong.
    """
    vp = volume_profile(df)
    if not vp.get("available"):
        return {"available": False, "signals": [], "score_bonus": 0,
                "note": "Không có dữ liệu volume cho mã này."}

    signals: List[Dict] = []
    bonus = 0

    # ---- Hấp thụ ----
    if vp["is_spike"] and vp["body_ratio"] < 0.45:
        signals.append({
            "kind": "HAP_THU",
            "label": "🔄 Hấp thụ (Absorption)",
            "detail": (f"Volume gấp {vp['ratio']}× trung bình nhưng thân nến chỉ "
                       f"{round(vp['body_ratio']*100)}% biên độ — có lực hấp thụ lớn."),
            "strong": vp["is_climax"],
        })
        bonus += 12 if vp["is_climax"] else 8

    # ---- Quét SL phía dưới (râu dưới dài) -> thuận BUY ----
    if vp["range"] > 0:
        wick_frac_low = vp["lower_wick"] / vp["range"]
        wick_frac_up = vp["upper_wick"] / vp["range"]
    else:
        wick_frac_low = wick_frac_up = 0.0

    if vp["is_spike"] and wick_frac_low >= 0.55:
        kind_ok = side == "BUY"
        signals.append({
            "kind": "QUET_SL_DUOI",
            "label": "🎯 Quét SL phía dưới (Stop Hunt)",
            "detail": (f"Râu dưới chiếm {round(wick_frac_low*100)}% biên độ với volume "
                       f"{vp['ratio']}× — MM vừa quét SL phe BUY rồi đẩy giá lên."),
            "supports": "BUY",
            "aligns": kind_ok,
        })
        bonus += 15 if kind_ok else -10

    if vp["is_spike"] and wick_frac_up >= 0.55:
        kind_ok = side == "SELL"
        signals.append({
            "kind": "QUET_SL_TREN",
            "label": "🎯 Quét SL phía trên (Stop Hunt)",
            "detail": (f"Râu trên chiếm {round(wick_frac_up*100)}% biên độ với volume "
                       f"{vp['ratio']}× — MM vừa quét SL phe SELL rồi đẩy giá xuống."),
            "supports": "SELL",
            "aligns": kind_ok,
        })
        bonus += 15 if kind_ok else -10

    # ---- Volume cạn ----
    if vp["is_dry"]:
        signals.append({
            "kind": "VOL_CAN",
            "label": "💤 Volume cạn",
            "detail": (f"Volume chỉ {vp['ratio']}× trung bình — thiếu lực xác nhận, "
                       f"dễ nhiễu."),
            "aligns": False,
        })
        bonus -= 8

    note = "Có tín hiệu dòng tiền xác nhận." if bonus > 0 else \
           ("Volume cạn — KHÔNG có xác nhận dòng tiền." if bonus < 0 else
            "Volume bình thường — chưa có dấu hiệu MM rõ ràng.")

    return {"available": True, "profile": vp, "signals": signals,
            "score_bonus": bonus, "note": note,
            "ratio": vp.get("ratio"), "current": vp.get("current"),
            "avg": vp.get("avg"), "is_spike": vp.get("is_spike"),
            "is_climax": vp.get("is_climax"), "is_dry": vp.get("is_dry")}


# ------------------------------------------------------------------- kijun
def kijun_sen(df: pd.DataFrame, period: int = 26) -> Optional[float]:
    """Kijun-sen (đường cơ sở Ichimoku) = (High + Low)/2 của `period` nến."""
    if df is None or len(df) < period:
        return None
    hi = float(df["high"].tail(period).max())
    lo = float(df["low"].tail(period).min())
    return round((hi + lo) / 2, 6)


def tenkan_sen(df: pd.DataFrame, period: int = 9) -> Optional[float]:
    if df is None or len(df) < period:
        return None
    hi = float(df["high"].tail(period).max())
    lo = float(df["low"].tail(period).min())
    return round((hi + lo) / 2, 6)


def kijun_status(df: pd.DataFrame, side: str, period: int = 26) -> Dict:
    """Kiểm tra giá đóng cửa so với Kijun — Bước 7 yêu cầu
    'nến H1 đóng vượt Kijun' để xác nhận.
    """
    kj = kijun_sen(df, period)
    if kj is None:
        return {"available": False}
    close = float(df["close"].iloc[-1])
    above = close > kj
    aligns = (side == "BUY" and above) or (side == "SELL" and not above)
    return {
        "available": True,
        "kijun": kj,
        "close": round(close, 6),
        "above": above,
        "aligns": aligns,
        "detail": (f"Giá {'trên' if above else 'dưới'} Kijun {kj} "
                   f"({'thuận' if aligns else 'NGƯỢC'} hướng {side})"),
    }


# -------------------------------------------------------------------- choch
def detect_choch(df: pd.DataFrame, window: int = 3) -> Dict:
    """Phát hiện CHoCH (Change of Character) — đổi cấu trúc thị trường.

    CHoCH TĂNG : giá vừa phá ĐỈNH gần nhất sau chuỗi đáy thấp dần
    CHoCH GIẢM : giá vừa phá ĐÁY gần nhất sau chuỗi đỉnh cao dần
    """
    if df is None or len(df) < window * 4:
        return {"available": False}

    highs: List[float] = []
    lows: List[float] = []
    for i in range(window, len(df) - window):
        h = df["high"].iloc[i - window: i + window + 1]
        l = df["low"].iloc[i - window: i + window + 1]
        if df["high"].iloc[i] >= h.max():
            highs.append(float(df["high"].iloc[i]))
        if df["low"].iloc[i] <= l.min():
            lows.append(float(df["low"].iloc[i]))

    if len(highs) < 2 or len(lows) < 2:
        return {"available": False}

    close = float(df["close"].iloc[-1])
    last_high = highs[-1]
    last_low = lows[-1]

    if close > last_high:
        return {"available": True, "type": "CHoCH_TANG", "bias": "BUY",
                "level": round(last_high, 6),
                "detail": f"Giá đóng cửa {close} phá đỉnh gần nhất {round(last_high,6)} — đổi cấu trúc TĂNG."}
    if close < last_low:
        return {"available": True, "type": "CHoCH_GIAM", "bias": "SELL",
                "level": round(last_low, 6),
                "detail": f"Giá đóng cửa {close} phá đáy gần nhất {round(last_low,6)} — đổi cấu trúc GIẢM."}

    return {"available": True, "type": "KHONG", "bias": None,
            "detail": "Chưa có CHoCH — cấu trúc chưa đổi."}


# ---------------------------------------------------------------- position
def crowd_position(df: pd.DataFrame, side: str, level: Optional[float],
                   atr: float) -> Dict:
    """BƯỚC 6 — Ước lượng VỊ TRÍ CỦA MM so với đám đông.

    Logic suy luận (không cần dữ liệu Level-2):
      • Giá vừa phá một vùng S/R và đi tiếp -> đám đông lao theo hướng phá
      • Volume lớn ở vùng phá + giá chững lại -> MM hấp thụ, đứng ngược đám đông
      • MM luôn ở phía ĐỐI DIỆN đám đông
    """
    vp = volume_profile(df)
    close = float(df["close"].iloc[-1])
    agree = 0
    notes: List[str] = []

    # Yếu tố 1: giá so với vùng vừa phá
    if level:
        if side == "BUY" and close > level:
            agree += 1
            notes.append(f"Giá đã vượt vùng {round(level,6)} — đám đông SELL đang bị kẹt.")
        elif side == "SELL" and close < level:
            agree += 1
            notes.append(f"Giá đã thủng vùng {round(level,6)} — đám đông BUY đang bị kẹt.")

    # Yếu tố 2: volume xác nhận
    if vp.get("available"):
        if vp["is_spike"]:
            agree += 1
            notes.append(f"Volume {vp['ratio']}× trung bình — dòng lệnh lớn đang dịch chuyển.")
        if vp["is_dry"]:
            agree -= 1
            notes.append("Volume cạn — đám đông chưa tham gia, chưa có gì để hấp thụ.")

    # Kết luận
    if agree >= 2:
        conf = "CAO"
        verdict = f"MM nhiều khả năng đang ở phía {side} (ngược đám đông)."
    elif agree == 1:
        conf = "TRUNG_BINH"
        verdict = f"Có dấu hiệu MM đứng phía {side}, nhưng chưa đủ xác nhận."
    else:
        conf = "THAP"
        verdict = "Chưa đủ dữ kiện để xác định vị trí MM — nên đứng ngoài chờ."

    crowd_side = "SELL" if side == "BUY" else "BUY"
    return {
        "available": vp.get("available", False),
        "confidence": conf,
        "verdict": verdict,
        "crowd_side": crowd_side,
        "mm_side": side if agree >= 1 else None,
        "notes": notes,
    }


# --------------------------------------------------------------- aggregate
def orderflow_report(df_main: pd.DataFrame, df_lower: Optional[pd.DataFrame],
                     side: str, level: Optional[float], atr: float) -> Dict:
    """Tổng hợp toàn bộ Bước 5 + 6 cho một setup."""
    vol = detect_volume_signals(df_main, side)
    kj = kijun_status(df_main, side)
    kj4 = kijun_status(df_lower, side) if df_lower is not None else {"available": False}
    choch = detect_choch(df_lower if df_lower is not None else df_main)
    pos = crowd_position(df_main, side, level, atr)

    # Điểm thưởng/phạt tổng hợp
    bonus = vol.get("score_bonus", 0)
    if kj.get("available"):
        bonus += 8 if kj["aligns"] else -10
    if choch.get("available") and choch.get("bias"):
        bonus += 10 if choch["bias"] == side else -8
    elif choch.get("available") and choch.get("bias") is None:
        bonus -= 5

    confirmed = (
        (vol.get("score_bonus", 0) > 0)
        and (kj.get("aligns") is True)
        and (choch.get("bias") == side)
    )

    return {
        "available": vol.get("available") or kj.get("available"),
        "volume": vol,
        "kijun": kj,
        "kijun_lower": kj4,
        "choch": choch,
        "position": pos,
        "score_bonus": int(max(-35, min(35, bonus))),
        "confirmed": confirmed,
        "verdict": ("✅ ĐỦ XÁC NHẬN dòng tiền" if confirmed else
                    "⚠️ CHƯA đủ xác nhận dòng tiền"),
    }
