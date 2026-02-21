"""
Backtesting Framework — Tests prediction market → equity correlations on historical data.
"""
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
except ImportError:
    yf = None

from .equities import get_related_tickers, CATEGORY_TICKERS
from .causal_v2 import classify_market

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "equity_cache"
PATTERN_LIBRARY = Path("/Users/xj.ai/.openclaw/workspace/pythia_pattern_library.json")
DEFAULT_DB = DATA_DIR / "pythia_live.db"


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_becker_spikes(path: str = None) -> List[Dict]:
    """Load spikes from pattern library JSON or SQLite database."""
    spikes = []

    # Try pattern library JSON
    lib_path = Path(path) if path else PATTERN_LIBRARY
    if lib_path.exists():
        try:
            with open(lib_path) as f:
                data = json.load(f)
            # Extract spike-like records from the pattern library
            if isinstance(data, dict):
                # Pattern library has meta + various pattern sections
                for key in ["temporal_patterns", "velocity_signatures"]:
                    if key in data and isinstance(data[key], (list, dict)):
                        pass  # These are pattern definitions, not individual spikes
                # Look for spike_examples or raw data
                if "spike_examples" in data:
                    spikes.extend(data["spike_examples"])
                if "spikes" in data:
                    spikes.extend(data["spikes"])
            elif isinstance(data, list):
                spikes = data
            logger.info("Loaded %d spikes from pattern library", len(spikes))
        except Exception as e:
            logger.warning("Failed to load pattern library: %s", e)

    # Try SQLite database
    db_path = DEFAULT_DB
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM spike_events ORDER BY timestamp DESC LIMIT 1000"
            ).fetchall()
            for row in rows:
                spike = dict(row)
                # Classify if category not present
                if "category" not in spike:
                    spike["category"] = classify_market(spike.get("market_title", ""))
                spikes.append(spike)
            conn.close()
            logger.info("Loaded %d spikes from database", len(rows))
        except Exception as e:
            logger.warning("Failed to load from database: %s", e)

    return spikes


def download_equity_history(tickers: List[str], start_date: str, end_date: str) -> pd.DataFrame:
    """Download historical data using yfinance with local caching."""
    if yf is None:
        raise ImportError("yfinance required for backtesting")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    all_data = []

    for ticker in tickers:
        cache_file = CACHE_DIR / f"{ticker.replace('/', '_')}_{start_date}_{end_date}.parquet"

        if cache_file.exists():
            df = pd.read_parquet(cache_file)
            logger.info("Loaded %s from cache (%d rows)", ticker, len(df))
        else:
            try:
                df = yf.download(
                    ticker, start=start_date, end=end_date,
                    interval="1h", progress=False, auto_adjust=True,
                )
                if df.empty:
                    # Fall back to daily
                    df = yf.download(
                        ticker, start=start_date, end=end_date,
                        interval="1d", progress=False, auto_adjust=True,
                    )
                if not df.empty:
                    # Flatten multi-level columns
                    if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
                        df.columns = df.columns.get_level_values(0)
                    df["ticker"] = ticker
                    df.to_parquet(cache_file)
                    logger.info("Downloaded %s: %d rows, cached", ticker, len(df))
                else:
                    logger.warning("No data for %s", ticker)
                    continue
            except Exception as e:
                logger.warning("Failed to download %s: %s", ticker, e)
                continue

        if "ticker" not in df.columns:
            df["ticker"] = ticker
        all_data.append(df)

    if not all_data:
        return pd.DataFrame()
    return pd.concat(all_data)


# ---------------------------------------------------------------------------
# Backtesting Engine
# ---------------------------------------------------------------------------

def run_backtest(spikes: List[Dict],
                 lookback_hours: List[int] = None) -> pd.DataFrame:
    """Run backtest: for each spike, check equity price reactions."""
    if lookback_hours is None:
        lookback_hours = [1, 4, 24]

    results = []

    for i, spike in enumerate(spikes):
        title = spike.get("market_title", "")
        category = spike.get("category", classify_market(title))
        direction = spike.get("direction", "up")
        magnitude = spike.get("magnitude", 0)
        timestamp = spike.get("timestamp", "")

        if not timestamp or not title:
            continue

        tickers = get_related_tickers(title, category)

        for t in tickers:
            ticker = t["ticker"]
            try:
                from .equities import get_price_around_spike
                price_data = get_price_around_spike(
                    ticker, timestamp, window_hours=max(lookback_hours)
                )
                if price_data is None:
                    continue

                # Direction match: did equity move in confirming direction?
                dir_match = (
                    (direction == "up" and price_data["direction"] == "up") or
                    (direction == "down" and price_data["direction"] == "down")
                )

                results.append({
                    "spike_id": spike.get("id", i),
                    "market_title": title[:80],
                    "category": category,
                    "spike_direction": direction,
                    "spike_magnitude": magnitude,
                    "ticker": ticker,
                    "return_1h": price_data.get("pct_change_1h", 0),
                    "return_4h": price_data.get("pct_change_4h", 0),
                    "return_24h": 0,  # Would need longer window data
                    "direction_match": dir_match,
                })

            except Exception as e:
                logger.warning("Backtest failed for %s/%s: %s", title[:30], ticker, e)

    return pd.DataFrame(results) if results else pd.DataFrame(
        columns=["spike_id", "market_title", "category", "spike_direction",
                 "spike_magnitude", "ticker", "return_1h", "return_4h",
                 "return_24h", "direction_match"]
    )


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------

def generate_report(results: pd.DataFrame, save_path: str = None) -> str:
    """Generate summary stats from backtest results."""
    if results.empty:
        return "# Backtest Report\n\nNo results to analyze."

    lines = [
        "# Pythia Equities Correlation Backtest Report",
        f"\nGenerated: {datetime.now().isoformat()}",
        f"\n## Overview",
        f"- Total observations: {len(results)}",
        f"- Unique spikes: {results['spike_id'].nunique()}",
        f"- Unique tickers: {results['ticker'].nunique()}",
        f"- Categories: {', '.join(results['category'].unique())}",
    ]

    # Hit rate by category
    lines.append("\n## Hit Rate by Category (Direction Match)")
    cat_stats = results.groupby("category").agg(
        count=("direction_match", "count"),
        hits=("direction_match", "sum"),
        avg_return_1h=("return_1h", "mean"),
        avg_return_4h=("return_4h", "mean"),
    )
    cat_stats["hit_rate"] = (cat_stats["hits"] / cat_stats["count"] * 100).round(1)

    for cat, row in cat_stats.iterrows():
        lines.append(
            f"- **{cat}**: {row['hit_rate']}% hit rate "
            f"({int(row['hits'])}/{int(row['count'])}) | "
            f"avg 1h: {row['avg_return_1h']:.2f}% | "
            f"avg 4h: {row['avg_return_4h']:.2f}%"
        )

    # Best/worst tickers
    lines.append("\n## Ticker Performance")
    ticker_stats = results.groupby("ticker").agg(
        count=("direction_match", "count"),
        hit_rate=("direction_match", "mean"),
        avg_4h=("return_4h", "mean"),
        std_4h=("return_4h", "std"),
    )
    ticker_stats["hit_rate"] = (ticker_stats["hit_rate"] * 100).round(1)

    # Sharpe-like: mean / std
    ticker_stats["sharpe"] = (
        ticker_stats["avg_4h"] / ticker_stats["std_4h"].replace(0, float("nan"))
    ).round(2)

    top = ticker_stats.nlargest(5, "hit_rate")
    lines.append("\n### Top 5 by Hit Rate")
    for ticker, row in top.iterrows():
        lines.append(
            f"- {ticker}: {row['hit_rate']}% ({int(row['count'])} obs) | "
            f"Sharpe: {row['sharpe']}"
        )

    bottom = ticker_stats.nsmallest(5, "hit_rate")
    lines.append("\n### Bottom 5 by Hit Rate")
    for ticker, row in bottom.iterrows():
        lines.append(
            f"- {ticker}: {row['hit_rate']}% ({int(row['count'])} obs) | "
            f"Sharpe: {row['sharpe']}"
        )

    # Overall stats
    overall_hit = results["direction_match"].mean() * 100
    lines.append(f"\n## Overall")
    lines.append(f"- **Overall hit rate**: {overall_hit:.1f}%")
    lines.append(f"- **Avg 1h return**: {results['return_1h'].mean():.3f}%")
    lines.append(f"- **Avg 4h return**: {results['return_4h'].mean():.3f}%")

    report = "\n".join(lines)

    # Save if path provided
    if save_path is None:
        save_path = str(DATA_DIR / "backtest_report.md")
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "w") as f:
        f.write(report)
    logger.info("Report saved to %s", save_path)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Loading spikes...")
    spikes = load_becker_spikes()
    print(f"Found {len(spikes)} spikes")

    if spikes:
        print("Running backtest (first 10 spikes)...")
        results = run_backtest(spikes[:10])
        print(f"Got {len(results)} observations")

        if not results.empty:
            report = generate_report(results)
            print(report)
