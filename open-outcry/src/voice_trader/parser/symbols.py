"""Built-in company-name -> ticker map and common ticker list.

This lets the parser translate "Apple" -> "AAPL" without a network call, which
keeps paper/simulation mode fully offline. The resolver extends this with
live asset lookups when a broker adapter with a symbol universe is available.
"""

from __future__ import annotations

# Lower-case company/ETF common names -> ticker.
KNOWN_NAMES: dict[str, str] = {
    "apple": "AAPL",
    "microsoft": "MSFT",
    "tesla": "TSLA",
    "amazon": "AMZN",
    "nvidia": "NVDA",
    "google": "GOOGL",
    "goog": "GOOG",
    "googl": "GOOGL",
    "alphabet": "GOOGL",
    "meta": "META",
    "facebook": "META",
    "netflix": "NFLX",
    "spy": "SPY",
    "spx": "SPX",
    "qqq": "QQQ",
    "amc": "AMC",
    "gamestop": "GME",
    "coinbase": "COIN",
    "palantir": "PLTR",
    "amd": "AMD",
    "intel": "INTC",
    "snowflake": "SNOW",
    "nike": "NKE",
    "disney": "DIS",
    "coca cola": "KO",
    "coke": "KO",
    "walmart": "WMT",
    "bank of america": "BAC",
    "goldman sachs": "GS",
    "jp morgan": "JPM",
    "jpmorgan": "JPM",
    "morgan stanley": "MS",
    "berkshire hathaway": "BRK.B",
    "vanguard s&p 500": "VOO",
    "vanguard total market": "VTI",
}

# Common tickers we always recognize even without a broker connection.
COMMON_TICKERS: set[str] = {
    "AAPL", "MSFT", "TSLA", "AMZN", "NVDA", "GOOGL", "GOOG", "META", "NFLX",
    "SPY", "SPX", "QQQ", "IWM", "DIA", "VOO", "VTI", "GME", "AMC", "COIN",
    "PLTR", "AMD", "INTC", "SNOW", "NKE", "DIS", "KO", "WMT", "BAC", "GS",
    "JPM", "MS", "BRK.B", "TLT", "GLD", "SLV", "USO", "XLE", "XLF", "XLI",
    "BTC", "ETH", "BTCUSDT", "ETHUSDT", "SOL", "SOLUSDT",
}

# Words that look like tickers but are actually not.
TICKER_STOPWORDS = {
    "I", "A", "AT", "TO", "FOR", "THE", "MY", "ME", "ON", "IN", "AND",
    "SELL", "BUY", "CLOSE", "OPEN", "CALL", "PUT", "CALLS", "PUTS",
    "SPREAD", "OPTION", "OPTIONS", "SHARES", "SHARE", "CONTRACTS",
    "EXPIRING", "EXPIRY", "EXPIRES", "STOP", "LIMIT", "MARKET", "TARGET",
    "PRICE", "EXP", "DTE", "THIS", "FRIDAY", "MONDAY", "TUESDAY",
    "WEDNESDAY", "THURSDAY", "NEXT", "WEEK", "MONTH",
}
