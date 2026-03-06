# Pythia Live -- Multi-Agent Analysis Report

**Generated:** 2026-03-06
**Codebase:** 54 Python modules | 18,841 lines | Next.js 15 frontend
**Version:** Latest commit `88c563c` (PMXT integration plan)

---

## 1. Finance Tracker

### Capital & Risk Configuration
| Parameter | Value |
|---|---|
| Initial Capital | $10,000 |
| Max Daily Trades | 10 |
| Daily Loss Limit | 10% |
| Max Drawdown | 20% |
| Min Liquidity | $10,000 |

### Paper Trading System
- **Engine:** `paper_trading.py` -- simulated execution with Kelly Criterion position sizing (Half Kelly, max 25% allocation)
- **Status Lifecycle:** PENDING --> EXECUTED --> CLOSED
- **Storage:** SQLite `paper_trades` table with hourly portfolio snapshots
- **P&L Tracking:** Per-trade and aggregate with automated end-of-day Telegram reports

### Track Record Engine (682 lines)
- Computes verifiable historical performance: hit rates, false positive rates, lead times
- Per-category breakdown across 11 event categories (fed_rate, tariffs, china_macro, defense, tech_regulation, crypto_regulation, government_shutdown, recession, geopolitical, earnings_macro, energy)
- Layer contribution analysis across 8 data layers
- Threshold-gated FPR analysis at 30%, 50%, 70%, 90% confidence levels
- Hit definition: suggested asset moves >= 0.5% in predicted direction within 24h

### Automation Controller
- Auto-creates paper trades from HIGH/CRITICAL severity signals
- Risk controls: 10% daily loss limit, 20% max drawdown circuit breaker
- Hourly portfolio snapshots for audit trail

### Assessment
**Strengths:** Institutional-grade risk management with Kelly sizing, governance-compliant audit trails, multi-threshold performance validation.
**Gaps:** No live trading integration yet (paper-only). No Sharpe ratio or risk-adjusted return metrics in track record. Position sizing doesn't account for correlation between concurrent positions.

---

## 2. Growth Hacker

### Distribution Strategy
- **Frontend:** Zero-friction mobile PWA (Next.js 15, React 19, Tailwind 4) -- no app install, no account creation, shareable via link
- **Target:** Institutional traders and design partners
- **Demo deployment:** Vercel serverless (`vercel --prod`)

### Growth Channels Currently Active
1. **Telegram Bot** (`telegram_commands.py`, 421 lines) -- interactive query interface with `/fed_rate`, `/similar`, `/what_caused`, `/patterns`, `/correlations` commands
2. **Companion Agent** (`companion.py`, 598 lines) -- multi-user interface with signal subscriptions, custom watchlists, portfolio tracking, context retention
3. **REST API** (`api.py`, 549 lines) -- 8 public endpoints for programmatic access

### Market Coverage (Growth Surface)
| Source | Type | Status |
|---|---|---|
| Polymarket | CLOB API + WebSocket | Live |
| Kalshi | CFTC-regulated exchange | Live |
| Manifold Markets | Community prediction | Live |

### User Engagement Hooks
- Real-time signal alerts via Telegram push notifications
- Custom watchlist management per user
- Signal severity tiers (CRITICAL auto-alerts, HIGH requires confirmation)
- 5-minute cooldown between signals to prevent alert fatigue

### Assessment
**Strengths:** PWA approach eliminates app store friction. Telegram bot is a high-engagement channel for financial signals. Multi-market coverage creates network effects.
**Gaps:** No user analytics or funnel tracking. No referral mechanism. No onboarding flow in the PWA. Email/SMS notification channels not implemented. No A/B testing infrastructure.

---

## 3. Performance Benchmarker

### System Architecture Performance
| Component | Metric | Value |
|---|---|---|
| Poll Interval | Market data refresh | 30 seconds |
| Signal Cooldown | Duplicate suppression | 5 minutes (300s) |
| Probability Spike Threshold | Price move trigger | >= 5% in 1 hour |
| Volume Spike Threshold | Activity trigger | >= 3x normal |
| WebSocket Streaming | Polymarket real-time | Integrated (Phase 2 complete) |

### Signal Detection Strategies (5 active)
1. **PROBABILITY_SPIKE** -- large price moves (>= 5%)
2. **VOLUME_ANOMALY** -- unusual activity (>= 3x baseline)
3. **MAKER_EDGE** -- liquidity provision opportunity (>= 1% spread)
4. **MOMENTUM_BREAKOUT** -- MA crossover trend continuation
5. **OPTIMISM_TAX** -- taker YES skew on longshots

### Confluence Scoring Performance
- **Layers monitored:** 8 (equities, congressional, twitter, fixed_income, crypto_onchain, macro_calendar, china_signals, causal)
- **Time window:** 4 hours for cross-layer convergence
- **Minimum layers:** 3 required (single-layer = noise)
- **Scoring:** 0.0 - 1.0 composite score

### Causal Attribution Pipeline (1,183 lines)
- **5-layer LLM pipeline:** Context Builder --> News Retriever --> Candidate Filter --> Causal Reasoner --> Storage Learner
- **Models:** Claude Sonnet (fast filtering) + Claude Opus (deep reasoning)
- **Governance:** $2 max per run, $10/hour, $50 emergency shutdown

### Backtesting Framework (481 lines)
- Tests prediction market --> equity correlations
- Historical spike analysis with yfinance equity data
- Walk-forward validation on historical data
- Local caching in `data/equity_cache/`

### Assessment
**Strengths:** 30-second polling with WebSocket streaming gives near real-time coverage. 5-strategy detection is comprehensive. 8-layer confluence scoring is a strong differentiator.
**Gaps:** No latency benchmarks or p99 measurements. No throughput testing under load. Backtest framework lacks Monte Carlo simulation. No comparison against naive baselines.

---

## 4. Pythia Evaluator

### Intelligence Quality Evaluation

#### Detection Coverage
- **11 event categories** with keyword-based auto-classification
- **8 data layers** providing independent signals
- **6 signal severity levels** mapped to action thresholds

#### Governance Compliance (Singapore IMDA + UC Berkeley)
| Agent | Role | Autonomy Level |
|---|---|---|
| Context Builder | Keyword extraction & classification | L3 (Limited) |
| News Retriever | Web API calls for news | L4 (High) |
| Candidate Filter | LLM relevance scoring | L4 (High) |
| Causal Reasoner | Deep causal analysis | L4 (High) |
| Storage Learner | DB writes & pattern updates | L3 (Limited) |
| Orchestrator | Pipeline coordination | L4 (High) |

#### Decision Gates
| Confidence | Action | Description |
|---|---|---|
| >= 85% | AUTO_RELAY | Signal auto-delivered to users |
| 70% - 85% | FLAG_REVIEW | Requires human review |
| < 70% | REJECT | Signal suppressed |

#### Multi-Agent Agreement
- Filter + Reasoner confidence must be within 20% of each other
- If disagreement detected, signal downgraded to FLAG_REVIEW regardless of confidence

#### Audit Trail
- Every agent action logged: timestamp, role, action type, I/O summary, confidence, cost, tokens, duration
- 90-day retention policy
- Batch export for enterprise compliance review

### Regime Detection (480 lines)
- 7 regime types: policy_uncertainty, geopolitical_shock, risk_off, crypto_event, china_macro_shock, tech_regulatory, calm
- Historical outcome mapping (e.g., policy_uncertainty --> SPX -1.2%, TLT +1.5%, VIX +8%)
- Regime persistence and transition detection

### Assessment
**Strengths:** Production-grade governance with circuit breakers, audit trails, and multi-agent validation. Regime detection adds strategic context beyond individual signals. Compliance framework is investor-ready.
**Gaps:** No model drift detection. No A/B testing between causal attribution models. Pattern library learning rate not measured. No ground truth labeling workflow for improving hit rate accuracy.

---

## 5. Reality Checker

### What's Real (Verified & Functional)
- 54 Python modules (18,841 lines) -- substantial, production-oriented codebase
- Full SQLite schema with migrations for markets, prices, signals, alerts, trades, spikes, confluence events, paper trades, portfolios
- 3 prediction market connectors (Polymarket, Kalshi, Manifold) with WebSocket streaming
- 5-strategy signal detection engine with pattern library integration
- 8-layer confluence scoring (the core product differentiator)
- 5-agent causal attribution pipeline with LLM integration
- Governance compliance layer (Singapore IMDA + UC Berkeley standards)
- Paper trading with Kelly Criterion sizing
- Telegram bot with 6+ interactive commands
- REST API with 8 endpoints
- Next.js 15 frontend (PWA, mobile-optimized)

### What's In Progress
- **PMXT Integration** (commit `88c563c`): Replacing mock frontend data with live backend feeds
- **UI Modernization**: Kalshi-style light theme, sparkline charts, signal analysis cards

### What's Missing / Needs Attention
| Area | Issue | Priority |
|---|---|---|
| Live Trading | Paper-only, no real execution | P1 |
| Frontend-Backend | Mock APIs, not connected to live data | P1 (PMXT plan exists) |
| User Auth | No authentication or user accounts | P2 |
| Tests | Test directory exists but coverage unknown | P2 |
| Monitoring | No production health monitoring/alerting | P2 |
| API Rate Limits | No rate limiting on REST endpoints | P3 |
| Error Recovery | No retry/backoff on connector failures | P3 |
| Documentation | Architecture docs archived, not maintained | P3 |

### Deployment Reality
- Backend: Local Python (uvicorn) -- no containerization or cloud deployment config
- Frontend: Vercel (configured and working)
- Database: Local SQLite -- not suitable for multi-instance deployment

### Assessment
**Bottom Line:** Pythia is a sophisticated, well-architected intelligence engine with institutional-grade governance. The core signal detection and confluence scoring is the real product. The main gap is the frontend-backend integration (being addressed via PMXT plan) and the lack of production deployment infrastructure.

---

## 6. Trend Researcher

### Prediction Market Landscape (March 2026)

#### Markets Monitored
- **Polymarket** -- largest by liquidity, CLOB orderbook, WebSocket streaming
- **Kalshi** -- CFTC-regulated, institutional credibility
- **Manifold Markets** -- community-driven, open-source

#### Event Categories Tracked (11)
1. Fed Rate decisions (FOMC, rate cuts/hikes, Powell)
2. Tariffs & Trade War (import duties, WTO, trade deals)
3. China Macro (PBOC, yuan, GDP, Xi Jinping)
4. Defense (NATO, military spending, weapons)
5. Tech Regulation (antitrust, AI regulation, FTC)
6. Crypto Regulation (SEC, Bitcoin ETF, stablecoin, CBDC)
7. Government Shutdown (debt ceiling, appropriations)
8. Recession (GDP, unemployment, jobs report, layoffs)
9. Geopolitical (war, sanctions, nuclear, Taiwan)
10. Earnings Macro (quarterly results, guidance, EPS)
11. Energy (OPEC, oil, natural gas, crude)

#### Data Layer Intelligence (8 sources)
| Layer | Source | Signal Type |
|---|---|---|
| Equities | yfinance | Ticker correlation to prediction markets |
| Congressional | US Congress data | Bill voting, committee activity, defense spending |
| Twitter/X | Sentiment API | Social momentum and narrative tracking |
| Fixed Income | Bond markets (1,079 lines) | Yield curve, Fed signals, spread analysis |
| Crypto On-chain | Blockchain data (742 lines) | Whale movements, exchange flows |
| Macro Calendar | Economic releases (753 lines) | GDP, CPI, jobs, PMI |
| China Signals | 5 dedicated modules | PBOC, equities, Weibo sentiment |
| Causal News | LLM attribution (1,183 lines) | Root cause analysis via Claude |

#### Orderbook Intelligence (434 lines)
- Whale order detection (large limit orders)
- Liquidity spike monitoring
- Spread compression/expansion tracking
- Bid/ask imbalance pressure
- Iceberg order detection

#### Emerging Trend: Multi-Layer Convergence
The core thesis -- "single-layer signals are noise, multi-layer convergence is the product" -- positions Pythia at the intersection of prediction markets, traditional finance data, and LLM-powered causal reasoning. This is a differentiated approach vs. single-source signal providers.

### Assessment
**Strengths:** Broad coverage across 11 event categories and 8 data layers. China intelligence (5 modules) is a unique differentiator. Fixed income depth (1,079 lines) suggests institutional-grade analysis.
**Gaps:** No options/derivatives data layer. No alternative data (satellite, shipping, credit card). No sentiment scoring normalization across layers. Twitter/X API reliability is a risk factor.

---

## Summary Scorecard

| Agent | Score | Key Finding |
|---|---|---|
| Finance Tracker | 7/10 | Solid risk management, needs live trading & risk-adjusted metrics |
| Growth Hacker | 5/10 | Good distribution channels, missing analytics & referral loops |
| Performance Benchmarker | 7/10 | Near real-time with 8-layer scoring, needs latency benchmarks |
| Pythia Evaluator | 8/10 | Best-in-class governance, needs model drift detection |
| Reality Checker | 7/10 | Production-quality code, frontend-backend integration is the gap |
| Trend Researcher | 8/10 | Broad coverage with unique China & fixed income depth |

**Overall Platform Maturity: 7/10** -- Strong institutional-grade intelligence engine with governance compliance. Primary blockers are frontend-backend integration and production deployment infrastructure.

---

*Report generated by Pythia Multi-Agent Analysis System*
*Codebase: /home/user/Pythia | Branch: claude/modernize-finance-ui-MuH7R*
