"""
Pythia Confluence Scorer — Cross-layer signal convergence engine.

Detects when multiple independent data layers agree on the same directional
signal within a time window. Single-layer signals are noise. Multi-layer
convergence is the product.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .asset_map import classify_market

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Event category taxonomy
# ------------------------------------------------------------------ #

EVENT_CATEGORIES = [
    "fed_rate",
    "tariffs",
    "china_macro",
    "defense",
    "tech_regulation",
    "crypto_regulation",
    "government_shutdown",
    "recession",
    "geopolitical",
    "earnings_macro",
    "energy",
]

# Keywords used to auto-classify signals into event categories
_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "fed_rate": ["fed", "fomc", "rate cut", "rate hike", "interest rate",
                 "monetary policy", "powell", "fed funds", "treasury", "yield"],
    "tariffs": ["tariff", "trade war", "trade deal", "import duty", "customs",
                "trade policy", "wto"],
    "china_macro": ["china", "pboc", "renminbi", "yuan", "cny", "nbs",
                    "chinese economy", "xi jinping", "beijing"],
    "defense": ["defense", "military", "nato", "pentagon", "lockheed",
                "raytheon", "weapons", "arms", "war"],
    "tech_regulation": ["antitrust", "big tech", "tech regulation", "ai regulation",
                        "section 230", "ftc", "doj tech", "google", "meta", "apple"],
    "crypto_regulation": ["sec crypto", "crypto regulation", "stablecoin",
                          "cbdc", "bitcoin etf", "crypto ban", "defi regulation"],
    "government_shutdown": ["shutdown", "government funding", "continuing resolution",
                            "debt ceiling", "appropriations"],
    "recession": ["recession", "gdp", "unemployment", "jobs report", "nonfarm",
                  "layoffs", "economic downturn", "soft landing"],
    "geopolitical": ["war", "conflict", "invasion", "nuclear", "sanctions",
                     "russia", "ukraine", "taiwan", "iran", "north korea"],
    "earnings_macro": ["earnings", "revenue", "guidance", "profit", "eps",
                       "quarterly results", "earnings season"],
    "energy": ["oil", "opec", "natural gas", "crude", "energy", "petroleum",
               "lng", "pipeline", "drilling"],
}

# Layer names for validation
VALID_LAYERS = [
    "equities",
    "congressional",
    "twitter",
    "fixed_income",
    "crypto_onchain",
    "macro_calendar",
    "china_signals",
    "causal",
]


# ------------------------------------------------------------------ #
# Data classes
# ------------------------------------------------------------------ #

@dataclass
class Signal:
    """Standardized signal emitted by any data layer."""
    layer: str              # "equities", "congressional", "twitter", etc.
    direction: str          # "bullish", "bearish", "neutral"
    event_category: str     # "fed_rate", "tariffs", "china_macro", etc.
    confidence: float       # 0.0 - 1.0
    timestamp: datetime
    description: str        # human-readable what happened
    raw_data: dict = field(default_factory=dict)  # layer-specific payload


@dataclass
class ConfluenceEvent:
    """Output when multiple layers converge on the same directional signal."""
    event_category: str
    direction: str
    confluence_score: float     # 0-1, higher = more layers agree
    layer_count: int            # how many layers fired
    layers: List[str]           # which layers
    signals: List[Signal]       # the raw signals
    confidence: float           # aggregate confidence
    timestamp: datetime         # when confluence detected
    historical_hit_rate: float  # optional, 0.0 if unknown
    suggested_assets: List[str] # from asset_map
    alert_text: str             # human-readable summary


# ------------------------------------------------------------------ #
# Category classification
# ------------------------------------------------------------------ #

def classify_event_category(text: str) -> str:
    """
    Classify free text into an event category using keyword matching.

    Args:
        text: Signal description or market title.

    Returns:
        Best-matching event category, or "geopolitical" as fallback.
    """
    text_lower = text.lower()
    best_category = "geopolitical"
    best_hits = 0

    for category, keywords in _CATEGORY_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits > best_hits:
            best_hits = hits
            best_category = category

    return best_category


# ------------------------------------------------------------------ #
# Layer adapters — translate existing module outputs into Signal format
# ------------------------------------------------------------------ #

def adapt_equities(correlation: dict) -> Optional[Signal]:
    """Adapt equities.correlate_spike() output to a Signal."""
    if not correlation or not correlation.get("moves"):
        return None

    confidence_map = {"high": 0.85, "medium": 0.6, "low": 0.3}
    conf = confidence_map.get(
        correlation.get("cross_asset_confidence", "low"), 0.3
    )

    # Determine direction from equity moves
    moves = correlation.get("moves", [])
    up_moves = sum(1 for m in moves if m.get("pct_change", 0) > 0)
    down_moves = sum(1 for m in moves if m.get("pct_change", 0) < 0)

    if up_moves > down_moves:
        direction = "bullish"
    elif down_moves > up_moves:
        direction = "bearish"
    else:
        direction = "neutral"

    description = correlation.get("summary", "Equity cross-asset correlation detected")
    category = classify_event_category(description)

    return Signal(
        layer="equities",
        direction=direction,
        event_category=category,
        confidence=conf,
        timestamp=datetime.now(timezone.utc),
        description=description,
        raw_data=correlation,
    )


def adapt_congressional(signal: dict) -> Optional[Signal]:
    """Adapt congressional.detect_congressional_signal() output to a Signal."""
    if not signal or not signal.get("is_signal"):
        return None

    txn = signal.get("transaction_type", "")
    if txn in ("buy", "purchase"):
        direction = "bullish"
    elif txn in ("sell", "sale"):
        direction = "bearish"
    else:
        direction = "neutral"

    description = signal.get("description", "")
    if not description:
        politician = signal.get("politician", "Unknown")
        ticker = signal.get("ticker", "?")
        description = f"{politician} {txn} {ticker}"

    category = classify_event_category(
        f"{description} {signal.get('ticker', '')} "
        f"{' '.join(signal.get('matched_markets', []))}"
    )

    confidence = min(1.0, signal.get("confidence", 0.5))

    return Signal(
        layer="congressional",
        direction=direction,
        event_category=category,
        confidence=confidence,
        timestamp=datetime.now(timezone.utc),
        description=description,
        raw_data=signal,
    )


def adapt_twitter(signal: dict) -> Optional[Signal]:
    """Adapt twitter_signals.detect_twitter_signal() output to a Signal."""
    if not signal or not signal.get("is_signal"):
        return None

    sentiment = signal.get("sentiment", "neutral")
    if sentiment in ("bullish", "positive"):
        direction = "bullish"
    elif sentiment in ("bearish", "negative"):
        direction = "bearish"
    else:
        direction = "neutral"

    velocity = signal.get("velocity", {})
    tweets_per_min = velocity.get("tweets_per_minute", 0)

    # Higher velocity = higher confidence, capped at 1.0
    confidence = min(1.0, max(0.2, tweets_per_min / 20.0))

    description = signal.get("description", "Twitter velocity signal detected")
    category = classify_event_category(description)

    return Signal(
        layer="twitter",
        direction=direction,
        event_category=category,
        confidence=confidence,
        timestamp=datetime.now(timezone.utc),
        description=description,
        raw_data=signal,
    )


def adapt_fixed_income(signal: dict) -> Optional[Signal]:
    """Adapt fixed_income.detect_rate_signals() output to a Signal."""
    if not signal:
        return None

    spread_bps = abs(signal.get("spread_bps", 0))
    # Determine direction from spread sign
    raw_spread = signal.get("spread_bps", 0)
    if raw_spread > 0:
        direction = "bullish"  # market pricing more cuts than FedWatch
    elif raw_spread < 0:
        direction = "bearish"  # market pricing fewer cuts than FedWatch
    else:
        direction = "neutral"

    confidence = min(1.0, spread_bps / 30.0)  # 30bps spread = full confidence

    description = signal.get("description", "")
    if not description:
        description = f"Rate spread: {spread_bps:.0f}bps"

    return Signal(
        layer="fixed_income",
        direction=direction,
        event_category="fed_rate",
        confidence=confidence,
        timestamp=datetime.now(timezone.utc),
        description=description,
        raw_data=signal,
    )


def adapt_crypto(signal: dict) -> Optional[Signal]:
    """Adapt crypto_onchain.detect_crypto_signals() output to a Signal."""
    if not signal or not signal.get("is_signal", True):
        return None

    source = signal.get("source", "")
    details = signal.get("details", {})

    # Determine direction based on signal source
    direction = "neutral"
    if source == "whale_movement":
        flow = details.get("flow_direction", "")
        if flow == "exchange_inflow":
            direction = "bearish"  # selling pressure
        elif flow == "exchange_outflow":
            direction = "bullish"  # accumulation
    elif source == "funding_rate":
        rate = details.get("rate", 0)
        if rate > 0.01:
            direction = "bearish"  # overleveraged longs
        elif rate < -0.01:
            direction = "bullish"  # overleveraged shorts
    elif source == "fear_greed":
        value = details.get("value", 50)
        if value < 25:
            direction = "bullish"  # extreme fear = buy signal
        elif value > 75:
            direction = "bearish"  # extreme greed = sell signal

    confidence = min(1.0, signal.get("confidence", 0.5))
    description = signal.get("description", "Crypto on-chain signal")
    category = classify_event_category(description)

    return Signal(
        layer="crypto_onchain",
        direction=direction,
        event_category=category,
        confidence=confidence,
        timestamp=datetime.now(timezone.utc),
        description=description,
        raw_data=signal,
    )


def adapt_macro_calendar(event: dict) -> Optional[Signal]:
    """Adapt macro_calendar event to a Signal."""
    if not event:
        return None

    impact = event.get("impact", "").lower()
    actual = event.get("actual")
    forecast = event.get("forecast")

    direction = "neutral"
    if actual is not None and forecast is not None:
        try:
            actual_f = float(str(actual).replace("%", "").replace(",", ""))
            forecast_f = float(str(forecast).replace("%", "").replace(",", ""))
            if actual_f > forecast_f:
                direction = "bullish"
            elif actual_f < forecast_f:
                direction = "bearish"
        except (ValueError, TypeError):
            pass

    confidence_map = {"high": 0.8, "medium": 0.5, "low": 0.3}
    confidence = confidence_map.get(impact, 0.4)

    title = event.get("title", event.get("event", "Macro event"))
    category = classify_event_category(title)

    return Signal(
        layer="macro_calendar",
        direction=direction,
        event_category=category,
        confidence=confidence,
        timestamp=datetime.now(timezone.utc),
        description=title,
        raw_data=event,
    )


def adapt_china_signals(signal: dict) -> Optional[Signal]:
    """Adapt china_signals.detect_china_signals() output to a Signal."""
    if not signal or not signal.get("is_signal"):
        return None

    source = signal.get("source", "")
    details = signal.get("details", {})

    # Direction based on signal source
    direction = "neutral"
    sentiment = details.get("sentiment", signal.get("sentiment", ""))
    if sentiment in ("bullish", "positive", "easing"):
        direction = "bullish"
    elif sentiment in ("bearish", "negative", "tightening"):
        direction = "bearish"

    confidence = min(1.0, signal.get("confidence", 0.5))
    description = signal.get("description", f"China signal ({source})")

    return Signal(
        layer="china_signals",
        direction=direction,
        event_category="china_macro",
        confidence=confidence,
        timestamp=datetime.now(timezone.utc),
        description=description,
        raw_data=signal,
    )


def adapt_causal(attribution: dict) -> Optional[Signal]:
    """Adapt causal_v2.attribute_spike_v2() output to a Signal."""
    if not attribution:
        return None

    attr = attribution.get("attribution", {})
    if not attr:
        return None

    confidence_map = {"HIGH": 0.85, "MEDIUM": 0.6, "LOW": 0.3}
    conf_str = attr.get("confidence", "LOW")
    confidence = confidence_map.get(conf_str, 0.3)

    cause = attr.get("most_likely_cause", "")
    if not cause or cause.startswith("[dry-run"):
        return None

    implication = attr.get("trading_implication", "")
    if "buy" in implication.lower() or "long" in implication.lower():
        direction = "bullish"
    elif "sell" in implication.lower() or "short" in implication.lower():
        direction = "bearish"
    else:
        direction = "neutral"

    category = classify_event_category(cause)

    return Signal(
        layer="causal",
        direction=direction,
        event_category=category,
        confidence=confidence,
        timestamp=datetime.now(timezone.utc),
        description=cause,
        raw_data=attribution,
    )


# ------------------------------------------------------------------ #
# Confluence scorer
# ------------------------------------------------------------------ #

class ConfluenceScorer:
    """
    Cross-layer signal confluence engine.

    Detects when multiple independent data layers agree on the same
    directional signal within a configurable time window.

    Usage::

        scorer = ConfluenceScorer(time_window_hours=4, min_layers=3)
        scorer.ingest_signal(signal_a)
        scorer.ingest_signal(signal_b)
        events = scorer.check_confluence()
    """

    def __init__(self, time_window_hours: int = 4, min_layers: int = 3):
        self.time_window = timedelta(hours=time_window_hours)
        self.min_layers = min_layers
        self._signals: List[Signal] = []

    # -------------------------------------------------------------- #
    # Public API
    # -------------------------------------------------------------- #

    def ingest_signal(self, signal: Signal) -> None:
        """
        Add a signal from any layer.

        Expired signals (older than the time window) are pruned on ingest.
        """
        self._prune_expired()
        self._signals.append(signal)
        logger.info("Ingested signal: layer=%s category=%s direction=%s",
                     signal.layer, signal.event_category, signal.direction)

    def ingest_signals(self, signals: List[Signal]) -> None:
        """Convenience method to ingest multiple signals at once."""
        for s in signals:
            self.ingest_signal(s)

    def check_confluence(self, event_category: Optional[str] = None) -> List[ConfluenceEvent]:
        """
        Check for multi-layer convergence.

        Args:
            event_category: If provided, only check confluence for this category.
                           If None, check all categories.

        Returns:
            List of ConfluenceEvent objects where enough layers agree.
        """
        self._prune_expired()

        if not self._signals:
            return []

        events = []

        # Group signals by (event_category, direction)
        groups: Dict[tuple, List[Signal]] = {}
        for signal in self._signals:
            if event_category and signal.event_category != event_category:
                continue
            if signal.direction == "neutral":
                continue  # neutral signals don't contribute to confluence
            key = (signal.event_category, signal.direction)
            groups.setdefault(key, []).append(signal)

        for (cat, direction), signals in groups.items():
            # Deduplicate by layer — only count one signal per layer
            layer_signals: Dict[str, Signal] = {}
            for s in signals:
                # Keep the highest-confidence signal per layer
                existing = layer_signals.get(s.layer)
                if existing is None or s.confidence > existing.confidence:
                    layer_signals[s.layer] = s

            unique_layers = list(layer_signals.keys())
            if len(unique_layers) < self.min_layers:
                continue

            deduped = list(layer_signals.values())
            event = self.score(deduped)
            events.append(event)
            logger.info("Confluence detected: category=%s direction=%s layers=%d score=%.2f",
                        cat, direction, len(unique_layers), event.confluence_score)

        # Sort by confluence score descending
        events.sort(key=lambda e: e.confluence_score, reverse=True)
        return events

    def score(
        self,
        signals: List[Signal],
        correlation_clusters: Optional[List[List[str]]] = None,
    ) -> ConfluenceEvent:
        """
        Score a group of converging signals.

        Scoring logic:
        - 2 layers agreeing: score 0.3 (low, just monitoring)
        - 3 layers agreeing: score 0.6 (medium, worth alerting)
        - 4+ layers agreeing: score 0.85+ (high, strong signal)
        - Weight by layer confidence and time decay.
        """
        if not signals:
            return ConfluenceEvent(
                event_category="unknown",
                direction="neutral",
                confluence_score=0.0,
                layer_count=0,
                layers=[],
                signals=[],
                confidence=0.0,
                timestamp=datetime.now(timezone.utc),
                historical_hit_rate=0.0,
                suggested_assets=[],
                alert_text="No signals to score.",
            )

        layer_count = len(set(s.layer for s in signals))
        category = signals[0].event_category
        direction = signals[0].direction
        layers = list(set(s.layer for s in signals))
        effective_layers = float(layer_count)
        if correlation_clusters:
            effective_layers = 0.0
            layer_set = set(layers)
            for cluster in correlation_clusters:
                cluster_layers = [x for x in cluster if x in layer_set]
                if cluster_layers:
                    effective_layers += 1.0 / len(cluster_layers)
            leftover = layer_set - {x for c in correlation_clusters for x in c}
            effective_layers += float(len(leftover))

        # --- Base score by layer count ---
        if effective_layers >= 5:
            base_score = 0.95
        elif effective_layers >= 4:
            base_score = 0.85
        elif effective_layers >= 3:
            base_score = 0.60
        elif effective_layers >= 2:
            base_score = 0.30
        else:
            base_score = 0.10

        # --- Confidence weight: average confidence across layers ---
        avg_confidence = sum(s.confidence for s in signals) / len(signals)

        # --- Time decay: signals lose weight as they age ---
        now = datetime.now(timezone.utc)
        decay_weights = []
        for s in signals:
            ts = s.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_hours = (now - ts).total_seconds() / 3600.0
            window_hours = self.time_window.total_seconds() / 3600.0
            decay = max(0.1, 1.0 - (age_hours / window_hours) * 0.5)
            decay_weights.append(decay)

        avg_decay = sum(decay_weights) / len(decay_weights)

        # --- Final confluence score ---
        confluence_score = round(
            min(1.0, base_score * (0.6 + 0.4 * avg_confidence) * avg_decay),
            3,
        )

        # --- Aggregate confidence ---
        aggregate_confidence = round(avg_confidence * avg_decay, 3)

        # --- Suggested assets from asset_map ---
        asset_info = classify_market(
            f"{category} {direction} {' '.join(s.description for s in signals[:3])}"
        )
        suggested = []
        if asset_info.get("instruments"):
            suggested = [i.strip() for i in asset_info["instruments"].split(",")]

        # --- Alert text ---
        alert_text = self._build_alert_text(
            category, direction, confluence_score, layer_count, layers, signals
        )

        return ConfluenceEvent(
            event_category=category,
            direction=direction,
            confluence_score=confluence_score,
            layer_count=layer_count,
            layers=layers,
            signals=signals,
            confidence=aggregate_confidence,
            timestamp=now,
            historical_hit_rate=0.0,  # Populated from DB when available
            suggested_assets=suggested,
            alert_text=alert_text,
        )

    def get_active_signals(self) -> List[Signal]:
        """Return all non-expired signals currently in the buffer."""
        self._prune_expired()
        return list(self._signals)

    def clear(self) -> None:
        """Clear all signals."""
        self._signals.clear()

    # -------------------------------------------------------------- #
    # Internal helpers
    # -------------------------------------------------------------- #

    def _prune_expired(self) -> None:
        """Remove signals older than the time window."""
        now = datetime.now(timezone.utc)
        before = len(self._signals)
        self._signals = [
            s for s in self._signals
            if (now - (s.timestamp.replace(tzinfo=timezone.utc)
                       if s.timestamp.tzinfo is None else s.timestamp)
                ) <= self.time_window
        ]
        pruned = before - len(self._signals)
        if pruned > 0:
            logger.debug("Pruned %d expired signals", pruned)

    @staticmethod
    def _build_alert_text(category: str, direction: str, score: float,
                          layer_count: int, layers: List[str],
                          signals: List[Signal]) -> str:
        """Build a human-readable alert summary."""
        emoji = "🟢" if direction == "bullish" else "🔴" if direction == "bearish" else "⚪"
        severity = "HIGH" if score >= 0.7 else "MEDIUM" if score >= 0.4 else "LOW"

        lines = [
            f"{emoji} CONFLUENCE {severity}: {category.upper()} — {direction.upper()}",
            f"Score: {score:.0%} | Layers: {layer_count}/8",
            f"Agreeing layers: {', '.join(sorted(layers))}",
            "",
        ]

        for s in signals[:5]:  # Cap at 5 to avoid flooding
            lines.append(f"  • [{s.layer}] {s.description[:100]}")

        return "\n".join(lines)


# ------------------------------------------------------------------ #
# Convenience: run confluence check on a batch of raw layer outputs
# ------------------------------------------------------------------ #

def run_confluence_check(
    equities_data: Optional[list] = None,
    congressional_data: Optional[list] = None,
    twitter_data: Optional[list] = None,
    fixed_income_data: Optional[list] = None,
    crypto_data: Optional[list] = None,
    macro_data: Optional[list] = None,
    china_data: Optional[list] = None,
    causal_data: Optional[list] = None,
    time_window_hours: int = 4,
    min_layers: int = 3,
) -> List[ConfluenceEvent]:
    """
    One-shot confluence check across all layers.

    Accepts raw output dicts from each module, adapts them to Signals,
    and runs confluence detection.

    Returns:
        List of ConfluenceEvent objects, sorted by score descending.
    """
    scorer = ConfluenceScorer(
        time_window_hours=time_window_hours,
        min_layers=min_layers,
    )

    adapters = [
        (equities_data, adapt_equities),
        (congressional_data, adapt_congressional),
        (twitter_data, adapt_twitter),
        (fixed_income_data, adapt_fixed_income),
        (crypto_data, adapt_crypto),
        (macro_data, adapt_macro_calendar),
        (china_data, adapt_china_signals),
        (causal_data, adapt_causal),
    ]

    for data_list, adapter_fn in adapters:
        if not data_list:
            continue
        for item in data_list:
            try:
                signal = adapter_fn(item)
                if signal:
                    scorer.ingest_signal(signal)
            except Exception as e:
                logger.warning("Adapter %s failed: %s", adapter_fn.__name__, e)

    return scorer.check_confluence()


# ------------------------------------------------------------------ #
# Alert formatting
# ------------------------------------------------------------------ #

def format_confluence_alert(event: ConfluenceEvent) -> str:
    """Format a ConfluenceEvent for Telegram / stdout output."""
    return event.alert_text


# ------------------------------------------------------------------ #
# Database persistence
# ------------------------------------------------------------------ #

def save_confluence_event(db, event: ConfluenceEvent) -> int:
    """
    Save a confluence event to the database.

    Args:
        db: PythiaDB instance.
        event: ConfluenceEvent to persist.

    Returns:
        Row ID of the saved event.
    """
    import sqlite3
    conn = sqlite3.connect(db.db_path)
    try:
        cursor = conn.execute("""
            INSERT INTO confluence_events
            (event_category, direction, confluence_score, layer_count,
             layers, confidence, timestamp, historical_hit_rate,
             suggested_assets, alert_text, signals_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.event_category,
            event.direction,
            event.confluence_score,
            event.layer_count,
            json.dumps(event.layers),
            event.confidence,
            event.timestamp.isoformat(),
            event.historical_hit_rate,
            json.dumps(event.suggested_assets),
            event.alert_text,
            json.dumps([{
                "layer": s.layer,
                "direction": s.direction,
                "event_category": s.event_category,
                "confidence": s.confidence,
                "timestamp": s.timestamp.isoformat(),
                "description": s.description,
            } for s in event.signals]),
        ))
        conn.commit()
        row_id = cursor.lastrowid
        logger.info("Saved confluence event %d: %s %s (score=%.2f)",
                     row_id, event.event_category, event.direction,
                     event.confluence_score)
        return row_id
    finally:
        conn.close()


def get_confluence_history(db, hours: int = 24, min_score: float = 0.0) -> list:
    """
    Retrieve recent confluence events from the database.

    Args:
        db: PythiaDB instance.
        hours: How far back to look.
        min_score: Minimum confluence score to include.

    Returns:
        List of dicts representing confluence events.
    """
    import sqlite3
    conn = sqlite3.connect(db.db_path)
    try:
        cursor = conn.execute("""
            SELECT * FROM confluence_events
            WHERE timestamp > datetime('now', ?)
            AND confluence_score >= ?
            ORDER BY timestamp DESC
        """, (f'-{hours} hours', min_score))
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    except sqlite3.OperationalError:
        # Table may not exist yet
        return []
    finally:
        conn.close()
