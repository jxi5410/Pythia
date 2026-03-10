"""
Crypto Deep Signals — Extended coverage from CoinGlass, DeFiLlama, Whale Alert,
CoinGecko, and Mempool.space for deeper market intelligence.
"""
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import certifi
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache (same pattern as crypto_onchain.py)
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
# HTTP helpers
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _get(url: str, params: dict = None, timeout: int = 15, headers: dict = None) -> requests.Response:
    """GET with SSL via certifi and standard headers."""
    return requests.get(
        url,
        params=params,
        headers={**_HEADERS, **(headers or {})},
        timeout=timeout,
        verify=certifi.where(),
    )


# ---------------------------------------------------------------------------
# CryptoDeepSignals
# ---------------------------------------------------------------------------

class CryptoDeepSignals:
    """Aggregates deep crypto signals from multiple free data sources."""

    # -------------------------------------------------------------------
    # 1. CoinGlass — Funding Rates
    # -------------------------------------------------------------------

    def get_funding_rates(self) -> Dict[str, Dict[str, float]]:
        """Funding rates across major exchanges for BTC and ETH.

        Returns dict keyed by symbol, each containing exchange -> rate.
        """
        cached = _cached("deep_funding_rates")
        if cached is not None:
            return cached

        result: Dict[str, Dict[str, float]] = {"BTC": {}, "ETH": {}}

        for symbol in ("BTC", "ETH"):
            try:
                resp = _get(
                    "https://open-api.coinglass.com/public/v2/funding",
                    params={"symbol": symbol, "time_type": "h8"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success") and data.get("data"):
                        for item in data["data"]:
                            exchange = item.get("exchangeName", "unknown")
                            rate = item.get("rate", 0)
                            result[symbol][exchange] = round(rate, 6)
            except Exception as e:
                logger.warning(f"CoinGlass funding fetch failed for {symbol}: {e}")

        # Fallback: try the public web JSON endpoint
        if not result["BTC"]:
            try:
                resp = _get(
                    "https://fapi.coinglass.com/api/fundingRate/v2/home",
                    headers={"Accept": "application/json"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("data", [])
                    for item in items:
                        sym = item.get("symbol", "").upper()
                        if sym in ("BTC", "ETH"):
                            for ex_data in item.get("uMarginList", []):
                                ex_name = ex_data.get("exchangeName", "unknown")
                                rate = ex_data.get("rate", 0)
                                result[sym][ex_name] = round(rate, 6)
            except Exception as e:
                logger.warning(f"CoinGlass fallback funding fetch failed: {e}")

        _set_cache("deep_funding_rates", result)
        return result

    # -------------------------------------------------------------------
    # 2. CoinGlass — Liquidations
    # -------------------------------------------------------------------

    def get_liquidations(self, hours: int = 24) -> dict:
        """Total long/short liquidations in the last N hours.

        Returns dict with total_long_usd, total_short_usd, ratio, dominant_side.
        """
        cache_key = f"deep_liquidations_{hours}"
        cached = _cached(cache_key)
        if cached is not None:
            return cached

        result = {
            "total_long_usd": 0.0,
            "total_short_usd": 0.0,
            "ratio": 1.0,
            "dominant_side": "balanced",
            "hours": hours,
            "source": "coinglass",
        }

        try:
            resp = _get(
                "https://open-api.coinglass.com/public/v2/liquidation_history",
                params={"symbol": "all", "time_type": "h1"},
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") and data.get("data"):
                    total_long = 0.0
                    total_short = 0.0
                    for item in data["data"][-hours:]:
                        total_long += float(item.get("longLiquidationUsd", 0))
                        total_short += float(item.get("shortLiquidationUsd", 0))
                    result["total_long_usd"] = round(total_long, 2)
                    result["total_short_usd"] = round(total_short, 2)
        except Exception as e:
            logger.warning(f"CoinGlass liquidation fetch failed: {e}")

        # Fallback: scrape liquidation summary page JSON
        if result["total_long_usd"] == 0 and result["total_short_usd"] == 0:
            try:
                resp = _get(
                    "https://fapi.coinglass.com/api/futures/liquidation/chart",
                    params={"symbol": "all", "timeType": "2"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("data", {}).get("dataMap", {})
                    for _, vals in items.items():
                        if isinstance(vals, list):
                            for v in vals[-min(hours, len(vals)):]:
                                result["total_long_usd"] += float(v.get("longVolUsd", 0))
                                result["total_short_usd"] += float(v.get("shortVolUsd", 0))
                    result["total_long_usd"] = round(result["total_long_usd"], 2)
                    result["total_short_usd"] = round(result["total_short_usd"], 2)
            except Exception as e:
                logger.warning(f"CoinGlass liquidation fallback failed: {e}")

        # Compute ratio and dominant side
        long_val = result["total_long_usd"]
        short_val = result["total_short_usd"]
        if long_val > 0 and short_val > 0:
            result["ratio"] = round(long_val / short_val, 2)
            if long_val > short_val * 1.5:
                result["dominant_side"] = "long_liquidations"
            elif short_val > long_val * 1.5:
                result["dominant_side"] = "short_liquidations"
            else:
                result["dominant_side"] = "balanced"

        _set_cache(cache_key, result)
        return result

    # -------------------------------------------------------------------
    # 3. DeFiLlama — TVL Changes
    # -------------------------------------------------------------------

    def get_defi_tvl_changes(self, hours: int = 24) -> dict:
        """Top DeFi protocol TVL gainers and losers.

        Returns dict with total_tvl, top_gainers, top_losers, chain_tvl.
        """
        cache_key = f"deep_defi_tvl_{hours}"
        cached = _cached(cache_key)
        if cached is not None:
            return cached

        result = {
            "total_tvl": 0.0,
            "top_gainers": [],
            "top_losers": [],
            "chain_tvl": {},
            "hours": hours,
            "source": "defillama",
        }

        # Fetch all protocols
        try:
            resp = _get("https://api.llama.fi/protocols", timeout=20)
            resp.raise_for_status()
            protocols = resp.json()

            scored = []
            for p in protocols:
                name = p.get("name", "unknown")
                tvl = p.get("tvl", 0)
                change_1d = p.get("change_1d")

                if tvl and tvl > 1_000_000 and change_1d is not None:
                    scored.append({
                        "name": name,
                        "tvl": round(tvl, 0),
                        "change_pct": round(change_1d, 2),
                        "chain": p.get("chain", "Multi"),
                        "category": p.get("category", ""),
                    })

            scored.sort(key=lambda x: x["change_pct"], reverse=True)
            result["top_gainers"] = scored[:10]
            result["top_losers"] = scored[-10:][::-1]  # worst first
            result["total_tvl"] = round(sum(p.get("tvl", 0) for p in protocols), 0)

        except Exception as e:
            logger.warning(f"DeFiLlama protocols fetch failed: {e}")

        # Fetch chain-level TVL
        try:
            resp = _get("https://api.llama.fi/v2/chains", timeout=15)
            resp.raise_for_status()
            chains = resp.json()
            for chain in chains[:20]:
                name = chain.get("name", "unknown")
                tvl = chain.get("tvl", 0)
                if tvl:
                    result["chain_tvl"][name] = round(tvl, 0)
        except Exception as e:
            logger.warning(f"DeFiLlama chains fetch failed: {e}")

        _set_cache(cache_key, result)
        return result

    # -------------------------------------------------------------------
    # 4. Whale Alert — Large Transactions
    # -------------------------------------------------------------------

    def get_whale_transactions(self, min_usd: int = 1_000_000) -> List[dict]:
        """Recent large crypto transactions from Whale Alert.

        Returns list of transaction dicts with amount, currency, from, to, usd_value.
        """
        cache_key = f"deep_whale_{min_usd}"
        cached = _cached(cache_key)
        if cached is not None:
            return cached

        transactions: List[dict] = []

        try:
            start_ts = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
            resp = _get(
                "https://api.whale-alert.io/v1/transactions",
                params={
                    "min_value": min_usd,
                    "start": start_ts,
                    "cursor": "",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("result") == "success":
                    for tx in data.get("transactions", []):
                        transactions.append({
                            "blockchain": tx.get("blockchain", "unknown"),
                            "symbol": tx.get("symbol", "").upper(),
                            "amount": tx.get("amount", 0),
                            "usd_value": round(tx.get("amount_usd", 0), 0),
                            "from_owner": tx.get("from", {}).get("owner", "unknown"),
                            "from_type": tx.get("from", {}).get("owner_type", "unknown"),
                            "to_owner": tx.get("to", {}).get("owner", "unknown"),
                            "to_type": tx.get("to", {}).get("owner_type", "unknown"),
                            "tx_hash": tx.get("hash", ""),
                            "timestamp": datetime.fromtimestamp(
                                tx.get("timestamp", 0), tz=timezone.utc
                            ).isoformat(),
                        })
            elif resp.status_code == 401:
                logger.info("Whale Alert requires API key for this request")
        except Exception as e:
            logger.warning(f"Whale Alert fetch failed: {e}")

        # Fallback: use mempool.space for BTC whale txs (same as crypto_onchain)
        if not transactions:
            try:
                resp = _get("https://mempool.space/api/mempool/recent", timeout=10)
                if resp.status_code == 200:
                    mempool_txs = resp.json()
                    for tx in mempool_txs:
                        value_btc = tx.get("value", 0) / 1e8
                        # Rough USD estimate
                        usd_est = value_btc * _get_btc_price_quick()
                        if usd_est >= min_usd:
                            transactions.append({
                                "blockchain": "bitcoin",
                                "symbol": "BTC",
                                "amount": round(value_btc, 4),
                                "usd_value": round(usd_est, 0),
                                "from_owner": "unknown",
                                "from_type": "unknown",
                                "to_owner": "unknown",
                                "to_type": "unknown",
                                "tx_hash": tx.get("txid", ""),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
            except Exception as e:
                logger.warning(f"Mempool whale fallback failed: {e}")

        transactions.sort(key=lambda x: x["usd_value"], reverse=True)
        transactions = transactions[:50]

        _set_cache(cache_key, transactions)
        return transactions

    # -------------------------------------------------------------------
    # 5. Mempool.space — BTC Mempool Congestion
    # -------------------------------------------------------------------

    def get_btc_mempool(self) -> dict:
        """BTC mempool size, fee rates, and congestion level.

        Returns dict with tx_count, vsize_mb, fee_histogram, recommended_fees,
        congestion_level (low/medium/high/extreme).
        """
        cached = _cached("deep_btc_mempool")
        if cached is not None:
            return cached

        result = {
            "tx_count": 0,
            "vsize_mb": 0.0,
            "recommended_fees": {},
            "congestion_level": "unknown",
            "source": "mempool.space",
        }

        # Mempool stats
        try:
            resp = _get("https://mempool.space/api/mempool", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                result["tx_count"] = data.get("count", 0)
                vsize_bytes = data.get("vsize", 0)
                result["vsize_mb"] = round(vsize_bytes / 1_000_000, 2)
        except Exception as e:
            logger.warning(f"Mempool stats fetch failed: {e}")

        # Recommended fees
        try:
            resp = _get("https://mempool.space/api/v1/fees/recommended", timeout=10)
            if resp.status_code == 200:
                fees = resp.json()
                result["recommended_fees"] = {
                    "fastest": fees.get("fastestFee", 0),
                    "half_hour": fees.get("halfHourFee", 0),
                    "hour": fees.get("hourFee", 0),
                    "economy": fees.get("economyFee", 0),
                    "minimum": fees.get("minimumFee", 0),
                }
        except Exception as e:
            logger.warning(f"Mempool fee fetch failed: {e}")

        # Congestion level based on tx count and fees
        tx_count = result["tx_count"]
        fastest_fee = result["recommended_fees"].get("fastest", 0)

        if tx_count > 150_000 or fastest_fee > 100:
            result["congestion_level"] = "extreme"
        elif tx_count > 80_000 or fastest_fee > 50:
            result["congestion_level"] = "high"
        elif tx_count > 30_000 or fastest_fee > 15:
            result["congestion_level"] = "medium"
        else:
            result["congestion_level"] = "low"

        _set_cache("deep_btc_mempool", result)
        return result

    # -------------------------------------------------------------------
    # 6. CoinGecko — Fear & Greed Proxy
    # -------------------------------------------------------------------

    def get_fear_greed(self) -> dict:
        """Composite sentiment score from price/volume/market cap data.

        Combines Alternative.me Fear & Greed Index with CoinGecko market data.
        Returns dict with score (0-100), label, components.
        """
        cached = _cached("deep_fear_greed")
        if cached is not None:
            return cached

        result = {
            "score": 50,
            "label": "Neutral",
            "components": {},
            "source": "composite",
        }

        # Primary: Alternative.me Fear & Greed
        fng_score = None
        try:
            resp = _get(
                "https://api.alternative.me/fng/",
                params={"limit": 7, "format": "json"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if data:
                fng_score = int(data[0]["value"])
                result["components"]["fear_greed_index"] = fng_score
                result["components"]["fng_classification"] = data[0].get("value_classification", "")
                if len(data) >= 7:
                    result["components"]["fng_7d_ago"] = int(data[-1]["value"])
        except Exception as e:
            logger.warning(f"Fear & Greed Index fetch failed: {e}")

        # Secondary: CoinGecko market data for volatility / momentum signals
        vol_score = None
        try:
            resp = _get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={
                    "vs_currency": "usd",
                    "ids": "bitcoin,ethereum",
                    "order": "market_cap_desc",
                    "sparkline": "false",
                    "price_change_percentage": "24h,7d",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                coins = resp.json()
                changes = []
                for coin in coins:
                    c24 = coin.get("price_change_percentage_24h", 0) or 0
                    c7d = coin.get("price_change_percentage_7d_in_currency", 0) or 0
                    changes.append(c24)
                    changes.append(c7d)
                    result["components"][f"{coin['symbol']}_24h_pct"] = round(c24, 2)
                    result["components"][f"{coin['symbol']}_7d_pct"] = round(c7d, 2)

                if changes:
                    avg_change = sum(changes) / len(changes)
                    # Map avg change to 0-100 scale: -10% -> 0, +10% -> 100
                    vol_score = max(0, min(100, int(50 + avg_change * 5)))
                    result["components"]["momentum_score"] = vol_score
        except Exception as e:
            logger.warning(f"CoinGecko market data fetch failed: {e}")

        # Composite: weighted average
        scores = []
        weights = []
        if fng_score is not None:
            scores.append(fng_score)
            weights.append(0.7)
        if vol_score is not None:
            scores.append(vol_score)
            weights.append(0.3)

        if scores:
            total_weight = sum(weights)
            composite = sum(s * w for s, w in zip(scores, weights)) / total_weight
            result["score"] = round(composite)
        else:
            result["score"] = 50

        # Label
        s = result["score"]
        if s <= 20:
            result["label"] = "Extreme Fear"
        elif s <= 40:
            result["label"] = "Fear"
        elif s <= 60:
            result["label"] = "Neutral"
        elif s <= 80:
            result["label"] = "Greed"
        else:
            result["label"] = "Extreme Greed"

        _set_cache("deep_fear_greed", result)
        return result

    # -------------------------------------------------------------------
    # 7. Combined Signal Summary
    # -------------------------------------------------------------------

    def get_crypto_signal_summary(self) -> dict:
        """Combined summary of all deep crypto signals for the companion bot.

        Returns dict with all signal categories plus an overall_sentiment.
        """
        cached = _cached("deep_signal_summary")
        if cached is not None:
            return cached

        summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "funding_rates": {},
            "liquidations": {},
            "defi_tvl": {},
            "whale_transactions": [],
            "btc_mempool": {},
            "fear_greed": {},
            "overall_sentiment": "neutral",
            "signal_count": 0,
            "signals": [],
        }

        # Gather all data sources
        try:
            summary["funding_rates"] = self.get_funding_rates()
        except Exception as e:
            logger.error(f"Deep funding rates error: {e}")

        try:
            summary["liquidations"] = self.get_liquidations(hours=24)
        except Exception as e:
            logger.error(f"Deep liquidations error: {e}")

        try:
            summary["defi_tvl"] = self.get_defi_tvl_changes(hours=24)
        except Exception as e:
            logger.error(f"Deep DeFi TVL error: {e}")

        try:
            summary["whale_transactions"] = self.get_whale_transactions(min_usd=1_000_000)
        except Exception as e:
            logger.error(f"Deep whale transactions error: {e}")

        try:
            summary["btc_mempool"] = self.get_btc_mempool()
        except Exception as e:
            logger.error(f"Deep BTC mempool error: {e}")

        try:
            summary["fear_greed"] = self.get_fear_greed()
        except Exception as e:
            logger.error(f"Deep fear & greed error: {e}")

        # Derive signals and overall sentiment
        bullish_points = 0
        bearish_points = 0
        signals = []

        # Funding rates signal
        fr = summary["funding_rates"]
        for sym in ("BTC", "ETH"):
            rates = fr.get(sym, {})
            if rates:
                avg_rate = sum(rates.values()) / len(rates)
                if avg_rate > 0.01:
                    bearish_points += 1
                    signals.append(f"{sym} funding high ({avg_rate:+.4f}%) — overleveraged longs")
                elif avg_rate < -0.01:
                    bullish_points += 1
                    signals.append(f"{sym} funding negative ({avg_rate:+.4f}%) — overleveraged shorts")

        # Liquidations signal
        liqs = summary["liquidations"]
        if liqs.get("dominant_side") == "long_liquidations":
            bearish_points += 1
            signals.append(
                f"Long liquidations dominant: ${liqs['total_long_usd']/1e6:.0f}M long "
                f"vs ${liqs['total_short_usd']/1e6:.0f}M short"
            )
        elif liqs.get("dominant_side") == "short_liquidations":
            bullish_points += 1
            signals.append(
                f"Short liquidations dominant: ${liqs['total_short_usd']/1e6:.0f}M short "
                f"vs ${liqs['total_long_usd']/1e6:.0f}M long"
            )

        # DeFi TVL signal
        defi = summary["defi_tvl"]
        gainers = defi.get("top_gainers", [])
        losers = defi.get("top_losers", [])
        if gainers and losers:
            avg_gain = sum(g["change_pct"] for g in gainers[:5]) / min(5, len(gainers))
            avg_loss = sum(l["change_pct"] for l in losers[:5]) / min(5, len(losers))
            if avg_gain > 10:
                bullish_points += 1
                signals.append(f"DeFi TVL surging: top gainers avg +{avg_gain:.1f}%")
            if avg_loss < -10:
                bearish_points += 1
                signals.append(f"DeFi TVL declining: top losers avg {avg_loss:.1f}%")

        # Whale signal
        whales = summary["whale_transactions"]
        if whales:
            exchange_inflows = [w for w in whales if w.get("to_type") == "exchange"]
            exchange_outflows = [w for w in whales if w.get("from_type") == "exchange"]
            if len(exchange_inflows) > len(exchange_outflows) * 1.5:
                bearish_points += 1
                signals.append(f"Whale exchange inflows dominating ({len(exchange_inflows)} in vs {len(exchange_outflows)} out)")
            elif len(exchange_outflows) > len(exchange_inflows) * 1.5:
                bullish_points += 1
                signals.append(f"Whale exchange outflows dominating ({len(exchange_outflows)} out vs {len(exchange_inflows)} in)")

        # Mempool signal
        mempool = summary["btc_mempool"]
        congestion = mempool.get("congestion_level", "unknown")
        if congestion in ("high", "extreme"):
            signals.append(f"BTC mempool congestion: {congestion} ({mempool.get('tx_count', 0):,} txs)")

        # Fear & Greed signal
        fg = summary["fear_greed"]
        fg_score = fg.get("score", 50)
        if fg_score <= 25:
            bullish_points += 1  # contrarian: extreme fear = buying opportunity
            signals.append(f"Extreme Fear ({fg_score}) — contrarian bullish signal")
        elif fg_score >= 75:
            bearish_points += 1  # contrarian: extreme greed = sell signal
            signals.append(f"Extreme Greed ({fg_score}) — contrarian bearish signal")

        # Overall sentiment
        if bullish_points > bearish_points + 1:
            summary["overall_sentiment"] = "bullish"
        elif bearish_points > bullish_points + 1:
            summary["overall_sentiment"] = "bearish"
        else:
            summary["overall_sentiment"] = "neutral"

        summary["signals"] = signals
        summary["signal_count"] = len(signals)

        _set_cache("deep_signal_summary", summary)
        return summary


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_btc_price_quick() -> float:
    """Quick BTC price from CoinGecko (cached)."""
    cached = _cached("deep_btc_price")
    if cached is not None:
        return cached
    try:
        r = _get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"},
            timeout=10,
        )
        price = r.json()["bitcoin"]["usd"]
    except Exception:
        price = 95000.0
    _set_cache("deep_btc_price", price)
    return price


# ---------------------------------------------------------------------------
# Public convenience function for companion bot
# ---------------------------------------------------------------------------

def get_crypto_deep_context() -> str:
    """Return a formatted string summary of all deep crypto signals,
    suitable for the companion bot to use when a trader asks about crypto."""

    ds = CryptoDeepSignals()
    summary = ds.get_crypto_signal_summary()

    lines = []
    lines.append("=== CRYPTO DEEP INTELLIGENCE ===")
    lines.append(f"Timestamp: {summary['timestamp']}")
    lines.append(f"Overall Sentiment: {summary['overall_sentiment'].upper()}")
    lines.append("")

    # Fear & Greed
    fg = summary.get("fear_greed", {})
    if fg.get("score") is not None:
        lines.append(f"Fear & Greed: {fg['score']} ({fg.get('label', 'N/A')})")
        components = fg.get("components", {})
        if components.get("btc_24h_pct") is not None:
            lines.append(f"  BTC 24h: {components['btc_24h_pct']:+.1f}%  |  7d: {components.get('btc_7d_pct', 0):+.1f}%")
        if components.get("eth_24h_pct") is not None:
            lines.append(f"  ETH 24h: {components['eth_24h_pct']:+.1f}%  |  7d: {components.get('eth_7d_pct', 0):+.1f}%")
        lines.append("")

    # Funding Rates
    fr = summary.get("funding_rates", {})
    if fr.get("BTC") or fr.get("ETH"):
        lines.append("Funding Rates:")
        for sym in ("BTC", "ETH"):
            rates = fr.get(sym, {})
            if rates:
                avg = sum(rates.values()) / len(rates)
                top_exchanges = sorted(rates.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
                ex_str = ", ".join(f"{ex}:{r:+.4f}%" for ex, r in top_exchanges)
                lines.append(f"  {sym} avg: {avg:+.4f}%  [{ex_str}]")
        lines.append("")

    # Liquidations
    liqs = summary.get("liquidations", {})
    if liqs.get("total_long_usd") or liqs.get("total_short_usd"):
        lines.append("Liquidations (24h):")
        lines.append(f"  Longs: ${liqs['total_long_usd']/1e6:.1f}M  |  Shorts: ${liqs['total_short_usd']/1e6:.1f}M")
        lines.append(f"  Dominant: {liqs.get('dominant_side', 'balanced')}")
        lines.append("")

    # DeFi TVL
    defi = summary.get("defi_tvl", {})
    total_tvl = defi.get("total_tvl", 0)
    if total_tvl:
        lines.append(f"DeFi Total TVL: ${total_tvl/1e9:.1f}B")
        gainers = defi.get("top_gainers", [])[:3]
        losers = defi.get("top_losers", [])[:3]
        if gainers:
            lines.append("  Top Gainers: " + ", ".join(
                f"{g['name']} ({g['change_pct']:+.1f}%)" for g in gainers
            ))
        if losers:
            lines.append("  Top Losers: " + ", ".join(
                f"{l['name']} ({l['change_pct']:+.1f}%)" for l in losers
            ))
        lines.append("")

    # Whale Transactions
    whales = summary.get("whale_transactions", [])
    if whales:
        lines.append(f"Whale Transactions: {len(whales)} large transfers detected")
        for w in whales[:5]:
            lines.append(
                f"  {w['symbol']} {w['amount']:,.0f} (${w['usd_value']/1e6:.1f}M) "
                f"{w['from_owner']}→{w['to_owner']}"
            )
        lines.append("")

    # BTC Mempool
    mempool = summary.get("btc_mempool", {})
    if mempool.get("tx_count"):
        fees = mempool.get("recommended_fees", {})
        lines.append(f"BTC Mempool: {mempool['tx_count']:,} txs ({mempool['vsize_mb']:.1f} MB)")
        lines.append(f"  Congestion: {mempool.get('congestion_level', 'unknown')}")
        if fees:
            lines.append(f"  Fees: fastest={fees.get('fastest', 0)} sat/vB, hour={fees.get('hour', 0)} sat/vB")
        lines.append("")

    # Active Signals
    sigs = summary.get("signals", [])
    if sigs:
        lines.append(f"Active Signals ({len(sigs)}):")
        for sig in sigs:
            lines.append(f"  - {sig}")
    else:
        lines.append("No active deep signals detected.")

    return "\n".join(lines)
