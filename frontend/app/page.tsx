'use client';

import { useState, useCallback, useRef, useEffect } from "react";

// ─── Types ───────────────────────────────────────────────────────────
interface PricePoint { t: string; price: number; }

interface MarketResult {
  id: string; question: string; slug: string; conditionId: string;
  clobTokenIds: string[]; outcomes: string[]; outcomePrices: string[];
  volume24hr: number; volume: number; image: string;
  spikeCount?: number; // -1 = failed to fetch, 0+ = actual count
}

interface Spike {
  index: number; timestamp: string; magnitude: number;
  direction: "up" | "down"; priceBefore: number; priceAfter: number;
}

interface Evidence {
  source: string;
  title: string;
  url: string | null;
  timestamp: string | null;
  timing: "before" | "concurrent" | "after";
}

interface Hypothesis {
  agent: string; agentRole: string; cause: string; reasoning: string;
  confidence: number; confidenceFactors: string;
  impactSpeed: string; impactSpeedExplain: string;
  timeToPeak: string; timeToPeakExplain: string;
  evidence: Evidence[];
  counterfactual: string;
}

interface Attribution {
  depth: number; agentsSpawned: number;
  hypothesesProposed: number; debateRounds: number; elapsed: number;
  hypotheses: Hypothesis[];
}

type Phase = "idle" | "searching" | "pick-market" | "loading-chart" | "chart" | "running-bace" | "result";

// ─── BACE progress state ─────────────────────────────────────────────
interface BACEState {
  step: number;
  entities: string[];
  agentsActive: string[];
  debateLog: string[];
  counterfactualsTested: number;
}

// ─── Spike detection ─────────────────────────────────────────────────
function detectSpikes(prices: PricePoint[], threshold = 0.05): Spike[] {
  if (prices.length < 8) return [];
  const spikes: Spike[] = [];
  const win = Math.min(4, Math.floor(prices.length / 10));
  for (let i = win; i < prices.length; i++) {
    const before = prices[i - win].price;
    const after = prices[i].price;
    const mag = Math.abs(after - before);
    if (mag >= threshold) {
      spikes.push({ index: i, timestamp: prices[i].t, magnitude: mag,
        direction: after > before ? "up" : "down", priceBefore: before, priceAfter: after });
    }
  }
  const deduped: Spike[] = [];
  for (const s of spikes) {
    const existing = deduped.find((d) => Math.abs(d.index - s.index) < 12);
    if (existing) { if (s.magnitude > existing.magnitude) deduped[deduped.indexOf(existing)] = s; }
    else deduped.push(s);
  }
  return deduped.sort((a, b) => b.magnitude - a.magnitude).slice(0, 15);
}

// ─── Mock data ───────────────────────────────────────────────────────
function generateMockAttribution(spike: Spike, question: string): Attribution {
  const q = question.slice(0, 50);
  const dir = spike.direction === "up" ? "bullish" : "bearish";
  const hyps: Hypothesis[] = [
    {
      agent: "Macro Policy Analyst", agentRole: "Monitors central bank decisions, fiscal policy, and economic indicators",
      cause: `FOMC meeting minutes revealed hawkish dissent — 3 committee members favored a 50bp rate hike, contradicting the dovish consensus. This repriced rate expectations across prediction markets within 30 minutes of publication.`,
      reasoning: `The committee minutes were released at 14:00 ET. The spike began at 14:08 ET, consistent with algorithmic parsing of the minutes followed by manual trader positioning. The magnitude (${(spike.magnitude*100).toFixed(1)}%) aligns with historical repricing events following hawkish FOMC surprises.`,
      confidence: 0.82,
      confidenceFactors: "Strong timing alignment (8 min lag), consistent with historical FOMC-spike patterns, corroborated by 2 other agents",
      impactSpeed: "immediate", impactSpeedExplain: "Price moved within minutes of the catalyst — typical of scheduled macro events where algorithms parse text instantly",
      timeToPeak: "30 min", timeToPeakExplain: "Most of the move completed in 30 minutes as both algo and human traders repositioned",
      evidence: [
        { source: "FOMC", title: "March 2026 Meeting Minutes", url: null, timestamp: "14:00 ET", timing: "before" },
        { source: "Reuters", title: "Fed minutes show hawkish dissent", url: null, timestamp: "14:03 ET", timing: "before" },
        { source: "CME FedWatch", title: "Rate hike probability jumped 12%", url: null, timestamp: "14:15 ET", timing: "concurrent" },
      ],
      counterfactual: "If the minutes had been dovish or neutral, rate-sensitive markets would have remained flat. No other catalyst explains the timing.",
    },
    {
      agent: "Informed Flow Analyst", agentRole: "Detects whale activity, block trades, and unusual positioning ahead of news",
      cause: `Large block trade detected: a single address placed $1.8M in YES tokens at ${(spike.priceBefore*100).toFixed(0)}¢ approximately 22 minutes before the Reuters headline. This suggests informed pre-positioning ahead of the public catalyst.`,
      reasoning: `Blockchain transaction analysis shows wallet 0x7a3f...c2e1 accumulated a concentrated position in a pattern inconsistent with normal market making. The order was filled against resting liquidity without moving price significantly, suggesting a sophisticated actor avoiding market impact.`,
      confidence: 0.71,
      confidenceFactors: "Clear pre-news timing, single-wallet concentration unusual for this market's typical flow, but cannot confirm information source",
      impactSpeed: "fast", impactSpeedExplain: "The initial informed trade was quiet, but the subsequent public catalyst triggered rapid price discovery over ~2 hours",
      timeToPeak: "2 hours", timeToPeakExplain: "Price drifted as the informed trader accumulated, then jumped sharply when news broke publicly",
      evidence: [
        { source: "On-chain", title: "Block trade: 0x7a3f...c2e1 bought $1.8M YES", url: null, timestamp: "-22 min", timing: "before" },
        { source: "Orderbook", title: "Resting asks swept at 47-52¢ range", url: null, timestamp: "-20 min", timing: "before" },
      ],
      counterfactual: "Without the informed flow, the spike would likely have started 22 minutes later when public news broke, and might have been smaller (less initial momentum).",
    },
    {
      agent: "Narrative & Sentiment", agentRole: "Tracks social media, Reddit, and news narrative shifts that drive retail flows",
      cause: `A thread by @PoliticsInsider (280K followers) posted a detailed analysis predicting this outcome 4 hours prior. The thread went viral (52K engagements in 2h) and drove retail buying pressure that preceded and amplified the fundamental catalyst.`,
      reasoning: `Sentiment analysis of Twitter/X and Reddit r/polymarket shows a sharp shift from neutral to ${dir} starting 3 hours before the spike. The @PoliticsInsider thread was the highest-engagement piece of content in the period, and reply sentiment was 78% aligned with the ${dir} move.`,
      confidence: 0.54,
      confidenceFactors: "Timeline fits but social media often reflects rather than causes moves. This thread may have anticipated the catalyst rather than independently caused the spike.",
      impactSpeed: "fast", impactSpeedExplain: "Retail sentiment shifts take 1-4 hours to manifest in prediction market prices as individual traders see and act on viral content",
      timeToPeak: "4 hours", timeToPeakExplain: "Social-media-driven moves build gradually as the content spreads through feeds and is discussed in trading communities",
      evidence: [
        { source: "Twitter/X", title: "@PoliticsInsider thread (52K engagements)", url: null, timestamp: "-4 hours", timing: "before" },
        { source: "Reddit", title: "r/polymarket sentiment shifted 78% bullish", url: null, timestamp: "-2 hours", timing: "before" },
      ],
      counterfactual: "The spike might have been smaller without the pre-existing sentiment shift, but the fundamental catalyst (FOMC) was the primary driver.",
    },
    {
      agent: "Cross-Market Contagion", agentRole: "Identifies spillover effects from equities, crypto, and related prediction markets",
      cause: `SPY dropped 1.4% between 13:45-14:15 ET, triggering a risk-off cascade that hit prediction markets ~12 minutes later. The cross-asset correlation suggests the equity move was the proximate trigger for repositioning.`,
      reasoning: `Historical analysis shows this prediction market has 0.62 correlation with SPY during high-volatility periods. The timing gap (12 min) is consistent with the typical lag for cross-asset contagion into prediction markets.`,
      confidence: 0.45,
      confidenceFactors: "Timing is consistent but correlation ≠ causation. The equity move and prediction market move may share a common cause (FOMC minutes) rather than one causing the other.",
      impactSpeed: "immediate", impactSpeedExplain: "Cross-market contagion happens within minutes as algorithmic traders and risk models propagate signals across asset classes",
      timeToPeak: "15 min", timeToPeakExplain: "Contagion effects are fast but short-lived; the prediction market repriced within one 15-minute candle",
      evidence: [
        { source: "Equities", title: "SPY -1.4% (13:45-14:15 ET)", url: null, timestamp: "-12 min", timing: "before" },
        { source: "Correlation", title: "Rolling 30d correlation: 0.62", url: null, timestamp: null, timing: "concurrent" },
      ],
      counterfactual: "If SPY had been flat, the prediction market move might have been 30-40% smaller, or delayed by the lag until traders independently processed FOMC.",
    },
    {
      agent: "Devil's Advocate", agentRole: "Adversarial agent: challenges all hypotheses and tests for spurious attribution",
      cause: `No single cause identified. The spike appears to be a convergence of multiple weak signals rather than one dominant catalyst. The timing overlaps of FOMC, whale flow, and social sentiment may be coincidental.`,
      reasoning: `Each proposed hypothesis has plausible alternative explanations. The FOMC minutes were largely priced in. The whale trade could be routine rebalancing. The social media thread may be effect rather than cause. Multiple weak signals converging does not prove any one is causal.`,
      confidence: 0.28,
      confidenceFactors: "This hypothesis is intentionally adversarial. Lower confidence reflects that multiple other agents independently identified FOMC timing as primary cause.",
      impactSpeed: "delayed", impactSpeedExplain: "If the move was convergence rather than a single catalyst, the buildup would have been more gradual — which partially contradicts the sharp spike shape",
      timeToPeak: "1-2 days", timeToPeakExplain: "Convergence-driven moves tend to unfold over longer periods. The sharp spike profile weakens this hypothesis.",
      evidence: [],
      counterfactual: "If each individual signal were removed, the spike might still have occurred from the remaining signals — which either supports convergence or undermines this hypothesis entirely.",
    },
    {
      agent: "Geopolitical Risk", agentRole: "Monitors geopolitical events, sanctions, military actions, and diplomatic shifts",
      cause: `No significant geopolitical catalyst identified in the spike window. Background geopolitical risk (Iran tensions, trade policy) remained stable during this period.`,
      reasoning: `Scanned Reuters, AP, and government press releases. No new geopolitical developments in the 6-hour window around the spike. This agent's hypothesis is null — the spike was not geopolitically driven.`,
      confidence: 0.12,
      confidenceFactors: "Low confidence is correct — this agent found no evidence supporting a geopolitical cause. The low score reflects honest null-finding, not weak analysis.",
      impactSpeed: "delayed", impactSpeedExplain: "Geopolitical events typically have delayed impact on domestic prediction markets (hours to days) — irrelevant here since no event was found",
      timeToPeak: "N/A", timeToPeakExplain: "No geopolitical catalyst identified",
      evidence: [],
      counterfactual: "N/A — this agent's null hypothesis: geopolitics did not cause this spike.",
    },
    {
      agent: "Null Hypothesis", agentRole: "Tests whether the spike is within normal variance or requires causal explanation",
      cause: `The spike magnitude (${(spike.magnitude*100).toFixed(1)}%) exceeds 3.2 standard deviations from this market's normal hourly volatility. This is statistically significant and unlikely to be random noise.`,
      reasoning: `Historical volatility analysis: mean hourly change = 0.8%, σ = 1.2%. The observed move of ${(spike.magnitude*100).toFixed(1)}% in 4 hours has a p-value of 0.003 — well below the 0.05 threshold. This spike warrants causal explanation; it is not normal market noise.`,
      confidence: 0.05,
      confidenceFactors: "Very low confidence that this was 'just noise'. The statistical test confirms the spike IS anomalous and some cause exists. Other agents should be trusted for identifying which cause.",
      impactSpeed: "immediate", impactSpeedExplain: "The spike's sharp profile (concentrated in a short window) further supports an external catalyst rather than drift",
      timeToPeak: "N/A", timeToPeakExplain: "This agent validates the spike is real, not what caused it",
      evidence: [
        { source: "Statistical", title: `${(spike.magnitude*100).toFixed(1)}% move = 3.2σ, p=0.003`, url: null, timestamp: null, timing: "concurrent" },
      ],
      counterfactual: "If this were noise, we'd expect the price to revert within 2-4 hours. Monitor for mean reversion to validate.",
    },
  ];
  hyps.sort((a, b) => b.confidence - a.confidence);
  return {
    depth: 2, agentsSpawned: 9, hypothesesProposed: hyps.length, debateRounds: 0,
    elapsed: 8.3 + Math.random() * 12, hypotheses: hyps,
  };
}

function generateBACEStates(spike: Spike, question: string): BACEState[] {
  const q = question.slice(0, 30);

  // Extract simple entities from the question
  const words = question.replace(/[?.,!]/g, "").split(/\s+/);
  const stopwords = new Set(["will", "the", "a", "an", "by", "in", "of", "to", "be", "is", "are", "was", "or", "and", "if", "its", "this", "that", "for", "on", "at", "with", "from", "before", "after", "not", "no", "yes"]);
  const entities = words
    .filter(w => w.length > 2 && !stopwords.has(w.toLowerCase()))
    .filter((w, i, arr) => arr.indexOf(w) === i)
    .slice(0, 5);

  return [
    { step: 0, entities: [], agentsActive: [], debateLog: ["Classifying market domain…", `Market: "${q}…"`, "Identifying category…"], counterfactualsTested: 0 },
    { step: 1, entities: [], agentsActive: [], debateLog: [`Spike: ${spike.direction === "up" ? "+" : "-"}${(spike.magnitude*100).toFixed(1)}% at ${new Date(spike.timestamp).toLocaleTimeString("en-US", {hour:"2-digit",minute:"2-digit"})}`, "Validating statistical significance…", "Result: exceeds threshold — proceeding"], counterfactualsTested: 0 },
    { step: 2, entities, agentsActive: [], debateLog: ["Extracting entities from market question + context…", `Found ${entities.length} entities`], counterfactualsTested: 0 },
    { step: 3, entities, agentsActive: [], debateLog: ["Fetching: Google News RSS…", "Fetching: DuckDuckGo News…", "Fetching: Reddit (category-mapped subreddits)…", "Filtering articles by spike temporal window…"], counterfactualsTested: 0 },
    { step: 4, entities, agentsActive: [], debateLog: ["Fetching domain-specific data…", "Checking equities correlation…", "Checking orderbook signals…", "Aggregating evidence items…"], counterfactualsTested: 0 },
    { step: 5, entities,
      agentsActive: ["Macro Policy Analyst", "Informed Flow Analyst", "Narrative & Sentiment", "Cross-Market Contagion", "Geopolitical Risk", "Devil's Advocate", "Null Hypothesis"],
      debateLog: ["Spawning 7 core + 2 adversarial agents", "Each agent receives: spike context + relevant evidence"], counterfactualsTested: 0 },
    { step: 6, entities,
      agentsActive: ["Macro Policy Analyst", "Informed Flow Analyst", "Narrative & Sentiment", "Cross-Market Contagion", "Geopolitical Risk", "Devil's Advocate", "Null Hypothesis"],
      debateLog: [
        "Macro Policy → generating hypothesis…",
        "Informed Flow → analyzing pre-spike order flow…",
        "Narrative → scanning social media sentiment…",
        "Cross-Market → checking correlated asset moves…",
        "Devil's Advocate → preparing challenges…",
        "Null Hypothesis → running statistical baseline…",
        "Geopolitical → scanning for geopolitical triggers…",
      ],
      counterfactualsTested: 0 },
    { step: 7, entities,
      agentsActive: ["Macro Policy Analyst", "Informed Flow Analyst", "Narrative & Sentiment", "Cross-Market Contagion", "Geopolitical Risk", "Devil's Advocate", "Null Hypothesis"],
      debateLog: [
        "Testing counterfactuals for each hypothesis…",
        "Calibrating confidence scores by timing + evidence strength…",
        "Cross-referencing agent proposals for consensus…",
        "Synthesizing final attribution…",
      ],
      counterfactualsTested: 3 },
  ];
}

// ─── Colors ──────────────────────────────────────────────────────────
const C = {
  bg: "#faf9f5", surface: "#FFFFFF", dark: "#141413", accent: "#d97757",
  yes: "#788c5d", muted: "#b0aea5", border: "#e8e6dc", info: "#6a9bcc", faint: "#f5f4ef",
};
const mono = "'JetBrains Mono', monospace";
const serif = "'Newsreader', 'Source Serif 4', Georgia, serif";

// ─── Components ──────────────────────────────────────────────────────

function MiniChart({ prices, spikes, selectedSpike, onSpikeClick, width = 860, height = 280 }: {
  prices: PricePoint[]; spikes: Spike[]; selectedSpike: Spike | null;
  onSpikeClick: (s: Spike) => void; width?: number; height?: number;
}) {
  const pad = { t: 20, r: 50, b: 30, l: 10 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  if (prices.length < 2) return <div style={{ padding: 40, color: C.muted }}>Not enough data</div>;
  const pMin = Math.min(...prices.map((p) => p.price)) - 0.02;
  const pMax = Math.max(...prices.map((p) => p.price)) + 0.02;
  const range = pMax - pMin || 0.01;
  const x = (i: number) => pad.l + (i / (prices.length - 1)) * w;
  const y = (p: number) => pad.t + (1 - (p - pMin) / range) * h;
  const line = prices.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.price).toFixed(1)}`).join(" ");
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => pMin + f * range);

  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      {yTicks.map((tick, i) => (
        <g key={i}>
          <line x1={pad.l} x2={width - pad.r} y1={y(tick)} y2={y(tick)} stroke={C.border} strokeWidth={0.5} />
          <text x={width - pad.r + 6} y={y(tick) + 4} fontSize={10} fontFamily={mono} fill={C.muted}>
            {(tick * 100).toFixed(0)}¢
          </text>
        </g>
      ))}
      <path d={line} fill="none" stroke={C.dark} strokeWidth={1.5} />
      {spikes.map((s, i) => {
        const sx = x(s.index); const sy = y(s.priceAfter);
        const isSel = selectedSpike?.index === s.index;
        return (
          <g key={i} onClick={() => onSpikeClick(s)} style={{ cursor: "pointer" }}>
            <rect x={sx - 8} y={pad.t} width={16} height={h}
              fill={isSel ? C.accent : "transparent"} opacity={isSel ? 0.12 : 0} />
            <circle cx={sx} cy={sy} r={isSel ? 7 : 5}
              fill={s.direction === "up" ? C.accent : C.info}
              stroke={isSel ? C.dark : "none"} strokeWidth={isSel ? 2 : 0} opacity={0.9} />
            <text x={sx} y={sy - 12} textAnchor="middle" fontSize={10} fontFamily={mono} fontWeight={700}
              fill={s.direction === "up" ? C.accent : C.info}>
              {s.direction === "up" ? "+" : "-"}{(s.magnitude * 100).toFixed(1)}%
            </text>
          </g>
        );
      })}
      <text x={pad.l} y={height - 6} fontSize={10} fontFamily={mono} fill={C.muted}>
        {new Date(prices[0]?.t).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
      </text>
      <text x={width - pad.r} y={height - 6} textAnchor="end" fontSize={10} fontFamily={mono} fill={C.muted}>
        {new Date(prices[prices.length - 1]?.t).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
      </text>
    </svg>
  );
}

// ─── Rich BACE Progress ──────────────────────────────────────────────
function BACELive({ baceState }: { baceState: BACEState }) {
  const stepLabels = [
    "Building spike context",
    "Extracting causal ontology",
    "Gathering news evidence",
    "Spawning specialist agents",
    "Fetching domain-specific data",
    "Agents proposing hypotheses",
    "Adversarial debate rounds",
    "Counterfactual testing & synthesis",
  ];

  return (
    <div style={{ padding: "20px 0" }}>
      {/* Step indicators */}
      <div style={{ display: "flex", gap: 4, marginBottom: 20 }}>
        {stepLabels.map((_, i) => (
          <div key={i} style={{
            flex: 1, height: 3, borderRadius: 2,
            background: i <= baceState.step ? C.accent : C.border,
            transition: "background 0.3s",
          }} />
        ))}
      </div>

      {/* Current step label */}
      <div style={{ fontFamily: mono, fontSize: 12, fontWeight: 600, color: C.accent, marginBottom: 16, display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ width: 7, height: 7, borderRadius: "50%", background: C.accent, animation: "pulse 1s infinite" }} />
        Step {baceState.step + 1}/8: {stepLabels[baceState.step]}
        <style>{`@keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:0.3 } }`}</style>
      </div>

      {/* Entities extracted */}
      {baceState.entities.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontFamily: mono, fontSize: 10, textTransform: "uppercase" as const, letterSpacing: 1, color: C.muted, marginBottom: 6 }}>
            Entities extracted
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" as const }}>
            {baceState.entities.map((e, i) => (
              <span key={i} style={{ fontFamily: mono, fontSize: 11, padding: "3px 8px", borderRadius: 4,
                background: C.faint, border: `1px solid ${C.border}`, color: C.dark }}>
                {e}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Agents spawned */}
      {baceState.agentsActive.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontFamily: mono, fontSize: 10, textTransform: "uppercase" as const, letterSpacing: 1, color: C.muted, marginBottom: 6 }}>
            Active agents ({baceState.agentsActive.length})
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" as const }}>
            {baceState.agentsActive.map((a, i) => {
              const isAdv = a === "Devil's Advocate" || a === "Null Hypothesis";
              return (
                <span key={i} style={{ fontFamily: mono, fontSize: 11, padding: "3px 8px", borderRadius: 4,
                  background: isAdv ? "#fdf0ed" : "#eef3e8", border: `1px solid ${isAdv ? C.accent + "40" : C.yes + "40"}`,
                  color: isAdv ? C.accent : C.yes }}>
                  {a}
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* Live log */}
      <div style={{ background: "#1a1a19", borderRadius: 6, padding: "14px 16px", fontFamily: mono, fontSize: 12, lineHeight: 1.8 }}>
        {baceState.debateLog.map((line, i) => {
          const isAgent = line.includes("→");
          const isResult = line.startsWith("Result:") || line.startsWith("Final") || line.startsWith("Testing counterfactual");
          return (
            <div key={i} style={{
              color: isResult ? C.accent : isAgent ? "#a8c77a" : "#a0a090",
              opacity: 1, transition: "opacity 0.3s",
            }}>
              <span style={{ color: "#555", marginRight: 8 }}>{'>'}</span>{line}
            </div>
          );
        })}
        <span style={{ color: "#555", animation: "blink 1s infinite" }}>▊</span>
        <style>{`@keyframes blink { 0%,100% { opacity:1 } 50% { opacity:0 } }`}</style>
      </div>
    </div>
  );
}

// ─── Result Panel ────────────────────────────────────────────────────
function ResultPanel({ attr, isLive }: { attr: Attribution; isLive: boolean }) {
  const [expanded, setExpanded] = useState<number | null>(0); // first one open by default

  return (
    <div style={{ padding: "24px 0" }}>
      {/* Run metadata */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16, flexWrap: "wrap" as const }}>
        <span style={{ fontFamily: mono, fontSize: 11, color: C.muted }}>
          Depth {attr.depth} · {attr.agentsSpawned} agents · {attr.hypothesesProposed} hypotheses · {attr.elapsed.toFixed(1)}s
        </span>
        <span style={{ fontFamily: mono, fontSize: 10, color: isLive ? C.yes : C.accent }}>
          {isLive ? "● live attribution" : "⚠ simulated — backend not connected"}
        </span>
      </div>

      {/* All hypotheses */}
      {attr.hypotheses.map((h, i) => {
        const isOpen = expanded === i;
        const confColor = h.confidence >= 0.7 ? C.yes : h.confidence >= 0.4 ? C.accent : C.muted;
        return (
          <div key={i} style={{
            background: C.surface, border: `1px solid ${isOpen ? confColor + "60" : C.border}`,
            borderRadius: 8, marginBottom: 10, overflow: "hidden", transition: "border-color 0.2s",
          }}>
            {/* Header — always visible */}
            <div onClick={() => setExpanded(isOpen ? null : i)} style={{ padding: "16px 20px", cursor: "pointer" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                {/* Confidence bar + number */}
                <div style={{ width: 44, height: 6, borderRadius: 3, background: C.border, overflow: "hidden", flexShrink: 0 }}>
                  <div style={{ width: `${h.confidence * 100}%`, height: "100%", borderRadius: 3, background: confColor }} />
                </div>
                <span style={{ fontFamily: mono, fontSize: 12, fontWeight: 700, color: confColor, width: 36, flexShrink: 0 }}>
                  {(h.confidence * 100).toFixed(0)}%
                </span>
                <span style={{ fontFamily: mono, fontSize: 11, fontWeight: 600, color: C.info }}>
                  {h.agent}
                </span>
                <span style={{ fontFamily: mono, fontSize: 10, color: C.muted, marginLeft: "auto" }}>
                  {isOpen ? "▾" : "▸"}
                </span>
              </div>

              {/* Full cause text — never truncated */}
              <div style={{ fontSize: 14, color: C.dark, lineHeight: 1.55 }}>
                {h.cause}
              </div>
            </div>

            {/* Expanded detail */}
            {isOpen && (
              <div style={{ padding: "0 20px 20px", borderTop: `1px solid ${C.border}` }}>

                {/* Agent role */}
                <div style={{ fontFamily: mono, fontSize: 11, color: C.muted, fontStyle: "italic" as const, padding: "12px 0 8px" }}>
                  {h.agentRole}
                </div>

                {/* Reasoning */}
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontFamily: mono, fontSize: 10, textTransform: "uppercase" as const, letterSpacing: 1, color: C.muted, marginBottom: 4 }}>Reasoning</div>
                  <div style={{ fontSize: 13, color: "#5a5850", lineHeight: 1.6 }}>{h.reasoning}</div>
                </div>

                {/* Confidence explanation */}
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontFamily: mono, fontSize: 10, textTransform: "uppercase" as const, letterSpacing: 1, color: C.muted, marginBottom: 4 }}>
                    Why {(h.confidence * 100).toFixed(0)}% confidence?
                  </div>
                  <div style={{ fontSize: 13, color: "#5a5850", lineHeight: 1.6 }}>{h.confidenceFactors}</div>
                </div>

                {/* Timing metadata — explained */}
                <div style={{ display: "flex", gap: 20, flexWrap: "wrap" as const, marginBottom: 16 }}>
                  <div style={{ flex: "1 1 200px" }}>
                    <div style={{ fontFamily: mono, fontSize: 10, textTransform: "uppercase" as const, letterSpacing: 1, color: C.muted, marginBottom: 4 }}>
                      Impact speed: <strong style={{ color: C.dark }}>{h.impactSpeed}</strong>
                    </div>
                    <div style={{ fontSize: 12, color: "#5a5850", lineHeight: 1.5 }}>{h.impactSpeedExplain}</div>
                  </div>
                  <div style={{ flex: "1 1 200px" }}>
                    <div style={{ fontFamily: mono, fontSize: 10, textTransform: "uppercase" as const, letterSpacing: 1, color: C.muted, marginBottom: 4 }}>
                      Time to peak: <strong style={{ color: C.dark }}>{h.timeToPeak}</strong>
                    </div>
                    <div style={{ fontSize: 12, color: "#5a5850", lineHeight: 1.5 }}>{h.timeToPeakExplain}</div>
                  </div>
                </div>

                {/* Evidence */}
                {h.evidence.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontFamily: mono, fontSize: 10, textTransform: "uppercase" as const, letterSpacing: 1, color: C.muted, marginBottom: 6 }}>
                      Evidence ({h.evidence.length})
                    </div>
                    {h.evidence.map((ev, j) => (
                      <div key={j} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0",
                        borderBottom: j < h.evidence.length - 1 ? `1px solid ${C.faint}` : "none" }}>
                        <span style={{ fontFamily: mono, fontSize: 10,
                          color: ev.timing === "before" ? C.yes : ev.timing === "concurrent" ? C.info : C.muted,
                          width: 70, flexShrink: 0, textTransform: "uppercase" as const }}>
                          {ev.timing === "before" ? "▴ before" : ev.timing === "concurrent" ? "● during" : "▾ after"}
                        </span>
                        <span style={{ fontFamily: mono, fontSize: 10, color: C.muted, width: 70, flexShrink: 0 }}>
                          {ev.source}
                        </span>
                        <span style={{ fontSize: 12, color: C.dark, flex: 1 }}>
                          {ev.url
                            ? <a href={ev.url} target="_blank" rel="noopener noreferrer" style={{ color: C.info, textDecoration: "underline" }}>{ev.title}</a>
                            : ev.title
                          }
                        </span>
                        {ev.timestamp && (
                          <span style={{ fontFamily: mono, fontSize: 10, color: C.muted, flexShrink: 0 }}>{ev.timestamp}</span>
                        )}
                      </div>
                    ))}
                    {!isLive && (
                      <div style={{ fontFamily: mono, fontSize: 10, color: C.muted, marginTop: 4, fontStyle: "italic" as const }}>
                        Source links will be available when backend is connected
                      </div>
                    )}
                  </div>
                )}

                {/* Counterfactual */}
                {h.counterfactual && (
                  <div>
                    <div style={{ fontFamily: mono, fontSize: 10, textTransform: "uppercase" as const, letterSpacing: 1, color: C.muted, marginBottom: 4 }}>
                      Counterfactual test
                    </div>
                    <div style={{ fontSize: 13, color: "#5a5850", lineHeight: 1.6, fontStyle: "italic" as const }}>
                      "{h.counterfactual}"
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Main ────────────────────────────────────────────────────────────
export default function Pythia() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [input, setInput] = useState("");
  const [searchResults, setSearchResults] = useState<MarketResult[]>([]);
  const [selectedMarket, setSelectedMarket] = useState<MarketResult | null>(null);
  const [prices, setPrices] = useState<PricePoint[]>([]);
  const [spikes, setSpikes] = useState<Spike[]>([]);
  const [selectedSpike, setSelectedSpike] = useState<Spike | null>(null);
  const [baceState, setBaceState] = useState<BACEState>({ step: 0, entities: [], agentsActive: [], debateLog: [], counterfactualsTested: 0 });
  const [attribution, setAttribution] = useState<Attribution | null>(null);
  const [isLive, setIsLive] = useState(false);
  const [error, setError] = useState("");
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const extractSlug = (text: string): string | null => {
    const m = text.match(/polymarket\.com\/(?:event|market)\/([a-z0-9-]+)/i);
    return m ? m[1] : null;
  };

  const handleAnalyze = useCallback(async () => {
    if (!input.trim()) return;
    setPhase("searching"); setError(""); setSearchResults([]);
    setSelectedMarket(null); setPrices([]); setSpikes([]);
    setSelectedSpike(null); setAttribution(null);

    try {
      const slug = extractSlug(input);
      const params = slug ? `slug=${encodeURIComponent(slug)}` : `q=${encodeURIComponent(input.trim())}`;
      const res = await fetch(`/api/polymarket/search?${params}`);
      const data = await res.json();

      if (!data.markets?.length) {
        setError("No markets found. Try a different search term or paste a Polymarket URL.");
        setPhase("idle"); return;
      }

      if (data.markets.length === 1) {
        await loadChart(data.markets[0]);
      } else {
        setSearchResults(data.markets);
        setPhase("pick-market");
      }
    } catch (err: any) {
      setError(`Search failed: ${err.message}`);
      setPhase("idle");
    }
  }, [input]);

  const loadChart = useCallback(async (market: MarketResult) => {
    setSelectedMarket(market);
    setPhase("loading-chart");

    try {
      const tokenId = market.clobTokenIds?.[0];
      if (!tokenId) { setError("No CLOB token ID for this market"); setPhase("idle"); return; }

      const res = await fetch(`/api/polymarket/history?tokenId=${encodeURIComponent(tokenId)}&interval=max&fidelity=60`);
      const data = await res.json();

      if (!data.history?.length) {
        setError("No price history available for this market.");
        setPhase("idle"); return;
      }

      setPrices(data.history);
      const allPrices = data.history.map((p: PricePoint) => p.price);
      const priceRange = Math.max(...allPrices) - Math.min(...allPrices);
      const medianPrice = allPrices.sort((a: number, b: number) => a - b)[Math.floor(allPrices.length / 2)] || 0.5;
      // Use the LOWER of: 15% of price range, or 10% of median price
      // This ensures low-price markets (e.g., 10¢) detect 2¢ moves as spikes
      const absThreshold = priceRange * 0.15;
      const relThreshold = medianPrice * 0.10; // 10% relative to current price
      const threshold = Math.max(0.005, Math.min(absThreshold, relThreshold));
      setSpikes(detectSpikes(data.history, threshold));
      setPhase("chart");
    } catch (err: any) {
      setError(`Failed to load price history: ${err.message}`);
      setPhase("idle");
    }
  }, []);

  const runBACE = useCallback(async (spike: Spike) => {
    setSelectedSpike(spike);
    setPhase("running-bace");
    setAttribution(null);
    setIsLive(false);

    const question = selectedMarket?.question || "";
    // Initialize animation with basic state
    setBaceState({ step: 0, entities: [], agentsActive: [], debateLog: [`Market: "${question.slice(0, 40)}…"`, "Connecting to BACE engine…"], counterfactualsTested: 0 });

    const backendUrl = process.env.NEXT_PUBLIC_PYTHIA_API_URL || "http://localhost:8000";

    // Try SSE streaming first
    try {
      const params = new URLSearchParams({
        market_title: question,
        market_id: selectedMarket?.id || "",
        timestamp: spike.timestamp,
        direction: spike.direction,
        magnitude: spike.magnitude.toString(),
        price_before: spike.priceBefore.toString(),
        price_after: spike.priceAfter.toString(),
        depth: "2",
      });

      const res = await fetch(`${backendUrl}/api/attribute/stream?${params}`);
      if (!res.ok || !res.body) throw new Error("SSE not available");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalResult: any = null;
      let currentStep = 0;
      const liveEntities: string[] = [];
      const liveAgents: string[] = [];
      const liveLog: string[] = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let eventType = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith("data: ") && eventType) {
            try {
              const data = JSON.parse(line.slice(6));

              if (eventType === "context") {
                currentStep = 0;
                liveLog.push(`Category: ${data.category}`);
                if (data.entities?.length) {
                  liveEntities.push(...data.entities);
                  liveLog.push(`Initial entities: ${data.entities.join(", ")}`);
                }
              } else if (eventType === "ontology") {
                currentStep = 1;
                liveEntities.length = 0;
                if (data.entities) liveEntities.push(...data.entities);
                liveLog.push(`Ontology: ${data.entity_count} entities, ${data.relationship_count} relationships`);
                liveLog.push(`Generated ${data.search_queries} search queries`);
              } else if (eventType === "evidence") {
                currentStep = 2;
                liveLog.push(`News evidence: ${data.count} articles gathered`);
              } else if (eventType === "agents") {
                currentStep = 3;
                liveAgents.length = 0;
                for (const a of data.agents || []) liveAgents.push(a.name);
                liveLog.push(`Spawned ${data.count} agents`);
              } else if (eventType === "domain_evidence") {
                currentStep = 4;
                liveLog.push(`Domain evidence: ${data.count} items`);
              } else if (eventType === "proposal") {
                currentStep = 5;
                const agentName = data.agent;
                for (const h of data.hypotheses || []) {
                  liveLog.push(`${agentName} → ${h.cause} (${Math.round(h.confidence * 100)}%)`);
                }
              } else if (eventType === "debate") {
                currentStep = 6;
                liveLog.push(`Debate round ${data.round}: ${data.surviving} surviving`);
              } else if (eventType === "counterfactual") {
                currentStep = 7;
                liveLog.push(`Counterfactual testing: ${data.tested} hypotheses tested`);
              } else if (eventType === "result") {
                finalResult = data;
              } else if (eventType === "error") {
                throw new Error(data.error || "Backend error");
              }

              // Update animation state with real data
              setBaceState({
                step: currentStep,
                entities: [...liveEntities],
                agentsActive: [...liveAgents],
                debateLog: liveLog.slice(-12), // show last 12 lines
                counterfactualsTested: currentStep >= 7 ? 1 : 0,
              });

            } catch (parseErr) {
              // Skip malformed events
            }
            eventType = "";
          }
        }
      }

      // Process final result
      if (finalResult) {
        const hyps: Hypothesis[] = (finalResult.hypotheses || []).map((h: any) => ({
          agent: h.agent || "Unknown",
          agentRole: "",
          cause: h.cause || "",
          reasoning: h.reasoning || "",
          confidence: typeof h.confidence === "number" ? h.confidence : 0.5,
          confidenceFactors: "",
          impactSpeed: h.impact_speed || "",
          impactSpeedExplain: "",
          timeToPeak: "",
          timeToPeakExplain: "",
          evidence: (h.evidence || []).map((e: any) => ({
            source: e.source || "",
            title: e.title || "",
            url: e.url || null,
            timestamp: e.timestamp || null,
            timing: e.timing || "concurrent",
          })),
          counterfactual: h.counterfactual || "",
        }));

        if (hyps.length > 0) {
          const md = finalResult.bace_metadata || {};
          setAttribution({
            depth: md.depth || 2,
            agentsSpawned: md.agents_spawned || hyps.length,
            hypothesesProposed: md.hypotheses_proposed || hyps.length,
            debateRounds: md.debate_rounds || 0,
            elapsed: md.elapsed_seconds || 0,
            hypotheses: hyps,
          });
          setIsLive(true);
          setPhase("result");
          return;
        }
      }
      // If we got here, SSE didn't produce a usable result — fall through
      console.log("[Pythia] SSE completed. finalResult:", finalResult ? "exists" : "null", "hypotheses:", finalResult?.hypotheses?.length || 0);
    } catch (sseErr) {
      // SSE failed — backend not running or connection error
      console.log("[Pythia] SSE failed:", sseErr);
    }

    // Fallback: mock data with animation
    const states = generateBACEStates(spike, question);
    let mockStep = 0;
    timerRef.current = setInterval(() => {
      mockStep++;
      if (mockStep < states.length) {
        setBaceState(states[mockStep]);
      } else if (mockStep === states.length) {
        clearInterval(timerRef.current!);
        setAttribution(generateMockAttribution(spike, question));
        setIsLive(false);
        setPhase("result");
      }
    }, 900 + Math.random() * 600);
  }, [selectedMarket]);

  useEffect(() => { return () => { if (timerRef.current) clearInterval(timerRef.current); }; }, []);

  const currentPrice = selectedMarket?.outcomePrices?.[0]
    ? `${(parseFloat(selectedMarket.outcomePrices[0]) * 100).toFixed(1)}¢` : null;

  return (
    <div style={{ minHeight: "100vh", background: C.bg, fontFamily: "'Source Serif 4', Georgia, serif", color: C.dark }}>
      <div style={{ padding: "24px 40px", borderBottom: `1px solid ${C.border}`, display: "flex", alignItems: "baseline", gap: 16 }}>
        <span style={{ fontSize: 22, fontWeight: 700, letterSpacing: -0.5, fontFamily: serif }}>Pythia</span>
        <span style={{ fontFamily: mono, fontSize: 11, color: C.muted, letterSpacing: 0.5 }}>BACKWARD ATTRIBUTION CAUSAL ENGINE</span>
      </div>

      <div style={{ maxWidth: 900, margin: "0 auto", padding: "40px 24px" }}>
        {/* Input */}
        <div style={{ marginBottom: 32 }}>
          <div style={{ fontSize: 14, color: C.muted, marginBottom: 12, fontFamily: mono }}>
            Paste a Polymarket URL or search for a market
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <input type="text" value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAnalyze()}
              placeholder="https://polymarket.com/event/fed-decision-in-march  or  iran hormuz"
              style={{ flex: 1, padding: "12px 16px", border: `1px solid ${C.border}`, borderRadius: 6,
                fontSize: 15, fontFamily: "'Source Serif 4', Georgia, serif", background: C.surface, color: C.dark, outline: "none" }} />
            <button onClick={handleAnalyze} disabled={!input.trim() || phase === "searching"}
              style={{ padding: "12px 28px", borderRadius: 6, border: "none", background: C.dark, color: C.bg,
                fontSize: 14, fontWeight: 600, cursor: "pointer", fontFamily: mono, opacity: !input.trim() ? 0.4 : 1 }}>
              {phase === "searching" ? "Searching…" : "Analyze"}
            </button>
          </div>
          {error && <div style={{ marginTop: 8, fontSize: 13, color: C.accent }}>{error}</div>}
        </div>

        {phase === "searching" && (
          <div style={{ textAlign: "center" as const, padding: 60, color: C.muted }}>
            <div style={{ width: 24, height: 24, border: `2px solid ${C.border}`, borderTopColor: C.accent,
              borderRadius: "50%", animation: "spin 0.8s linear infinite", margin: "0 auto 16px" }} />
            <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
            Searching Polymarket…
          </div>
        )}

        {phase === "pick-market" && searchResults.length > 0 && (
          <div>
            <div style={{ fontFamily: mono, fontSize: 11, fontWeight: 600,
              textTransform: "uppercase" as const, letterSpacing: 1, color: C.muted, marginBottom: 12 }}>
              {searchResults.length} markets found — select one
            </div>
            {searchResults.map((m, i) => {
              const sc = m.spikeCount;
              const hasSpikes = sc !== undefined && sc > 0;
              const noSpikes = sc === 0;
              return (
                <div key={i} onClick={() => loadChart(m)} style={{ background: C.surface,
                  border: `1px solid ${noSpikes ? C.border : C.border}`,
                  borderRadius: 6, padding: "14px 18px", marginBottom: 8, cursor: "pointer",
                  transition: "border-color 0.2s", opacity: noSpikes ? 0.55 : 1 }}
                  onMouseEnter={(e) => (e.currentTarget.style.borderColor = C.accent)}
                  onMouseLeave={(e) => (e.currentTarget.style.borderColor = C.border)}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                    <span style={{ fontSize: 15, fontWeight: 600, flex: 1 }}>{m.question}</span>
                    {hasSpikes && (
                      <span style={{ fontFamily: mono, fontSize: 10, fontWeight: 700,
                        padding: "2px 8px", borderRadius: 10, background: C.accent, color: "#fff", flexShrink: 0 }}>
                        {sc} spike{sc !== 1 ? "s" : ""}
                      </span>
                    )}
                    {noSpikes && (
                      <span style={{ fontFamily: mono, fontSize: 10,
                        padding: "2px 8px", borderRadius: 10, background: C.faint, color: C.muted, flexShrink: 0 }}>
                        no spikes
                      </span>
                    )}
                    {sc === undefined || sc === -1 ? null : null}
                  </div>
                  <div style={{ fontFamily: mono, fontSize: 11, color: C.muted }}>
                    Yes: {(parseFloat(m.outcomePrices?.[0] || "0") * 100).toFixed(1)}¢
                    {" · "}Vol 24h: ${(m.volume24hr / 1000).toFixed(0)}K
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {phase === "loading-chart" && (
          <div style={{ textAlign: "center" as const, padding: 60, color: C.muted }}>
            <div style={{ width: 24, height: 24, border: `2px solid ${C.border}`, borderTopColor: C.accent,
              borderRadius: "50%", animation: "spin 0.8s linear infinite", margin: "0 auto 16px" }} />
            Fetching price history from Polymarket CLOB…
          </div>
        )}

        {(phase === "chart" || phase === "running-bace" || phase === "result") && selectedMarket && (
          <div>
            {searchResults.length > 1 && (
              <button onClick={() => { setPhase("pick-market"); setSelectedMarket(null); setSelectedSpike(null); setAttribution(null); setPrices([]); setSpikes([]); }}
                style={{ fontFamily: mono, fontSize: 11, color: C.info, background: "none", border: "none",
                  cursor: "pointer", padding: "0 0 12px", display: "flex", alignItems: "center", gap: 4 }}>
                ← Back to search results ({searchResults.length})
              </button>
            )}
            <div style={{ fontFamily: serif, fontSize: 24, fontWeight: 700, marginBottom: 4 }}>
              {selectedMarket.question}
            </div>
            <div style={{ fontFamily: mono, fontSize: 11, color: C.muted, marginBottom: 20 }}>
              {currentPrice && <span style={{ color: C.dark, fontWeight: 600 }}>{currentPrice} Yes</span>}
              {" · "}{prices.length} data points · {spikes.length} spike{spikes.length !== 1 ? "s" : ""} detected
              {" · "}Vol 24h: ${(selectedMarket.volume24hr / 1000).toFixed(0)}K
              <span style={{ color: C.yes, marginLeft: 8 }}>● live data</span>
            </div>

            <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8,
              padding: "16px 12px", marginBottom: 24, overflowX: "auto" as const }}>
              <MiniChart prices={prices} spikes={spikes} selectedSpike={selectedSpike} onSpikeClick={runBACE} />
              {spikes.length === 0 && (
                <div style={{ textAlign: "center" as const, padding: "12px 0", fontFamily: mono, fontSize: 12, color: C.muted }}>
                  No significant spikes detected in this market's price history
                </div>
              )}
            </div>

            {spikes.length > 0 && phase === "chart" && (
              <div style={{ fontFamily: mono, fontSize: 12, color: C.muted, textAlign: "center" as const, padding: "8px 0" }}>
                Click any spike dot on the chart to run attribution
              </div>
            )}

            {selectedSpike && phase === "running-bace" && (
              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: "20px 24px" }}>
                <div style={{ fontFamily: mono, fontSize: 11, fontWeight: 600,
                  textTransform: "uppercase" as const, letterSpacing: 1, color: C.muted, marginBottom: 4 }}>
                  Running BACE depth 2
                </div>
                <div style={{ fontSize: 15, marginBottom: 4 }}>
                  <span style={{ color: selectedSpike.direction === "up" ? C.accent : C.info, fontWeight: 700 }}>
                    {selectedSpike.direction === "up" ? "+" : "-"}{(selectedSpike.magnitude * 100).toFixed(1)}%
                  </span>
                  {" "}at {new Date(selectedSpike.timestamp).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                </div>
                <BACELive baceState={baceState} />
              </div>
            )}

            {phase === "result" && attribution && <ResultPanel attr={attribution} isLive={isLive} />}
          </div>
        )}

        {phase === "idle" && !error && (
          <div style={{ textAlign: "center" as const, padding: "80px 0", color: C.muted }}>
            <div style={{ fontSize: 48, marginBottom: 16, opacity: 0.3 }}>⚡</div>
            <div style={{ fontFamily: serif, fontSize: 20, fontWeight: 600, color: C.dark, marginBottom: 8 }}>
              Why did this spike happen?
            </div>
            <div style={{ fontSize: 14, maxWidth: 440, margin: "0 auto", lineHeight: 1.6 }}>
              Paste a Polymarket URL or search by keyword. Pythia fetches real price history,
              detects spikes, and attributes their causes using 9 specialized AI agents.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
