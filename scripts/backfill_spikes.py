#!/usr/bin/env python3
"""
Pythia Spike Backfill — Fetch historical Polymarket data, detect spikes,
run attribution pipeline, and train the heterogeneous effects model.

Usage:
    python scripts/backfill_spikes.py                  # Backfill top 50 markets
    python scripts/backfill_spikes.py --markets 20     # Backfill top 20
    python scripts/backfill_spikes.py --train-only      # Skip backfill, just retrain P3
    python scripts/backfill_spikes.py --dry-run         # Show what would be detected, don't save

Data flow:
    1. Fetch top N liquid Polymarket markets from Gamma API
    2. For each market, fetch full price history from CLOB API (interval=max)
    3. Run spike detection on sliding 2-hour windows
    4. For each spike: classify, search news, build context, save to DB
    5. After all markets processed: train EconML heterogeneous effects model

Rate limiting:
    - Gamma API: ~60 req/min (no auth needed)
    - CLOB API: ~60 req/min (no auth needed)
    - NewsAPI: 100 req/day (free tier) — used sparingly for high-magnitude spikes only
    - DuckDuckGo/Google News: best-effort, with delays

Estimated runtime: ~10-15 minutes for 50 markets.
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import httpx
import numpy as np
import pandas as pd

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.database import PythiaDB
from core.config import Config
from core.spike_archive import SpikeEvent, save_spike

logger = logging.getLogger("backfill")

# API endpoints
GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"

# Rate limiting
REQUEST_DELAY = 1.0  # seconds between API calls
NEWS_DELAY = 2.0     # seconds between news searches (more conservative)


# ------------------------------------------------------------------ #
# Step 1: Fetch markets
# ------------------------------------------------------------------ #

def fetch_top_markets(client: httpx.Client, limit: int = 50) -> List[Dict]:
    """Fetch top markets by liquidity from Gamma API."""
    all_markets = []
    offset = 0
    page_size = min(limit, 100)

    while len(all_markets) < limit:
        try:
            resp = client.get(f"{GAMMA_URL}/markets", params={
                "active": "true",
                "closed": "false",
                "limit": page_size,
                "offset": offset,
                "order": "liquidityNum",
                "ascending": "false",
            })
            resp.raise_for_status()
            markets = resp.json()

            if not markets:
                break

            for m in markets:
                clob_ids = m.get("clobTokenIds", "")
                if isinstance(clob_ids, str):
                    try:
                        clob_ids = json.loads(clob_ids)
                    except Exception:
                        clob_ids = []

                if not clob_ids:
                    continue

                all_markets.append({
                    "id": m.get("conditionId", ""),
                    "title": m.get("question", m.get("title", "")),
                    "slug": m.get("slug", ""),
                    "token_id": clob_ids[0],
                    "liquidity": float(m.get("liquidity", 0) or 0),
                    "volume": float(m.get("volume", 0) or 0),
                    "source": "polymarket",
                    "category": m.get("groupItemTitle", ""),
                })

            offset += page_size
            time.sleep(REQUEST_DELAY)

        except Exception as e:
            logger.error("Failed to fetch markets (offset=%d): %s", offset, e)
            break

    return all_markets[:limit]


# ------------------------------------------------------------------ #
# Step 2: Fetch price history
# ------------------------------------------------------------------ #

def fetch_price_history(client: httpx.Client, token_id: str) -> pd.DataFrame:
    """Fetch full price history for a market from CLOB API."""
    try:
        resp = client.get(f"{CLOB_URL}/prices-history", params={
            "market": token_id,
            "interval": "max",
        })
        resp.raise_for_status()
        data = resp.json()

        history = data.get("history", [])
        if not history:
            return pd.DataFrame()

        df = pd.DataFrame(history)
        df["timestamp"] = pd.to_datetime(df["t"], unit="s", utc=True)
        df["yes_price"] = df["p"].astype(float)
        df = df.sort_values("timestamp").reset_index(drop=True)

        return df[["timestamp", "yes_price"]]

    except Exception as e:
        logger.warning("Failed to fetch history for token %s: %s", token_id[:20], e)
        return pd.DataFrame()


# ------------------------------------------------------------------ #
# Step 3: Detect spikes in historical data
# ------------------------------------------------------------------ #

def detect_spikes_in_history(
    df: pd.DataFrame,
    market_id: str,
    market_title: str,
    threshold: float = 0.05,
    window_hours: float = 2.0,
    min_gap_hours: float = 4.0,
) -> List[SpikeEvent]:
    """
    Scan price history for spikes using sliding window.

    Args:
        df: DataFrame with timestamp and yes_price columns
        market_id: Market identifier
        market_title: Market title for context
        threshold: Minimum absolute price change to qualify (0-1)
        window_hours: Sliding window size in hours
        min_gap_hours: Minimum gap between detected spikes (dedup)

    Returns:
        List of SpikeEvent objects
    """
    if df.empty or len(df) < 10:
        return []

    spikes = []
    last_spike_ts = None

    # Slide through data
    for i in range(len(df)):
        current_ts = df.iloc[i]["timestamp"]
        current_price = float(df.iloc[i]["yes_price"])

        # Look back window_hours
        window_start = current_ts - timedelta(hours=window_hours)
        window = df[(df["timestamp"] >= window_start) & (df["timestamp"] <= current_ts)]

        if len(window) < 3:
            continue

        prices = window["yes_price"].values.astype(float)
        first_price = prices[0]
        magnitude = abs(current_price - first_price)

        if magnitude < threshold:
            continue

        # Enforce minimum gap between spikes
        if last_spike_ts is not None:
            gap = (current_ts - last_spike_ts).total_seconds() / 3600
            if gap < min_gap_hours:
                continue

        direction = "up" if current_price > first_price else "down"

        spike = SpikeEvent(
            id=0,
            market_id=market_id,
            market_title=market_title,
            timestamp=current_ts.to_pydatetime() if hasattr(current_ts, "to_pydatetime") else current_ts,
            direction=direction,
            magnitude=magnitude,
            price_before=first_price,
            price_after=current_price,
            volume_at_spike=0,  # Not available in price history
            asset_class="",     # Classified later
        )

        spikes.append(spike)
        last_spike_ts = current_ts

    return spikes


# ------------------------------------------------------------------ #
# Step 4: Classify and attribute spikes
# ------------------------------------------------------------------ #

def classify_spike(spike: SpikeEvent) -> str:
    """Classify spike into market category using keyword matching."""
    # Reuse the category keywords from causal_v2
    CATEGORY_KEYWORDS = {
        "fed_rate": ["fed", "federal reserve", "fomc", "interest rate", "powell", "rate cut", "rate hike"],
        "inflation": ["inflation", "cpi", "pce", "consumer price"],
        "election": ["election", "president", "vote", "candidate", "democrat", "republican", "trump", "biden"],
        "crypto": ["bitcoin", "btc", "ethereum", "eth", "crypto"],
        "trade_war": ["tariff", "trade war", "sanctions"],
        "geopolitical": ["war", "ceasefire", "nato", "invasion", "military"],
        "tech": ["openai", "gpt", "google", "apple", "ai regulation", "antitrust"],
        "recession": ["recession", "gdp", "unemployment", "yield curve", "layoffs"],
        "energy": ["oil", "opec", "natural gas", "energy"],
    }

    title_lower = spike.market_title.lower()
    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in title_lower)
        if score > 0:
            scores[cat] = score

    return max(scores, key=scores.get) if scores else "general"


def light_attribution(spike: SpikeEvent) -> List[Dict]:
    """
    Lightweight attribution using DuckDuckGo search.
    Skips LLM calls — just finds temporally relevant news headlines.
    Used for backfill to avoid burning API credits.
    """
    from urllib.parse import quote_plus
    import requests
    from bs4 import BeautifulSoup

    try:
        # Build search query
        title = spike.market_title.strip("?").strip()
        ts = spike.timestamp
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        date_str = ts.strftime("%Y-%m-%d")
        query = f"{title} {date_str}"

        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        resp = requests.get(url, timeout=5, headers={
            "User-Agent": "Mozilla/5.0 (compatible; PythiaBackfill/1.0)"
        })
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        for result in soup.select(".result__body")[:3]:
            title_el = result.select_one(".result__a")
            if not title_el:
                continue
            results.append({
                "headline": title_el.get_text(strip=True)[:200],
                "source": "duckduckgo",
                "url": title_el.get("href", ""),
            })

        return results

    except Exception as e:
        logger.debug("Light attribution failed for %s: %s", spike.market_title[:30], e)
        return []


# ------------------------------------------------------------------ #
# Step 5: Train heterogeneous effects model
# ------------------------------------------------------------------ #

def retrain_model(db: PythiaDB) -> Dict:
    """Train the EconML heterogeneous effects model on accumulated spike data."""
    try:
        from core.heterogeneous_effects import train_heterogeneous_model
        result = train_heterogeneous_model(db, n_estimators=200, save=True)
        return result
    except ImportError:
        logger.warning("heterogeneous_effects module not available")
        return {"error": "module_not_available"}
    except Exception as e:
        logger.error("Model training failed: %s", e)
        return {"error": str(e)}


# ------------------------------------------------------------------ #
# Main pipeline
# ------------------------------------------------------------------ #

def run_backfill(
    n_markets: int = 50,
    spike_threshold: float = 0.05,
    dry_run: bool = False,
    train_after: bool = True,
    db_path: str = None,
):
    """
    Run the full backfill pipeline.

    1. Fetch top N markets
    2. For each: fetch history → detect spikes → classify → attribute → save
    3. Train P3 model on accumulated data
    """
    if db_path is None:
        db_path = str(PROJECT_ROOT / "data" / "pythia_live.db")

    db = PythiaDB(db_path) if not dry_run else None

    client = httpx.Client(
        headers={"Accept": "application/json"},
        follow_redirects=True,
        timeout=15,
    )

    # Step 1: Fetch markets
    logger.info("Fetching top %d markets by liquidity...", n_markets)
    markets = fetch_top_markets(client, limit=n_markets)
    logger.info("Found %d markets with CLOB token IDs", len(markets))

    total_spikes = 0
    total_attributed = 0
    market_stats = []

    for i, market in enumerate(markets):
        title = market["title"][:50]
        logger.info("[%d/%d] %s", i + 1, len(markets), title)

        # Step 2: Fetch history
        time.sleep(REQUEST_DELAY)
        history = fetch_price_history(client, market["token_id"])
        if history.empty:
            logger.info("  No history — skipping")
            continue

        # Save market to DB
        if db:
            db.save_market({
                "id": market["id"],
                "title": market["title"],
                "source": "polymarket",
                "yes_price": float(history.iloc[-1]["yes_price"]),
                "no_price": 1 - float(history.iloc[-1]["yes_price"]),
                "volume_24h": market["volume"],
                "liquidity": market["liquidity"],
                "slug": market["slug"],
            })

        # Step 3: Detect spikes
        spikes = detect_spikes_in_history(
            history,
            market_id=market["id"],
            market_title=market["title"],
            threshold=spike_threshold,
        )

        if not spikes:
            logger.info("  %d points, 0 spikes", len(history))
            continue

        logger.info("  %d points, %d spikes detected", len(history), len(spikes))

        # Step 4: Classify and attribute each spike
        for spike in spikes:
            spike.asset_class = classify_spike(spike)

            # Light attribution (DuckDuckGo only, no LLM)
            # Attribute all detected spikes — threshold matches detection (5%)
            time.sleep(NEWS_DELAY)
            spike.attributed_events = light_attribution(spike)
            if spike.attributed_events:
                total_attributed += 1

            if dry_run:
                logger.info(
                    "  [DRY RUN] %s %s %.1f%% (%s) — %d articles",
                    spike.direction,
                    spike.asset_class,
                    spike.magnitude * 100,
                    spike.timestamp,
                    len(spike.attributed_events),
                )
            else:
                save_spike(db, spike)

            total_spikes += 1

        market_stats.append({
            "title": market["title"][:50],
            "points": len(history),
            "spikes": len(spikes),
        })

    client.close()

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("BACKFILL COMPLETE")
    logger.info("  Markets processed: %d", len(markets))
    logger.info("  Total spikes: %d", total_spikes)
    logger.info("  Attributed (>8%%): %d", total_attributed)
    logger.info("=" * 60)

    # Step 5: Train model
    if train_after and not dry_run and db:
        logger.info("")
        logger.info("Training heterogeneous effects model...")
        result = retrain_model(db)
        if result.get("error"):
            logger.warning("Training result: %s", result)
        else:
            logger.info(
                "Model trained: n=%d ATE=%.4f [%.4f, %.4f]",
                result.get("n_samples", 0),
                result.get("ate", 0),
                result.get("ate_ci_lower", 0),
                result.get("ate_ci_upper", 0),
            )

    return {
        "markets_processed": len(markets),
        "total_spikes": total_spikes,
        "total_attributed": total_attributed,
        "market_stats": market_stats,
    }


# ------------------------------------------------------------------ #
# CLI
# ------------------------------------------------------------------ #

def main():
    parser = argparse.ArgumentParser(description="Pythia Spike Backfill")
    parser.add_argument("--markets", type=int, default=50, help="Number of markets to backfill")
    parser.add_argument("--threshold", type=float, default=0.05, help="Spike detection threshold (0-1)")
    parser.add_argument("--db", type=str, default=None, help="Database path")
    parser.add_argument("--dry-run", action="store_true", help="Don't save to DB, just show detections")
    parser.add_argument("--train-only", action="store_true", help="Skip backfill, just retrain model")
    parser.add_argument("--no-train", action="store_true", help="Skip model training after backfill")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.train_only:
        db_path = args.db or str(PROJECT_ROOT / "data" / "pythia_live.db")
        db = PythiaDB(db_path)
        logger.info("Training model only...")
        result = retrain_model(db)
        logger.info("Result: %s", json.dumps(result, indent=2, default=str))
        return

    run_backfill(
        n_markets=args.markets,
        spike_threshold=args.threshold,
        dry_run=args.dry_run,
        train_after=not args.no_train,
        db_path=args.db,
    )


if __name__ == "__main__":
    main()
