'use client';

import { useState, useCallback, useRef, useEffect } from "react";

// ─── Types ───────────────────────────────────────────────────────────
interface PricePoint { t: string; price: number; }

interface MarketResult {
  id: string; question: string; slug: string; conditionId: string;
  clobTokenIds: string[]; outcomes: string[]; outcomePrices: string[];
  volume24hr: number; volume: number; image: string;
}

interface Spike {
  index: number; timestamp: string; magnitude: number;
  direction: "up" | "down"; priceBefore: number; priceAfter: number;
}

interface Hypothesis {
  agent: string; cause: string; confidence: number; chain: string;
  impactSpeed: string; timeToPeak: string; evidence: string[];
}

interface Attribution {
  mostLikelyCause: string; confidence: "HIGH" | "MEDIUM" | "LOW";
  chain: string; depth: number; agentsSpawned: number;
  hypothesesProposed: number; debateRounds: number; elapsed: number;
  hypotheses: Hypothesis[];
}

type Phase = "idle" | "searching" | "pick-market" | "loading-chart" | "chart" | "running-bace" | "result";

// ─── Spike detection on real data ────────────────────────────────────
function detectSpikes(prices: PricePoint[], threshold = 0.05): Spike[] {
  if (prices.length < 8) return [];
  const spikes: Spike[] = [];
  // Look at 4-hour windows
  const window = Math.min(4, Math.floor(prices.length / 10));
  for (let i = window; i < prices.length; i++) {
    const before = prices[i - window].price;
    const after = prices[i].price;
    const mag = Math.abs(after - before);
    if (mag >= threshold) {
      spikes.push({
        index: i, timestamp: prices[i].t, magnitude: mag,
        direction: after > before ? "up" : "down",
        priceBefore: before, priceAfter: after,
      });
    }
  }
  // Deduplicate: keep strongest per 12-point window
  const deduped: Spike[] = [];
  for (const s of spikes) {
    const existing = deduped.find((d) => Math.abs(d.index - s.index) < 12);
    if (existing) {
      if (s.magnitude > existing.magnitude) {
        deduped[deduped.indexOf(existing)] = s;
      }
    } else {
      deduped.push(s);
    }
  }
  return deduped.sort((a, b) => b.magnitude - a.magnitude).slice(0, 15);
}

// ─── Mock attribution (replace when backend wired) ───────────────────
function generateMockAttribution(spike: Spike, question: string): Attribution {
  const agents = [
    "Macro Policy", "Market Structure", "Geopolitical", "Regulatory",
    "Narrative & Sentiment", "Informed Flow", "Cross-Market"
  ];
  const causes = [
    `Policy shift detected: government action directly affecting "${question.slice(0, 40)}…"`,
    `Whale accumulation: single large order ($1.2M+) placed 18 min before public news broke`,
    `Geopolitical escalation: Reuters alert triggered cascade across related prediction markets`,
    `Regulatory filing published 2 hours prior — market initially underreacted, then repriced`,
    `Viral social media thread (47K engagements in 1h) shifted retail sentiment rapidly`,
    `SPY correlation: equity market move preceded this contract by ~12 minutes, suggesting contagion`,
    `Informed flow: block trades at ${(spike.priceAfter * 100).toFixed(0)}¢ appeared before any public catalyst`,
  ];
  const hyps: Hypothesis[] = agents.map((a, i) => ({
    agent: a,
    cause: causes[i],
    confidence: Math.round((0.25 + Math.random() * 0.65) * 100) / 100,
    chain: `${a} analysis → identified pattern consistent with ${spike.direction === "up" ? "bullish" : "bearish"} catalyst → cross-referenced with ${2 + Math.floor(Math.random() * 4)} evidence sources`,
    impactSpeed: ["immediate", "fast", "delayed", "fast", "immediate", "fast", "immediate"][i],
    timeToPeak: ["30 min", "2 hours", "1-2 days", "4 hours", "1 hour", "2 hours", "15 min"][i],
    evidence: [`Source ${i + 1}a`, `Source ${i + 1}b`, `Source ${i + 1}c`].slice(0, 2 + Math.floor(Math.random() * 2)),
  }));
  hyps.sort((a, b) => b.confidence - a.confidence);
  const best = hyps[0];
  return {
    mostLikelyCause: best.cause,
    confidence: best.confidence >= 0.7 ? "HIGH" : best.confidence >= 0.4 ? "MEDIUM" : "LOW",
    chain: best.chain, depth: 2, agentsSpawned: 9,
    hypothesesProposed: hyps.length, debateRounds: 0,
    elapsed: 8.3 + Math.random() * 12, hypotheses: hyps,
  };
}

// ─── Colors ──────────────────────────────────────────────────────────
const C = {
  bg: "#faf9f5", surface: "#FFFFFF", dark: "#141413", accent: "#d97757",
  yes: "#788c5d", muted: "#b0aea5", border: "#e8e6dc", info: "#6a9bcc", faint: "#f5f4ef",
};

// ─── Components ──────────────────────────────────────────────────────
function ConfBadge({ level }: { level: string }) {
  const color = level === "HIGH" ? C.yes : level === "MEDIUM" ? C.accent : C.muted;
  return (
    <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, fontWeight: 700,
      padding: "2px 8px", borderRadius: 3, background: color, color: "#fff", letterSpacing: 0.5 }}>
      {level}
    </span>
  );
}

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
          <text x={width - pad.r + 6} y={y(tick) + 4} fontSize={10} fontFamily="'JetBrains Mono', monospace" fill={C.muted}>
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
            <text x={sx} y={sy - 12} textAnchor="middle" fontSize={10}
              fontFamily="'JetBrains Mono', monospace" fontWeight={700}
              fill={s.direction === "up" ? C.accent : C.info}>
              {s.direction === "up" ? "+" : "-"}{(s.magnitude * 100).toFixed(1)}%
            </text>
          </g>
        );
      })}
      <text x={pad.l} y={height - 6} fontSize={10} fontFamily="'JetBrains Mono', monospace" fill={C.muted}>
        {new Date(prices[0]?.t).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
      </text>
      <text x={width - pad.r} y={height - 6} textAnchor="end" fontSize={10} fontFamily="'JetBrains Mono', monospace" fill={C.muted}>
        {new Date(prices[prices.length - 1]?.t).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
      </text>
    </svg>
  );
}

function BACEProgress({ step }: { step: number }) {
  const steps = [
    "Building context…", "Statistical validation…", "Extracting ontology…",
    "Gathering news evidence…", "Fetching domain data…", "Spawning agents…",
    "Agents proposing hypotheses…", "Synthesizing…",
  ];
  return (
    <div style={{ padding: "32px 0" }}>
      {steps.map((label, i) => {
        const done = i < step; const active = i === step;
        return (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "6px 0",
            opacity: done ? 1 : active ? 1 : 0.3, transition: "opacity 0.4s" }}>
            <span style={{ width: 20, height: 20, borderRadius: "50%",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 11, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace",
              background: done ? C.yes : active ? C.accent : C.border,
              color: done || active ? "#fff" : C.muted, transition: "background 0.3s" }}>
              {done ? "✓" : i + 1}
            </span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13,
              color: active ? C.dark : done ? C.muted : C.border, fontWeight: active ? 600 : 400 }}>
              {label}
            </span>
            {active && <span style={{ width: 6, height: 6, borderRadius: "50%", background: C.accent, animation: "pulse 1s infinite" }} />}
          </div>
        );
      })}
      <style>{`@keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:0.3 } }`}</style>
    </div>
  );
}

function ResultPanel({ attr }: { attr: Attribution }) {
  const [expanded, setExpanded] = useState<number | null>(null);
  return (
    <div style={{ padding: "24px 0" }}>
      <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: "20px 24px", marginBottom: 20 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <ConfBadge level={attr.confidence} />
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: C.muted }}>
            Depth {attr.depth} · {attr.agentsSpawned} agents · {attr.elapsed.toFixed(1)}s
          </span>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: C.accent, marginLeft: "auto" }}>
            ⚠ mock attribution — backend not connected
          </span>
        </div>
        <div style={{ fontFamily: "'Newsreader', 'Source Serif 4', Georgia, serif",
          fontSize: 20, fontWeight: 600, lineHeight: 1.4, color: C.dark, marginBottom: 8 }}>
          {attr.mostLikelyCause}
        </div>
        <div style={{ fontSize: 13, color: "#5a5850", lineHeight: 1.6 }}>{attr.chain}</div>
      </div>

      <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, fontWeight: 600,
        textTransform: "uppercase" as const, letterSpacing: 1, color: C.muted, marginBottom: 12 }}>
        All Agent Hypotheses ({attr.hypotheses.length})
      </div>

      {attr.hypotheses.map((h, i) => {
        const isTop = i === 0; const isOpen = expanded === i;
        return (
          <div key={i} onClick={() => setExpanded(isOpen ? null : i)}
            style={{ background: isTop ? "#f8f5f0" : C.surface,
              border: `1px solid ${isTop ? C.accent + "40" : C.border}`,
              borderRadius: 6, padding: "14px 18px", marginBottom: 8, cursor: "pointer" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ width: 40, height: 6, borderRadius: 3, background: C.border, overflow: "hidden", flexShrink: 0 }}>
                <div style={{ width: `${h.confidence * 100}%`, height: "100%", borderRadius: 3,
                  background: h.confidence >= 0.7 ? C.yes : h.confidence >= 0.4 ? C.accent : C.muted }} />
              </div>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: C.muted, width: 36, flexShrink: 0 }}>
                {(h.confidence * 100).toFixed(0)}%
              </span>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, fontWeight: 600, color: C.info, width: 140, flexShrink: 0 }}>
                {h.agent}
              </span>
              <span style={{ fontSize: 13, color: C.dark, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const }}>
                {h.cause}
              </span>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: C.muted, flexShrink: 0 }}>
                {h.impactSpeed}
              </span>
            </div>
            {isOpen && (
              <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${C.border}` }}>
                <div style={{ fontSize: 13, color: "#5a5850", lineHeight: 1.6, marginBottom: 8 }}>{h.chain}</div>
                <div style={{ display: "flex", gap: 16, flexWrap: "wrap" as const }}>
                  {[["Speed", h.impactSpeed], ["Peak impact", h.timeToPeak], ["Evidence", `${h.evidence.length} sources`]].map(([k, v]) => (
                    <span key={k} style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: C.muted }}>
                      {k}: <strong style={{ color: C.dark }}>{v}</strong>
                    </span>
                  ))}
                </div>
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
  const [baceStep, setBaceStep] = useState(0);
  const [attribution, setAttribution] = useState<Attribution | null>(null);
  const [error, setError] = useState("");
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Parse URL to extract slug
  const extractSlug = (text: string): string | null => {
    const m = text.match(/polymarket\.com\/(?:event|market)\/([a-z0-9-]+)/i);
    return m ? m[1] : null;
  };

  // Search or resolve market
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

      if (data.markets.length === 1 || slug) {
        // Direct match — load chart immediately
        await loadChart(data.markets[0]);
      } else {
        // Multiple results — let user pick
        setSearchResults(data.markets);
        setPhase("pick-market");
      }
    } catch (err: any) {
      setError(`Search failed: ${err.message}`);
      setPhase("idle");
    }
  }, [input]);

  // Load price history for a market
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
      // Adaptive threshold: use smaller threshold for low-volatility markets
      const priceRange = Math.max(...data.history.map((p: PricePoint) => p.price)) -
                         Math.min(...data.history.map((p: PricePoint) => p.price));
      const threshold = Math.max(0.02, priceRange * 0.15);
      setSpikes(detectSpikes(data.history, threshold));
      setPhase("chart");
    } catch (err: any) {
      setError(`Failed to load price history: ${err.message}`);
      setPhase("idle");
    }
  }, []);

  // Run BACE (mock for now)
  const runBACE = useCallback((spike: Spike) => {
    setSelectedSpike(spike);
    setPhase("running-bace");
    setBaceStep(0); setAttribution(null);

    let step = 0;
    timerRef.current = setInterval(() => {
      step++;
      if (step >= 8) {
        clearInterval(timerRef.current!);
        setAttribution(generateMockAttribution(spike, selectedMarket?.question || ""));
        setPhase("result");
      } else { setBaceStep(step); }
    }, 600 + Math.random() * 400);
  }, [selectedMarket]);

  useEffect(() => { return () => { if (timerRef.current) clearInterval(timerRef.current); }; }, []);

  const currentPrice = selectedMarket?.outcomePrices?.[0]
    ? `${(parseFloat(selectedMarket.outcomePrices[0]) * 100).toFixed(1)}¢`
    : null;

  return (
    <div style={{ minHeight: "100vh", background: C.bg, fontFamily: "'Source Serif 4', Georgia, serif", color: C.dark }}>
      {/* Header */}
      <div style={{ padding: "24px 40px", borderBottom: `1px solid ${C.border}`, display: "flex", alignItems: "baseline", gap: 16 }}>
        <span style={{ fontSize: 22, fontWeight: 700, letterSpacing: -0.5, fontFamily: "'Newsreader', 'Source Serif 4', Georgia, serif" }}>Pythia</span>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: C.muted, letterSpacing: 0.5 }}>BACKWARD ATTRIBUTION CAUSAL ENGINE</span>
      </div>

      <div style={{ maxWidth: 900, margin: "0 auto", padding: "40px 24px" }}>
        {/* Input */}
        <div style={{ marginBottom: 32 }}>
          <div style={{ fontSize: 14, color: C.muted, marginBottom: 12, fontFamily: "'JetBrains Mono', monospace" }}>
            Paste a Polymarket URL or search for a market
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <input type="text" value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAnalyze()}
              placeholder="https://polymarket.com/event/fed-decision-in-march  or  trump tariff"
              style={{ flex: 1, padding: "12px 16px", border: `1px solid ${C.border}`, borderRadius: 6,
                fontSize: 15, fontFamily: "'Source Serif 4', Georgia, serif", background: C.surface, color: C.dark, outline: "none" }} />
            <button onClick={handleAnalyze} disabled={!input.trim() || phase === "searching"}
              style={{ padding: "12px 28px", borderRadius: 6, border: "none", background: C.dark, color: C.bg,
                fontSize: 14, fontWeight: 600, cursor: "pointer", fontFamily: "'JetBrains Mono', monospace",
                opacity: !input.trim() ? 0.4 : 1 }}>
              {phase === "searching" ? "Searching…" : "Analyze"}
            </button>
          </div>
          {error && <div style={{ marginTop: 8, fontSize: 13, color: C.accent }}>{error}</div>}
        </div>

        {/* Searching */}
        {phase === "searching" && (
          <div style={{ textAlign: "center" as const, padding: 60, color: C.muted }}>
            <div style={{ width: 24, height: 24, border: `2px solid ${C.border}`, borderTopColor: C.accent,
              borderRadius: "50%", animation: "spin 0.8s linear infinite", margin: "0 auto 16px" }} />
            <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
            Searching Polymarket…
          </div>
        )}

        {/* Pick market */}
        {phase === "pick-market" && searchResults.length > 0 && (
          <div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, fontWeight: 600,
              textTransform: "uppercase" as const, letterSpacing: 1, color: C.muted, marginBottom: 12 }}>
              {searchResults.length} markets found — select one
            </div>
            {searchResults.map((m, i) => (
              <div key={i} onClick={() => loadChart(m)} style={{ background: C.surface, border: `1px solid ${C.border}`,
                borderRadius: 6, padding: "14px 18px", marginBottom: 8, cursor: "pointer",
                transition: "border-color 0.2s" }}
                onMouseEnter={(e) => (e.currentTarget.style.borderColor = C.accent)}
                onMouseLeave={(e) => (e.currentTarget.style.borderColor = C.border)}>
                <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>{m.question}</div>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: C.muted }}>
                  Yes: {(parseFloat(m.outcomePrices?.[0] || "0") * 100).toFixed(1)}¢
                  {" · "}Vol 24h: ${(m.volume24hr / 1000).toFixed(0)}K
                  {" · "}{m.slug}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Loading chart */}
        {phase === "loading-chart" && (
          <div style={{ textAlign: "center" as const, padding: 60, color: C.muted }}>
            <div style={{ width: 24, height: 24, border: `2px solid ${C.border}`, borderTopColor: C.accent,
              borderRadius: "50%", animation: "spin 0.8s linear infinite", margin: "0 auto 16px" }} />
            Fetching price history from Polymarket CLOB…
          </div>
        )}

        {/* Chart + results */}
        {(phase === "chart" || phase === "running-bace" || phase === "result") && selectedMarket && (
          <div>
            <div style={{ fontFamily: "'Newsreader', 'Source Serif 4', Georgia, serif", fontSize: 24, fontWeight: 700, marginBottom: 4 }}>
              {selectedMarket.question}
            </div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: C.muted, marginBottom: 20 }}>
              {currentPrice && <span style={{ color: C.dark, fontWeight: 600 }}>{currentPrice} Yes</span>}
              {" · "}{prices.length} data points · {spikes.length} spike{spikes.length !== 1 ? "s" : ""} detected
              {" · "}Vol 24h: ${(selectedMarket.volume24hr / 1000).toFixed(0)}K
              <span style={{ color: C.yes, marginLeft: 8 }}>● live data</span>
            </div>

            <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8,
              padding: "16px 12px", marginBottom: 24, overflowX: "auto" as const }}>
              <MiniChart prices={prices} spikes={spikes} selectedSpike={selectedSpike} onSpikeClick={runBACE} />
              {spikes.length === 0 && (
                <div style={{ textAlign: "center" as const, padding: "12px 0", fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 12, color: C.muted }}>
                  No significant spikes detected in this market's price history
                </div>
              )}
            </div>

            {spikes.length > 0 && phase === "chart" && (
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: C.muted, textAlign: "center" as const, padding: "8px 0" }}>
                ↑ Click any spike dot on the chart to run attribution
              </div>
            )}

            {selectedSpike && phase === "running-bace" && (
              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: "20px 24px" }}>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, fontWeight: 600,
                  textTransform: "uppercase" as const, letterSpacing: 1, color: C.muted, marginBottom: 8 }}>
                  Running BACE depth 2 on spike
                </div>
                <div style={{ fontSize: 15, marginBottom: 4 }}>
                  <span style={{ color: selectedSpike.direction === "up" ? C.accent : C.info, fontWeight: 700 }}>
                    {selectedSpike.direction === "up" ? "+" : "-"}{(selectedSpike.magnitude * 100).toFixed(1)}%
                  </span>
                  {" "}at {new Date(selectedSpike.timestamp).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                </div>
                <BACEProgress step={baceStep} />
              </div>
            )}

            {phase === "result" && attribution && <ResultPanel attr={attribution} />}
          </div>
        )}

        {/* Idle */}
        {phase === "idle" && !error && (
          <div style={{ textAlign: "center" as const, padding: "80px 0", color: C.muted }}>
            <div style={{ fontSize: 48, marginBottom: 16, opacity: 0.3 }}>⚡</div>
            <div style={{ fontFamily: "'Newsreader', 'Source Serif 4', Georgia, serif",
              fontSize: 20, fontWeight: 600, color: C.dark, marginBottom: 8 }}>
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
