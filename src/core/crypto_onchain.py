"""
Crypto On-Chain Signals — Monitors whale movements, exchange flows, funding rates,
and cross-references with crypto prediction market contracts.
"""
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache: Dict[str, dict] = {}
CACHE_TTL = 300  # 5 minutes


def _cached(key: str):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < CACHE_TTL:
        return entry["data"]
    return None


def _set_cache(key: str, data):
    _cache[key] = {"data": data, "ts": time.time()}

# ---------------------------------------------------------------------------
# Known Exchange Addresses (BTC)
# ---------------------------------------------------------------------------

KNOWN_EXCHANGES = {
    # Coinbase
    "1FzWLkAahHooV3kzTgyx6qsXoRDrBv1AX2": "Coinbase",
    "3JZq4atUahhuA9rLhXLMhhTo133J9rF97j": "Coinbase",
    "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh": "Coinbase",
    "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo": "Coinbase",
    "3Cbq7aT1tY8kMxWLbitaG7yT6bPbKChq64": "Coinbase",
    # Binance
    "1NDyJtNTjmwk5xPNhjgAMu4HDHigtobu1s": "Binance",
    "3JJmF63ifcamPLKsLBrC1rMBnMBd5DTj8M": "Binance",
    "bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h": "Binance",
    "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo": "Binance",
    "3LYJfcfHPXYJreMsASk2jkn69LWEYKzexb": "Binance",
    # Kraken
    "3AfP8C3nMJhJQ4ogcEHDQgBCGBYPGfZPsK": "Kraken",
    "bc1qr4dl5wa7kl8yu792dceg9z5knl2gkn220lk7a9": "Kraken",
    # Bitfinex
    "3D2oetdNuZUqQHPJmcMDDHYoqkyNVsFk9r": "Bitfinex",
    "bc1qgdjqv0av3q56jvd82tkdjpy7gdp9ut8tlqmgrpmv24sq90ecnvqqjwvw97": "Bitfinex",
    # OKX
    "3LQUu4v9z6KNch71j7kbj8GPeAGUo1FW6a": "OKX",
    # Gemini
    "3JEmL8XTJNQ2LkLsRCSGXiU4X5JnSnQ4FB": "Gemini",
    # Bybit
    "1ByBi5fQReUisKpEmVaeBfAMH4HrUhBGBN": "Bybit",
}

EXCHANGE_NAMES = set(KNOWN_EXCHANGES.values())

# Headers
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _classify_address(addr: str) -> str:
    """Classify a BTC address as exchange name or 'unknown'."""
    return KNOWN_EXCHANGES.get(addr, "unknown")


# ---------------------------------------------------------------------------
# 1. Whale Movements (mempool.space)
# ---------------------------------------------------------------------------

def fetch_whale_movements(min_btc: float = 100, hours_back: int = 4) -> List[dict]:
    """Detect large BTC transactions from recent blocks via mempool.space."""
    cached = _cached(f"whale_{min_btc}_{hours_back}")
    if cached is not None:
        return cached

    whales = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    # Get current BTC price for USD conversion
    btc_price = _get_btc_price()

    try:
        # Get recent blocks
        resp = requests.get(
            "https://mempool.space/api/v1/blocks",
            headers=_HEADERS, timeout=15
        )
        resp.raise_for_status()
        blocks = resp.json()[:6]  # last ~6 blocks (~1 hour)

        for block in blocks:
            block_ts = datetime.fromtimestamp(block["timestamp"], tz=timezone.utc)
            if block_ts < cutoff:
                continue

            block_hash = block["id"]
            # Get block txs
            try:
                tx_resp = requests.get(
                    f"https://mempool.space/api/block/{block_hash}/txs",
                    headers=_HEADERS, timeout=15
                )
                tx_resp.raise_for_status()
                txs = tx_resp.json()
            except Exception:
                continue

            for tx in txs:
                # Sum outputs to get total value
                total_sats = sum(
                    vout.get("value", 0) for vout in tx.get("vout", [])
                )
                btc_amount = total_sats / 1e8

                if btc_amount < min_btc:
                    continue

                # Classify input/output addresses
                from_addrs = set()
                to_addrs = set()
                for vin in tx.get("vin", []):
                    prevout = vin.get("prevout", {})
                    addr = prevout.get("scriptpubkey_address", "")
                    if addr:
                        from_addrs.add(addr)
                for vout in tx.get("vout", []):
                    addr = vout.get("scriptpubkey_address", "")
                    if addr:
                        to_addrs.add(addr)

                from_types = {_classify_address(a) for a in from_addrs}
                to_types = {_classify_address(a) for a in to_addrs}

                from_type = next((t for t in from_types if t != "unknown"), "unknown")
                to_type = next((t for t in to_types if t != "unknown"), "unknown")

                whales.append({
                    "tx_hash": tx["txid"],
                    "btc_amount": round(btc_amount, 4),
                    "usd_value": round(btc_amount * btc_price, 0),
                    "from_type": from_type,
                    "to_type": to_type,
                    "timestamp": block_ts.isoformat(),
                })

        # Sort by value descending
        whales.sort(key=lambda x: x["usd_value"], reverse=True)
        # Limit to top 50
        whales = whales[:50]

    except Exception as e:
        logger.error(f"Whale movement fetch failed: {e}")

    _set_cache(f"whale_{min_btc}_{hours_back}", whales)
    return whales


def _get_btc_price() -> float:
    """Quick BTC price from CoinGecko."""
    cached = _cached("btc_price")
    if cached is not None:
        return cached
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"},
            headers=_HEADERS, timeout=10
        )
        price = r.json()["bitcoin"]["usd"]
    except Exception:
        price = 95000.0  # fallback
    _set_cache("btc_price", price)
    return price


# ---------------------------------------------------------------------------
# 2. Exchange Flows (estimated from whale movements + CoinGlass scrape)
# ---------------------------------------------------------------------------

def fetch_exchange_flows(hours_back: int = 24) -> dict:
    """Estimate net exchange inflows/outflows from on-chain data."""
    cached = _cached(f"exchange_flows_{hours_back}")
    if cached is not None:
        return cached

    result = {
        "btc_net_flow": 0.0,
        "eth_net_flow": 0.0,
        "direction": "neutral",
        "exchange_breakdown": {},
        "source": "mempool.space+estimate",
        "hours_back": hours_back,
    }

    btc_price = _get_btc_price()

    # Try scraping CoinGlass for exchange flow data
    try:
        resp = requests.get(
            "https://www.coinglass.com/bitcoin-exchange-flow",
            headers={
                **_HEADERS,
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Try to extract data from the page
            text = soup.get_text()
            # CoinGlass pages are JS-rendered; we may not get data
            # Fall through to estimation
    except Exception:
        pass

    # Estimate from whale movements
    try:
        whales = fetch_whale_movements(min_btc=50, hours_back=hours_back)
        exchange_flows = {}
        net_inflow_btc = 0.0

        for w in whales:
            # Inflow: unknown -> exchange
            if w["from_type"] == "unknown" and w["to_type"] != "unknown":
                net_inflow_btc += w["btc_amount"]
                ex = w["to_type"]
                exchange_flows[ex] = exchange_flows.get(ex, 0) + w["btc_amount"]
            # Outflow: exchange -> unknown
            elif w["from_type"] != "unknown" and w["to_type"] == "unknown":
                net_inflow_btc -= w["btc_amount"]
                ex = w["from_type"]
                exchange_flows[ex] = exchange_flows.get(ex, 0) - w["btc_amount"]

        result["btc_net_flow"] = round(net_inflow_btc, 4)
        result["btc_net_flow_usd"] = round(net_inflow_btc * btc_price, 0)
        result["exchange_breakdown"] = {
            k: round(v, 4) for k, v in exchange_flows.items()
        }

        if net_inflow_btc > 50:
            result["direction"] = "bearish"  # inflow = selling pressure
        elif net_inflow_btc < -50:
            result["direction"] = "bullish"  # outflow = accumulation
        else:
            result["direction"] = "neutral"

    except Exception as e:
        logger.error(f"Exchange flow estimation failed: {e}")

    _set_cache(f"exchange_flows_{hours_back}", result)
    return result


# ---------------------------------------------------------------------------
# 3. Funding Rates (CoinGlass scrape + fallback)
# ---------------------------------------------------------------------------

def fetch_funding_rates() -> dict:
    """Fetch perpetual futures funding rates."""
    cached = _cached("funding_rates")
    if cached is not None:
        return cached

    result = {
        "btc_funding": None,
        "eth_funding": None,
        "weighted_avg": None,
        "signal": "neutral",
        "exchanges": {},
        "source": "coinglass",
    }

    # Try CoinGlass API (undocumented public endpoint)
    try:
        resp = requests.get(
            "https://open-api.coinglass.com/public/v2/funding",
            params={"symbol": "BTC", "time_type": "h8"},
            headers={**_HEADERS, "Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success") and data.get("data"):
                rates = data["data"]
                btc_rates = {}
                for item in rates:
                    exchange = item.get("exchangeName", "unknown")
                    rate = item.get("rate", 0)
                    btc_rates[exchange] = rate
                if btc_rates:
                    avg = sum(btc_rates.values()) / len(btc_rates)
                    result["btc_funding"] = round(avg, 6)
                    result["exchanges"] = btc_rates
    except Exception:
        pass

    # Fallback: scrape CoinGlass funding page
    if result["btc_funding"] is None:
        try:
            resp = requests.get(
                "https://www.coinglass.com/FundingRate",
                headers={
                    **_HEADERS,
                    "Accept": "text/html,application/xhtml+xml",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                # JS-rendered page — try to find JSON data in script tags
                for script in soup.find_all("script"):
                    text = script.string or ""
                    if "fundingRate" in text or "funding_rate" in text:
                        # Try to extract structured data
                        try:
                            start = text.index("{")
                            end = text.rindex("}") + 1
                            chunk = text[start:end]
                            data = json.loads(chunk)
                            if "btc" in str(data).lower():
                                logger.info("Found funding data in script tag")
                        except (ValueError, json.JSONDecodeError):
                            pass
        except Exception:
            pass

    # If still no data, use a reasonable estimate marker
    if result["btc_funding"] is None:
        result["btc_funding"] = 0.0
        result["source"] = "unavailable"
        result["note"] = "CoinGlass requires JS rendering; data may be stale"

    # ETH funding — try same approach
    if result["eth_funding"] is None:
        try:
            resp = requests.get(
                "https://open-api.coinglass.com/public/v2/funding",
                params={"symbol": "ETH", "time_type": "h8"},
                headers={**_HEADERS},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") and data.get("data"):
                    rates = [item.get("rate", 0) for item in data["data"]]
                    if rates:
                        result["eth_funding"] = round(sum(rates) / len(rates), 6)
        except Exception:
            result["eth_funding"] = 0.0

    # Weighted average
    btc_f = result["btc_funding"] or 0
    eth_f = result["eth_funding"] or 0
    result["weighted_avg"] = round(btc_f * 0.6 + eth_f * 0.4, 6)

    # Signal
    avg = result["weighted_avg"]
    if avg > 0.01:
        result["signal"] = "bearish"  # overleveraged longs
    elif avg < -0.01:
        result["signal"] = "bullish"  # overleveraged shorts
    else:
        result["signal"] = "neutral"

    _set_cache("funding_rates", result)
    return result


# ---------------------------------------------------------------------------
# 4. Fear & Greed Index
# ---------------------------------------------------------------------------

def fetch_fear_greed() -> dict:
    """Fetch Alternative.me Fear & Greed Index."""
    cached = _cached("fear_greed")
    if cached is not None:
        return cached

    result = {"value": None, "classification": "unknown", "trend_7d": None}

    try:
        resp = requests.get(
            "https://api.alternative.me/fng/",
            params={"limit": 7, "format": "json"},
            headers=_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])

        if data:
            latest = data[0]
            result["value"] = int(latest["value"])
            result["classification"] = latest["value_classification"]
            result["timestamp"] = latest.get("timestamp")

            # 7-day trend
            if len(data) >= 7:
                week_ago = int(data[-1]["value"])
                current = result["value"]
                diff = current - week_ago
                if diff > 5:
                    result["trend_7d"] = "improving"
                elif diff < -5:
                    result["trend_7d"] = "declining"
                else:
                    result["trend_7d"] = "stable"
                result["value_7d_ago"] = week_ago
    except Exception as e:
        logger.error(f"Fear & Greed fetch failed: {e}")

    _set_cache("fear_greed", result)
    return result


# ---------------------------------------------------------------------------
# 5. Crypto Market Data (CoinGecko)
# ---------------------------------------------------------------------------

def fetch_crypto_market_data(symbols: List[str] = None) -> dict:
    """Fetch price, volume, market cap from CoinGecko."""
    if symbols is None:
        symbols = ["bitcoin", "ethereum"]

    cache_key = f"market_{'_'.join(sorted(symbols))}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    result = {}

    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={
                "vs_currency": "usd",
                "ids": ",".join(symbols),
                "order": "market_cap_desc",
                "sparkline": "false",
                "price_change_percentage": "24h,7d",
            },
            headers=_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()

        for coin in resp.json():
            result[coin["id"]] = {
                "symbol": coin["symbol"].upper(),
                "price": coin["current_price"],
                "market_cap": coin["market_cap"],
                "volume_24h": coin["total_volume"],
                "change_24h_pct": coin.get("price_change_percentage_24h"),
                "change_7d_pct": coin.get("price_change_percentage_7d_in_currency"),
                "ath": coin.get("ath"),
                "ath_change_pct": coin.get("ath_change_percentage"),
            }
    except Exception as e:
        logger.error(f"CoinGecko market data fetch failed: {e}")

    _set_cache(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# 6. Signal Detection Pipeline
# ---------------------------------------------------------------------------

# Keywords that link prediction markets to crypto
CRYPTO_MARKET_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "crypto",
    "solana", "sol", "xrp", "ripple",
    "defi", "nft", "stablecoin",
    "binance", "coinbase",
]

BEARISH_KEYWORDS = ["drop", "below", "crash", "fall", "decline", "bear", "dump", "collapse"]
BULLISH_KEYWORDS = ["above", "rise", "rally", "bull", "surge", "ath", "high", "moon"]


def _match_market_to_signals(market: dict, signals_context: dict) -> Optional[dict]:
    """Check if a prediction market relates to crypto on-chain signals."""
    question = (market.get("question") or market.get("title") or "").lower()

    # Must be crypto-related
    if not any(kw in question for kw in CRYPTO_MARKET_KEYWORDS):
        return None

    sentiment = "neutral"
    if any(kw in question for kw in BEARISH_KEYWORDS):
        sentiment = "bearish"
    elif any(kw in question for kw in BULLISH_KEYWORDS):
        sentiment = "bullish"

    score = 0.0
    reasons = []

    # Cross-reference with on-chain data
    flows = signals_context.get("exchange_flows", {})
    funding = signals_context.get("funding_rates", {})
    fear_greed = signals_context.get("fear_greed", {})
    whales = signals_context.get("whales", [])

    # Whale activity
    if whales:
        large_whales = [w for w in whales if w.get("usd_value", 0) > 50_000_000]
        if large_whales:
            score += 0.3
            biggest = max(large_whales, key=lambda w: w["usd_value"])
            reasons.append(
                f"🐋 {biggest['btc_amount']:,.0f} BTC (${biggest['usd_value']/1e6:.0f}M) "
                f"moved {biggest['from_type']}→{biggest['to_type']}"
            )

    # Exchange flows
    flow_dir = flows.get("direction", "neutral")
    if flow_dir != "neutral":
        net = flows.get("btc_net_flow", 0)
        usd = flows.get("btc_net_flow_usd", 0)
        if (flow_dir == "bearish" and sentiment == "bearish") or \
           (flow_dir == "bullish" and sentiment == "bullish"):
            score += 0.25
            direction_word = "inflow" if net > 0 else "outflow"
            reasons.append(
                f"📊 Exchange {direction_word}: {abs(net):,.0f} BTC (${abs(usd)/1e6:.0f}M)"
            )

    # Funding rates
    funding_signal = funding.get("signal", "neutral")
    btc_funding = funding.get("btc_funding", 0)
    if funding_signal != "neutral":
        if (funding_signal == "bearish" and sentiment == "bearish") or \
           (funding_signal == "bullish" and sentiment == "bullish"):
            score += 0.2
            reasons.append(f"💰 Funding rate: {btc_funding:+.4f}%")

    # Fear & Greed
    fg_val = fear_greed.get("value")
    if fg_val is not None:
        fg_class = fear_greed.get("classification", "")
        if (fg_val < 30 and sentiment == "bearish") or \
           (fg_val > 70 and sentiment == "bullish"):
            score += 0.15
            reasons.append(f"😱 Fear & Greed: {fg_val} ({fg_class})")

    if score < 0.1:
        return None

    return {
        "type": "crypto_onchain",
        "market": market,
        "score": round(min(score, 1.0), 2),
        "sentiment": sentiment,
        "on_chain_alignment": flow_dir,
        "reasons": reasons,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def detect_crypto_signals(active_markets: List[dict] = None) -> List[dict]:
    """Full pipeline: gather on-chain data, cross-reference with prediction markets."""
    cached = _cached("crypto_signals")
    if cached is not None:
        return cached

    logger.info("Running crypto on-chain signal detection...")

    # Gather all data sources
    context = {}

    try:
        context["whales"] = fetch_whale_movements(min_btc=100, hours_back=4)
    except Exception as e:
        logger.error(f"Whale fetch error: {e}")
        context["whales"] = []

    try:
        context["exchange_flows"] = fetch_exchange_flows(hours_back=24)
    except Exception as e:
        logger.error(f"Exchange flow error: {e}")
        context["exchange_flows"] = {}

    try:
        context["funding_rates"] = fetch_funding_rates()
    except Exception as e:
        logger.error(f"Funding rate error: {e}")
        context["funding_rates"] = {}

    try:
        context["fear_greed"] = fetch_fear_greed()
    except Exception as e:
        logger.error(f"Fear & greed error: {e}")
        context["fear_greed"] = {}

    try:
        context["market_data"] = fetch_crypto_market_data()
    except Exception as e:
        logger.error(f"Market data error: {e}")
        context["market_data"] = {}

    signals = []

    # If we have active prediction markets, cross-reference
    if active_markets:
        for market in active_markets:
            signal = _match_market_to_signals(market, context)
            if signal:
                signals.append(signal)

    # Also generate standalone on-chain signals
    whales = context.get("whales", [])
    big_whales = [w for w in whales if w.get("usd_value", 0) > 100_000_000]
    if big_whales:
        for w in big_whales[:3]:
            signals.append({
                "type": "whale_alert",
                "score": min(0.5 + w["usd_value"] / 1e9, 1.0),
                "reasons": [
                    f"🐋 {w['btc_amount']:,.0f} BTC (${w['usd_value']/1e6:.0f}M) "
                    f"moved {w['from_type']}→{w['to_type']}"
                ],
                "data": w,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    # Funding rate extreme signal
    funding = context.get("funding_rates", {})
    btc_f = funding.get("btc_funding", 0)
    if abs(btc_f) > 0.03:
        direction = "overleveraged longs" if btc_f > 0 else "overleveraged shorts"
        signals.append({
            "type": "funding_extreme",
            "score": min(0.4 + abs(btc_f) * 5, 1.0),
            "reasons": [f"💰 Extreme funding rate: {btc_f:+.4f}% ({direction})"],
            "data": funding,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # Fear & Greed extreme
    fg = context.get("fear_greed", {})
    fg_val = fg.get("value")
    if fg_val is not None and (fg_val <= 20 or fg_val >= 80):
        signals.append({
            "type": "fear_greed_extreme",
            "score": 0.4,
            "reasons": [f"😱 Extreme Fear & Greed: {fg_val} ({fg.get('classification', '')})"],
            "data": fg,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # Sort by score
    signals.sort(key=lambda s: s.get("score", 0), reverse=True)

    _set_cache("crypto_signals", signals)
    return signals


# ---------------------------------------------------------------------------
# 7. Alert Formatting
# ---------------------------------------------------------------------------

def format_crypto_alert(signal: dict) -> str:
    """Format a crypto signal for Telegram."""
    lines = ["⛓️ ON-CHAIN SIGNAL"]

    sig_type = signal.get("type", "unknown")

    # Reasons are pre-formatted with emoji
    for reason in signal.get("reasons", []):
        lines.append(reason)

    # Add market reference if present
    market = signal.get("market")
    if market:
        question = market.get("question") or market.get("title", "")
        price = market.get("last_price") or market.get("yes_price")
        if price is not None:
            if isinstance(price, float) and price < 1:
                price_str = f"{price*100:.0f}¢"
            else:
                price_str = f"{price}¢"
            lines.append(f'\nRelated: "{question}" at {price_str}')
        else:
            lines.append(f'\nRelated: "{question}"')

    # Score
    score = signal.get("score", 0)
    if score >= 0.7:
        lines.append(f"\n🔴 Signal strength: {score:.0%}")
    elif score >= 0.4:
        lines.append(f"\n🟡 Signal strength: {score:.0%}")
    else:
        lines.append(f"\n🟢 Signal strength: {score:.0%}")

    return "\n".join(lines)


def format_crypto_summary(signals: List[dict], context: dict = None) -> str:
    """Format a full crypto on-chain summary for Telegram."""
    if not signals and not context:
        return "⛓️ No significant on-chain signals detected."

    lines = ["⛓️ CRYPTO ON-CHAIN SUMMARY\n"]

    # Market data
    if context and context.get("market_data"):
        md = context["market_data"]
        for coin_id, data in md.items():
            change = data.get("change_24h_pct", 0)
            arrow = "🟢" if change and change > 0 else "🔴"
            lines.append(
                f"{arrow} {data['symbol']}: ${data['price']:,.0f} "
                f"({change:+.1f}%)" if change else
                f"  {data['symbol']}: ${data['price']:,.0f}"
            )

    # Fear & Greed
    if context and context.get("fear_greed", {}).get("value"):
        fg = context["fear_greed"]
        lines.append(f"\n😱 Fear & Greed: {fg['value']} ({fg['classification']})")

    # Signals
    if signals:
        lines.append(f"\n📡 {len(signals)} signal(s) detected:")
        for s in signals[:5]:
            for reason in s.get("reasons", []):
                lines.append(f"  {reason}")

    return "\n".join(lines)
