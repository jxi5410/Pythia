"""
Asset Class Mapping
Connects prediction market events to tradeable asset classes.
"""
from typing import Dict

ASSET_CLASS_MAP = {
    "rates": {
        "keywords": ["fed", "interest rate", "rate cut", "rate hike", "fomc",
                      "treasury", "bond", "yield", "monetary policy",
                      "inflation", "cpi", "pce"],
        "instruments": "US Treasuries, Eurodollar futures, SOFR, rate swaps",
        "how_it_matters": "Probability shifts in rate decisions directly reprice the front end of the curve",
    },
    "fx": {
        "keywords": ["dollar", "usd", "euro", "eur", "gbp", "yen", "currency",
                      "forex", "tariff", "trade war", "sanctions"],
        "instruments": "DXY, EUR/USD, USD/JPY, EM FX",
        "how_it_matters": "Trade policy and sanctions directly impact currency pairs and EM risk",
    },
    "equities": {
        "keywords": ["stock", "s&p", "nasdaq", "tech", "regulation", "antitrust",
                      "ipo", "earnings", "recession", "gdp", "unemployment"],
        "instruments": "S&P 500, Nasdaq, sector ETFs, single stocks",
        "how_it_matters": "Macro probability shifts reprice equity risk premium and sector rotation",
    },
    "commodities": {
        "keywords": ["oil", "opec", "gas", "energy", "gold", "commodity",
                      "climate", "weather", "agriculture"],
        "instruments": "Crude oil, natural gas, gold, agricultural futures",
        "how_it_matters": "Geopolitical and climate probability shifts move energy and commodity markets",
    },
    "crypto": {
        "keywords": ["bitcoin", "btc", "ethereum", "eth", "crypto", "defi",
                      "sec crypto", "stablecoin", "cbdc"],
        "instruments": "BTC, ETH, crypto derivatives",
        "how_it_matters": "Regulatory and adoption probability shifts drive crypto volatility",
    },
    "geopolitical": {
        "keywords": ["war", "conflict", "china", "russia", "ukraine", "taiwan",
                      "nato", "military", "nuclear", "invasion", "election",
                      "trump", "president", "congress", "senate"],
        "instruments": "Safe havens (gold, CHF, JPY), defense stocks, VIX",
        "how_it_matters": "Geopolitical risk reprices safe haven demand and risk appetite",
    },
}


def classify_market(title: str, description: str = "") -> Dict:
    """
    Classify a prediction market into an asset class based on keyword matching.

    Returns dict with asset_class, instruments, how_it_matters, confidence.
    """
    text = f"{title} {description}".lower()
    best_class = None
    best_score = 0
    best_info = None

    for asset_class, info in ASSET_CLASS_MAP.items():
        hits = sum(1 for kw in info["keywords"] if kw in text)
        total = len(info["keywords"])
        if hits > 0:
            score = hits / total
            if hits > best_score or (hits == best_score and score > (best_score / total if best_class else 0)):
                best_class = asset_class
                best_score = hits
                best_info = info

    if best_class and best_score >= 1:
        total_kw = len(ASSET_CLASS_MAP[best_class]["keywords"])
        confidence = min(1.0, best_score / max(total_kw * 0.3, 1))
        return {
            "asset_class": best_class,
            "instruments": best_info["instruments"],
            "how_it_matters": best_info["how_it_matters"],
            "confidence": round(confidence, 2),
        }

    return {
        "asset_class": "general",
        "instruments": "Depends on event outcome",
        "how_it_matters": "Monitor for cross-asset implications",
        "confidence": 0.0,
    }
