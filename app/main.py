from datetime import datetime, timezone

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .analyzer import analyze_symbol
from .data_fetcher import INFO_BY_TICKER, INTERVALS, SYMBOL_INFO, SYMBOLS, fetch_ohlcv, get_info
from .db import get_settings, init_db, save_settings
from .scheduler import run_full_scan, start_scheduler, stop_scheduler
from . import setup_state as st_mod
from .watchlist import scan_watchlist

app = FastAPI(title="Phân tích Kỹ thuật Tự động")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def _startup():
    init_db()
    start_scheduler()


@app.on_event("shutdown")
async def _shutdown():
    stop_scheduler()


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "settings": get_settings(),
            "symbol_info": SYMBOL_INFO,
            "categories": SYMBOLS,
            "intervals": INTERVALS,
        },
    )


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/symbols")
async def api_symbols():
    return {"symbols": SYMBOL_INFO, "categories": SYMBOLS,
            "intervals": {k: v.get("label", k) for k, v in INTERVALS.items()}}



# Các khung dùng cho phân tích đa khung (Bước 1) và CHoCH (Bước 5)
MTF_TFS = ["1d", "4h"]


def _gather_frames(symbol: str, interval: str) -> tuple:
    """Lấy dữ liệu đa khung cho Bước 1 và khung nhỏ hơn cho CHoCH (Bước 5).

    Trả về (tf_frames, df_lower). Lỗi ở khung nào thì bỏ qua khung đó,
    KHÔNG làm hỏng phân tích chính.
    """
    tf_frames = {}
    for tf in MTF_TFS:
        if tf == interval:
            continue
        try:
            d = fetch_ohlcv(symbol, interval=tf)
            if d is not None and not d.empty:
                tf_frames[tf] = d
        except Exception:
            pass

    df_lower = None
    lower_map = {"1h": "15m", "4h": "1h", "1d": "4h", "1wk": "1d"}
    low_tf = lower_map.get(interval)
    if low_tf and low_tf in INTERVALS:
        try:
            d = fetch_ohlcv(symbol, interval=low_tf)
            if d is not None and not d.empty:
                df_lower = d
        except Exception:
            pass

    return tf_frames, df_lower


@app.get("/api/scan")
async def api_scan(symbol: str = Query(...), interval: str = Query("1h"),
                   reset: bool = Query(False)):
    """Phân tích một mã.

    Có KHOÁ HƯỚNG: nếu mã đang có setup sống thì giữ nguyên hướng đó,
    không lật BUY/SELL mỗi lần refresh.

    reset=true -> xoá trạng thái, phân tích lại từ đầu.
    """
    if interval not in INTERVALS:
        raise HTTPException(status_code=400, detail=f"Khung thời gian không hợp lệ: {interval}")
    try:
        df = fetch_ohlcv(symbol, interval=interval)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Lỗi lấy dữ liệu: {e}")
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail=f"Không có dữ liệu cho {symbol} ({interval})")

    key = st_mod._key(symbol, interval)
    state = st_mod.load_state()
    if reset:
        state.pop(key, None)
        st_mod.save_state(state)

    locked = state.get(key)
    tf_frames, df_lower = _gather_frames(symbol, interval)
    result = analyze_symbol(df, symbol, interval, get_info(symbol), locked=locked,
                            tf_frames=tf_frames, df_lower=df_lower)

    # Cập nhật / tạo mới bản ghi trạng thái
    candles = result.get("candles") or []
    best = result["setups"][0] if result["setups"] else None
    lock = result.get("lock") or {}

    if lock.get("locked"):
        # Đang khoá -> chỉ cập nhật tiến trình, giữ nguyên record gốc
        rec = dict(locked) if locked else {}
        rec = st_mod.evaluate(rec, candles, interval) if rec else {}
        if rec:
            rec["blocked_signals"] = lock.get("blocked_signals", rec.get("blocked_signals", 0))
            state[key] = rec
            st_mod.save_state(state)
    elif lock.get("just_closed"):
        # Vừa đóng -> cho phép tạo chu kỳ mới nếu có setup
        if best:
            state[key] = _new_record(symbol, interval, best, result, candles)
        else:
            state.pop(key, None)
        st_mod.save_state(state)
    elif best:
        # Không có gì khoá -> tạo chu kỳ mới
        state[key] = _new_record(symbol, interval, best, result, candles)
        st_mod.save_state(state)

    return JSONResponse(result)


def _new_record(symbol: str, interval: str, best: dict, result: dict, candles: list) -> dict:
    """Tạo bản ghi chu kỳ mới từ setup tốt nhất."""
    opened_ts = candles[-1]["time"] if candles else int(datetime.now(tz=timezone.utc).timestamp())
    return {
        "symbol": symbol,
        "interval": interval,
        "side": best["type"],
        "entry": best["entry"],
        "sl": best["sl"],
        "tp1": best["tp"],
        "tp2": best.get("tp2"),
        "score": best["score"],
        "grade": best["grade"],
        "pattern": best.get("pattern"),
        "opened_time": opened_ts,
        "opened_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "state": "CHO",
        "bars_alive": 0,
        "blocked_signals": 0,
        "event": None,
    }


@app.get("/api/state")
async def api_state(symbol: str = Query(...), interval: str = Query("1h")):
    """Xem trạng thái chu kỳ hiện tại của một mã."""
    state = st_mod.load_state()
    rec = state.get(st_mod._key(symbol, interval))
    return JSONResponse(st_mod.describe(rec))


@app.get("/api/state-all")
async def api_state_all():
    """Xem toàn bộ chu kỳ đang lưu."""
    state = st_mod.load_state()
    return JSONResponse({
        k: st_mod.describe(v) for k, v in state.items()
    })


@app.get("/api/state-reset")
async def api_state_reset(symbol: str = Query(None), interval: str = Query(None)):
    """Xoá trạng thái chu kỳ (một mã hoặc toàn bộ)."""
    state = st_mod.load_state()
    if symbol:
        state.pop(st_mod._key(symbol, interval or "1h"), None)
    else:
        state = {}
    st_mod.save_state(state)
    return {"status": "ok", "remaining": len(state)}


@app.get("/api/scan-all")
async def api_scan_all(interval: str = Query("1h"), limit: int = Query(0)):
    if interval not in INTERVALS:
        raise HTTPException(status_code=400, detail=f"Khung thời gian không hợp lệ: {interval}")
    return JSONResponse(run_full_scan(interval=interval, limit=(limit or None)))


@app.get("/api/watchlist-scan")
async def api_watchlist_scan(interval: str = Query("1h"),
                             only_beautiful: bool = Query(True)):
    """Quét các mã trong watchlist và trả về những mã có SETUP ĐẸP."""
    s = get_settings()
    tickers = s.get("watchlist") or s.get("favorite_symbols") or []
    results = scan_watchlist(tickers, interval=interval, only_beautiful=only_beautiful)
    return JSONResponse({"interval": interval, "scanned": len(tickers), "results": results})


@app.get("/api/settings")
async def api_settings():
    return JSONResponse(get_settings())


@app.post("/api/settings")
async def api_save_settings(payload: dict = Body(...)):
    save_settings(payload)
    return {"status": "ok", "settings": get_settings()}


@app.get("/api/ticker-info")
async def api_ticker_info(symbol: str = Query(...)):
    return JSONResponse(get_info(symbol))
