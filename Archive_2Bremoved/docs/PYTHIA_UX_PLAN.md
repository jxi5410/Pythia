# Pythia UX Improvement Plan — End User Experience

**Date:** 2026-02-22
**Input:** Shadow trader panel v2, QuantFox UX analysis, confluence scorer architecture

---

## Current State

Pythia's UI is a Bloomberg-style dark Streamlit terminal with 5 rigid tabs:
- Signal Feed, Inquiry, Patterns, Correlations, News Impact
- No customization, no watchlists, no alerts, no API
- Looks like a hackathon demo, not a product

## Design Principles (from trader feedback)

1. **Push > Pull.** Traders don't stare at dashboards. They get alerts, investigate, act.
2. **6 excellent > 20 mediocre.** QuantFox has 20 widgets. We need 6 that work perfectly.
3. **Dark mode, dense, Bloomberg-adjacent.** Elena: "If it looks like fintech pastel, I won't trust it."
4. **Causal narrative = opt-in.** Elena loves it. Raj hates it. Default to data, offer narrative as a layer.
5. **API-first, UI-second.** Every feature should work via API before it has a widget.

---

## Phase 1: Core UX Overhaul (Week 1-2)

### 1.1 Watchlists — The Foundation

**What:** Users define their contract universe. Everything filters through this.

**UX flow:**
- Sidebar: "My Watchlists" with create/edit/delete
- Default watchlists: "Fed/Rates", "Geopolitical", "Crypto", "Tech Regulation"
- Each watchlist = a set of prediction market contracts + optional equity tickers
- All views filter by active watchlist (or "All")

**Why first:** Without watchlists, everything is noise. Elena's #1 request. Table stakes for any institutional tool.

### 1.2 Alert System — Push-Based Workflow

**What:** Configurable notifications when watchlist contracts move.

**Triggers:**
- Absolute move: contract moves >X points in Y minutes
- Velocity: rate of change exceeds threshold
- Confluence: 3+ data layers converge (from new confluence scorer)
- Divergence: Kalshi vs Polymarket vs FedWatch disagree by >X points
- Pattern match: historical pattern detected (from Becker data)

**Delivery:**
- Telegram bot (primary — Marcus's #1 request, already have bot infrastructure)
- Slack webhook
- Email digest (hourly/daily summary)

**Alert format:**
```
🔴 HIGH CONFLUENCE [3/8 layers] — Fed Rate Cut

Polymarket "Fed cuts March": 61% → 72% (+11pts, 45min)
FedWatch divergence: CME says 68% (gap: +4pts)
Congressional: 3 Senate Banking members sold bank stocks (7d)
Twitter velocity: "Fed cut" mentions 4.2x baseline

Historical: When 3+ layers converge on fed_rate, assets moved
in expected direction 73% of the time within 24h (n=47)

Suggested: Short 2Y Treasury, Long rate-sensitive equities
```

**Why second:** Sarah literally said "I will NOT add a 7th screen." Alerts are how she and Marcus engage. This is the delivery mechanism for the confluence scorer.

### 1.3 Homepage Redesign — "What's Moving Now"

Replace the current Signal Feed tab with a single hero view:

**Layout (top to bottom):**

```
┌─────────────────────────────────────────────────────┐
│  ACTIVE CONFLUENCE EVENTS (high priority)            │
│  ┌──────────────────┐ ┌──────────────────┐          │
│  │ 🔴 Fed Rate Cut  │ │ 🟡 China Tariffs │          │
│  │ 3 layers | 0.72  │ │ 2 layers | 0.35  │          │
│  │ +11pts 45min     │ │ +5pts 2hr        │          │
│  └──────────────────┘ └──────────────────┘          │
├─────────────────────────────────────────────────────┤
│  WATCHLIST FEED (filtered, most recent first)        │
│  09:14  Polymarket "Fed March cut"  61%→72%  ▲11    │
│  09:02  Kalshi "Gov shutdown"       23%→28%  ▲5     │
│  08:45  Polymarket "CHIPS ext"      44%→41%  ▼3     │
├─────────────────────────────────────────────────────┤
│  CROSS-PLATFORM DIVERGENCE                           │
│  Fed Rate Cut:  Poly 72% | Kalshi 68% | CME 65%     │
│  Tariffs:       Poly 45% | Kalshi 48% | gap: 3pts   │
├─────────────────────────────────────────────────────┤
│  RECENT CAUSAL ATTRIBUTIONS (opt-in panel)           │
│  "Fed cut spike driven by Waller speech at 08:52,   │
│   corroborated by 3.8x Twitter velocity..." [more]  │
└─────────────────────────────────────────────────────┘
```

**Key design decisions:**
- Confluence events at the top (the product's unique value)
- Everything filtered by watchlist
- Causal attribution is collapsed by default (click to expand)
- Dark mode, monospace numbers, Bloomberg-adjacent density
- No charts on homepage — charts are on click-through detail pages

---

## Phase 2: Depth & Proof (Week 3-4)

### 2.1 Contract Detail View

Click any contract to get a deep dive:

```
┌─────────────────────────────────────────────────────┐
│  POLYMARKET: "Will Fed cut rates in March 2026?"     │
│                                                      │
│  [Price Chart — 24h/7d/30d/All toggle]              │
│                                                      │
│  Current: 72%  |  24h Δ: +11pts  |  Volume: $2.3M  │
│  Kalshi: 68%   |  CME FedWatch: 65%                 │
├─────────────────────────────────────────────────────┤
│  CONFLUENCE STATUS                                   │
│  ████████░░ 3/8 layers active                       │
│  ✅ Prediction Market (spike detected)               │
│  ✅ Congressional (3 trades, banking sector)          │
│  ✅ Twitter (4.2x velocity)                          │
│  ⬜ Equities (no correlated move yet)                │
│  ⬜ Fixed Income (FedWatch divergence: 7pts)          │
│  ⬜ Crypto (no signal)                               │
│  ⬜ China (no signal)                                │
│  ⬜ Macro Calendar (FOMC in 18 days)                 │
├─────────────────────────────────────────────────────┤
│  CAUSAL ATTRIBUTION                                  │
│  Confidence: 0.82 | Source: Fed Governor Waller      │
│  "Waller signaled openness to rate adjustment in     │
│  March testimony, contradicting prior hawkish..."    │
│  [Full analysis →]                                   │
├─────────────────────────────────────────────────────┤
│  HISTORICAL PATTERNS                                 │
│  Similar spikes (>10pts on fed_rate): 47 instances   │
│  → Asset moved as expected within 24h: 73%           │
│  → Avg magnitude: 8bps on 2Y Treasury               │
│  → Best predictor: 4+ layers = 89% hit rate          │
│  [View all patterns →]                               │
├─────────────────────────────────────────────────────┤
│  SUGGESTED ASSETS                                    │
│  TLT (20Y Treasury ETF) | IEF (7-10Y) | XLF (Fins) │
│  SOFR futures | Rate-sensitive equities basket       │
└─────────────────────────────────────────────────────┘
```

### 2.2 Regime Dashboard

A single view for macro traders (Sarah's request):

```
┌─────────────────────────────────────────────────────┐
│  REGIME HEATMAP                                      │
│                                                      │
│  Current: POLICY UNCERTAINTY (3 clusters active)     │
│                                                      │
│  [Heatmap grid: categories × time]                  │
│  fed_rate:     ████████░░  HIGH activity             │
│  tariffs:      ██████░░░░  MEDIUM                    │
│  geopolitical: ██░░░░░░░░  LOW                       │
│  recession:    ░░░░░░░░░░  QUIET                     │
│  crypto_reg:   ███░░░░░░░  LOW-MEDIUM                │
│                                                      │
│  CLUSTER DETECTION                                   │
│  🔴 Active cluster: fed_rate + tariffs + recession   │
│     Last seen: 2025-09-14 → SPX -2.3% in 48h        │
│     Last seen: 2025-06-02 → 2Y yield -12bps in 24h  │
│     Historical hit rate: 67% (n=12)                  │
└─────────────────────────────────────────────────────┘
```

### 2.3 Historical Proof Page

Dedicated section showing Pythia's track record:

- Every confluence event with outcome (did assets move as predicted?)
- Running statistics: hit rate by category, by layer count, by time horizon
- Lead-lag analysis: average time between prediction market spike and equity/rates move
- False positive rate by confidence threshold
- Exportable for due diligence (PDF)

---

## Phase 3: Platform (Month 2-3)

### 3.1 REST API + Python SDK

Every view above should also be available via API:

```python
import pythia

# Get active confluence events
events = pythia.confluence(min_score=0.6)

# Get watchlist signals
signals = pythia.signals(watchlist="my_macro", since="2h")

# Get contract time series
ts = pythia.timeseries("polymarket:fed-rate-cut-mar26", freq="1min")

# Get regime state
regime = pythia.regime()

# Get historical patterns
patterns = pythia.patterns(category="fed_rate", min_layers=3)
```

### 3.2 Telegram Bot Commands

Extend existing bot with:
- `/watchlist` — manage watchlists
- `/confluence` — show active confluence events
- `/alert set <contract> <threshold>` — set alert
- `/regime` — current regime heatmap (as text)
- `/proof` — latest track record stats
- `/detail <contract>` — contract deep dive

### 3.3 Custom Workspaces

Let users save layouts:
- "Fed/Rates Workspace" = Fed contracts + Treasury yields + FedWatch divergence
- "Merger Arb Workspace" = DOJ contracts + target stock prices + congressional trades
- "China Macro Workspace" = Tariff contracts + Weibo + PBOC + CNY

---

## Phase 4: Polish & Trust (Month 3-4)

### 4.1 Credibility Signals

- "Powered by 9.15M historical data points"
- Live accuracy counter: "Last 30 days: 47 confluence alerts, 34 correct (72%)"
- Methodology page: how scoring works, what data sources, update frequency
- Status page: system uptime, data freshness per source

### 4.2 Onboarding Flow

NOT a wizard. A single "Quick Start" that:
1. Asks: "What do you trade?" (Equities / Rates / Macro / Crypto)
2. Pre-populates a relevant watchlist
3. Sets up 3 default alerts
4. Shows one real example of a confluence event with outcome
5. Done in <60 seconds

### 4.3 Mobile Responsive

Not an app. Just make the dashboard usable on phone:
- Alert management
- Confluence event detail
- Quick glance at watchlist

---

## What NOT to Build

- ❌ Light mode as default (offer it, don't default it)
- ❌ 20+ widgets (6 excellent beats 20 mediocre)
- ❌ Guided onboarding wizard (institutional traders hate hand-holding)
- ❌ Gamification / achievements
- ❌ Trading execution
- ❌ Full Bloomberg replacement
- ❌ Causal narrative as mandatory (always opt-in)
- ❌ Complex chart types (keep it clean: line charts, heatmaps, that's it)

---

## Technical Migration Path

**Phase 1-2 (Streamlit):** Doable in Streamlit with st.columns, st.expander, custom CSS for dark mode. Watchlists via session state + JSON storage. Alerts via background thread + Telegram bot.

**Phase 3+ (React/Next.js):** Streamlit hits limits on custom layouts, real-time updates, and API serving. Migrate to:
- Next.js frontend (dark mode, responsive, real-time via WebSocket)
- FastAPI backend (serves both UI and API)
- PostgreSQL/TimescaleDB (time series + confluence events)
- Redis (real-time signal cache)

**Migration strategy:** Build the API first (FastAPI). Streamlit becomes one client of the API. Then build React frontend as second client. Streamlit dies naturally.

---

## Priority Summary

| Week | Deliverable | Impact |
|------|------------|--------|
| 1 | Watchlists + alert system | Makes product usable |
| 2 | Homepage redesign ("What's Moving Now") | First impression = product, not demo |
| 3 | Contract detail view + confluence display | Shows unique value |
| 4 | Regime dashboard + historical proof page | Unlocks Sarah segment |
| 5-8 | API + Python SDK + Telegram commands | Unlocks Raj segment |
| 8-12 | Custom workspaces + mobile + credibility | Retention + trust |

*Total estimated effort: 2-3 months to go from demo to product.*
