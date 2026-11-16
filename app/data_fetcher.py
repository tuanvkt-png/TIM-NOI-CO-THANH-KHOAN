"""
Lấy dữ liệu nến (OHLCV).
Ưu tiên gọi trực tiếp Yahoo Finance Chart API (nhanh, ổn định trên server).
Nếu thất bại thì fallback sang yfinance.
"""
import json
import urllib.parse
import urllib.request

import pandas as pd

# Mỗi mã: ticker Yahoo, tên hiển thị, nhóm tài sản, đơn vị
SYMBOL_INFO = [
    # FX
    {"t": "EURUSD=X", "name": "EUR/USD", "cat": "Ngoại hối", "sub": "EUR/USD", "unit": "USD"},
    {"t": "GBPUSD=X", "name": "GBP/USD", "cat": "Ngoại hối", "sub": "GBP/USD", "unit": "USD"},
    {"t": "USDJPY=X", "name": "USD/JPY", "cat": "Ngoại hối", "sub": "USD/JPY", "unit": "JPY"},
    {"t": "AUDUSD=X", "name": "AUD/USD", "cat": "Ngoại hối", "sub": "AUD/USD", "unit": "USD"},
    {"t": "USDCAD=X", "name": "USD/CAD", "cat": "Ngoại hối", "sub": "USD/CAD", "unit": "CAD"},
    {"t": "USDCHF=X", "name": "USD/CHF", "cat": "Ngoại hối", "sub": "USD/CHF", "unit": "CHF"},
    # Kim loại quý
    {"t": "GC=F", "name": "Vàng giao sau", "cat": "Kim loại quý", "sub": "XAUUSD (Gold Futures)", "unit": "USD/oz"},
    {"t": "SI=F", "name": "Bạc giao sau", "cat": "Kim loại quý", "sub": "XAGUSD (Silver Futures)", "unit": "USD/oz"},
    {"t": "HG=F", "name": "Đồng giao sau", "cat": "Kim loại quý", "sub": "Copper Futures", "unit": "USD/lb"},
    # Năng lượng
    {"t": "CL=F", "name": "Dầu thô WTI", "cat": "Năng lượng", "sub": "WTI Crude Oil", "unit": "USD/thùng"},
    {"t": "NG=F", "name": "Khí tự nhiên", "cat": "Năng lượng", "sub": "Natural Gas", "unit": "USD/MMBtu"},
    # Crypto
    {"t": "BTC-USD", "name": "Bitcoin", "cat": "Tiền mã hoá", "sub": "BTC/USD", "unit": "USD"},
    {"t": "ETH-USD", "name": "Ethereum", "cat": "Tiền mã hoá", "sub": "ETH/USD", "unit": "USD"},
    {"t": "XRP-USD", "name": "Ripple", "cat": "Tiền mã hoá", "sub": "XRP/USD", "unit": "USD"},
    {"t": "SOL-USD", "name": "Solana", "cat": "Tiền mã hoá", "sub": "SOL/USD", "unit": "USD"},
    {"t": "ADA-USD", "name": "Cardano", "cat": "Tiền mã hoá", "sub": "ADA/USD", "unit": "USD"},
    # Chỉ số
    {"t": "^DJI", "name": "Dow Jones 30", "cat": "Chỉ số", "sub": "US30 / DJIA", "unit": "điểm"},
    {"t": "^IXIC", "name": "Nasdaq Composite", "cat": "Chỉ số", "sub": "US100 / NASDAQ", "unit": "điểm"},
    {"t": "^GSPC", "name": "S&P 500", "cat": "Chỉ số", "sub": "SPX", "unit": "điểm"},
    {"t": "^N225", "name": "Nikkei 225", "cat": "Chỉ số", "sub": "JP225", "unit": "điểm"},
    {"t": "^VIX", "name": "VIX – Chỉ số sợ hãi", "cat": "Chỉ số", "sub": "Volatility Index", "unit": "điểm"},
    # Cổ phiếu
    {"t": "AAPL", "name": "Apple Inc.", "cat": "Cổ phiếu", "sub": "AAPL", "unit": "USD"},
    {"t": "TSLA", "name": "Tesla Inc.", "cat": "Cổ phiếu", "sub": "TSLA", "unit": "USD"},
    {"t": "NVDA", "name": "NVIDIA Corp.", "cat": "Cổ phiếu", "sub": "NVDA", "unit": "USD"},
    {"t": "MSFT", "name": "Microsoft Corp.", "cat": "Cổ phiếu", "sub": "MSFT", "unit": "USD"},
    {"t": "AMZN", "name": "Amazon.com Inc.", "cat": "Cổ phiếu", "sub": "AMZN", "unit": "USD"},
]

INFO_BY_TICKER = {x["t"]: x for x in SYMBOL_INFO}

# Giữ dạng dict theo nhóm để tương thích code cũ
SYMBOLS: dict[str, list[str]] = {}
for _x in SYMBOL_INFO:
    SYMBOLS.setdefault(_x["cat"], []).append(_x["t"])

INTERVALS = {
    "15m": {"interval": "15m", "range": "1mo", "label": "15 phút"},
    "30m": {"interval": "30m", "range": "2mo", "label": "30 phút"},
    "1h": {"interval": "1h", "range": "6mo", "label": "1 giờ"},
    "4h": {"interval": "1h", "range": "1y", "resample": "4h", "label": "4 giờ"},
    "1d": {"interval": "1d", "range": "2y", "label": "1 ngày"},
    "1wk": {"interval": "1wk", "range": "5y", "label": "1 tuần"},
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_info(ticker: str) -> dict:
    return INFO_BY_TICKER.get(
        ticker, {"t": ticker, "name": ticker, "cat": "Khác", "sub": ticker, "unit": ""}
    )


def _fetch_yahoo_http(symbol: str, interval: str, rng: str) -> pd.DataFrame | None:
    base = "https://query1.finance.yahoo.com/v8/finance/chart/"
    url = f"{base}{urllib.parse.quote(symbol)}?range={rng}&interval={interval}&includePrePost=false"
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(chart["error"])
    results = chart.get("result") or []
    if not results:
        return None

    res = results[0]
    timestamps = res.get("timestamp") or []
    quotes = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    if not timestamps or not quotes:
        return None

    df = pd.DataFrame(
        {
            "open": quotes.get("open"),
            "high": quotes.get("high"),
            "low": quotes.get("low"),
            "close": quotes.get("close"),
            "volume": quotes.get("volume"),
        },
        index=pd.to_datetime(timestamps, unit="s", utc=True),
    )
    df.index.name = "datetime"
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0)
    return df if not df.empty else None


def _fetch_yfinance(symbol: str, interval: str, period: str) -> pd.DataFrame | None:
    import yfinance as yf

    df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
    if df is None or df.empty:
        return None
    df = df.rename(columns=str.lower)
    df = df[["open", "high", "low", "close", "volume"]].dropna(
        subset=["open", "high", "low", "close"]
    )
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index.name = "datetime"
    return df


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = df.resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return out.dropna(subset=["open", "high", "low", "close"])


_YF_PERIOD = {"15m": "1mo", "30m": "2mo", "1h": "6mo", "1d": "2y", "1wk": "5y"}


def fetch_ohlcv(symbol: str, interval: str = "1h") -> pd.DataFrame | None:
    cfg = INTERVALS.get(interval, INTERVALS["1h"])
    base_interval = cfg["interval"]
    rng = cfg["range"]

    df = None
    try:
        df = _fetch_yahoo_http(symbol, base_interval, rng)
    except Exception as e:
        print(f"[data_fetcher] HTTP Yahoo lỗi {symbol}: {e}")

    if df is None:
        try:
            df = _fetch_yfinance(symbol, base_interval, _YF_PERIOD.get(base_interval, "6mo"))
        except Exception as e:
            print(f"[data_fetcher] yfinance lỗi {symbol}: {e}")
            return None

    if df is None or df.empty:
        return None

    rule = cfg.get("resample")
    if rule:
        df = _resample(df, rule)

    if df.empty:
        return None

    return df.tail(400)
