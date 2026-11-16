from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .analyzer import analyze_symbol
from .data_fetcher import INFO_BY_TICKER, INTERVALS, SYMBOL_INFO, SYMBOLS, fetch_ohlcv, get_info
from .db import get_settings, init_db, save_settings
from .scheduler import run_full_scan, start_scheduler, stop_scheduler
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


@app.get("/api/scan")
async def api_scan(symbol: str = Query(...), interval: str = Query("1h")):
    if interval not in INTERVALS:
        raise HTTPException(status_code=400, detail=f"Khung thời gian không hợp lệ: {interval}")
    try:
        df = fetch_ohlcv(symbol, interval=interval)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Lỗi lấy dữ liệu: {e}")
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail=f"Không có dữ liệu cho {symbol} ({interval})")
    return JSONResponse(analyze_symbol(df, symbol, interval, get_info(symbol)))


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
