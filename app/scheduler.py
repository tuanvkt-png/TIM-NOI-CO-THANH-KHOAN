import json
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from .analyzer import analyze_symbol
from .data_fetcher import SYMBOLS, fetch_ohlcv, get_info

scheduler = BackgroundScheduler(timezone="UTC")
RESULTS_FILE = "scan_results.json"


def _all_symbols():
    out = []
    for syms in SYMBOLS.values():
        out.extend(syms)
    return out


def run_full_scan(interval: str = "1h", limit: int | None = None) -> dict:
    results = {}
    symbols = _all_symbols()
    if limit:
        symbols = symbols[:limit]
    for symbol in symbols:
        try:
            df = fetch_ohlcv(symbol, interval=interval)
            if df is None or df.empty:
                results[symbol] = {"error": "Không có dữ liệu"}
                continue
            a = analyze_symbol(df, symbol, interval, get_info(symbol))
            results[symbol] = {
                "symbol": symbol,
                "name": a["name"],
                "cat": a["cat"],
                "sub": a["sub"],
                "interval": interval,
                "current_price": a["current_price"],
                "setups": a["setups"],
                "patterns": a["patterns"],
                "supports": a["supports"],
                "resistances": a["resistances"],
                "score": a["score"],
                "grade": a["grade"],
                "direction": a["direction"],
            }
        except Exception as e:
            results[symbol] = {"error": str(e)}
    return results


def _job_scan():
    try:
        results = run_full_scan("1h")
        with open(RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump({"time": datetime.utcnow().isoformat(), "results": results},
                      f, ensure_ascii=False, default=str, indent=2)
        print(f"[scheduler] Đã quét {len(results)} mã lúc {datetime.now().isoformat()}")
    except Exception as e:
        print(f"[scheduler] Lỗi quét: {e}")


def start_scheduler():
    if scheduler.running:
        return
    scheduler.add_job(_job_scan, "interval", hours=6, id="auto_scan",
                      replace_existing=True, max_instances=1, coalesce=True)
    scheduler.start()
    print("[scheduler] Đã khởi động APScheduler (quét mỗi 6 giờ)")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[scheduler] Đã dừng APScheduler")
