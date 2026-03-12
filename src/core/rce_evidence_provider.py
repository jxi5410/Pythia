"""
RCE Evidence Provider — Domain-specific data for each agent.

The critical gap in v1: all agents received identical news articles.
The "On-chain Analyst" claimed to use Glassnode but actually just read Reuters.

This module wires the existing data source modules (crypto_onchain, fixed_income,
macro_calendar, twitter_signals, congressional, equities, orderbook_analyzer, etc.)
into each agent's evidence pipeline, so agents reason from genuinely different data.

Each agent gets:
  1. SHARED evidence: news articles (same as before)
  2. DOMAIN evidence: structured data from their actual claimed sources
  3. TIMING context: when each data point was produced relative to the spike

The timing context is key: agents must evaluate whether a data signal preceded
the spike (potential cause), followed it (potential reaction), or is too far
removed to be relevant.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class EvidenceItem:
    """A single piece of evidence with timing metadata."""
    source: str              # e.g. "crypto_onchain", "cme_fedwatch", "twitter"
    data_type: str           # e.g. "whale_movement", "rate_probability", "tweet"
    summary: str             # Human-readable summary
    raw_data: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[str] = None   # When this data point was produced
    timing_vs_spike: Optional[str] = None  # "before:2h", "after:30m", "concurrent"
    confidence: float = 1.0  # Data quality / freshness


@dataclass
class AgentEvidence:
    """Evidence package for a specific agent."""
    agent_id: str
    shared_news: List[Dict]        # News articles (same for all agents)
    domain_data: List[EvidenceItem]  # Agent-specific structured data
    timing_summary: str             # Pre-formatted timing analysis for the prompt
    fetch_errors: List[str] = field(default_factory=list)


def _compute_timing(data_timestamp: str, spike_timestamp: str) -> str:
    """Compute timing relationship between a data point and the spike.

    Returns: 'before:Xh', 'after:Xm', 'concurrent', or 'unknown'
    """
    try:
        spike_dt = _parse_dt(spike_timestamp)
        data_dt = _parse_dt(data_timestamp)
        if spike_dt is None or data_dt is None:
            return "unknown"

        delta = spike_dt - data_dt
        total_minutes = delta.total_seconds() / 60

        if abs(total_minutes) < 30:
            return "concurrent"
        elif total_minutes > 0:
            # Data came before spike
            hours = total_minutes / 60
            if hours >= 1:
                return f"before:{hours:.1f}h"
            return f"before:{total_minutes:.0f}m"
        else:
            # Data came after spike
            minutes_after = abs(total_minutes)
            if minutes_after >= 60:
                return f"after:{minutes_after / 60:.1f}h"
            return f"after:{minutes_after:.0f}m"
    except Exception:
        return "unknown"


def _parse_dt(ts: str) -> Optional[datetime]:
    """Best-effort timestamp parsing."""
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts.replace("+00:00", "Z").rstrip("Z"), fmt.rstrip("Z"))
        except ValueError:
            continue
    return None


# ----------------------------------------------------------------
# Domain evidence fetchers — one per data source module
# ----------------------------------------------------------------

def _fetch_crypto_evidence(spike_context: Dict) -> List[EvidenceItem]:
    """Fetch on-chain data, exchange flows, funding rates, fear/greed."""
    items = []
    spike_ts = spike_context.get("spike", {}).get("timestamp", "")

    try:
        from .crypto_onchain import (
            fetch_whale_movements, fetch_exchange_flows,
            fetch_funding_rates, fetch_fear_greed,
        )

        whales = fetch_whale_movements(min_btc=50, hours_back=6)
        if whales:
            for w in whales[:5]:
                items.append(EvidenceItem(
                    source="crypto_onchain",
                    data_type="whale_movement",
                    summary=f"Whale: {w.get('amount_btc', '?')} BTC "
                            f"from {w.get('from_type', '?')} to {w.get('to_type', '?')}",
                    raw_data=w,
                    timestamp=w.get("timestamp", ""),
                    timing_vs_spike=_compute_timing(w.get("timestamp", ""), spike_ts),
                ))

        flows = fetch_exchange_flows(hours_back=6)
        if flows:
            items.append(EvidenceItem(
                source="crypto_onchain",
                data_type="exchange_flows",
                summary=f"Net flow: {flows.get('net_flow_btc', '?')} BTC "
                        f"(inflow={flows.get('inflow_btc', '?')}, outflow={flows.get('outflow_btc', '?')})",
                raw_data=flows,
                timing_vs_spike="concurrent",
            ))

        funding = fetch_funding_rates()
        if funding:
            items.append(EvidenceItem(
                source="crypto_onchain",
                data_type="funding_rate",
                summary=f"Funding rate: {funding.get('btc_rate', '?')}% "
                        f"(OI: {funding.get('open_interest', '?')})",
                raw_data=funding,
                timing_vs_spike="concurrent",
            ))

        fg = fetch_fear_greed()
        if fg:
            items.append(EvidenceItem(
                source="crypto_onchain",
                data_type="fear_greed",
                summary=f"Fear & Greed Index: {fg.get('value', '?')} ({fg.get('classification', '?')})",
                raw_data=fg,
                timing_vs_spike="concurrent",
            ))

    except ImportError:
        logger.debug("crypto_onchain module not available")
    except Exception as e:
        logger.warning("Crypto evidence fetch failed: %s", e)

    return items


def _fetch_fixed_income_evidence(spike_context: Dict) -> List[EvidenceItem]:
    """Fetch FedWatch probabilities, yield curve data."""
    items = []
    try:
        from .fixed_income import fetch_fedwatch_probabilities

        fw = fetch_fedwatch_probabilities()
        if fw:
            meeting = fw.get("next_meeting", "?")
            probs = fw.get("probabilities", {})
            items.append(EvidenceItem(
                source="cme_fedwatch",
                data_type="rate_probability",
                summary=f"FedWatch for {meeting}: "
                        + ", ".join(f"{k}: {v}%" for k, v in list(probs.items())[:4]),
                raw_data=fw,
                timing_vs_spike="concurrent",
            ))

    except ImportError:
        logger.debug("fixed_income module not available")
    except Exception as e:
        logger.warning("Fixed income evidence fetch failed: %s", e)

    return items


def _fetch_macro_evidence(spike_context: Dict) -> List[EvidenceItem]:
    """Fetch economic calendar events near the spike."""
    items = []
    spike_ts = spike_context.get("spike", {}).get("timestamp", "")

    try:
        from .macro_calendar import fetch_economic_calendar

        events = fetch_economic_calendar(days_ahead=3)
        if events:
            for evt in events[:8]:
                timing = _compute_timing(evt.get("datetime", ""), spike_ts)
                items.append(EvidenceItem(
                    source="macro_calendar",
                    data_type="economic_event",
                    summary=f"{evt.get('name', '?')} ({evt.get('country', '?')}): "
                            f"actual={evt.get('actual', '?')}, forecast={evt.get('forecast', '?')}, "
                            f"prior={evt.get('prior', '?')}",
                    raw_data=evt,
                    timestamp=evt.get("datetime", ""),
                    timing_vs_spike=timing,
                ))

    except ImportError:
        logger.debug("macro_calendar module not available")
    except Exception as e:
        logger.warning("Macro evidence fetch failed: %s", e)

    return items


def _fetch_social_evidence(spike_context: Dict) -> List[EvidenceItem]:
    """Fetch social media signals (Twitter/X)."""
    items = []
    spike_ts = spike_context.get("spike", {}).get("timestamp", "")

    try:
        from .twitter_signals import search_recent_tweets, extract_search_terms

        title = spike_context.get("market_title", "")
        terms = extract_search_terms(title)

        for term in terms[:3]:
            tweets = search_recent_tweets(term, hours_back=4)
            for t in tweets[:3]:
                items.append(EvidenceItem(
                    source="twitter",
                    data_type="tweet",
                    summary=f"@{t.get('author', '?')}: {t.get('text', '')[:120]}",
                    raw_data=t,
                    timestamp=t.get("created_at", ""),
                    timing_vs_spike=_compute_timing(t.get("created_at", ""), spike_ts),
                ))
            time.sleep(0.3)

    except ImportError:
        logger.debug("twitter_signals module not available")
    except Exception as e:
        logger.warning("Social evidence fetch failed: %s", e)

    return items


def _fetch_congressional_evidence(spike_context: Dict) -> List[EvidenceItem]:
    """Fetch congressional trading signals."""
    items = []
    try:
        from .congressional import _fetch_quiver_quant, _fetch_capitol_trades

        trades = _fetch_quiver_quant(days_back=3) or _fetch_capitol_trades(days_back=3)
        if trades:
            for t in trades[:5]:
                items.append(EvidenceItem(
                    source="congressional",
                    data_type="congressional_trade",
                    summary=f"{t.get('politician', '?')} {t.get('transaction_type', '?')} "
                            f"{t.get('ticker', '?')} ({t.get('amount', '?')})",
                    raw_data=t,
                    timestamp=t.get("date", ""),
                    timing_vs_spike=_compute_timing(t.get("date", ""), 
                                                     spike_context.get("spike", {}).get("timestamp", "")),
                ))

    except ImportError:
        logger.debug("congressional module not available")
    except Exception as e:
        logger.warning("Congressional evidence fetch failed: %s", e)

    return items


def _fetch_equities_evidence(spike_context: Dict) -> List[EvidenceItem]:
    """Fetch correlated equity moves around the spike."""
    items = []
    try:
        from .equities import get_related_tickers, get_price_around_spike

        title = spike_context.get("market_title", "")
        category = spike_context.get("category", "")
        spike_time = spike_context.get("spike", {}).get("timestamp", "")

        tickers = get_related_tickers(title, category)
        for t in tickers[:4]:
            move = get_price_around_spike(t["ticker"], spike_time, window_hours=4)
            if move:
                items.append(EvidenceItem(
                    source="equities",
                    data_type="equity_move",
                    summary=f"{t['ticker']} ({t.get('relation', '?')}): "
                            f"{move.get('direction', '?')} {move.get('change_pct', 0):.2f}%",
                    raw_data={**t, **move},
                    timing_vs_spike="concurrent",
                ))

    except ImportError:
        logger.debug("equities module not available")
    except Exception as e:
        logger.warning("Equities evidence fetch failed: %s", e)

    return items


def _fetch_orderbook_evidence(spike_context: Dict) -> List[EvidenceItem]:
    """Fetch orderbook / liquidity signals."""
    items = []
    try:
        from .orderbook_analyzer import OrderbookAnalyzer

        market_id = spike_context.get("spike", {}).get("market_id", "")
        if market_id:
            analyzer = OrderbookAnalyzer()
            snapshot = analyzer.get_snapshot(market_id)
            if snapshot:
                items.append(EvidenceItem(
                    source="orderbook",
                    data_type="liquidity_snapshot",
                    summary=f"Bid depth: {snapshot.bid_depth:.0f}, "
                            f"Ask depth: {snapshot.ask_depth:.0f}, "
                            f"Spread: {snapshot.spread:.4f}",
                    raw_data=snapshot.__dict__ if hasattr(snapshot, '__dict__') else {},
                    timing_vs_spike="concurrent",
                ))

    except (ImportError, AttributeError):
        logger.debug("orderbook_analyzer module not available or not applicable")
    except Exception as e:
        logger.warning("Orderbook evidence fetch failed: %s", e)

    return items


# ----------------------------------------------------------------
# Agent-to-data-source mapping
# ----------------------------------------------------------------

# Maps agent domain → list of fetcher functions
DOMAIN_FETCHERS: Dict[str, List[Callable]] = {
    "macro_policy":     [_fetch_macro_evidence, _fetch_fixed_income_evidence, _fetch_equities_evidence],
    "market_structure":  [_fetch_orderbook_evidence, _fetch_equities_evidence],
    "geopolitical":     [_fetch_social_evidence, _fetch_equities_evidence],
    "regulatory":       [_fetch_congressional_evidence, _fetch_equities_evidence],
    "narrative":        [_fetch_social_evidence],
    "crypto_onchain":   [_fetch_crypto_evidence],
    "crypto_etf":       [_fetch_equities_evidence, _fetch_crypto_evidence],
    "fixed_income":     [_fetch_fixed_income_evidence, _fetch_macro_evidence],
    "fx_carry":         [_fetch_fixed_income_evidence, _fetch_equities_evidence],
    "supply_chain":     [_fetch_macro_evidence, _fetch_equities_evidence],
    "defense_intel":    [_fetch_social_evidence],
    "adversarial":      [],  # Adversarial agents use all shared evidence, no domain data
}


def _build_timing_summary(items: List[EvidenceItem], spike_context: Dict) -> str:
    """Build a timing analysis summary from evidence items.

    Groups evidence into: preceded spike, concurrent, followed spike, unknown.
    This is injected into agent prompts so they reason about temporal plausibility.
    """
    before = [i for i in items if i.timing_vs_spike and i.timing_vs_spike.startswith("before")]
    concurrent = [i for i in items if i.timing_vs_spike == "concurrent"]
    after = [i for i in items if i.timing_vs_spike and i.timing_vs_spike.startswith("after")]
    unknown = [i for i in items if not i.timing_vs_spike or i.timing_vs_spike == "unknown"]

    lines = ["TIMING ANALYSIS (relative to spike):"]

    if before:
        lines.append(f"\n  PRECEDED spike ({len(before)} signals) — potential causes:")
        for i in sorted(before, key=lambda x: x.timing_vs_spike):
            lines.append(f"    [{i.timing_vs_spike}] {i.summary[:100]}")

    if concurrent:
        lines.append(f"\n  CONCURRENT with spike ({len(concurrent)} signals) — ambiguous causality:")
        for i in concurrent:
            lines.append(f"    [concurrent] {i.summary[:100]}")

    if after:
        lines.append(f"\n  FOLLOWED spike ({len(after)} signals) — likely reactions, not causes:")
        for i in after:
            lines.append(f"    [{i.timing_vs_spike}] {i.summary[:100]}")

    if unknown:
        lines.append(f"\n  UNKNOWN timing ({len(unknown)} signals):")
        for i in unknown[:3]:
            lines.append(f"    [?] {i.summary[:100]}")

    lines.append(f"\n  TIMING RULE: Causes must precede effects. Evidence that followed the spike ")
    lines.append(f"  is likely a reaction. Weight 'before' signals heavily. Be skeptical of 'concurrent'.")
    lines.append(f"  Some causes (policy shifts, regulatory changes) have delayed effects — up to 24-48h.")
    lines.append(f"  Others (data releases, breaking news) have immediate impact within minutes.")

    return "\n".join(lines)


def gather_agent_evidence(
    agent_id: str,
    agent_domain: str,
    spike_context: Dict,
    shared_news: List[Dict],
) -> AgentEvidence:
    """Gather domain-specific evidence for a single agent.

    Args:
        agent_id: Agent identifier
        agent_domain: Agent's domain (maps to DOMAIN_FETCHERS)
        spike_context: Full spike context dict
        shared_news: News articles shared across all agents

    Returns:
        AgentEvidence with both shared and domain-specific data
    """
    domain_items: List[EvidenceItem] = []
    errors: List[str] = []

    fetchers = DOMAIN_FETCHERS.get(agent_domain, [])
    for fetcher in fetchers:
        try:
            items = fetcher(spike_context)
            domain_items.extend(items)
        except Exception as e:
            error_msg = f"{fetcher.__name__}: {e}"
            errors.append(error_msg)
            logger.warning("Evidence fetch error for agent %s: %s", agent_id, error_msg)

    timing_summary = _build_timing_summary(domain_items, spike_context)

    return AgentEvidence(
        agent_id=agent_id,
        shared_news=shared_news,
        domain_data=domain_items,
        timing_summary=timing_summary,
        fetch_errors=errors,
    )


def gather_all_agent_evidence(
    agents: List[Any],  # List[AgentPersona]
    spike_context: Dict,
    shared_news: List[Dict],
) -> Dict[str, AgentEvidence]:
    """Gather evidence for all agents.

    Caches fetcher results so the same data source isn't called multiple times
    if multiple agents share the same domain fetchers.

    Returns:
        Dict mapping agent_id → AgentEvidence
    """
    # Cache fetcher results to avoid duplicate calls
    fetcher_cache: Dict[str, List[EvidenceItem]] = {}
    result: Dict[str, AgentEvidence] = {}

    for agent in agents:
        domain_items: List[EvidenceItem] = []
        errors: List[str] = []

        fetchers = DOMAIN_FETCHERS.get(agent.domain, [])
        for fetcher in fetchers:
            cache_key = fetcher.__name__
            if cache_key not in fetcher_cache:
                try:
                    fetcher_cache[cache_key] = fetcher(spike_context)
                except Exception as e:
                    fetcher_cache[cache_key] = []
                    errors.append(f"{cache_key}: {e}")
            domain_items.extend(fetcher_cache[cache_key])

        timing_summary = _build_timing_summary(domain_items, spike_context)

        result[agent.id] = AgentEvidence(
            agent_id=agent.id,
            shared_news=shared_news,
            domain_data=domain_items,
            timing_summary=timing_summary,
            fetch_errors=errors,
        )

    n_unique = len(fetcher_cache)
    n_total_items = sum(len(e.domain_data) for e in result.values())
    logger.info(
        "Evidence gathered for %d agents: %d unique fetchers called, %d total domain items",
        len(agents), n_unique, n_total_items,
    )

    return result


def format_domain_evidence_for_prompt(evidence: AgentEvidence) -> str:
    """Format domain evidence into a string for injection into agent prompts.

    Separates shared news from domain-specific data, and includes timing context.
    """
    sections = []

    # Domain-specific data
    if evidence.domain_data:
        sections.append(f"YOUR DOMAIN DATA ({len(evidence.domain_data)} signals):")
        for item in evidence.domain_data:
            timing = f"[{item.timing_vs_spike}]" if item.timing_vs_spike else "[?]"
            sections.append(f"  {timing} [{item.source}/{item.data_type}] {item.summary}")
    else:
        sections.append("YOUR DOMAIN DATA: None available for this spike.")

    # Timing analysis
    sections.append("")
    sections.append(evidence.timing_summary)

    # Shared news (abbreviated — agents already get this)
    n_news = len(evidence.shared_news)
    sections.append(f"\nSHARED NEWS EVIDENCE: {n_news} articles (see NEWS EVIDENCE section above)")

    # Fetch errors (transparency)
    if evidence.fetch_errors:
        sections.append(f"\nDATA GAPS (could not fetch): {', '.join(evidence.fetch_errors)}")

    return "\n".join(sections)
