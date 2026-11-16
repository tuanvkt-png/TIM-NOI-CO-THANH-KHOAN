"""
Quét danh sách mã người dùng chọn (watchlist) để tìm "SETUP ĐẸP".
Chạy song song bằng ThreadPoolExecutor để nhanh hơn nhiều so với quét tuần tự.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from .analyzer import analyze_symbol
from .data_fetcher import fetch_ohlcv, get_info

# Ngưỡng "setup đẹp": ≥3/4 điều kiện HỘI TỤ, R:R ≥ 1.5, điểm ≥ 55
MIN_PASSED = 3
MIN_RR = 1.5
MIN_SCORE = 55.0


def _scan_one(ticker: str, interval: str) -> Dict:
    try:
        df = fetch_ohlcv(ticker, interval)
        if df is None or df.empty:
            return {"ticker": ticker, "error": "Không có dữ liệu"}
        a = analyze_symbol(df, ticker, interval, get_info(ticker))
        best = a["setups"][0] if a["setups"] else None
        return {
            "ticker": ticker,
            "name": a["name"],
            "cat": a["cat"],
            "sub": a["sub"],
            "price": a["current_price"],
            "score": a["score"],
            "grade": a["grade"],
            "direction": a["direction"],
            "rr": best["rr"] if best else None,
            "passed": best["passed"] if best else 0,
            "total": best["total"] if best else 0,
            "entry": best["entry"] if best else None,
            "sl": best["sl"] if best else None,
            "tp": best["tp"] if best else None,
            "error": None,
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def scan_watchlist(tickers: List[str], interval: str = "1h",
                   only_beautiful: bool = True, max_workers: int = 8) -> List[Dict]:
    results: List[Dict] = []
    if not tickers:
        return results

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_scan_one, t, interval): t for t in tickers}
        for fut in as_completed(futures):
            results.append(fut.result())

    if only_beautiful:
        results = [
            r for r in results
            if not r.get("error")
            and r.get("passed", 0) >= MIN_PASSED
            and (r.get("rr") or 0) >= MIN_RR
            and r.get("score", 0) >= MIN_SCORE
        ]

    results.sort(key=lambda r: (r.get("score") or 0), reverse=True)
    return results
