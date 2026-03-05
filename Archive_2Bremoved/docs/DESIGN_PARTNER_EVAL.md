# Pythia — Design Partner Evaluation Panel

*Simulated feedback from 5 institutional market participants. Written to be brutally honest.*

---

## 1. Sarah Chen — Macro Hedge Fund PM (Citadel-style)

### A. First Reaction

"Interesting concept, but I've seen a dozen 'alternative data meets macro' pitches this year. The causal attribution layer is the only thing here that's genuinely new — everything else I can approximate with Bloomberg alerts and my analysts. The question is whether your causal engine is actually better than my team's judgment."

### B. What Excites Her

- **Cross-asset signal mapping.** If a prediction market spike on "Fed rate cut" reliably leads equities by even 5–10 minutes, that's actionable. The fact that Pythia cross-references with equities (tariff market → NVDA) is exactly the workflow she wants — she doesn't want to stare at Polymarket, she wants someone to tell her *when prediction markets are saying something her Bloomberg isn't*.
- **The 9.15M historical spike dataset.** If she can backtest "when prediction market X spikes by Y%, what happens to asset Z over the next N hours," that's a real research tool for her analysts.
- **Confidence scoring with expected duration.** She sizes positions differently for a 2-hour catalyst vs a 2-week regime shift. Duration estimates matter.

### C. What Concerns Her

- **Prediction markets are thin.** Polymarket and Kalshi combined have a fraction of the liquidity of rates futures. A $50K trade on Polymarket can cause a 15% spike. How does Pythia distinguish between a real information event and someone fat-fingering a bet? If the answer is "we use news retrieval," then you're telling me what Bloomberg already told me 3 minutes ago.
- **Latency.** By the time your LLM pipeline runs 5 layers of causal analysis, the move in the real asset (SPY, TLT, etc.) is probably already done. She doesn't need an explanation 10 minutes later — she needs the signal *now* and the explanation can come after.
- **"73% accuracy" for Verso means nothing.** What's Pythia's accuracy? If you can't give me a number with a confidence interval, I assume you don't know.
- **Regulatory risk.** Using prediction market data to trade equities sits in a grey area. Her compliance team will have questions.

### D. How She'd Actually Use It

She wouldn't have Pythia open on her desk. She'd set it up as an alert system: push notifications when a prediction market she cares about (Fed, tariffs, election outcomes) spikes above a threshold. Her analyst would then pull up the Pythia causal chain, cross-check it against their own view, and flag it to Sarah if it's non-obvious. Maybe 2–3 times per week something actionable comes through. The historical dataset would go to her quant analyst for a weekend research project.

### E. What Would Make Her Pay

Show her three historical examples where Pythia's causal attribution identified something *before* it hit Bloomberg or sell-side research. Not "at the same time" — *before*. If prediction markets are genuinely a leading indicator and Pythia can prove it with timestamps and P&L attribution, she's in. Otherwise it's a nice-to-have she'll forget about.

### F. Price Sensitivity

- **Would pay:** $3K–$8K/month if it demonstrably saves one analyst 10+ hours/week or generates even one additional trade idea per month with positive expectancy.
- **Comparison:** Bloomberg terminal ($2K/month), alternative data vendors ($5K–$50K/month), expert networks ($10K+/month). Pythia needs to be cheaper than an analyst but more reliable than Twitter.
- **Dealbreaker price:** Anything above $15K/month without a proven track record. She can hire a junior analyst for that.

### G. Killer Question

*"Show me the last 20 HIGH-confidence causal attributions you generated. For each one, what was the lag between the prediction market spike and the corresponding move in the underlying equity or rates market? And how many of those 20 were actionable — meaning the move hadn't already happened by the time the alert fired?"*

---

## 2. Marcus Webb — Crypto-native Fund Manager (Paradigm-style)

### A. First Reaction

"I already watch Polymarket all day. I literally have a custom dashboard that alerts me on volume spikes. What you're selling me is the *why* behind the spike, and honestly, I usually know the why before your model does because I'm on CT [Crypto Twitter] in real time. But the cross-referencing with equities is interesting — I don't have that wired up well."

### B. What Excites Him

- **Historical pattern database.** 30 discoverable patterns across 9.15M spikes? He wants to data-mine that for edges in prediction market trading itself — not to trade equities, but to trade *the prediction markets*. Are there mean-reversion patterns after false spikes? Momentum patterns after real ones?
- **Cross-asset signals.** He trades crypto, but macro events move crypto. If tariff prediction markets spike and that historically correlates with BTC selling, he wants that signal.
- **Competitive intelligence.** If Pythia can tell him *who's* moving the market (whale wallet analysis on Polymarket + causal context), that's gold.

### C. What Concerns Him

- **Edge decay.** If Pythia becomes popular, the signal decays. Prediction markets are small enough that 50 funds running the same Pythia alerts would arbitrage away any edge in days. He needs to know: how many subscribers will you have?
- **He's already the expert.** For pure prediction market trading, he probably knows more than Pythia's model. The causal attribution might actually be *worse* than his intuition for crypto-adjacent markets.
- **No on-chain integration.** Pythia doesn't mention wallet tracking, order flow analysis, or Polymarket-specific microstructure data. That's what he actually needs.
- **Speed.** He can read a tweet and react in 30 seconds. If Pythia's alert comes 2 minutes later with a nice causal explanation, it's a post-mortem, not a signal.

### D. How He'd Actually Use It

Honestly, limited. He'd use the historical dataset for research — looking for patterns in how prediction markets react to different event types. He might use the equity cross-reference as a secondary screen: "Polymarket is spiking on China tariffs → check if BABA is moving → if not, maybe there's a trade there." But Pythia wouldn't be central to his workflow. It'd be a tab he checks a few times a day.

### E. What Would Make Him Pay

API access to the full historical spike dataset with granular timestamps, plus real-time websocket feed of spikes. He wants to build his own models on top of Pythia's data, not use your UI. If the data is unique and clean, he'd pay for the data alone and ignore the causal attribution.

### F. Price Sensitivity

- **Would pay:** $1K–$3K/month for the data feed/API. He'd compare it against running his own Polymarket data pipeline (which costs him ~$500/month in infra + engineering time).
- **Would NOT pay for:** A dashboard or alert system. He has those.
- **Comparison:** Arkham Intelligence ($500–$2K/month), Nansen ($1K–$5K/month), Kaito ($2K/month). Data infra products.

### G. Killer Question

*"How many other funds will have access to the same real-time alerts? And what's your data on edge half-life — how long does a Pythia signal remain profitable after it fires, given that every subscriber sees it simultaneously?"*

---

## 3. Raj Patel — Systematic Quant (Two Sigma-style)

### A. First Reaction

"The pitch is interesting but academically sloppy. You're telling me you have 9.15M spikes and 30 patterns, but you haven't told me the Sharpe of a strategy that trades on those patterns, the statistical significance of the patterns, or whether they survive transaction costs. 'Causal attribution via LLM' is a red flag — LLMs hallucinate, and I can't put a confidence interval on a hallucination."

### B. What Excites Him

- **The dataset.** 9.15M historical spikes is genuinely interesting as an alternative data source. If the data is clean, timestamped to the millisecond, and available via API, his team could do something with it.
- **Prediction markets as a leading indicator for traditional assets.** This is a testable hypothesis. He'd want to run Granger causality tests between Polymarket movements and equity/rates movements. If the lead-lag relationship is statistically significant, that's a new signal for his factor models.

### C. What Concerns Him

- **LLM-based causal attribution is not backtestable.** You can't backtest a system whose core logic is a non-deterministic language model. The causal chain it generates today for a given spike might differ from what it would have generated yesterday. This is fundamentally incompatible with systematic trading.
- **Data quality.** Prediction markets have thin order books, wide spreads, and manipulation. How are spikes defined? What's the minimum volume threshold? Are wash trades filtered?
- **No statistical rigor in the pitch.** "30 discoverable patterns" means nothing without p-values, out-of-sample tests, and multiple comparison corrections. He's seen too many data-mined artifacts sold as "patterns."
- **Latency.** What's the end-to-end latency from market event to API delivery? If it's >1 second, it's research data, not a trading signal.

### D. How He'd Actually Use It

He would **not** use the causal attribution layer at all. He'd buy the raw data feed: every spike, every prediction market movement, every contract price change. His team would build their own models on top. Pythia's "intelligence" layer is noise to him — he trusts his own models, not an LLM's opinion.

If the data proves to have alpha (lead-lag vs. equities), he'd integrate it as one more signal in a multi-factor model, probably weighted at 2–5% of total signal.

### E. What Would Make Him Pay

A backtest showing that a simple strategy — "buy SPY when Fed-cut probability spikes >10% in an hour, sell after 24h" — has a Sharpe above 1.0 out of sample over 3+ years. He doesn't need fancy causal attribution. He needs statistical proof that prediction market data predicts traditional market moves.

### F. Price Sensitivity

- **Would pay:** $5K–$20K/month for a clean, low-latency data feed with full historical backfill. This is in line with what he pays other alternative data vendors.
- **Would NOT pay for:** The causal attribution layer, the UI, or the confidence scores. Those are subjective overlays on top of data he'd rather interpret himself.
- **Comparison:** Alternative data vendors (satellite imagery, credit card data, etc.) charge $10K–$100K/month. Pythia needs to prove comparable alpha contribution.

### G. Killer Question

*"Can you give me the full historical dataset via API with millisecond timestamps, and have you run any out-of-sample statistical tests on the predictive power of prediction market spikes for traditional asset returns? Specifically, what's the information coefficient and the decay profile?"*

---

## 4. Elena Volkov — Event-Driven L/S Equity PM (Point72-style)

### A. First Reaction

"Okay, *this* is actually relevant to what I do. My whole job is figuring out which catalysts matter and when they'll hit. If prediction markets are pricing in a regulatory decision before the sell-side catches up, I want to know. The cross-asset signal is exactly my workflow — I just didn't have prediction markets wired into it."

### B. What Excites Her

- **Cross-asset catalyst detection.** This is her bread and butter. "Tariff probability spikes → here are the equities that historically move" is literally her job described as a product. If Pythia can show her that a political event is being priced in prediction markets *before* it's priced in equities, she has a window to act.
- **Causal attribution.** Unlike Raj, she *wants* the narrative. She needs to explain to her risk committee *why* she's putting on a position. "Pythia detected a 20% spike in the tariff probability driven by a leaked draft executive order, with HIGH confidence, historically correlated with a 3-5% decline in semiconductor names over 48 hours" — that's a trade thesis she can act on.
- **Expected duration.** Knowing whether a catalyst is a 1-day event or a multi-week regime shift changes her position sizing and structure (options vs. equity).

### C. What Concerns Her

- **Coverage.** Prediction markets only cover a narrow set of events — mostly US politics, some macro, some crypto. She trades around M&A, earnings, FDA approvals, antitrust rulings. Does Pythia cover those? If it's only "will Trump win" and "will the Fed cut," it's too narrow.
- **False positives.** If Pythia fires 10 alerts a day and 8 of them are noise, her team will start ignoring it within a week. What's the precision/recall tradeoff?
- **Equity mapping quality.** Saying "tariff spike → NVDA down" is obvious. She wants to know if Pythia can identify *non-obvious* second and third-order equity impacts. Can it tell her that a prediction market spike on EU AI regulation should affect FICO and Palantir, not just the mega-caps?
- **Already priced in.** By the time a prediction market moves 15%, the smart money in equities might have already moved. She needs evidence of the lead-lag.

### D. How She'd Actually Use It

Elena would set up Pythia alerts for her watchlist of political/regulatory catalysts. When an alert fires, she'd read the causal chain, check the equity cross-references, and use it as a *starting point* for a trade idea — not the trade itself. She'd then do her own work: call her expert network contacts, check the options market for unusual activity, and size the position based on her own conviction. Pythia would be one input among many, but a potentially valuable one.

She'd also use the historical data to build "event playbooks" — when this type of prediction market spike happened before, what worked?

### E. What Would Make Her Pay

A live demo during a real event. Show her an alert firing in real time — prediction market spikes on, say, a surprise regulatory announcement — with the causal chain, equity implications, and historical analogues. If the equity moves she identifies play out over the next 24–48 hours, she's sold. One real-time win is worth more than a hundred backtests to someone in her seat.

### F. Price Sensitivity

- **Would pay:** $5K–$10K/month — roughly the cost of one expert network call per month, which is the closest comparison. If Pythia replaces even 2–3 expert network calls per month, it pays for itself.
- **Comparison:** Expert networks ($5K–$15K/month), sell-side research (bundled with commissions), news terminals (Bloomberg $2K, Factiva $1K). She'd bucket Pythia as "research tool."
- **Sweet spot:** $7.5K/month with a 3-month trial period to prove value.

### G. Killer Question

*"Walk me through a specific historical example where Pythia detected a prediction market spike, attributed it to a cause, and the corresponding equity move hadn't yet fully priced in. What was the equity, how much alpha was left on the table, and over what timeframe did it play out?"*

---

## 5. Tom Nakamura — Prop Trading Desk Head (Jane Street-style)

### A. First Reaction

"This isn't for me. I don't need someone to tell me *why* a prediction market moved — I need to know if the *price is wrong*. My edge is speed and pricing accuracy, not causal narratives. If anything, Pythia is a product for my counterparties, the people I trade against."

### B. What Excites Him

- **Honestly, very little from the core product.** The causal attribution and confidence scoring are irrelevant to market-making.
- **One exception:** The historical dataset. If he can analyze 9.15M historical spikes to understand *how prediction markets mean-revert after spikes* — the speed of mean reversion, the overshoot patterns, the relationship between spike size and subsequent reversal — that's useful for his market-making models. But he'd need the raw tick data, not processed "spikes."
- **Potential contrarian use:** If Pythia subscribers start trading on Pythia's signals, and those signals are predictable, Tom can trade *against* them. Understanding what Pythia tells its users could be an edge in itself.

### C. What Concerns Him

- **Latency is everything, and Pythia is slow.** A 5-layer LLM pipeline takes seconds to minutes. His systems react in milliseconds. Pythia is structurally incapable of operating at his speed.
- **He IS the sophisticated player.** Pythia is designed to help people understand prediction markets. Tom *is* the prediction market. He provides the liquidity that others trade against. He doesn't need a guide.
- **Information leakage.** If many funds use Pythia, their collective behavior becomes predictable. Tom would prefer his competitors NOT have access to this tool, because informed counterparties make market-making harder.
- **No microstructure data.** He cares about order book depth, trade sizes, maker/taker ratios, queue position. Pythia doesn't seem to touch any of this.

### D. How He'd Actually Use It

He probably wouldn't subscribe. If he did anything, he'd negotiate a one-time purchase of the historical dataset for his research team to mine for microstructure patterns. He might also monitor what Pythia is telling the market — if Pythia becomes popular, understanding its signals becomes a form of "flow intelligence" for him.

### E. What Would Make Him Pay

Almost nothing in the current product. The only scenario: if Pythia added a **market microstructure layer** — real-time order book analytics, flow toxicity scoring, adverse selection metrics for prediction markets — *that* would be relevant. But that's essentially a different product.

Alternatively, if Pythia could prove that its alerts *cause* predictable flow in prediction markets (i.e., "when Pythia fires a HIGH alert, Polymarket volume increases 40% in the next 5 minutes"), then the *meta-signal* of knowing what Pythia is telling people would be valuable.

### F. Price Sensitivity

- **Would pay:** $0–$2K/month for the current product. It's not relevant to his workflow.
- **Would pay for the data:** $10K–$50K one-time for the full historical tick dataset if it's clean and granular enough.
- **Comparison:** He spends $50K–$200K/month on exchange connectivity, co-location, and internal infrastructure. Pythia is in a completely different category.

### G. Killer Question

*"What's the end-to-end latency from a prediction market trade executing to a Pythia alert being delivered? And do you have data on how your subscribers' trading activity impacts the very markets you're monitoring — i.e., are you creating a feedback loop?"*

---

## Summary Matrix

| Dimension | Sarah (Macro) | Marcus (Crypto) | Raj (Quant) | Elena (Event) | Tom (Prop) |
|-----------|:---:|:---:|:---:|:---:|:---:|
| **Product Fit** | Medium | Low-Medium | Medium (data only) | **High** | Low |
| **Willingness to Pay** | $3–8K | $1–3K | $5–20K (data) | **$5–10K** | ~$0 |
| **Wants Causal Layer** | Maybe | No | No | **Yes** | No |
| **Wants Raw Data/API** | Some | **Yes** | **Yes** | Some | **Yes** (one-time) |
| **Biggest Objection** | Latency | Edge decay | No statistical rigor | Narrow coverage | Not relevant |
| **Conversion Difficulty** | Medium | Hard | Medium | **Easiest** | Near-impossible |

## Key Takeaways

1. **Elena (Event-Driven) is the ideal design partner.** Her workflow maps almost perfectly to what Pythia does. She values the narrative, needs cross-asset signals, and would pay meaningful money. Start here.

2. **The causal attribution layer is polarizing.** Elena loves it, everyone else is skeptical or indifferent. The *data* is universally interesting; the *intelligence layer* is niche.

3. **Raw data/API access is table stakes.** Every serious participant wants programmatic access. A UI-only product will not sell to institutions.

4. **Latency will come up in every conversation.** Even Elena, who doesn't need millisecond speed, will ask about it. Have a clear answer on end-to-end alert delivery time.

5. **Statistical proof > demos.** Show Sharpe ratios, information coefficients, and out-of-sample backtests. "We have 9.15M spikes" is a data pitch; "those spikes predict equity returns with IC of 0.04 and Sharpe of 1.2" is a product pitch.

6. **Verso at 73% accuracy is a weak benchmark.** Nobody in this panel knows or cares about Verso. Benchmark against Bloomberg alerts + analyst time, not another startup.

7. **Edge decay is a real risk.** Marcus raised it explicitly, but it's implicit for everyone. Consider tiered access or limited subscriber counts for premium signals.
