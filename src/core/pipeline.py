"""
Pythia Live Pipeline — Core product loop.

Polls Polymarket, detects spikes, runs causal attribution (v2), outputs structured alerts.
"""
import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from .connectors.polymarket import PolymarketConnector
from .database import PythiaDB
from .detector import SignalDetector, Signal
from .attribution.adapters import PCEEngineAdapter, RCEEngineAdapter
from .attribution.orchestrator import AttributionOrchestrator
from .config import Config
from .equities import correlate_spike, format_correlation_alert
from .confluence import (
    ConfluenceScorer, adapt_equities, adapt_causal,
    save_confluence_event, format_confluence_alert,
)

logger = logging.getLogger(__name__)


@dataclass
class SpikeProxy:
    """Minimal spike object compatible with causal_v2.attribute_spike_v2()."""
    id: int
    market_id: str
    market_title: str
    timestamp: str
    direction: str
    magnitude: float
    price_before: float
    price_after: float
    volume_at_spike: float
    asset_class: str = ""
    attributed_events: list = field(default_factory=list)
    manual_tag: str = ""
    asset_reaction: dict = field(default_factory=dict)


def llm_call(prompt: str) -> str:
    """Call Claude via subprocess for LLM inference."""
    from .llm_integration import sanitize_llm_input
    prompt = sanitize_llm_input(prompt)
    try:
        result = subprocess.run(
            ['claude', '--print', '--model', 'sonnet', '-p', prompt],
            capture_output=True, text=True, timeout=90,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning("LLM call timed out")
        return ""
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        return ""


class Pipeline:
    """Main pipeline: fetch → detect → attribute → output."""

    def __init__(self, db_path: str = "data/pythia_live.db", dry_run: bool = False):
        self.db = PythiaDB(db_path)
        self.connector = PolymarketConnector()
        self.config = Config()
        self.detector = SignalDetector(self.db, vars(self.config))
        self.dry_run = dry_run
        self._recent_spike_proxies: List[SpikeProxy] = []
        self._confluence_scorer = ConfluenceScorer(time_window_hours=4, min_layers=3)
        self._attribution_orchestrator = AttributionOrchestrator(
            mode=getattr(self.config, "ATTRIBUTION_MODE", "fast"),
            engines={
                "pce_v2": PCEEngineAdapter(
                    entity_llm=llm_call,
                    filter_llm=llm_call,
                    reasoning_llm=llm_call,
                ),
                "rce_v1": RCEEngineAdapter(
                    llm_call=llm_call,
                    ontology_llm=llm_call,
                ),
            },
        )

    def run_cycle(self) -> List[Dict]:
        """Run one polling cycle. Returns list of alert dicts."""
        logger.info("=== Pipeline cycle start ===")
        alerts = []

        # 1. Fetch markets
        markets = self.connector.get_active_markets(limit=50)
        logger.info("Fetched %d markets from Polymarket", len(markets))
        if not markets:
            logger.warning("No markets fetched")
            return alerts

        # Save markets and prices to DB
        for m in markets:
            self.db.save_market(m)
            self.db.save_price(m['id'], m['yes_price'], m['no_price'],
                               m.get('volume_24h', 0))

        # 2. Detect signals
        all_signals: List[Signal] = []
        for m in markets:
            history = self.db.get_market_history(m['id'], hours=24)
            signals = self.detector.detect_all(m, history)
            all_signals.extend(signals)

        logger.info("Detected %d signals across %d markets", len(all_signals), len(markets))

        # 3. Filter to HIGH/CRITICAL spikes for attribution
        high_signals = [s for s in all_signals
                        if s.severity in ("HIGH", "CRITICAL")
                        and s.signal_type == "PROBABILITY_SPIKE"]

        logger.info("%d HIGH/CRITICAL probability spikes to attribute", len(high_signals))

        for signal in high_signals:
            # Save signal to DB
            signal_id = self.db.save_signal(
                market_id=signal.market_id,
                signal_type=signal.signal_type,
                severity=signal.severity,
                description=signal.description,
                old_price=signal.old_price,
                new_price=signal.new_price,
                expected_return=signal.expected_return,
            )

            # Create spike proxy for causal_v2
            direction = "up" if (signal.new_price or 0) > (signal.old_price or 0) else "down"
            magnitude = abs((signal.new_price or 0) - (signal.old_price or 0))

            spike = SpikeProxy(
                id=signal_id,
                market_id=signal.market_id,
                market_title=signal.market_title,
                timestamp=datetime.now().isoformat(),
                direction=direction,
                magnitude=magnitude,
                price_before=signal.old_price or 0,
                price_after=signal.new_price or 0,
                volume_at_spike=signal.metadata.get('current_volume', 0),
            )

            # Save spike event
            spike_id = self.db.save_spike_event({
                'market_id': spike.market_id,
                'market_title': spike.market_title,
                'timestamp': spike.timestamp,
                'direction': spike.direction,
                'magnitude': spike.magnitude,
                'price_before': spike.price_before,
                'price_after': spike.price_after,
                'volume_at_spike': spike.volume_at_spike,
            })
            spike.id = spike_id

            # Run causal attribution via orchestrator (fast/deep/shadow)
            if not self.dry_run:
                logger.info("Running causal attribution for: %s", spike.market_title[:60])
                attribution_result = self._attribution_orchestrator.attribute_spike(
                    spike=spike,
                    all_recent_spikes=self._recent_spike_proxies,
                    db=self.db,
                )
                result = attribution_result.to_legacy_result()
            else:
                result = {
                    "spike_id": spike_id,
                    "attribution": {
                        "most_likely_cause": "[dry-run — attribution skipped]",
                        "causal_chain": "",
                        "confidence": "N/A",
                        "expected_duration": "N/A",
                        "trading_implication": "",
                    },
                    "candidates_retrieved": 0,
                    "candidates_filtered": 0,
                    "top_candidates": [],
                }

            # Run cross-asset correlation
            correlation = None
            if not self.dry_run:
                try:
                    from .causal_v2 import classify_market
                    category = classify_market(spike.market_title)
                    correlation = correlate_spike(
                        market_title=spike.market_title,
                        category=category,
                        spike_time=spike.timestamp,
                        spike_direction=spike.direction,
                    )
                    logger.info("Cross-asset correlation: %s",
                                correlation.get("cross_asset_confidence", "N/A"))
                except Exception as e:
                    logger.warning("Cross-asset correlation failed: %s", e)

            self._recent_spike_proxies.append(spike)
            # Keep only last 20
            self._recent_spike_proxies = self._recent_spike_proxies[-20:]

            # Build alert
            alert = {
                "timestamp": datetime.now().isoformat(),
                "market_title": spike.market_title,
                "market_id": spike.market_id,
                "severity": signal.severity,
                "direction": spike.direction,
                "magnitude": spike.magnitude,
                "price_before": spike.price_before,
                "price_after": spike.price_after,
                "volume": spike.volume_at_spike,
                "attribution": result.get("attribution", {}),
                "candidates_retrieved": result.get("candidates_retrieved", 0),
                "candidates_filtered": result.get("candidates_filtered", 0),
                "correlation": correlation,
            }
            alerts.append(alert)

            # Output as JSON line to stdout
            print(json.dumps(alert), flush=True)

        # 4. Confluence check — feed correlation and causal results
        if not self.dry_run:
            for alert in alerts:
                corr = alert.get("correlation")
                if corr:
                    sig = adapt_equities(corr)
                    if sig:
                        self._confluence_scorer.ingest_signal(sig)
                attr = alert.get("attribution")
                if attr:
                    sig = adapt_causal({"attribution": attr})
                    if sig:
                        self._confluence_scorer.ingest_signal(sig)

            confluence_events = self._confluence_scorer.check_confluence()
            for ce in confluence_events:
                logger.info("Confluence event: %s %s (score=%.2f, layers=%d)",
                            ce.event_category, ce.direction,
                            ce.confluence_score, ce.layer_count)
                try:
                    save_confluence_event(self.db, ce)
                except Exception as e:
                    logger.warning("Failed to save confluence event: %s", e)
                print(json.dumps({
                    "type": "confluence",
                    "timestamp": ce.timestamp.isoformat(),
                    "event_category": ce.event_category,
                    "direction": ce.direction,
                    "confluence_score": ce.confluence_score,
                    "layer_count": ce.layer_count,
                    "layers": ce.layers,
                    "alert_text": ce.alert_text,
                }), flush=True)

        # Also report non-spike signals briefly
        other_signals = [s for s in all_signals if s not in high_signals]
        if other_signals:
            logger.info("Other signals (not attributed): %d", len(other_signals))
            for s in other_signals:
                self.db.save_signal(
                    market_id=s.market_id,
                    signal_type=s.signal_type,
                    severity=s.severity,
                    description=s.description,
                    old_price=s.old_price,
                    new_price=s.new_price,
                    expected_return=s.expected_return,
                )

        if not all_signals:
            logger.info("No spikes detected this cycle")

        logger.info("=== Pipeline cycle complete: %d alerts ===", len(alerts))
        return alerts

    def run_loop(self, interval: int = 60):
        """Run pipeline continuously."""
        logger.info("Starting pipeline loop (interval=%ds, dry_run=%s)", interval, self.dry_run)
        while True:
            try:
                self.run_cycle()
            except KeyboardInterrupt:
                raise
            except Exception as e:
                logger.error("Pipeline cycle error: %s", e, exc_info=True)
            time.sleep(interval)
