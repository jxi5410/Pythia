"""
Contract Detail Engine — Assembles a full detail view for any prediction market contract.

Pulls data from multiple Pythia modules to build a comprehensive picture:
cross-platform prices, confluence status, causal attribution, historical
patterns, and suggested tradeable assets.

This is a data assembly layer — no UI or formatting logic.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .asset_map import classify_market, ASSET_CLASS_MAP
from .confluence import (
    ConfluenceScorer,
    ConfluenceEvent,
    VALID_LAYERS,
    EVENT_CATEGORIES,
    classify_event_category,
    get_confluence_history,
)
from .correlations import find_correlated_markets
from .database import PythiaDB
from .patterns import build_patterns, CausalPattern

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Data classes
# ------------------------------------------------------------------ #

@dataclass
class LayerStatus:
    """Status of a single confluence layer for a specific contract."""
    layer: str
    active: bool
    direction: Optional[str] = None       # "bullish", "bearish", "neutral"
    confidence: float = 0.0
    description: str = ""
    last_signal_time: Optional[datetime] = None


@dataclass
class PatternMatch:
    """A matching historical pattern for the contract's category."""
    pattern_id: str
    market_category: str
    direction: str
    spike_count: int
    hit_rate: float             # fraction of spikes where predicted asset moved
    avg_magnitude: float        # average spike size
    avg_reaction: float         # average subsequent asset reaction
    time_to_resolution_hours: float


@dataclass
class CausalAttribution:
    """Latest causal analysis result for this contract."""
    most_likely_cause: str
    causal_chain: str
    confidence: str             # "HIGH", "MEDIUM", "LOW"
    macro_or_idiosyncratic: str
    expected_duration: str
    trading_implication: str
    alternative_explanations: List[str] = field(default_factory=list)
    timestamp: Optional[datetime] = None


@dataclass
class ContractDetail:
    """
    Full detail view for a prediction market contract.

    Contains everything a trader needs: current pricing across platforms,
    which confluence layers are active, causal analysis, historical
    patterns, and suggested assets to trade.
    """
    # Contract info
    slug: str
    title: str
    platform: str
    current_price: float
    delta_24h: Optional[float] = None
    volume_24h: float = 0.0
    category: str = ""

    # Cross-platform prices
    cross_platform_prices: Dict[str, float] = field(default_factory=dict)

    # Confluence status — which of the 8 layers are active
    confluence_layers: List[LayerStatus] = field(default_factory=list)
    confluence_score: float = 0.0
    active_layer_count: int = 0

    # Causal attribution
    causal_attribution: Optional[CausalAttribution] = None

    # Historical patterns
    historical_patterns: List[PatternMatch] = field(default_factory=list)

    # Suggested tradeable assets
    suggested_assets: List[str] = field(default_factory=list)
    asset_class: str = ""
    asset_rationale: str = ""

    # Correlated markets
    correlated_markets: List[Dict] = field(default_factory=list)

    # Metadata
    last_updated: Optional[datetime] = None


# ------------------------------------------------------------------ #
# Contract lookup helpers
# ------------------------------------------------------------------ #

def _fetch_contract_from_db(db: PythiaDB, slug: str) -> Optional[Dict]:
    """
    Look up a contract by slug/ID in the local database.

    Checks markets table, returns dict with title, source, prices, etc.
    """
    try:
        with sqlite3.connect(db.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Try exact match on id
            row = conn.execute(
                "SELECT * FROM markets WHERE id = ? OR id LIKE ?",
                (slug, f"%{slug}%"),
            ).fetchone()

            if not row:
                # Try title search
                row = conn.execute(
                    "SELECT * FROM markets WHERE title LIKE ?",
                    (f"%{slug}%",),
                ).fetchone()

            if not row:
                return None

            return dict(row)
    except Exception as e:
        logger.warning("Contract DB lookup failed for '%s': %s", slug, e)
        return None


def _get_latest_price(db: PythiaDB, market_id: str) -> Optional[Dict]:
    """Get the latest price and 24h price delta for a market."""
    try:
        with sqlite3.connect(db.db_path) as conn:
            # Latest price
            latest = conn.execute(
                "SELECT yes_price, volume, timestamp FROM prices "
                "WHERE market_id = ? ORDER BY timestamp DESC LIMIT 1",
                (market_id,),
            ).fetchone()

            if not latest:
                return None

            current_price = latest[0]
            volume = latest[1] or 0.0
            ts = latest[2]

            # 24h ago price
            old = conn.execute(
                "SELECT yes_price FROM prices "
                "WHERE market_id = ? AND timestamp <= datetime(?, '-24 hours') "
                "ORDER BY timestamp DESC LIMIT 1",
                (market_id, ts),
            ).fetchone()

            delta_24h = None
            if old and old[0] is not None and current_price is not None:
                delta_24h = current_price - old[0]

            return {
                "current_price": current_price,
                "volume": volume,
                "delta_24h": delta_24h,
            }
    except Exception as e:
        logger.warning("Price lookup failed for '%s': %s", market_id, e)
        return None


def _get_cross_platform_prices(
    db: PythiaDB, title: str, exclude_id: str = ""
) -> Dict[str, float]:
    """
    Find the same event on other platforms via title keyword matching.

    Returns {platform_name: price} dict.
    """
    prices: Dict[str, float] = {}
    try:
        with sqlite3.connect(db.db_path) as conn:
            # Extract key words for matching
            words = [w.lower() for w in title.split() if len(w) > 3]
            if len(words) < 2:
                return prices

            # Build LIKE clauses for the most distinctive words
            search_words = words[:4]
            like_clauses = " AND ".join(
                f"LOWER(m.title) LIKE '%' || ? || '%'" for _ in search_words
            )

            query = f"""
                SELECT m.id, m.title, m.source, p.yes_price
                FROM markets m
                LEFT JOIN (
                    SELECT market_id, yes_price,
                           ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY timestamp DESC) AS rn
                    FROM prices
                ) p ON p.market_id = m.id AND p.rn = 1
                WHERE {like_clauses}
                AND m.id != ?
                LIMIT 10
            """
            params = search_words + [exclude_id]

            rows = conn.execute(query, params).fetchall()
            for row in rows:
                platform = row[2] or "unknown"
                price = row[3]
                if price is not None:
                    prices[f"{platform}:{row[1][:40]}"] = round(price, 4)

        # Also try FedWatch data for rate-related contracts
        if any(kw in title.lower() for kw in ["fed", "rate", "fomc"]):
            try:
                from .fixed_income import fetch_fedwatch_probabilities
                fw = fetch_fedwatch_probabilities()
                if fw:
                    # Take the first meeting's hold probability as an example
                    for meeting, probs in list(fw.items())[:1]:
                        if "cut" in title.lower():
                            total_cut = probs.get("cut_25bp", 0) + probs.get("cut_50bp", 0)
                            prices[f"FedWatch:{meeting}"] = round(total_cut / 100, 4)
                        elif "hold" in title.lower():
                            prices[f"FedWatch:{meeting}"] = round(
                                probs.get("hold", 0) / 100, 4
                            )
            except Exception as e:
                logger.debug("FedWatch cross-platform lookup failed: %s", e)

    except Exception as e:
        logger.warning("Cross-platform price lookup failed: %s", e)

    return prices


# ------------------------------------------------------------------ #
# Confluence layer inspection
# ------------------------------------------------------------------ #

def _get_confluence_layers(
    db: PythiaDB, title: str, category: str, hours: int = 24
) -> List[LayerStatus]:
    """
    Determine which of the 8 confluence layers are currently active
    for a given event category.

    Checks recent confluence events and signals stored in the database.
    """
    layers: List[LayerStatus] = []

    # Get recent confluence events for this category
    recent_events = get_confluence_history(db, hours=hours, min_score=0.0)
    category_events = [
        e for e in recent_events
        if e.get("event_category") == category
    ]

    # Track which layers have fired for this category
    active_layers: Dict[str, Dict] = {}
    for evt in category_events:
        evt_layers = evt.get("layers", "[]")
        if isinstance(evt_layers, str):
            try:
                evt_layers = json.loads(evt_layers)
            except (json.JSONDecodeError, TypeError):
                evt_layers = []

        signals_json = evt.get("signals_json", "[]")
        if isinstance(signals_json, str):
            try:
                signals_data = json.loads(signals_json)
            except (json.JSONDecodeError, TypeError):
                signals_data = []
        else:
            signals_data = signals_json or []

        for sig in signals_data:
            layer_name = sig.get("layer", "")
            if layer_name and layer_name in VALID_LAYERS:
                existing = active_layers.get(layer_name, {})
                # Keep the highest confidence signal per layer
                if sig.get("confidence", 0) > existing.get("confidence", 0):
                    active_layers[layer_name] = {
                        "direction": sig.get("direction", "neutral"),
                        "confidence": sig.get("confidence", 0),
                        "description": sig.get("description", ""),
                        "timestamp": sig.get("timestamp"),
                    }

    # Build LayerStatus for each valid layer
    for layer_name in VALID_LAYERS:
        info = active_layers.get(layer_name)
        if info:
            ts = None
            if info.get("timestamp"):
                try:
                    ts = datetime.fromisoformat(
                        str(info["timestamp"]).replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    ts = None

            layers.append(LayerStatus(
                layer=layer_name,
                active=True,
                direction=info["direction"],
                confidence=info["confidence"],
                description=info["description"][:120],
                last_signal_time=ts,
            ))
        else:
            layers.append(LayerStatus(layer=layer_name, active=False))

    return layers


# ------------------------------------------------------------------ #
# Pattern matching
# ------------------------------------------------------------------ #

def _get_historical_patterns(
    db: PythiaDB, category: str
) -> List[PatternMatch]:
    """
    Find matching historical patterns from the pattern library
    for the contract's event category.
    """
    try:
        all_patterns = build_patterns(db)
    except Exception as e:
        logger.warning("Pattern build failed: %s", e)
        return []

    matches: List[PatternMatch] = []
    for pat in all_patterns:
        if pat.market_category != category:
            continue

        # Calculate hit rate: fraction of spikes with positive asset reaction
        hit_rate = 0.0
        if pat.sample_size > 0 and pat.avg_asset_reaction != 0:
            # Use confidence as a proxy for hit rate when we don't have
            # detailed outcome tracking yet
            hit_rate = pat.confidence

        matches.append(PatternMatch(
            pattern_id=pat.pattern_id,
            market_category=pat.market_category,
            direction=pat.direction,
            spike_count=pat.sample_size,
            hit_rate=round(hit_rate, 3),
            avg_magnitude=round(pat.avg_magnitude, 4),
            avg_reaction=round(pat.avg_asset_reaction, 4),
            time_to_resolution_hours=round(
                pat.avg_reaction_timeframe_hours, 1
            ),
        ))

    # Sort by spike count descending
    matches.sort(key=lambda m: m.spike_count, reverse=True)
    return matches[:10]


# ------------------------------------------------------------------ #
# Causal attribution lookup
# ------------------------------------------------------------------ #

def _get_latest_causal(db: PythiaDB, market_id: str) -> Optional[CausalAttribution]:
    """
    Retrieve the latest causal v2 attribution for the contract
    from the spike_events table.
    """
    try:
        with sqlite3.connect(db.db_path) as conn:
            row = conn.execute(
                "SELECT attributed_events, timestamp FROM spike_events "
                "WHERE market_id = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (market_id,),
            ).fetchone()

            if not row:
                return None

            raw = row[0]
            if isinstance(raw, str):
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    return None
            else:
                data = raw

            # V2 attribution is nested under "v2_attribution"
            attr = data.get("v2_attribution") if isinstance(data, dict) else None
            if not attr:
                return None

            ts = None
            if row[1]:
                try:
                    ts = datetime.fromisoformat(str(row[1]))
                except (ValueError, TypeError):
                    ts = None

            return CausalAttribution(
                most_likely_cause=attr.get("most_likely_cause", "Unknown"),
                causal_chain=attr.get("causal_chain", ""),
                confidence=attr.get("confidence", "LOW"),
                macro_or_idiosyncratic=attr.get(
                    "macro_or_idiosyncratic", "UNKNOWN"
                ),
                expected_duration=attr.get("expected_duration", "UNKNOWN"),
                trading_implication=attr.get("trading_implication", ""),
                alternative_explanations=attr.get(
                    "alternative_explanations", []
                ),
                timestamp=ts,
            )
    except Exception as e:
        logger.warning("Causal lookup failed for '%s': %s", market_id, e)
        return None


# ------------------------------------------------------------------ #
# Main API
# ------------------------------------------------------------------ #

def get_contract_detail(
    contract_slug: str,
    db: Optional[PythiaDB] = None,
    db_path: str = "data/pythia_live.db",
) -> ContractDetail:
    """
    Assemble a full detail view for a prediction market contract.

    Gathers data from multiple Pythia modules:
    - Contract info (title, price, volume, 24h delta)
    - Cross-platform prices (Polymarket / Kalshi / FedWatch)
    - Confluence layer status (which of the 8 layers are active)
    - Causal attribution (latest v2 analysis if available)
    - Historical patterns (matching patterns from the library)
    - Suggested assets (from the asset map)

    Args:
        contract_slug: Market ID, slug, or title substring to search for.
        db: Optional pre-initialised PythiaDB instance.
        db_path: Path to the database file (used if ``db`` is None).

    Returns:
        ContractDetail dataclass with all assembled information.
    """
    if db is None:
        db = PythiaDB(db_path)

    now = datetime.now(timezone.utc)

    # --- 1. Look up contract ---
    market = _fetch_contract_from_db(db, contract_slug)

    if not market:
        # Return a minimal detail with empty fields
        return ContractDetail(
            slug=contract_slug,
            title=f"Contract not found: {contract_slug}",
            platform="unknown",
            current_price=0.0,
            last_updated=now,
        )

    market_id = market.get("id", contract_slug)
    title = market.get("title", contract_slug)
    platform = market.get("source", "unknown")
    category_raw = market.get("category", "")
    category = classify_event_category(title) if not category_raw else category_raw

    # --- 2. Prices ---
    price_info = _get_latest_price(db, market_id) or {}
    current_price = price_info.get("current_price", 0.0)
    delta_24h = price_info.get("delta_24h")
    volume_24h = price_info.get("volume", market.get("volume_24h", 0.0) or 0.0)

    # --- 3. Cross-platform prices ---
    cross_platform = _get_cross_platform_prices(db, title, exclude_id=market_id)

    # --- 4. Confluence layers ---
    confluence_layers = _get_confluence_layers(db, title, category)
    active_count = sum(1 for l in confluence_layers if l.active)
    conf_score = 0.0
    if active_count >= 5:
        conf_score = 0.95
    elif active_count == 4:
        conf_score = 0.85
    elif active_count == 3:
        conf_score = 0.60
    elif active_count == 2:
        conf_score = 0.30
    elif active_count == 1:
        conf_score = 0.10

    # --- 5. Causal attribution ---
    causal = _get_latest_causal(db, market_id)

    # --- 6. Historical patterns ---
    patterns = _get_historical_patterns(db, category)

    # --- 7. Suggested assets ---
    asset_info = classify_market(title)
    suggested_assets: List[str] = []
    if asset_info.get("instruments"):
        suggested_assets = [
            i.strip() for i in asset_info["instruments"].split(",")
        ]
    asset_class = asset_info.get("asset_class", "general")
    asset_rationale = asset_info.get("how_it_matters", "")

    # --- 8. Correlated markets ---
    correlated = find_correlated_markets(db, market_id, title, limit=5)

    return ContractDetail(
        slug=contract_slug,
        title=title,
        platform=platform,
        current_price=current_price,
        delta_24h=delta_24h,
        volume_24h=volume_24h,
        category=category,
        cross_platform_prices=cross_platform,
        confluence_layers=confluence_layers,
        confluence_score=conf_score,
        active_layer_count=active_count,
        causal_attribution=causal,
        historical_patterns=patterns,
        suggested_assets=suggested_assets,
        asset_class=asset_class,
        asset_rationale=asset_rationale,
        correlated_markets=correlated,
        last_updated=now,
    )
