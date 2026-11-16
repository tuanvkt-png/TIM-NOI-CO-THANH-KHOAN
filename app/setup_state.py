"""
Quản lý CHU KỲ SETUP — trái tim của cơ chế "khoá hướng" (hysteresis).

VẤN ĐỀ CẦN GIẢI QUYẾT
---------------------
Bản V4 tính lại setup từ đầu mỗi lần quét. Vì vậy chỉ cần giá nhích 0.2–0.3%
là hướng có thể lật BUY ↔ SELL liên tục (đo thực tế: 4 lần đảo hướng / 13 nến).
Điều này SAI về mặt logic Market Maker: một chu kỳ MM cần nhiều nến để hấp thụ
lệnh đám đông rồi đẩy giá quét SL ở các đỉnh/đáy thanh khoản — trong suốt giai
đoạn đó hướng KHÔNG được lật.

GIẢI PHÁP
---------
Một setup khi đã được xác nhận sẽ được LƯU LẠI và giữ hướng cho tới khi xảy ra
một trong ba sự kiện ĐÓNG (chỉ khi đó mới phân tích lại):

    ĐÓNG khi giá đóng cửa THỦNG SL      -> setup sai, huỷ
    ĐÓNG khi giá CHẠM TP1               -> MM đã quét xong vùng thanh khoản
    ĐÓNG khi quá số nến hết hạn         -> cơ hội đã trôi qua

TRẠNG THÁI CHU KỲ
-----------------
    CHO          : vừa tạo, giá chưa tới Entry
    DA_KICH_HOAT : giá đã chạm Entry, đang chạy
    DA_CHAM_TP   : đã chạm TP1 -> chờ chu kỳ mới
    THUNG_SL     : đã thủng SL -> chờ chu kỳ mới
    HET_HAN      : quá số nến mà chưa kích hoạt
"""
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

STATE_FILE = "setup_state.json"

# Số nến tối đa một setup được phép "sống" nếu giá chưa kích hoạt
DEFAULT_EXPIRY_BARS = 20

# Giá phải vượt Entry bao nhiêu % mới coi là "đã kích hoạt"
ENTRY_TRIGGER_PCT = 0.0015   # 0.15%

# Trạng thái kết thúc — không khoá hướng nữa
CLOSED_STATES = {"DA_CHAM_TP", "THUNG_SL", "HET_HAN"}

STATE_LABEL = {
    "CHO": "⏳ Đang chờ giá tới Entry",
    "DA_KICH_HOAT": "🟢 Đã kích hoạt — đang chạy",
    "DA_CHAM_TP": "✅ Đã chạm mục tiêu — chờ chu kỳ mới",
    "THUNG_SL": "❌ Đã thủng SL — chờ chu kỳ mới",
    "HET_HAN": "⌛ Hết hạn — chờ chu kỳ mới",
}


def _key(symbol: str, interval: str) -> str:
    return f"{symbol}|{interval}"


def load_state() -> Dict:
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_state(state: Dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[state] Không ghi được {STATE_FILE}: {e}")


INTERVAL_SECONDS = {
    "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400, "1wk": 604800,
}


def _bars_since(candles: List[Dict], opened_time: int, interval: str) -> int:
    """Số nến đã trôi qua kể từ mốc opened_time (tính cả nến đang chạy).

    Dùng phép chia thời gian thay vì đếm, để không phụ thuộc số nến
    thực tế có trong cửa sổ dữ liệu.
    """
    if not opened_time:
        return 0
    sec = INTERVAL_SECONDS.get(interval, 3600)
    now_ts = candles[-1]["time"] if candles else opened_time
    diff = int((now_ts - opened_time) // sec)
    return max(0, diff)


def _high_since(candles: List[Dict], opened_time: int) -> Optional[float]:
    hs = [c["high"] for c in candles if c["time"] > opened_time]
    return max(hs) if hs else None


def _low_since(candles: List[Dict], opened_time: int) -> Optional[float]:
    ls = [c["low"] for c in candles if c["time"] > opened_time]
    return min(ls) if ls else None


def _last_close(candles: List[Dict]) -> Optional[float]:
    return candles[-1]["close"] if candles else None


def evaluate(record: Dict, candles: List[Dict], interval: str,
             expiry_bars: int = DEFAULT_EXPIRY_BARS) -> Dict:
    """Cập nhật trạng thái của một setup đang sống dựa trên dữ liệu nến mới.

    Trả về record đã cập nhật (có thêm: state, bars_alive, blocked_signals,
    event, event_time).
    """
    rec = dict(record)
    opened = rec.get("opened_time") or 0
    side = rec.get("side")
    entry = rec.get("entry")
    sl = rec.get("sl")
    tp1 = rec.get("tp1")

    rec.setdefault("blocked_signals", 0)
    rec.setdefault("state", "CHO")
    rec.setdefault("event", None)

    if not candles:
        return rec

    rec["bars_alive"] = _bars_since(candles, opened, interval)
    # Dung toan bo nen (ke ca nen mo setup) de bat TP/SL ngay trong nen dau
    hi = _high_since(candles, opened)
    lo = _low_since(candles, opened)
    if hi is None:   # truong hop opened == nen cuoi
        hi = candles[-1]["high"]
    if lo is None:
        lo = candles[-1]["low"]
    last_close = _last_close(candles)

    # --- Nếu đã ở trạng thái kết thúc thì giữ nguyên ---
    if rec["state"] in CLOSED_STATES:
        return rec

    # 1) Kiểm tra THỦNG SL
    if sl and last_close is not None:
        if side == "BUY" and last_close <= float(sl):
            rec["state"] = "THUNG_SL"
            rec["event"] = f"Giá đóng cửa {last_close} thủng SL {sl}"
            rec["event_time"] = candles[-1]["time"]
            rec["blocked_signals"] = 0
            return rec
        if side == "SELL" and last_close >= float(sl):
            rec["state"] = "THUNG_SL"
            rec["event"] = f"Giá đóng cửa {last_close} vượt SL {sl}"
            rec["event_time"] = candles[-1]["time"]
            rec["blocked_signals"] = 0
            return rec

    # 2) Kiểm tra CHẠM TP1
    if tp1:
        if side == "BUY" and hi is not None and hi >= float(tp1):
            rec["state"] = "DA_CHAM_TP"
            rec["event"] = f"Giá đã chạm TP1 {tp1}"
            rec["event_time"] = candles[-1]["time"]
            rec["blocked_signals"] = 0
            return rec
        if side == "SELL" and lo is not None and lo <= float(tp1):
            rec["state"] = "DA_CHAM_TP"
            rec["event"] = f"Giá đã chạm TP1 {tp1}"
            rec["event_time"] = candles[-1]["time"]
            rec["blocked_signals"] = 0
            return rec

    # 3) Cập nhật trạng thái kích hoạt
    if rec["state"] == "CHO" and entry:
        e = float(entry)
        if last_close is not None:
            reached = False
            if side == "BUY" and last_close >= e * (1 - ENTRY_TRIGGER_PCT):
                reached = True
            if side == "SELL" and last_close <= e * (1 + ENTRY_TRIGGER_PCT):
                reached = True
            if reached:
                rec["state"] = "DA_KICH_HOAT"

    # 4) Kiểm tra HẾT HẠN
    if rec["state"] == "CHO" and rec.get("bars_alive", 0) >= expiry_bars:
        rec["state"] = "HET_HAN"
        rec["event"] = f"Quá {expiry_bars} nến chưa kích hoạt"
        rec["event_time"] = candles[-1]["time"]
        rec["blocked_signals"] = 0

    return rec


def is_locked(record: Optional[Dict]) -> bool:
    """Setup còn khoá hướng không?"""
    if not record:
        return False
    return record.get("state") not in CLOSED_STATES


def describe(record: Optional[Dict]) -> Dict:
    """Thông tin hiển thị cho người dùng."""
    if not record:
        return {"locked": False}
    st = record.get("state", "CHO")
    return {
        "locked": st not in CLOSED_STATES,
        "state": st,
        "state_label": STATE_LABEL.get(st, st),
        "side": record.get("side"),
        "entry": record.get("entry"),
        "sl": record.get("sl"),
        "tp1": record.get("tp1"),
        "tp2": record.get("tp2"),
        "score": record.get("score"),
        "opened_at": record.get("opened_at"),
        "bars_alive": record.get("bars_alive", 0),
        "blocked_signals": record.get("blocked_signals", 0),
        "event": record.get("event"),
        "pattern": record.get("pattern"),
    }
