"""
Pythia Alert Engine — Configurable alert rules with cooldown and delivery.

Telegram bot removed. Delivery is currently log-only.
Future: webhook, email, push notification channels.

Trigger types:
  SPIKE       — Contract moves >X points in Y minutes
  VELOCITY    — Rate of change exceeds threshold
  CONFLUENCE  — N+ data layers converge (from confluence scorer)
  DIVERGENCE  — Cross-platform disagreement exceeds threshold
  PATTERN     — Historical pattern detected (from Becker data)

Each AlertRule defines a trigger, thresholds, and delivery channels.
Alert history tracks sent alerts with cooldown to avoid duplicates.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ALERT_HISTORY_FILE = os.path.join("data", "alert_history.json")


# ------------------------------------------------------------------ #
# Trigger types
# ------------------------------------------------------------------ #

class TriggerType(str, Enum):
    SPIKE = "SPIKE"
    VELOCITY = "VELOCITY"
    CONFLUENCE = "CONFLUENCE"
    DIVERGENCE = "DIVERGENCE"
    PATTERN = "PATTERN"


# ------------------------------------------------------------------ #
# Data classes
# ------------------------------------------------------------------ #

@dataclass
class AlertRule:
    """A single configurable alert rule."""
    name: str
    trigger: TriggerType
    enabled: bool = True
    # Thresholds (interpretation depends on trigger type)
    threshold: float = 0.05          # e.g. 5pp for SPIKE, 0.6 score for CONFLUENCE
    time_window_minutes: int = 60    # lookback for SPIKE / VELOCITY
    min_layers: int = 3              # for CONFLUENCE trigger
    divergence_points: float = 5.0   # for DIVERGENCE trigger
    # Targeting
    watchlist: Optional[str] = None  # filter to a specific watchlist, or None for all
    categories: List[str] = field(default_factory=list)  # event categories to watch
    # Delivery
    channels: List[str] = field(default_factory=lambda: ["log"])
    # Cooldown
    cooldown_minutes: int = 15


@dataclass
class FiredAlert:
    """Record of a sent alert for deduplication / cooldown."""
    rule_name: str
    trigger: str
    key: str               # dedup key: e.g. "SPIKE:fed_rate:bullish"
    message: str
    timestamp: datetime
    delivered_to: List[str] = field(default_factory=list)


# ------------------------------------------------------------------ #
# Alert history — cooldown & deduplication
# ------------------------------------------------------------------ #

class AlertHistory:
    """Tracks sent alerts to enforce cooldown windows."""

    def __init__(self, file_path: str = ALERT_HISTORY_FILE):
        self.file_path = file_path
        self._history: List[FiredAlert] = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.file_path):
            return
        try:
            with open(self.file_path, "r") as f:
                data = json.load(f)
            for item in data:
                self._history.append(FiredAlert(
                    rule_name=item["rule_name"],
                    trigger=item["trigger"],
                    key=item["key"],
                    message=item.get("message", ""),
                    timestamp=datetime.fromisoformat(item["timestamp"]),
                    delivered_to=item.get("delivered_to", []),
                ))
        except Exception as e:
            logger.warning("Failed to load alert history: %s", e)

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.file_path) or ".", exist_ok=True)
        data = []
        # Only persist last 500 alerts
        for a in self._history[-500:]:
            data.append({
                "rule_name": a.rule_name,
                "trigger": a.trigger,
                "key": a.key,
                "message": a.message[:200],
                "timestamp": a.timestamp.isoformat(),
                "delivered_to": a.delivered_to,
            })
        try:
            with open(self.file_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save alert history: %s", e)

    def is_cooled_down(self, key: str, cooldown_minutes: int) -> bool:
        """Check if enough time has passed since last alert with this key."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=cooldown_minutes)
        for alert in reversed(self._history):
            if alert.key == key:
                ts = alert.timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts > cutoff:
                    return False  # still in cooldown
                return True
        return True  # never fired

    def record(self, alert: FiredAlert) -> None:
        self._history.append(alert)
        self._save()

    def recent(self, hours: int = 24) -> List[FiredAlert]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        results = []
        for a in reversed(self._history):
            ts = a.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                break
            results.append(a)
        return results


# ------------------------------------------------------------------ #
# Telegram delivery
# ------------------------------------------------------------------ #

# ------------------------------------------------------------------ #
# Delivery (stub — telegram removed, future: webhook, email, push)
# ------------------------------------------------------------------ #

def _deliver_alert(message: str, channels: List[str]) -> List[str]:
    """Deliver alert to configured channels. Returns list of delivery results."""
    delivered_to: List[str] = []
    for channel in channels:
        # Future: implement webhook, email, push delivery
        logger.info("Alert [%s]: %s", channel, message[:200])
        delivered_to.append(f"{channel}:logged")
    return delivered_to


# ------------------------------------------------------------------ #
# Alert evaluation
# ------------------------------------------------------------------ #

def _build_dedup_key(trigger: TriggerType, category: str, direction: str) -> str:
    return f"{trigger.value}:{category}:{direction}"


def _format_alert_message(
    trigger: TriggerType,
    category: str,
    direction: str,
    details: Dict[str, Any],
) -> str:
    """Build a human-readable alert message for Telegram / dashboard."""
    severity_map = {
        TriggerType.CONFLUENCE: "HIGH CONFLUENCE",
        TriggerType.SPIKE: "SPIKE ALERT",
        TriggerType.VELOCITY: "VELOCITY ALERT",
        TriggerType.DIVERGENCE: "DIVERGENCE ALERT",
        TriggerType.PATTERN: "PATTERN MATCH",
    }
    label = severity_map.get(trigger, trigger.value)

    emoji = "\U0001f534" if trigger == TriggerType.CONFLUENCE else "\U0001f7e0"  # red / orange
    if trigger == TriggerType.DIVERGENCE:
        emoji = "\U0001f7e1"  # yellow

    lines = [f"{emoji} <b>{label}</b> — {category.upper()} ({direction.upper()})"]

    if trigger == TriggerType.SPIKE:
        move = details.get("move_pp", 0)
        contract = details.get("contract", "")
        sign = "+" if move >= 0 else ""
        lines.append(f"  {contract[:80]}")
        lines.append(f"  Move: {sign}{move:.0f}pp in {details.get('window_min', '?')}min")

    elif trigger == TriggerType.VELOCITY:
        rate = details.get("rate_per_min", 0)
        lines.append(f"  Rate of change: {rate:.2f}pp/min")

    elif trigger == TriggerType.CONFLUENCE:
        score = details.get("score", 0)
        layers = details.get("layers", [])
        lines.append(f"  Score: {score:.0%} | Layers: {len(layers)}/8")
        lines.append(f"  Agreeing: {', '.join(sorted(layers))}")
        for sig_desc in details.get("signal_descriptions", [])[:4]:
            lines.append(f"  \u2022 {sig_desc[:100]}")

    elif trigger == TriggerType.DIVERGENCE:
        platforms = details.get("platforms", {})
        for platform, price in platforms.items():
            lines.append(f"  {platform}: {price:.0f}%")
        gap = details.get("gap_pp", 0)
        lines.append(f"  Gap: {gap:.0f}pp")

    elif trigger == TriggerType.PATTERN:
        pattern = details.get("pattern_name", "")
        hit_rate = details.get("hit_rate", 0)
        samples = details.get("sample_size", 0)
        lines.append(f"  Pattern: {pattern}")
        lines.append(f"  Historical hit rate: {hit_rate:.0%} (n={samples})")

    # Suggested assets
    assets = details.get("suggested_assets", [])
    if assets:
        lines.append(f"\n  Assets: {', '.join(assets[:5])}")

    return "\n".join(lines)


# ------------------------------------------------------------------ #
# Alert Engine — main class
# ------------------------------------------------------------------ #

class AlertEngine:
    """
    Evaluates data against alert rules and fires notifications.

    Usage::

        engine = AlertEngine()
        engine.add_rule(AlertRule(name="fed_confluence", trigger=TriggerType.CONFLUENCE))
        engine.evaluate_confluence(confluence_events)
        engine.evaluate_spikes(spike_events)
    """

    def __init__(
        self,
        history_file: str = ALERT_HISTORY_FILE,
    ):
        self.rules: List[AlertRule] = []
        self.history = AlertHistory(history_file)

    # ------------------------------------------------------------------ #
    # Rule management
    # ------------------------------------------------------------------ #

    def add_rule(self, rule: AlertRule) -> None:
        self.rules.append(rule)

    def remove_rule(self, name: str) -> bool:
        before = len(self.rules)
        self.rules = [r for r in self.rules if r.name != name]
        return len(self.rules) < before

    def get_rules(self) -> List[AlertRule]:
        return list(self.rules)

    def load_default_rules(self) -> None:
        """Load sensible default alert rules."""
        defaults = [
            AlertRule(
                name="confluence_high",
                trigger=TriggerType.CONFLUENCE,
                threshold=0.6,
                min_layers=3,
                cooldown_minutes=30,
            ),
            AlertRule(
                name="spike_major",
                trigger=TriggerType.SPIKE,
                threshold=10.0,  # 10pp
                time_window_minutes=60,
                cooldown_minutes=15,
            ),
            AlertRule(
                name="divergence_cross_platform",
                trigger=TriggerType.DIVERGENCE,
                divergence_points=5.0,
                cooldown_minutes=60,
            ),
            AlertRule(
                name="pattern_high_confidence",
                trigger=TriggerType.PATTERN,
                threshold=0.7,  # 70% hit rate
                cooldown_minutes=120,
            ),
        ]
        for rule in defaults:
            if not any(r.name == rule.name for r in self.rules):
                self.rules.append(rule)

    # ------------------------------------------------------------------ #
    # Evaluation methods
    # ------------------------------------------------------------------ #

    def evaluate_confluence(self, confluence_events: list) -> List[FiredAlert]:
        """Evaluate confluence events against CONFLUENCE rules."""
        fired: List[FiredAlert] = []
        rules = [r for r in self.rules if r.enabled and r.trigger == TriggerType.CONFLUENCE]

        for event in confluence_events:
            score = event.get("confluence_score", 0) if isinstance(event, dict) else getattr(event, "confluence_score", 0)
            category = event.get("event_category", "") if isinstance(event, dict) else getattr(event, "event_category", "")
            direction = event.get("direction", "") if isinstance(event, dict) else getattr(event, "direction", "")
            layers = event.get("layers", []) if isinstance(event, dict) else getattr(event, "layers", [])
            if isinstance(layers, str):
                try:
                    layers = json.loads(layers)
                except (json.JSONDecodeError, TypeError):
                    layers = []
            layer_count = len(layers) if isinstance(layers, list) else int(layers or 0)
            alert_text = event.get("alert_text", "") if isinstance(event, dict) else getattr(event, "alert_text", "")

            for rule in rules:
                if score < rule.threshold:
                    continue
                if layer_count < rule.min_layers:
                    continue
                if rule.categories and category not in rule.categories:
                    continue

                key = _build_dedup_key(TriggerType.CONFLUENCE, category, direction)
                if not self.history.is_cooled_down(key, rule.cooldown_minutes):
                    continue

                # Build signal descriptions from signals_json if available
                sig_descs = []
                signals_raw = event.get("signals_json", "[]") if isinstance(event, dict) else getattr(event, "signals", [])
                if isinstance(signals_raw, str):
                    try:
                        signals_raw = json.loads(signals_raw)
                    except (json.JSONDecodeError, TypeError):
                        signals_raw = []
                for sig in (signals_raw or []):
                    if isinstance(sig, dict):
                        sig_descs.append(sig.get("description", "")[:100])
                    else:
                        sig_descs.append(getattr(sig, "description", "")[:100])

                suggested = event.get("suggested_assets", []) if isinstance(event, dict) else getattr(event, "suggested_assets", [])
                if isinstance(suggested, str):
                    try:
                        suggested = json.loads(suggested)
                    except (json.JSONDecodeError, TypeError):
                        suggested = []

                message = _format_alert_message(
                    TriggerType.CONFLUENCE, category, direction,
                    {
                        "score": score,
                        "layers": layers if isinstance(layers, list) else [],
                        "signal_descriptions": sig_descs,
                        "suggested_assets": suggested if isinstance(suggested, list) else [],
                    },
                )

                alert = self._fire(rule, key, message)
                if alert:
                    fired.append(alert)

        return fired

    def evaluate_spikes(self, spike_events: list) -> List[FiredAlert]:
        """Evaluate spike events against SPIKE rules."""
        fired: List[FiredAlert] = []
        rules = [r for r in self.rules if r.enabled and r.trigger == TriggerType.SPIKE]

        for spike in spike_events:
            magnitude = spike.get("magnitude", 0) if isinstance(spike, dict) else getattr(spike, "magnitude", 0)
            move_pp = magnitude * 100  # convert to percentage points
            title = spike.get("market_title", "") if isinstance(spike, dict) else getattr(spike, "market_title", "")
            direction = spike.get("direction", "") if isinstance(spike, dict) else getattr(spike, "direction", "")

            for rule in rules:
                if move_pp < rule.threshold:
                    continue

                key = _build_dedup_key(TriggerType.SPIKE, title[:30], direction)
                if not self.history.is_cooled_down(key, rule.cooldown_minutes):
                    continue

                message = _format_alert_message(
                    TriggerType.SPIKE, title[:50], direction,
                    {
                        "contract": title,
                        "move_pp": move_pp,
                        "window_min": rule.time_window_minutes,
                    },
                )

                alert = self._fire(rule, key, message)
                if alert:
                    fired.append(alert)

        return fired

    def evaluate_divergences(self, divergences: list) -> List[FiredAlert]:
        """Evaluate cross-platform divergences against DIVERGENCE rules."""
        fired: List[FiredAlert] = []
        rules = [r for r in self.rules if r.enabled and r.trigger == TriggerType.DIVERGENCE]

        for div in divergences:
            gap = div.get("gap_pp", 0)
            category = div.get("category", div.get("market_title", "unknown"))
            platforms = div.get("platforms", {})

            for rule in rules:
                if gap < rule.divergence_points:
                    continue

                key = _build_dedup_key(TriggerType.DIVERGENCE, category[:30], "divergence")
                if not self.history.is_cooled_down(key, rule.cooldown_minutes):
                    continue

                message = _format_alert_message(
                    TriggerType.DIVERGENCE, category, "divergence",
                    {"platforms": platforms, "gap_pp": gap},
                )

                alert = self._fire(rule, key, message)
                if alert:
                    fired.append(alert)

        return fired

    def evaluate_patterns(self, patterns: list) -> List[FiredAlert]:
        """Evaluate pattern matches against PATTERN rules."""
        fired: List[FiredAlert] = []
        rules = [r for r in self.rules if r.enabled and r.trigger == TriggerType.PATTERN]

        for pat in patterns:
            hit_rate = pat.get("hit_rate", 0) if isinstance(pat, dict) else getattr(pat, "confidence", 0)
            category = pat.get("category", "") if isinstance(pat, dict) else getattr(pat, "market_category", "")
            direction = pat.get("direction", "") if isinstance(pat, dict) else getattr(pat, "direction", "")
            samples = pat.get("sample_size", 0) if isinstance(pat, dict) else getattr(pat, "sample_size", 0)

            for rule in rules:
                if hit_rate < rule.threshold:
                    continue

                key = _build_dedup_key(TriggerType.PATTERN, category, direction)
                if not self.history.is_cooled_down(key, rule.cooldown_minutes):
                    continue

                message = _format_alert_message(
                    TriggerType.PATTERN, category, direction,
                    {
                        "pattern_name": category,
                        "hit_rate": hit_rate,
                        "sample_size": samples,
                    },
                )

                alert = self._fire(rule, key, message)
                if alert:
                    fired.append(alert)

        return fired

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _fire(self, rule: AlertRule, key: str, message: str) -> Optional[FiredAlert]:
        """Deliver alert and record it."""
        delivered_to = _deliver_alert(message, rule.channels)

        alert = FiredAlert(
            rule_name=rule.name,
            trigger=rule.trigger.value,
            key=key,
            message=message,
            timestamp=datetime.now(timezone.utc),
            delivered_to=delivered_to,
        )
        self.history.record(alert)
        logger.info("Alert fired: %s key=%s channels=%s", rule.name, key, delivered_to)
        return alert
