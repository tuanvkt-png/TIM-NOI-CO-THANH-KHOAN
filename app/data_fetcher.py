"""
Lấy dữ liệu nến (OHLCV).
Ưu tiên gọi trực tiếp Yahoo Finance Chart API (nhanh, ổn định trên server).
Nếu thất bại thì fallback sang yfinance.
"""
import json
import urllib.parse
import urllib.request
import pandas as pd

SYMBOLS = {
    "FX (Ngoại hối)": ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X", "USDCHF=X"],
    "Crypto": ["BTC-USD", "ETH-USD", "XRP-USD", "SOL-USD", "ADA-USD"],
    "Kim loại / Năng lượng": ["GC=F", "SI=F", "CL=F", "NG=F", "HG=F"],
    "Chỉ số": ["^DJI", "^IXIC", "^GSPC", "^VIX", "^N225"],
    "Cổ phiếu": ["AAPL", "TSLA", "NVDA", "MSFT", "AMZN"],
}

INTERVALS = {
    "15m": {"interval": "15m", "range": "1mo"},
    "30m": {"interval": "30m", "range": "2mo"},
    "1h": {"interval": "1h", "range": "6mo"},
    "4h": {"interval": "1h", "range": "1y", "resample": "4h"},
    "1d": {"interval": "1d", "range": "2y"},
    "1wk": {"interval": "1wk", "range": "5y"},
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


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
    df = df[["open", "high", "low", "close", "volume"]].dropna(subset=["open", "high", "low", "close"])
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