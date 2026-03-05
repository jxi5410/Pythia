# Pythia Causal Analysis v2 — Architecture

## The Problem

Current attribution is a dumb DuckDuckGo search. No temporal filtering, no relevance scoring, no reasoning. News results are generic, not causal.

## Design Principles

1. **Temporal precision** — Only consider news published in the 2 hours before a spike
2. **LLM reasoning** — Use Opus to reason about causality, not keyword matching
3. **Cross-market validation** — If multiple markets in the same category spike simultaneously, the cause is macro
4. **Confidence scoring** — Every attribution gets a confidence level with reasoning
5. **Layered approach** — Cheap filters first, expensive reasoning only on candidates that pass

## Architecture

```
SPIKE DETECTED
    │
    ▼
┌─────────────────────────────┐
│  Layer 1: CONTEXT BUILDER   │  (Free / Cheap)
│                             │
│  • Classify market category │
│  • Identify key entities    │
│  • Check: did other markets │
│    in same category spike?  │
│  • Build temporal window    │
│    (2h before → 30min after)│
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Layer 2: NEWS RETRIEVAL    │  (Free APIs)
│                             │
│  • NewsAPI.org (free tier:  │
│    100 req/day)             │
│  • Google News RSS          │
│  • Reddit (relevant subs)   │
│  • Twitter/X search         │
│  • Filter: published within │
│    temporal window ONLY     │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Layer 3: CANDIDATE FILTER  │  (Sonnet — fast)
│                             │
│  • Score each article 0-10  │
│    on relevance to market   │
│  • Discard score < 5        │
│  • Rank by relevance        │
│  • Keep top 5 candidates    │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Layer 4: CAUSAL REASONING  │  (Opus — deep)
│                             │
│  Given:                     │
│  • Market: [title]          │
│  • Spike: [dir] [mag] [ts] │
│  • Category: [cat]          │
│  • Correlated markets: [..] │
│  • Candidate articles: [..] │
│                             │
│  Ask Opus:                  │
│  1. Which article(s) most   │
│     plausibly caused this?  │
│  2. What's the causal chain?│
│     (event → mechanism →    │
│      market impact)         │
│  3. Confidence: HIGH/MED/LOW│
│  4. Was this macro or       │
│     idiosyncratic?          │
│  5. Expected duration of    │
│     the move                │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Layer 5: STORE & LEARN     │
│                             │
│  • Save attribution with    │
│    confidence + reasoning   │
│  • Track: did the move      │
│    sustain or reverse?      │
│  • Feed outcomes back into  │
│    pattern library          │
│  • Over time: learn which   │
│    news sources/types are   │
│    actually predictive      │
└─────────────────────────────┘
```

## Layer 1: Context Builder

```python
def build_spike_context(spike, all_recent_spikes):
    """
    Enrich a spike with contextual information before attribution.
    """
    context = {
        "market_title": spike.market_title,
        "category": classify_market(spike.market_title),
        "entities": extract_entities(spike.market_title),
        # e.g. ["Federal Reserve", "interest rates", "March 2025"]
        "spike": {
            "direction": spike.direction,
            "magnitude": spike.magnitude,
            "timestamp": spike.timestamp,
            "price_before": spike.price_before,
            "price_after": spike.price_after,
            "volume": spike.volume_at_spike,
        },
        "temporal_window": {
            "start": spike.timestamp - timedelta(hours=2),
            "end": spike.timestamp + timedelta(minutes=30),
        },
        # Cross-market correlation
        "correlated_spikes": find_concurrent_spikes(
            spike, all_recent_spikes, window_hours=2
        ),
        "is_macro": len(correlated_spikes) >= 2,
    }
    return context
```

Key: `extract_entities` uses an LLM (Sonnet, one call) to pull out the specific entities, people, and concepts from the market title. This gives us much better search queries than raw title text.

## Layer 2: News Retrieval

Multiple free sources, temporal filtering:

```python
def retrieve_candidate_news(context):
    """
    Fetch news articles published within the temporal window.
    Uses multiple free sources for coverage.
    """
    candidates = []
    window = context["temporal_window"]
    entities = context["entities"]

    # Source 1: NewsAPI.org (free: 100 req/day)
    # Searches by keyword + date range
    candidates += newsapi_search(
        query=" OR ".join(entities[:3]),
        from_date=window["start"],
        to_date=window["end"],
    )

    # Source 2: Google News RSS (free, no API key)
    # Searches by keyword, filter by published date
    candidates += google_news_rss(
        query=" ".join(entities[:2]),
        after=window["start"],
    )

    # Source 3: Reddit (free API)
    # Check relevant subreddits for discussion
    subreddit_map = {
        "fed_rate": "economics+finance",
        "crypto": "cryptocurrency+bitcoin",
        "election": "politics",
        "geopolitical": "worldnews+geopolitics",
    }
    subreddit = subreddit_map.get(context["category"], "news")
    candidates += reddit_search(
        query=" ".join(entities[:2]),
        subreddit=subreddit,
        after=window["start"],
    )

    # Deduplicate by headline similarity
    candidates = deduplicate(candidates)

    return candidates
```

## Layer 3: Candidate Filter (Sonnet)

Quick relevance scoring — one LLM call for all candidates:

```python
FILTER_PROMPT = """
Score each article's relevance to this prediction market spike.

MARKET: {market_title}
SPIKE: {direction} {magnitude:.1%} at {timestamp}
CATEGORY: {category}

ARTICLES:
{articles_formatted}

For each article, respond with:
- Article number
- Relevance score (0-10)
- One-line reason

Only articles scoring 5+ are worth deeper analysis.
"""
```

## Layer 4: Causal Reasoning (Opus)

The core differentiator. One deep reasoning call per spike:

```python
CAUSAL_PROMPT = """
You are analyzing a prediction market spike to determine its cause.

MARKET: {market_title}
CATEGORY: {category}
SPIKE: {direction} {magnitude:.1%} move
  Price: {price_before:.2f} → {price_after:.2f}
  Time: {timestamp}
  Volume: ${volume:,.0f}

CONCURRENT MARKET MOVES:
{correlated_spikes_formatted}

CANDIDATE CAUSES (relevance-filtered news):
{top_candidates_formatted}

ANALYSIS REQUIRED:

1. MOST LIKELY CAUSE: Which article(s) most plausibly caused this spike?
   Explain the causal chain: [Event] → [Mechanism] → [Market Impact]

2. MACRO VS IDIOSYNCRATIC: Is this a broad market move (macro catalyst)
   or specific to this contract?
   Evidence: {n_correlated} other markets moved simultaneously.

3. CONFIDENCE: Rate your attribution confidence.
   - HIGH: Clear causal link, timing matches, mechanism is obvious
   - MEDIUM: Plausible link but other explanations possible
   - LOW: Speculative, weak evidence

4. EXPECTED DURATION: Is this spike likely to sustain or reverse?
   - SUSTAINED: Fundamental shift (policy change, confirmed event)
   - TEMPORARY: Sentiment-driven, likely to revert
   - UNKNOWN: Insufficient information

5. TRADING IMPLICATION: If a trader sees this spike, what should they do?

Respond in structured format.
"""
```

## Layer 5: Store & Learn

```python
def store_attribution(spike, attribution):
    """
    Save the full attribution with reasoning.
    Track outcome for future learning.
    """
    record = {
        "spike_id": spike.id,
        "cause_headline": attribution["most_likely_cause"],
        "causal_chain": attribution["causal_chain"],
        "confidence": attribution["confidence"],  # HIGH/MED/LOW
        "macro_or_idiosyncratic": attribution["macro_vs_idio"],
        "expected_duration": attribution["duration"],
        "trading_implication": attribution["trading_implication"],
        "n_correlated_markets": attribution["n_correlated"],
        "candidate_articles": attribution["all_candidates"],
        "reasoning": attribution["full_reasoning"],
        # Outcome tracking (filled later)
        "price_1h_later": None,
        "price_24h_later": None,
        "attribution_validated": None,  # True/False after outcome
    }
    db.save_attribution(record)
```

## Free Tier Limits

| Source | Free Tier | Limit |
|--------|-----------|-------|
| NewsAPI.org | 100 requests/day | Enough for ~30 spikes/day |
| Google News RSS | Unlimited | No rate limit |
| Reddit API | 60 req/min | More than enough |
| Brave Search (via OpenClaw) | Already available | Already configured |

## Implementation Plan

1. Build `causal_v2.py` with all 5 layers
2. Register for NewsAPI.org free key
3. Test on the 100 synthetic spikes in DB
4. Compare v1 vs v2 attributions on same spikes
5. Integrate into live Pythia when ready

## Cost Per Spike

- Layer 1 (Context): Free (local computation)
- Layer 2 (News): Free (API calls)
- Layer 3 (Filter): 1 Sonnet call (~500 tokens) — flat subscription
- Layer 4 (Reasoning): 1 Opus call (~2000 tokens) — flat subscription
- Layer 5 (Store): Free (local DB)

**Total: $0 marginal cost.** Flat subscriptions for the win.
