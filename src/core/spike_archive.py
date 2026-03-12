"""
Spike Archive — Detects and stores significant price moves with event attribution.
Searches for real-world causes using DuckDuckGo HTML scraping.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import quote_plus

import pandas as pd
import requests
from bs4 import BeautifulSoup

from .database import PythiaDB

logger = logging.getLogger(__name__)


@dataclass
class SpikeEvent:
    id: int  # auto from DB
    market_id: str
    market_title: str
    timestamp: datetime
    direction: str  # "up" or "down"
    magnitude: float  # absolute price change (0-1)
    price_before: float
    price_after: float
    volume_at_spike: float
    asset_class: str
    # Attribution
    attributed_events: List[Dict] = field(default_factory=list)
    manual_tag: str = ""
    # Outcome tracking
    asset_reaction: Dict = field(default_factory=dict)


def detect_spike(price_history: pd.DataFrame, threshold: float = 0.05) -> Optional[SpikeEvent]:
    """
    Scan price history for moves >= threshold within a 2-hour window.

    Args:
        price_history: DataFrame with columns: timestamp, yes_price, volume
        threshold: Minimum absolute price change to qualify as a spike (0-1)

    Returns:
        SpikeEvent if a qualifying spike is found, else None
    """
    if price_history.empty or len(price_history) < 2:
        return None

    df = price_history.copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')

    # Sliding 2-hour window: compare each price to all prices within 2h before it
    latest_ts = df['timestamp'].max()
    window_start = latest_ts - timedelta(hours=2)

    window = df[df['timestamp'] >= window_start]
    if len(window) < 2:
        return None

    # Find max price swing in the window
    prices = window['yes_price'].values
    min_price = prices.min()
    max_price = prices.max()
    magnitude = max_price - min_price

    if magnitude < threshold:
        return None

    # Determine direction based on recent trend (first vs last in window)
    first_price = prices[0]
    last_price = prices[-1]
    direction = "up" if last_price > first_price else "down"

    price_before = first_price
    price_after = last_price

    # Volume at spike time
    volume_col = 'volume' if 'volume' in window.columns else None
    volume_at_spike = float(window[volume_col].iloc[-1]) if volume_col and not window[volume_col].isna().all() else 0.0

    return SpikeEvent(
        id=0,  # filled by DB
        market_id=window.get('market_id', pd.Series([''])).iloc[0] if 'market_id' in window.columns else '',
        market_title='',  # filled by caller
        timestamp=latest_ts.to_pydatetime() if hasattr(latest_ts, 'to_pydatetime') else latest_ts,
        direction=direction,
        magnitude=abs(last_price - first_price),
        price_before=price_before,
        price_after=price_after,
        volume_at_spike=volume_at_spike,
        asset_class='',  # filled by caller
    )


def attribute_spike(spike: SpikeEvent) -> SpikeEvent:
    """
    Search for news around the spike timestamp using DuckDuckGo HTML scraping.

    Query: market title keywords + date range (2h before to 1h after spike).
    Stores top 3 results as attributed_events.
    """
    try:
        # Build search query from market title keywords
        title = spike.market_title or ''
        # Strip common filler words for a tighter query
        query = title.strip('?').strip()

        # Add date context
        spike_date = spike.timestamp
        if isinstance(spike_date, str):
            spike_date = datetime.fromisoformat(spike_date)
        date_str = spike_date.strftime('%Y-%m-%d')
        search_query = f"{query} {date_str}"

        # Scrape DuckDuckGo HTML search results
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(search_query)}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; PythiaLive/0.5)',
        }
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []

        # DuckDuckGo HTML results are in .result__body elements
        for result in soup.select('.result__body'):
            title_el = result.select_one('.result__a')
            snippet_el = result.select_one('.result__snippet')

            if not title_el:
                continue

            headline = title_el.get_text(strip=True)
            link = title_el.get('href', '')
            snippet = snippet_el.get_text(strip=True) if snippet_el else ''

            # Clean up DuckDuckGo redirect URLs
            if '/l/?uddg=' in link:
                match = re.search(r'uddg=([^&]+)', link)
                if match:
                    from urllib.parse import unquote
                    link = unquote(match.group(1))

            results.append({
                'headline': headline[:200],
                'source': _extract_domain(link),
                'url': link,
                'timestamp': date_str,
            })

            if len(results) >= 3:
                break

        spike.attributed_events = results

    except Exception as e:
        logger.warning("Spike attribution failed: %s", e)
        spike.attributed_events = []

    return spike


def _extract_domain(url: str) -> str:
    """Extract domain name from URL."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path
        return domain.replace('www.', '')
    except Exception:
        return ''


def save_spike(db: PythiaDB, spike: SpikeEvent) -> int:
    """Save a spike event to the database. Returns the spike ID."""
    spike_dict = {
        'market_id': spike.market_id,
        'market_title': spike.market_title,
        'timestamp': spike.timestamp,
        'direction': spike.direction,
        'magnitude': spike.magnitude,
        'price_before': spike.price_before,
        'price_after': spike.price_after,
        'volume_at_spike': spike.volume_at_spike,
        'asset_class': spike.asset_class,
        'attributed_events': spike.attributed_events,
        'manual_tag': spike.manual_tag,
        'asset_reaction': spike.asset_reaction,
    }
    spike_id = db.save_spike_event(spike_dict)
    spike.id = spike_id
    return spike_id


def get_spike_history(db: PythiaDB, market_id: str = None, asset_class: str = None,
                      min_magnitude: float = 0.03, limit: int = 50) -> List[SpikeEvent]:
    """Retrieve spike events from the database as SpikeEvent objects."""
    df = db.get_spike_events(
        market_id=market_id,
        asset_class=asset_class,
        min_magnitude=min_magnitude,
        limit=limit,
    )
    spikes = []
    for _, row in df.iterrows():
        attributed = row.get('attributed_events', '[]')
        if isinstance(attributed, str):
            try:
                attributed = json.loads(attributed)
            except (json.JSONDecodeError, TypeError):
                attributed = []

        reaction = row.get('asset_reaction', '{}')
        if isinstance(reaction, str):
            try:
                reaction = json.loads(reaction)
            except (json.JSONDecodeError, TypeError):
                reaction = {}

        spikes.append(SpikeEvent(
            id=int(row['id']),
            market_id=row['market_id'],
            market_title=row.get('market_title', ''),
            timestamp=row['timestamp'],
            direction=row.get('direction', ''),
            magnitude=float(row.get('magnitude', 0)),
            price_before=float(row.get('price_before', 0)),
            price_after=float(row.get('price_after', 0)),
            volume_at_spike=float(row.get('volume_at_spike', 0)),
            asset_class=row.get('asset_class', ''),
            attributed_events=attributed,
            manual_tag=row.get('manual_tag', ''),
            asset_reaction=reaction,
        ))
    return spikes


def tag_spike(db: PythiaDB, spike_id: int, manual_tag: str):
    """Manually tag a spike event with a cause description."""
    db.update_spike_tag(spike_id, manual_tag)


def attribute_spike_v2_wrapper(spike: SpikeEvent, db: PythiaDB,
                                all_recent_spikes: List[SpikeEvent] = None) -> SpikeEvent:
    """
    V2 attribution wrapper — drop-in replacement for attribute_spike().
    Uses the full 5-layer causal pipeline with LLM reasoning.
    Falls back to v1 if LLM is unavailable.
    """
    try:
        from .bace import attribute_spike, BACEDepth
        from .llm_integration import sonnet_call, opus_call

        result = attribute_spike(
            spike,
            all_recent_spikes=all_recent_spikes or [],
            db=db,
            depth=BACEDepth.FAST,
            llm_fast=sonnet_call,
            llm_strong=opus_call,
        )

        # Update spike with v2 attribution data
        attr = result.get("attribution", {})
        spike.attributed_events = result.get("top_candidates", [])
        spike.manual_tag = attr.get("most_likely_cause", "")

        return spike

    except Exception as e:
        logger.warning("V2 attribution failed, falling back to v1: %s", e)
        return attribute_spike(spike)
