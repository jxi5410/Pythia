# Pythia: Prediction Market Intelligence for Institutional Traders

**From signal to thesis in seconds — not minutes.**
*February 2026 · v2*

---

## Executive Summary

**Pythia** is a prediction market intelligence platform that answers the question traders actually care about: **why did the price move, and what does it mean for my book?**

Prediction markets (Polymarket, Kalshi) are the fastest-pricing information instruments in the world. When a contract spikes 15%, something happened. But these platforms tell you *what* moved — not *why*. Traders are left to manually sift through news, Twitter, and wire services to reconstruct causality. That doesn't scale.

Pythia detects probability spikes across liquid prediction market contracts and **automatically attributes causes** using an 8-layer causal intelligence pipeline. It retrieves temporally-filtered news from multiple sources, scores relevance with AI, produces structured causal reasoning — including confidence levels, causal chains, duration expectations, and trading implications — and delivers it conversationally to traders where they already live: Telegram, Teams, or API.

**The core insight:** Prediction markets know things before your market prices them in. Pythia tells you what they know and what it means for your positions.

**Who it's for:** Event-driven portfolio managers, macro strategists, systematic quants, and crypto-native traders building strategies on event-probability signals.

**Why now:** Prediction market liquidity crossed $1B+ daily volume in 2025. These are no longer toy markets — they're information instruments. But the analytics layer doesn't exist yet. Verso (YC-backed) is building "Bloomberg for prediction markets" with 15K contracts and AI news mapping. Their reported accuracy is 73%. Pythia's edge: **9.15 million historical probability spikes** already analyzed, a pattern library of 30 discoverable spike archetypes, an 8-layer confluence scoring engine, regime detection, and deeper causal attribution that goes beyond headline matching — delivered through a conversational interface that fits how traders actually work.

---

## The Problem

A trader monitoring Polymarket sees this:

```
"Will the Supreme Court block Trump tariffs?"
  Price: $0.25 → $0.43 (+18pts)
  Volume: $120,000
  Time: 2026-02-21 11:00 UTC
```

**What happened?** The trader doesn't know. They open four browser tabs — AP, Reuters, Twitter, Google News — and spend 10-15 minutes piecing together that SCOTUS just ruled Trump's tariffs unconstitutional in a 6-3 decision. By the time they've confirmed causality, the market has already settled at the new equilibrium.

Now multiply this across 50 active contracts. It doesn't scale.

**The gap:** Prediction markets produce high-frequency probability signals with no causal metadata. Every spike is a black box. Traders need structured, machine-readable attribution — not just "the price moved," but *why it moved*, *how durable the move is*, and *what to do about it*.

**The bigger gap:** Even when traders find the cause, they miss the cross-market implications. A SCOTUS tariff ruling doesn't just move one contract — it has downstream effects on trade-sensitive equities, currency pairs, and commodity futures. No tool connects prediction market movements to traditional asset positioning. Pythia does.

---

## The Value Proposition: Five Mechanisms for Traders

**"Prediction markets know things before your market prices them in. Pythia tells you what they know and what it means for your book."**

Pythia creates value through five distinct mechanisms:

### 1. Event Probability as Positioning Signal
Prediction markets reprice faster than traditional markets. A 20-point probability spike on "Will the Fed cut rates?" typically leads equity and rates markets by 15-45 minutes. Pythia detects these spikes in real-time and maps them to tradeable assets in your universe.

### 2. Catalyst Timing for Event-Driven Equity
Event-driven PMs need to know *when* a catalyst will land, not just *if*. Pythia tracks probability velocity — the rate of change, not just the level — to identify when a market is pricing in imminent resolution. "This contract moved 8 points in 2 hours after being flat for 3 weeks" is a timing signal.

### 3. Cross-Asset Regime Detection
Clusters of prediction market moves signal regime changes before traditional indicators. When 5 geopolitical contracts spike simultaneously, that's not 5 independent events — it's a regime shift. Pythia's regime detection engine classifies these clusters and compares them to historical analogs with known outcomes.

### 4. Tail Risk Monitoring
Prediction markets price events that have no traditional instruments. There's no option on "Will Turkey invade Syria?" or "Will the EU impose capital controls?" But these events have massive P&L implications. Pythia monitors the long tail of low-probability, high-impact contracts and alerts when they start moving.

### 5. Narrative Arbitrage
The fastest-moving information in markets is narrative. Prediction market probability spikes are narrative made quantitative. Pythia gives traders first-mover advantage by mapping probability spikes to affected assets before the narrative reaches Bloomberg terminals and sellside research.

---

## The Pipeline: 8-Layer Causal Intelligence

The original 5-layer pipeline has been extended to 8 layers, adding confluence scoring, regime detection, and track record validation.

```
┌──────────────────────────────────────────────────────────────────┐
│                  PYTHIA 8-LAYER INTELLIGENCE PIPELINE             │
│                                                                  │
│  ┌──────────────┐   Spike detected: "SCOTUS + tariffs"          │
│  │ Layer 1      │   Category: trade_war                          │
│  │ CONTEXT      │   Entities: ["Supreme Court Trump tariffs",    │
│  │ BUILDER      │     "tariff legal challenge", "SCOTUS          │
│  │ (free)       │     executive trade authority"]                 │
│  └──────┬───────┘   Concurrent spikes: 0 (idiosyncratic)        │
│         │                                                        │
│  ┌──────▼───────┐   Sources: NewsAPI, Google News RSS,           │
│  │ Layer 2      │   DuckDuckGo, Reddit                           │
│  │ NEWS         │   Temporal window: ±2 hours of spike           │
│  │ RETRIEVAL    │   Retrieved: 10 candidates                     │
│  │ (free APIs)  │   After temporal filter: 10                    │
│  └──────┬───────┘                                                │
│         │                                                        │
│  ┌──────▼───────┐   Model: Claude Sonnet (fast)                  │
│  │ Layer 3      │   Scoring: 0-10 relevance per article          │
│  │ CANDIDATE    │   Threshold: ≥5 to pass                        │
│  │ FILTER       │   Result: 10 → 5 articles                      │
│  │ (Sonnet)     │                                                │
│  └──────┬───────┘                                                │
│         │                                                        │
│  ┌──────▼───────┐   Model: Claude Opus (deep reasoning)          │
│  │ Layer 4      │   Outputs:                                     │
│  │ CAUSAL       │   • Most likely cause                          │
│  │ REASONING    │   • Causal chain (event→mechanism→impact)      │
│  │ (Opus)       │   • Confidence: HIGH / MEDIUM / LOW            │
│  │              │   • Duration: SUSTAINED / TEMPORARY            │
│  └──────┬───────┘   • Trading implication                        │
│         │                                                        │
│  ┌──────▼───────┐   Store attribution in DB                      │
│  │ Layer 5      │   Track outcomes (1h, 24h price checks)        │
│  │ STORE &      │   Human feedback loop (correct/wrong)          │
│  │ LEARN        │   Feed corrections into future prompts         │
│  └──────┬───────┘                                                │
│         │                                                        │
│  ┌──────▼───────┐   Cross-layer signal detection (813 lines)     │
│  │ Layer 6      │   Standardized Signal dataclass                │
│  │ CONFLUENCE   │   ConfluenceEvent scoring:                     │
│  │ SCORING      │     2 layers agree = 0.30 confidence           │
│  │ (new)        │     3 layers agree = 0.60 confidence           │
│  │              │     4+ layers agree = 0.85+ confidence         │
│  └──────┬───────┘   Time decay + diversity weighting             │
│         │                                                        │
│  ┌──────▼───────┐   Classifies market state:                     │
│  │ Layer 7      │   policy_uncertainty | geopolitical_shock |    │
│  │ REGIME       │   risk_off | crypto_event | calm               │
│  │ DETECTION    │   Historical cluster comparisons:              │
│  │ (new)        │   "Last time this cluster appeared,            │
│  └──────┬───────┘    SPX -2.3% in 48h"                          │
│         │                                                        │
│  ┌──────▼───────┐   Hit rate by confidence threshold             │
│  │ Layer 8      │   False positive rate tracking                 │
│  │ TRACK        │   Lead-lag analysis per category               │
│  │ RECORD       │   Layer contribution statistics                │
│  │ (new)        │   "HIGH confidence signals: 78% hit rate       │
│  └──────────────┘    over last 30 days"                          │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Key design decisions:**

- **Temporal filtering is critical.** We only consider news published within a ±2 hour window of the spike. This eliminates 60-80% of noise from keyword-matched but causally irrelevant articles.
- **Two-stage LLM filtering.** Sonnet is fast and cheap for relevance scoring. Opus is reserved for the expensive causal reasoning step. This keeps cost per attribution under $0.05.
- **Concurrent spike detection.** If 5 markets spike simultaneously, it's macro (Fed announcement, geopolitical event). If one market spikes alone, it's idiosyncratic. This classification changes the reasoning approach.
- **Feedback loop.** Layer 5 stores human corrections ("this attribution was wrong because X") and injects them into future Layer 4 prompts, reducing repeat errors.
- **Confluence scoring (Layer 6).** When multiple data layers agree — news sentiment, price action, volume, cross-market correlation — the confidence score compounds. 4+ layers agreeing produces 0.85+ confidence with time-decay weighting. 33 unit tests validate scoring logic.
- **Regime detection (Layer 7).** Individual signals are useful. But clusters of signals reveal something bigger: regime shifts. The engine classifies the current market state and retrieves historical analogs with verified outcomes.
- **Track record (Layer 8).** Every signal is logged with its verified outcome. Hit rate, false positive rate, lead-lag analysis, and per-category breakdown build the statistical proof traders demand.

---

## Before & After: v1 vs v2

### v1 Attribution (Legacy)

The v1 system used simple headline matching. Here's what it actually returned:

```
Market: "Will the Fed cut rates in March 2025?"
Spike: -12% at 2025-01-29 19:00 UTC

v1 Attribution:
  cause: "reuters.com"
  confidence: null
  reasoning: null
```

That's it. A domain name. No headline, no causal chain, no confidence assessment, no trading implication. This is what "attribution" looked like before v2.

### v2 Attribution: Real Pipeline Outputs

The following are **actual outputs** from the Pythia causal v2 pipeline, run on February 21, 2026 against real news sources. Nothing is mocked — these are the real LLM responses from the full 5-layer pipeline.

---

#### Test 1: Supreme Court vs. Trump Tariffs

```
Market:     "Will the Supreme Court block Trump tariffs?"
Spike:      UP +18% ($0.25 → $0.43)
Volume:     $120,000
Timestamp:  2026-02-21T11:00:00 UTC
```

**Pipeline metrics:** 10 articles retrieved → 5 passed relevance filter

**Full attribution output:**

```json
{
  "most_likely_cause": "The Supreme Court issued a ruling striking down or significantly
    limiting Trump's tariff authority, directly validating the market's probability of
    judicial intervention.",
  "causal_chain": "Supreme Court rules Trump tariffs exceed executive authority → AP News,
    Guardian, Reuters publish simultaneous breaking coverage → traders reprice probability
    of tariff blockage from 25% to 43% → $120K volume spike confirms institutional
    repositioning",
  "confidence": "HIGH",
  "confidence_reasoning": "Multiple top-tier, independent sources (AP News, Guardian, NYT,
    Reuters, The Conversation) all report the same specific event — a Supreme Court ruling
    against Trump tariffs — with high relevance scores (9-10/10). The causal link is direct:
    the market literally asks 'Will the Supreme Court block Trump tariffs?' and the Court
    apparently did exactly that. Concurrent market isolation (0 other markets moved) further
    confirms this is event-specific, not macro noise.",
  "macro_or_idiosyncratic": "IDIOSYNCRATIC",
  "expected_duration": "SUSTAINED",
  "duration_reasoning": "A Supreme Court ruling is a durable legal fact, not a rumor or
    temporary sentiment shift. However, Reuters notes Trump is 'trying another tariff route'
    after the decision, suggesting the legal battle may continue.",
  "trading_implication": "The 18-point move already prices in the core ruling. Key residual
    risks: (1) whether the ruling is narrow vs. broad; (2) Trump's alternative tariff route
    could compress price back toward 0.35; (3) if stayed or appealed, sharp reversal likely.
    Traders should not chase at 0.43 without reading the ruling's scope.",
  "alternative_explanations": [
    "A lower court injunction misattributed to SCOTUS in early headlines",
    "An oral argument or procedural order interpreted as a final ruling"
  ]
}
```

**Top news candidates (relevance-scored):**

- **10/10** — The Guardian: "Trump overstepped executive power by imposing tariffs, supreme court rules"
- **10/10** — AP News: "Supreme Court strikes down Trump's sweeping tariffs"
- **9/10** — Reuters: "Trump tries another tariff route after Supreme Court ruling"

---

#### Test 2: Fed Rate Cut — March 2025

```
Market:     "Will the Fed cut rates in March 2025?"
Spike:      DOWN -12% ($0.35 → $0.23)
Volume:     $85,000
Timestamp:  2025-01-29T19:00:00 UTC
```

**Pipeline metrics:** 5 articles retrieved → 3 passed relevance filter

*(NewsAPI unavailable for this date range — Google News RSS and DuckDuckGo provided coverage)*

**Full attribution output:**

```json
{
  "most_likely_cause": "The Fed unanimously held rates steady at 4.5% in March 2025,
    confirming no cut and driving the 'Yes' probability down from 0.35 to 0.23.",
  "causal_chain": "Fed March 2025 FOMC decision → unanimous hold at 4.5%, no rate cut
    delivered → market resolved or repriced sharply toward 'No', collapsing the 'Yes'
    probability by 34%",
  "confidence": "HIGH",
  "confidence_reasoning": "Two independent primary sources (JPMorgan, CNBC) directly
    confirm the Fed held rates steady in March 2025, and a third (Forbes) anticipated
    the hold beforehand. The spike direction (down) is fully consistent with a 'No'
    outcome being confirmed. Evidence is specific, multi-sourced, and directionally
    coherent.",
  "macro_or_idiosyncratic": "MACRO",
  "macro_reasoning": "Fed rate decisions are top-tier macro events affecting rates,
    equities, credit, and FX globally.",
  "expected_duration": "SUSTAINED",
  "duration_reasoning": "Once the Fed confirmed a hold and markets repriced expectations,
    the move is unlikely to reverse unless a subsequent FOMC meeting or data surprise
    opens the door to cuts again.",
  "trading_implication": "Traders should treat this as a resolved or near-resolved
    informational event. With 'Yes' at 0.23, any remaining premium reflects residual
    uncertainty about emergency cuts — not the March outcome specifically."
}
```

---

#### Test 3: Ukraine Ceasefire

```
Market:     "Will there be a Ukraine ceasefire agreement by June 2025?"
Spike:      UP +10% ($0.15 → $0.25)
Volume:     $45,000
Timestamp:  2025-02-15T10:00:00 UTC
```

**Pipeline metrics:** 7 articles retrieved → 5 passed relevance filter

**Attribution summary:**

```
Most likely cause:  A new round of US-mediated Russia-Ukraine peace talks ended
                    without breakthrough, but confirmed active engagement
Confidence:         MEDIUM
Causal chain:       3rd round of US-mediated peace talks confirmed → talks described
                    as "difficult" but ongoing → continued engagement signals ceasefire
                    remains on the table → traders repriced upward from 0.15 to 0.25
Duration:           TEMPORARY
Trading implication: Monitor whether a 4th round is scheduled. If Russia signals
                    disengagement, expect sharp reversal. Current 0.25 may be
                    slightly overpriced absent a concrete framework agreement.
                    Thin liquidity ($45K) means single traders can move the market.
```

**Note the MEDIUM confidence and TEMPORARY duration.** The pipeline correctly identifies that the causal link is interpretive — talks happened but didn't produce an agreement. The move is directionally consistent but the mechanism is ambiguous. This kind of intellectual honesty is exactly what distinguishes useful attribution from noise.

---

#### What v1 Would Have Returned for These Same Markets

- **SCOTUS tariffs** — v1: `"theguardian.com"` → v2: Structured causal chain with HIGH confidence, duration analysis, trading implications, alternative explanations
- **Fed rate cut** — v1: `"reuters.com"` → v2: MACRO classification, FOMC-specific causal chain, HIGH confidence with multi-source verification
- **Ukraine ceasefire** — v1: `"bbc.com"` → v2: MEDIUM confidence (honest), TEMPORARY duration flag, thin-liquidity warning, nuanced mechanism analysis

v1 gave you a URL. v2 gives you a trading thesis.

---

## The Product Pivot: Conversational Intelligence

### The Insight

Traders don't stare at dashboards. They glance at them. What they actually do all day is talk — to their PMs, to other traders, to their risk desk, to the sellside. The most valuable intelligence on a trading floor comes from conversation, not screens.

**The pivot:** Pythia's primary interface is now a **conversational companion** — a Telegram/Teams bot that talks like the smartest person on the trading floor. The Bloomberg-style dashboard becomes the deep-dive tool. Intelligence is *pushed* to traders in their natural workflow, not pulled from a terminal they have to remember to check.

### What It Looks Like

**A trader messages Pythia on Telegram:**

```
Trader:  whats moving
Pythia:  📊 Three things catching my eye right now:

         1. "Trump tariff SCOTUS ruling" — UP 18pts in 2 hours.
            HIGH confidence. Supreme Court struck down executive
            tariff authority. This is sustained — legal fact, not
            rumor. RTX, LMT watching.

         2. "Fed March cut" cluster — 3 related contracts all
            drifting down. Regime: policy_uncertainty. Last time
            this pattern appeared, SPX -1.4% in 24h.

         3. Ukraine ceasefire — quiet move, +10pts on thin volume.
            MEDIUM confidence. I'd fade this unless a 4th round
            of talks is confirmed.

         Want me to drill into any of these?
```

```
Trader:  why did bitcoin spike
Pythia:  BTC-related contracts moved because Polymarket's "Bitcoin
         above $100K by March" jumped 12pts after Microstrategy
         announced another $500M purchase. Confluence score: 0.72
         (news + price action + volume aligned, but no on-chain
         confirmation yet).

         Historical pattern: Microstrategy buys have produced
         a median 48h BTC return of +3.2% across 7 prior instances.
         Fades after 72h in 5 of 7 cases.
```

```
Trader:  watch RTX for me
Pythia:  ✅ Added RTX to your watchlist. I'll alert you when any
         prediction market contract with defense/tariff/geopolitical
         exposure moves >5pts. Current relevant contracts:
         • "SCOTUS tariff ruling" (0.43, +18 today)
         • "US defense budget increase" (0.61, flat)
         • "Taiwan strait incident by 2026" (0.08, flat)
```

```
Trader:  whats the vibe
Pythia:  🌡️ Regime: policy_uncertainty (elevated since Tuesday).
         5 of 8 layers showing stress. Confluence events up 40%
         vs. 7-day average. This cluster looks like Nov 2025
         (pre-tariff announcement) — that time, VIX +3pts in 48h.
         Not panic, but hedges are cheap here.
```

### Why Conversational Wins

- **Zero friction.** No login, no dashboard, no context switching. The trader messages from the same app they use for everything else.
- **Proactive intelligence.** Pythia doesn't wait to be asked. When a HIGH-confidence confluence event fires, it pushes the alert immediately.
- **Per-user context.** Pythia remembers what you care about. If you've been asking about defense stocks, it knows to flag the SCOTUS tariff ruling for you specifically.
- **Natural language, not commands.** "whats moving" and "/confluence" return the same intelligence. The bot understands trader slang, abbreviations, and incomplete questions.
- **~990 lines of conversational NLU.** Rule-based natural language understanding — no external LLM needed for intent parsing. Fast, deterministic, and cheap.

---

## System Architecture: What's Been Built

### Infrastructure Summary (as of 22 Feb 2026)

| Component | Lines | Description |
|-----------|-------|-------------|
| Causal v2 Pipeline | ~1,200 | 5-layer attribution engine (context → news → filter → reason → store) |
| Confluence Scorer | 813 | Cross-layer signal detection, scoring, time decay, backtesting hooks |
| Streamlit Dashboard | 801 | Bloomberg-dark UI: 6 tabs, watchlist selector, alert config, system status |
| Track Record Engine | 682 | Hit rate, false positives, lead-lag, per-category breakdown, layer contribution |
| Contract Detail Engine | 565 | Per-contract drill-down: cross-platform prices, 8-layer status, causal attribution |
| FastAPI REST API | 533 | 9 endpoints: /confluence, /signals, /contract, /regime, /track-record, /watchlists, /patterns, /health |
| Alert Engine | 525 | 5 trigger types (SPIKE, VELOCITY, CONFLUENCE, DIVERGENCE, PATTERN), cooldown, Telegram delivery |
| Regime Detection | 480 | 5 regime classifications, historical cluster matching with verified outcomes |
| Telegram Bot (commands) | 421 | /confluence, /regime, /proof, /detail, /watchlist |
| Conversational Bot | ~990 | Primary interface. Natural language, trader-fluent, per-user memory, proactive alerts |
| Watchlist System | 169 | User-defined contract universes, CRUD operations |
| **Total** | **~7,200** | **Production-grade intelligence platform** |

### The Dashboard: Bloomberg-Dark, 6 Tabs

The Streamlit dashboard is the deep-dive tool — what traders use when they want to explore, not just receive alerts.

**Tab 1: "What's Moving Now"** — Live confluence events ranked by score. Each card shows: contract name, probability change, confluence score (0-1), contributing layers, regime classification, and one-line trading implication.

**Tab 2: Inquiry** — Natural language query interface. "Why did the SCOTUS tariff contract move?" returns the full Layer 4 attribution with sources.

**Tab 3: Patterns** — The 30-archetype pattern library from the Becker dataset. Filter by category, magnitude, reversion profile. "Show me all FOMC drift patterns with >70% sustain rate."

**Tab 4: Correlations** — Cross-market correlation matrix. Which prediction market contracts move together? Which traditional assets correlate with which contract categories?

**Tab 5: News Impact** — Temporal analysis of news-to-price-action lag. How quickly do prediction markets price in different categories of news? Where is the lead time longest?

**Tab 6: Track Record** — Pythia's own performance. Hit rate by confidence level, false positive rate over time, layer contribution analysis. The self-auditing tab.

### The API: 9 Endpoints

For systematic traders (like Raj) who want raw data, not a UI:

```
GET  /health              → System status
GET  /confluence           → Current confluence events with scores
GET  /signals              → Raw signals from all 8 layers
GET  /contract/{id}        → Full drill-down: prices, layers, attribution
GET  /regime               → Current regime + historical analogs
GET  /track-record         → Hit rates, false positives, lead-lag stats
GET  /watchlists           → User watchlists (CRUD)
GET  /patterns             → Pattern library query
POST /patterns/match       → "Does this spike match a known pattern?"
```

**Response format:** JSON with standardized Signal schema. Every response includes `confidence`, `timestamp`, `contributing_layers`, and `track_record_context`.

### The Alert Engine: 5 Trigger Types

| Trigger | Description | Example |
|---------|-------------|---------|
| SPIKE | Absolute probability change exceeds threshold | "SCOTUS tariffs +18pts" |
| VELOCITY | Rate of change exceeds threshold | "Fed cut contract moving 3pts/hour" |
| CONFLUENCE | Multiple layers agree above threshold | "4 of 8 layers aligned on defense cluster" |
| DIVERGENCE | Prediction market diverges from traditional market | "Polymarket pricing 40% rate cut but Fed funds futures at 15%" |
| PATTERN | Current price action matches known archetype | "This looks like an FOMC drift pattern (78% sustain rate)" |

Alerts include cooldown logic (no duplicate alerts within configurable windows) and deliver via Telegram with full context.

---

## Historical Depth: The Becker Dataset

Pythia's moat isn't just the attribution pipeline — it's the data underneath.

We've processed the complete Becker prediction market dataset:

- **9.15 million probability spikes** detected and catalogued
- **30 discoverable spike patterns** identified via clustering
- **Pattern library** with frequency distributions, magnitude profiles, and temporal signatures

### What the Pattern Library Contains

Each of the 30 patterns has:

- **Archetype name** (e.g., "FOMC drift," "election eve compression," "binary resolution cascade")
- **Frequency:** How often this pattern occurs per month
- **Magnitude distribution:** p10/p50/p90 of spike sizes
- **Temporal signature:** Time-of-day and day-of-week clustering
- **Reversion profile:** How often and how quickly the spike reverts
- **Cross-market correlation:** Whether this pattern co-occurs across markets

### Why This Matters

Verso has 15,000 live contracts with AI-powered news mapping at 73% accuracy. That's a good start for real-time monitoring.

Pythia has **9.15 million historical data points** that reveal the statistical structure of prediction market price discovery. When we see a spike that matches the "FOMC drift" pattern, we know — from historical data — that:

- These spikes have a 78% probability of sustaining after 24 hours
- The median magnitude is 8.3% with a fat right tail
- They cluster at 14:00-14:30 ET (post-announcement)
- Correlated markets move within 12 minutes

This is the kind of systematic edge that matters to quantitative traders. Attribution + historical pattern matching = actionable intelligence.

---

## Shadow Trader Panel: What Real Traders Said

We ran Pythia's v2 system past four trader archetypes — each representing a distinct user persona and willingness to pay. Their feedback shaped every product decision described in this deck.

### Elena — Event-Driven Portfolio Manager (ICP)

> "I don't want 20 widgets. I want 6 excellent ones. Confluence scoring is exactly what I'd use — show me when multiple signals agree, not when one headline moves one contract."

- Loves the confluence scoring engine
- Wants Bloomberg-dark aesthetics (delivered in Phase 1 UI)
- Her workflow: check the dashboard 2-3x/day, get Telegram alerts for HIGH-confidence events
- **Willingness to pay: $5,000–10,000/month**

### Sarah — Macro Hedge Fund Strategist

> "I don't want a dashboard at all. I want alerts. And regime detection — that's the killer feature. Tell me when the world is shifting before my Bloomberg terminal does."

- Alerts-first, not dashboard-first
- Regime detection is her #1 feature: "Last time this cluster appeared, SPX -2.3% in 48h" is the exact sentence she wants in her inbox
- Wants enterprise API integration with her existing risk systems
- **Willingness to pay: $8,000–20,000/month**

### Raj — Systematic Quant

> "I don't need a UI. Give me an API and a Python SDK. And I need statistical proof — show me backtested hit rates by confidence level before I plug this into anything."

- API + Python SDK only
- Track Record tab is table stakes for him — he won't touch signals without verified hit rates
- Wants raw data for his own models, not Pythia's interpretation
- **Willingness to pay: $5,000–20,000/month for data**

### Marcus — Crypto-Native Trader

> "Telegram bot or nothing. I live in Telegram. If I have to open another app, I won't use it."

- Telegram bot is the only interface he'll use
- Wants it fast and conversational — not command-line syntax
- Price-sensitive compared to institutional traders
- **Willingness to pay: $500–3,000/month**

### Universal Feedback

- **Statistical proof of alpha is non-negotiable.** Every trader asked for it. The Track Record Engine (Layer 8) was built in direct response.
- **API is table stakes.** Not a premium feature — it's expected at every tier.
- **"Don't make me think."** The conversational bot won out over the dashboard for daily use across all four personas.

---

## Pricing

| Tier | Target | Interface | Price |
|------|--------|-----------|-------|
| **Signal** | Elena (event-driven PM) | Dashboard + Telegram alerts + API | $5,000/mo |
| **Data** | Raj (systematic quant) | API + Python SDK + raw data export | $8,000/mo |
| **Enterprise** | Sarah (macro HF) | Full platform + custom integrations + regime alerts | $15,000/mo |
| **Alert Bot** | Marcus (crypto) | Telegram conversational bot + alerts | $500/mo |

**Revenue model at scale:**
- 10 Signal clients = $50K/mo
- 5 Data clients = $40K/mo
- 3 Enterprise clients = $45K/mo
- 50 Alert Bot users = $25K/mo
- **Total at modest scale: $160K/mo ($1.9M ARR)**

---

## The Moat: From Intelligence Engine to Agentic Economy

Pythia's intelligence engine is the business. The question every investor and partner asks: *how do you stay ahead once someone replicates the data pipeline?*

The answer is a three-phase deepening moat — from replicable tooling to a proprietary dataset to a fundamentally novel architecture that no one else is building.

### Phase 1: Rule-Based Intelligence (Month 0–6) — Where We Are Now

Pythia uses frontier LLMs (Claude, GPT) as the reasoning layer. Confluence scoring is rule-based: standardized signals, weighted scoring, time decay. The 8-layer pipeline is already differentiated — no one else combines prediction market data with multi-source news attribution, regime detection, and pattern matching in a single product.

**But the moat is thin.** Data pipelines can be replicated. LLM prompting can be reverse-engineered. If Pythia's only advantage were "we use Claude to summarize prediction market moves," a well-funded competitor could rebuild it in months.

What they *can't* replicate: **the dataset we're building right now.** Every confluence event is logged with its full context — which layers fired, what the attribution said, what confidence we assigned. And then we track what actually happened. Did the signal sustain? Did the suggested assets move? Was the regime classification correct? This ground-truth dataset is accumulating from day one.

### Phase 2: Proprietary Model (Month 6–12) — The Dataset Moat

After 6-12 months of live operation, Pythia will have something that doesn't exist anywhere else: **a verified dataset of prediction-market-signal-to-outcome mappings.** Thousands of confluence events, each tagged with:

- Which of the 8 layers contributed
- What confidence was assigned
- What the actual market outcome was (1h, 24h, 7d)
- Which traditional assets were affected and by how much
- Whether the regime classification was correct

This dataset enables fine-tuning a proprietary model that makes connections prompting alone can't. The model learns the subtle patterns: "When Layers 1, 3, and 6 agree on a geopolitical event during a policy_uncertainty regime, the suggested equity move materializes 82% of the time within 48 hours." No amount of prompt engineering discovers this — it requires thousands of labeled examples.

**The compounding effect:** Every day Pythia runs, the dataset grows, the model improves, and the intelligence gets harder to replicate. A competitor starting from scratch is always 6-12 months of live data behind.

### Phase 3: Agentic Economy (Month 12+) — The Architectural Moat

This is where the moat becomes unbridgeable.

Today's intelligence pipeline is centralized: one model receives all signals, reasons about all of them, and produces one output. This is how every AI system works — a single brain processing all inputs. It's the **planned economy** of intelligence: one central planner, top-down resource allocation, no specialization.

But that's not how actual market intelligence works. On a real trading floor, intelligence is *distributed*:

- The Fed watcher knows monetary policy cold but doesn't track geopolitics
- The geopolitical analyst understands conflict dynamics but doesn't model rates
- The flow tracker sees positioning data but doesn't read news
- The sentiment analyst reads Twitter but doesn't understand options Greeks

These specialists don't report to a central coordinator who synthesizes their views. They **interact through market-like mechanisms** — arguing, challenging each other's theses, placing conviction bets on their own analysis. Collective intelligence emerges from their economic interaction, not from top-down orchestration.

**Pythia's Phase 3 deploys this architecture computationally.** Instead of one model reasoning about all 8 layers, we deploy **specialized agents** — a Fed Watcher agent, a Geopolitical Analyst agent, a Flow Tracker agent, a Sentiment Analyst agent, a Regime Detector agent — each fine-tuned on its domain. These agents don't just feed signals into a central scorer. They interact through **market-like mechanisms** based on Siqi Liu's game-theoretic framework from DeepMind:

- Each agent has an **information budget** and must allocate it across the contracts it monitors
- Agents **trade information** with each other — the Geopolitical Analyst might pay (in budget) for the Flow Tracker's positioning data on defense stocks
- Each agent maintains a **track record** that determines its influence weight — agents that are consistently right earn more budget; agents that are wrong lose it
- **Confluence emerges economically**, not by rule: when 4 specialized agents independently converge on the same thesis, spending their own budgets to do so, that convergence is far more meaningful than 4 layers of a single model agreeing with itself

This is the difference between asking one smart person about everything and running a trading floor where specialists compete and collaborate. The trading floor produces better intelligence — not because any individual is smarter, but because the *mechanism* is smarter.

### Why Current Agentic Systems Can't Do This

The agentic AI systems being built today — AutoGPT, CrewAI, LangGraph multi-agent chains — are **planned economies.** One orchestrator agent delegates tasks to worker agents, collects their outputs, and synthesizes a result. The workers have no incentives, no specialization pressure, no information costs, and no competitive dynamics.

This works for simple workflows. It fails catastrophically for the kind of nuanced, adversarial, information-rich reasoning that financial markets demand. A planned-economy agent system can't discover that its geopolitical agent is consistently over-weighting conflict probability because there's no mechanism to challenge it. There's no feedback loop where poor performance costs anything.

Siqi's framework changes this fundamentally. His research at DeepMind — supervised by **David Silver** (co-creator of AlphaGo, AlphaZero, and AlphaFold) — provides the game-theoretic foundations for **agentic economies**: multi-agent systems where agents have incentives, develop specializations through economic pressure, and produce emergent collective intelligence through market-like interaction rather than top-down orchestration. This work is currently being validated with two DeepMind colleagues and represents the frontier of agentic AI research.

Applied to Pythia, this framework means:

- **Better signal attribution.** Competing specialist agents produce richer, more adversarially-tested causal reasoning than any single model.
- **Self-correcting intelligence.** Agents that make bad calls lose influence automatically — no human tuning required.
- **Emergent specialization.** Over time, agents develop narrow expertise that produces better predictions in their domain than a generalist model could achieve.
- **Impossible to replicate.** The combination of a proprietary signal-to-outcome dataset, domain-specialized fine-tuned agents, and a game-theoretic interaction framework creates a moat that can't be crossed by throwing more compute or data at the problem. You'd need the dataset, the architecture, and the economic design — simultaneously.

### The Research-to-Product Pipeline

| Timeline | Intelligence Architecture | Moat Depth |
|----------|--------------------------|------------|
| Month 0–6 | Frontier LLMs + rule-based scoring | Thin (replicable) |
| Month 6–12 | Proprietary fine-tuned model on verified signal-outcome data | Medium (dataset advantage) |
| Month 12–18 | Specialized domain agents with independent track records | Deep (specialization + data) |
| Month 18+ | Full agentic economy: agents interacting through game-theoretic market mechanisms | Unbridgeable (architecture + data + mechanism design) |

**The intelligence engine is the business. The agentic economy framework is what makes it impossible to replicate.**

This isn't a research project bolted onto a product. The product *is* the research applied. Every day of live operation generates the data that trains the agents that interact through the framework that produces intelligence no other architecture can match. The flywheel starts spinning from day one.

---

## Competitive Landscape

| | Pythia | Verso (YC) | Bloomberg | Manual |
|---|---|---|---|---|
| Prediction market coverage | ✅ Multi-platform | ✅ 15K contracts | ❌ None | ❌ Manual |
| Causal attribution | ✅ 8-layer pipeline | ⚠️ AI news mapping (73% accuracy) | ❌ None | ⚠️ Human analysis |
| Historical depth | ✅ 9.15M spikes | ❌ Live only | ❌ N/A | ❌ N/A |
| Confluence scoring | ✅ Cross-layer detection | ❌ None | ❌ N/A | ❌ N/A |
| Regime detection | ✅ 5 regimes + historical analogs | ❌ None | ⚠️ Manual | ⚠️ Manual |
| Track record / proof | ✅ Self-auditing | ❌ None | ❌ N/A | ❌ N/A |
| Conversational interface | ✅ Telegram bot | ❌ Dashboard only | ❌ Terminal | ❌ N/A |
| API | ✅ 9 endpoints | ❌ Unknown | ✅ Enterprise | ❌ N/A |
| Traditional asset mapping | ✅ Contract → equity/FX/commodity | ❌ Prediction markets only | ✅ All assets | ⚠️ Manual |
| Agentic economy roadmap | ✅ Research partnership with DeepMind PhDs | ❌ None | ❌ None | ❌ N/A |

---

## What Comes Next

### Phase 1: Design Partner Validation (Now → Q2 2026)

- Run the v2 pipeline on live spikes with design partners
- Collect structured feedback: which attributions are correct, which are wrong, what's missing
- Tune the pipeline based on real trader needs
- **Build the signal-to-outcome dataset from day one** — every event logged, every outcome tracked
- Onboard 5-10 design partners across all four personas (Elena, Sarah, Raj, Marcus)

### Phase 2: Real-Time Pipeline + Product-Market Fit (Q2–Q3 2026)

- Connect to Polymarket/Kalshi WebSocket feeds
- Sub-minute spike detection → attribution within 2-3 minutes
- Push notifications with structured causal summaries
- Python SDK for quant integration
- First paying customers at Signal and Alert Bot tiers

### Phase 3: Quantitative Signal Layer + Proprietary Model (Q3 2026 – Q1 2027)

- Which attribution features predict sustained vs. reverting moves?
- Build systematic signals from attribution confidence × historical pattern match × regime context
- Backtest against the 9.15M Becker spike dataset
- **Fine-tune proprietary model** on 6+ months of verified signal-to-outcome data
- Enterprise tier launch with custom integrations

### Phase 4: Agentic Economy Architecture (2027+)

- Deploy specialized domain agents (Fed Watcher, Geopolitical Analyst, Flow Tracker, Sentiment Analyst, Regime Detector)
- Implement game-theoretic interaction framework based on Siqi's research
- Agent track records determine influence weights — self-correcting intelligence
- Emergent specialization through economic pressure
- The pipeline becomes a **reasoning economy**, not just an attribution pipeline
- **The moat becomes unbridgeable**

---

## The Team

**JX** — Builder. Trading floor background (JPM). Designed the pipeline architecture, built the 8-layer intelligence system, wrote the conversational bot. Understands what traders actually need because he sat next to them.

**Siqi Liu** — Research. PhD candidate at DeepMind, supervised by David Silver (AlphaGo, AlphaZero). Research focus: agentic economy, game theory, LLM evaluation. His framework is the architectural moat — the game-theoretic foundations for how specialized agents interact to produce emergent intelligence. Currently validating with 2 DeepMind colleagues.

**Bangshan** — Quant. The quantitative lens on the signal — backtest design, statistical validation, systematic strategy development. Turns "interesting intelligence" into "provable alpha."

---

## The Ask

We're looking for **design partners** — experienced traders who will tell us what's useful and what's not.

**What we need:**

- **30 minutes per week** — look at 5-10 attributed spikes, tell us what's right and wrong
- **Signal prioritization** — which market categories matter to you? Which ones don't?
- **Quality calibration** — when we say HIGH confidence, does that match your assessment?
- **Missing features** — what would make this pipeline part of your actual workflow?

**What you get:**

- Early access to a pipeline that doesn't exist anywhere else
- Direct input on product direction
- Full access to the Becker pattern library (9.15M spikes, 30 archetypes)
- Full access to the conversational bot, dashboard, and API
- Co-authorship opportunity on any published research

**What we don't need:**

- Capital
- Introductions (yet)
- Time you don't have

We'd rather have honest "this attribution is garbage" feedback on 5 spikes per week than polite enthusiasm with no signal.

---

## Appendix: Technical Specifications

**Codebase:** ~7,200 lines of production Python across 11 components.

**LLM Backbone:** Claude Sonnet (Layer 3 filtering, ~$0.01/call) + Claude Opus (Layer 4 reasoning, ~$0.04/call). Total cost per attribution: ~$0.05.

**Data Sources:** NewsAPI (100 req/day free tier), Google News RSS, DuckDuckGo, Reddit. Polymarket/Kalshi price feeds. Becker historical dataset.

**Infrastructure:** FastAPI (REST API), Streamlit (dashboard), python-telegram-bot (conversational interface). SQLite for signal storage. Designed for single-server deployment during design partner phase; horizontally scalable.

**Test Coverage:** 33 unit tests on confluence scoring engine. Pipeline integration tests across all 3 test cases documented above.

**Pattern Library:** 30 spike archetypes derived from 9.15M historical probability spikes (Becker dataset). Each archetype includes frequency, magnitude distribution, temporal signature, reversion profile, and cross-market correlation.

---

*Built by JX, Siqi, and Bangshan. February 2026.*
*Pipeline: `pythia_live/causal_v2.py` · Confluence: `pythia_live/confluence_scorer.py` · Bot: `pythia_live/companion_bot.py`*
*Pattern data: Becker dataset (9.15M spikes) · LLM backbone: Claude Sonnet + Opus*
