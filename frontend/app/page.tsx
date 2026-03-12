'use client';

import { useState, useCallback, useRef, useEffect } from "react";

// ─── Types ───────────────────────────────────────────────────────────
interface PricePoint {
  t: string;
  price: number;
  volume: number;
}

interface Spike {
  index: number;
  timestamp: string;
  magnitude: number;
  direction: "up" | "down";
  priceBefore: number;
  priceAfter: number;
}

interface Hypothesis {
  agent: string;
  cause: string;
  confidence: number;
  chain: string;
  impactSpeed: string;
  timeToPeak: string;
  evidence: string[];
}

interface Attribution {
  mostLikelyCause: string;
  confidence: "HIGH" | "MEDIUM" | "LOW";
  chain: string;
  depth: number;
  agentsSpawned: number;
  hypothesesProposed: number;
  debateRounds: number;
  elapsed: number;
  hypotheses: Hypothesis[];
}

type Phase = "idle" | "loading-market" | "chart" | "running-bace" | "result";

// ─── Mock data (replace with real API) ───────────────────────────────
function generateMockPrices(title: string): PricePoint[] {
  const pts: PricePoint[] = [];
  let price = 0.35 + Math.random() * 0.3;
  const now = Date.now();
  for (let i = 0; i < 720; i++) {
    const t = new Date(now - (720 - i) * 3600000).toISOString();
    const drift = (Math.random() - 0.48) * 0.008;
    const shock = Math.random() < 0.02 ? (Math.random() - 0.3) * 0.12 : 0;
    price = Math.max(0.01, Math.min(0.99, price + drift + shock));
    const volume = Math.floor(5000 + Math.random() * 30000 + (shock !== 0 ? 80000 : 0));
    pts.push({ t, price, volume });
  }
  return pts;
}

function detectSpikes(prices: PricePoint[], threshold = 0.05): Spike[] {
  const spikes: Spike[] = [];
  for (let i = 4; i < prices.length; i++) {
    const before = prices[i - 4].price;
    const after = prices[i].price;
    const mag = Math.abs(after - before);
    if (mag >= threshold) {
      spikes.push({
        index: i,
        timestamp: prices[i].t,
        magnitude: mag,
        direction: after > before ? "up" : "down",
        priceBefore: before,
        priceAfter: after,
      });
    }
  }
  const deduped: Spike[] = [];
  for (const s of spikes) {
    const tooClose = deduped.some((d) => Math.abs(d.index - s.index) < 12);
    if (!tooClose) deduped.push(s);
  }
  return deduped;
}

function generateMockAttribution(spike: Spike): Attribution {
  const agents = [
    "Macro Policy", "Market Structure", "Geopolitical", "Regulatory",
    "Narrative & Sentiment", "Informed Flow", "Cross-Market"
  ];
  const causes = [
    "FOMC minutes revealed hawkish dissent — 3 members favored 50bp hike",
    "Whale accumulation: single address bought $2.3M in 45 minutes pre-news",
    "Executive order draft leaked on X — tariff escalation on semiconductors",
    "SEC enforcement action filed against major market maker",
    "Viral Twitter thread by political insider shifted narrative",
    "SPY dropped 1.8% triggering risk-off contagion across prediction markets",
    "Unusual block trades preceded Reuters breaking news by 22 minutes",
  ];
  const hyps: Hypothesis[] = agents.map((a, i) => ({
    agent: a,
    cause: causes[i % causes.length],
    confidence: Math.round((0.3 + Math.random() * 0.6) * 100) / 100,
    chain: `${a} analysis → identified causal pattern → confirmed by evidence`,
    impactSpeed: ["immediate", "fast", "delayed", "fast", "immediate", "fast", "immediate"][i],
    timeToPeak: ["30 min", "2 hours", "1-2 days", "4 hours", "1 hour", "2 hours", "15 min"][i],
    evidence: [`Source ${i + 1}a`, `Source ${i + 1}b`],
  }));
  hyps.sort((a, b) => b.confidence - a.confidence);
  const best = hyps[0];
  return {
    mostLikelyCause: best.cause,
    confidence: best.confidence >= 0.7 ? "HIGH" : best.confidence >= 0.4 ? "MEDIUM" : "LOW",
    chain: best.chain,
    depth: 2,
    agentsSpawned: 9,
    hypothesesProposed: hyps.length,
    debateRounds: 0,
    elapsed: 8.3 + Math.random() * 12,
    hypotheses: hyps,
  };
}

// ─── Colors ──────────────────────────────────────────────────────────
const C = {
  bg: "#faf9f5",
  surface: "#FFFFFF",
  dark: "#141413",
  accent: "#d97757",
  yes: "#788c5d",
  muted: "#b0aea5",
  border: "#e8e6dc",
  info: "#6a9bcc",
  faint: "#f5f4ef",
};

// ─── Confidence badge ────────────────────────────────────────────────
function ConfBadge({ level }: { level: string }) {
  const color =
    level === "HIGH" ? C.yes : level === "MEDIUM" ? C.accent : C.muted;
  return (
    <span
      style={{
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
        fontWeight: 700,
        padding: "2px 8px",
        borderRadius: 3,
        background: color,
        color: "#fff",
        letterSpacing: 0.5,
      }}
    >
      {level}
    </span>
  );
}

// ─── Mini Chart (SVG) ────────────────────────────────────────────────
function MiniChart({
  prices,
  spikes,
  selectedSpike,
  onSpikeClick,
  width = 860,
  height = 280,
}: {
  prices: PricePoint[];
  spikes: Spike[];
  selectedSpike: Spike | null;
  onSpikeClick: (s: Spike) => void;
  width?: number;
  height?: number;
}) {
  const pad = { t: 20, r: 50, b: 30, l: 10 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const pMin = Math.min(...prices.map((p) => p.price)) - 0.02;
  const pMax = Math.max(...prices.map((p) => p.price)) + 0.02;
  const x = (i: number) => pad.l + (i / (prices.length - 1)) * w;
  const y = (p: number) => pad.t + (1 - (p - pMin) / (pMax - pMin)) * h;

  const line = prices
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.price).toFixed(1)}`)
    .join(" ");

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => pMin + f * (pMax - pMin));

  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      {yTicks.map((tick, i) => (
        <g key={i}>
          <line x1={pad.l} x2={width - pad.r} y1={y(tick)} y2={y(tick)} stroke={C.border} strokeWidth={0.5} />
          <text x={width - pad.r + 6} y={y(tick) + 4} fontSize={10} fontFamily="'JetBrains Mono', monospace" fill={C.muted}>
            {(tick * 100).toFixed(0)}%
          </text>
        </g>
      ))}
      <path d={line} fill="none" stroke={C.dark} strokeWidth={1.5} />
      {spikes.map((s, i) => {
        const sx = x(s.index);
        const sy = y(s.priceAfter);
        const isSelected = selectedSpike?.index === s.index;
        return (
          <g key={i} onClick={() => onSpikeClick(s)} style={{ cursor: "pointer" }}>
            <rect
              x={sx - 8} y={pad.t} width={16} height={h}
              fill={isSelected ? C.accent : C.faint}
              opacity={isSelected ? 0.15 : 0}
            />
            <circle
              cx={sx} cy={sy} r={isSelected ? 7 : 5}
              fill={s.direction === "up" ? C.accent : C.info}
              stroke={isSelected ? C.dark : "none"}
              strokeWidth={isSelected ? 2 : 0}
              opacity={0.9}
            />
            <text
              x={sx} y={sy - 12}
              textAnchor="middle" fontSize={10}
              fontFamily="'JetBrains Mono', monospace"
              fontWeight={700}
              fill={s.direction === "up" ? C.accent : C.info}
            >
              {s.direction === "up" ? "+" : ""}{(s.magnitude * 100).toFixed(1)}%
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

// ─── Progress Steps ──────────────────────────────────────────────────
function BACEProgress({ step }: { step: number }) {
  const steps = [
    "Building context…",
    "Statistical validation…",
    "Extracting ontology…",
    "Gathering news evidence…",
    "Fetching domain data…",
    "Spawning agents…",
    "Agents proposing hypotheses…",
    "Synthesizing…",
  ];
  return (
    <div style={{ padding: "32px 0" }}>
      {steps.map((label, i) => {
        const done = i < step;
        const active = i === step;
        return (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: "6px 0",
              opacity: done ? 1 : active ? 1 : 0.3,
              transition: "opacity 0.4s",
            }}
          >
            <span
              style={{
                width: 20, height: 20, borderRadius: "50%",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 11, fontWeight: 700,
                fontFamily: "'JetBrains Mono', monospace",
                background: done ? C.yes : active ? C.accent : C.border,
                color: done || active ? "#fff" : C.muted,
                transition: "background 0.3s",
              }}
            >
              {done ? "✓" : i + 1}
            </span>
            <span style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 13,
              color: active ? C.dark : done ? C.muted : C.border,
              fontWeight: active ? 600 : 400,
            }}>
              {label}
            </span>
            {active && (
              <span style={{
                width: 6, height: 6, borderRadius: "50%",
                background: C.accent,
                animation: "pulse 1s infinite",
              }} />
            )}
          </div>
        );
      })}
      <style>{`@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }`}</style>
    </div>
  );
}

// ─── Result Panel ────────────────────────────────────────────────────
function ResultPanel({ attr, spike }: { attr: Attribution; spike: Spike }) {
  const [expanded, setExpanded] = useState<number | null>(null);
  return (
    <div style={{ padding: "24px 0" }}>
      <div style={{
        background: C.surface, border: `1px solid ${C.border}`,
        borderRadius: 8, padding: "20px 24px", marginBottom: 20,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <ConfBadge level={attr.confidence} />
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: C.muted }}>
            Depth {attr.depth} · {attr.agentsSpawned} agents · {attr.elapsed.toFixed(1)}s
          </span>
        </div>
        <div style={{
          fontFamily: "'Newsreader', 'Source Serif 4', Georgia, serif",
          fontSize: 20, fontWeight: 600, lineHeight: 1.4, color: C.dark,
          marginBottom: 8,
        }}>
          {attr.mostLikelyCause}
        </div>
        <div style={{ fontSize: 13, color: "#5a5850", lineHeight: 1.6 }}>
          {attr.chain}
        </div>
      </div>

      <div style={{
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11, fontWeight: 600, textTransform: "uppercase" as const,
        letterSpacing: 1, color: C.muted, marginBottom: 12,
      }}>
        All Agent Hypotheses ({attr.hypotheses.length})
      </div>

      {attr.hypotheses.map((h, i) => {
        const isTop = i === 0;
        const isOpen = expanded === i;
        return (
          <div
            key={i}
            onClick={() => setExpanded(isOpen ? null : i)}
            style={{
              background: isTop ? "#f8f5f0" : C.surface,
              border: `1px solid ${isTop ? C.accent + "40" : C.border}`,
              borderRadius: 6, padding: "14px 18px",
              marginBottom: 8, cursor: "pointer",
              transition: "border-color 0.2s",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{
                width: 40, height: 6, borderRadius: 3,
                background: C.border, overflow: "hidden", flexShrink: 0,
              }}>
                <div style={{
                  width: `${h.confidence * 100}%`, height: "100%", borderRadius: 3,
                  background: h.confidence >= 0.7 ? C.yes : h.confidence >= 0.4 ? C.accent : C.muted,
                }} />
              </div>
              <span style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11, color: C.muted, width: 36, flexShrink: 0,
              }}>
                {(h.confidence * 100).toFixed(0)}%
              </span>
              <span style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11, fontWeight: 600, color: C.info,
                width: 140, flexShrink: 0,
              }}>
                {h.agent}
              </span>
              <span style={{
                fontSize: 13, color: C.dark, flex: 1,
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const,
              }}>
                {h.cause}
              </span>
              <span style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 10, color: C.muted, flexShrink: 0,
              }}>
                {h.impactSpeed}
              </span>
            </div>

            {isOpen && (
              <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${C.border}` }}>
                <div style={{ fontSize: 13, color: "#5a5850", lineHeight: 1.6, marginBottom: 8 }}>
                  {h.chain}
                </div>
                <div style={{ display: "flex", gap: 16, flexWrap: "wrap" as const }}>
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: C.muted }}>
                    Speed: <strong style={{ color: C.dark }}>{h.impactSpeed}</strong>
                  </span>
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: C.muted }}>
                    Peak impact: <strong style={{ color: C.dark }}>{h.timeToPeak}</strong>
                  </span>
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: C.muted }}>
                    Evidence: <strong style={{ color: C.dark }}>{h.evidence.length} sources</strong>
                  </span>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Main App ────────────────────────────────────────────────────────
export default function Pythia() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [input, setInput] = useState("");
  const [marketTitle, setMarketTitle] = useState("");
  const [prices, setPrices] = useState<PricePoint[]>([]);
  const [spikes, setSpikes] = useState<Spike[]>([]);
  const [selectedSpike, setSelectedSpike] = useState<Spike | null>(null);
  const [baceStep, setBaceStep] = useState(0);
  const [attribution, setAttribution] = useState<Attribution | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadMarket = useCallback(() => {
    if (!input.trim()) return;
    setPhase("loading-market");
    setSelectedSpike(null);
    setAttribution(null);

    let title = input.trim();
    if (title.includes("polymarket.com")) {
      const parts = title.split("/").pop()?.replace(/-/g, " ") || "Market";
      title = parts.charAt(0).toUpperCase() + parts.slice(1);
    }
    setMarketTitle(title);

    setTimeout(() => {
      const p = generateMockPrices(title);
      setPrices(p);
      setSpikes(detectSpikes(p));
      setPhase("chart");
    }, 800);
  }, [input]);

  const runBACE = useCallback((spike: Spike) => {
    setSelectedSpike(spike);
    setPhase("running-bace");
    setBaceStep(0);
    setAttribution(null);

    let step = 0;
    timerRef.current = setInterval(() => {
      step++;
      if (step >= 8) {
        clearInterval(timerRef.current!);
        const result = generateMockAttribution(spike);
        setAttribution(result);
        setPhase("result");
      } else {
        setBaceStep(step);
      }
    }, 600 + Math.random() * 400);
  }, []);

  useEffect(() => {
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  return (
    <div style={{
      minHeight: "100vh", background: C.bg,
      fontFamily: "'Source Serif 4', Georgia, serif", color: C.dark,
    }}>
      {/* Header */}
      <div style={{
        padding: "24px 40px",
        borderBottom: `1px solid ${C.border}`,
        display: "flex", alignItems: "baseline", gap: 16,
      }}>
        <span style={{
          fontSize: 22, fontWeight: 700, letterSpacing: -0.5,
          fontFamily: "'Newsreader', 'Source Serif 4', Georgia, serif",
        }}>
          Pythia
        </span>
        <span style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11, color: C.muted, letterSpacing: 0.5,
        }}>
          BACKWARD ATTRIBUTION CAUSAL ENGINE
        </span>
      </div>

      {/* Content */}
      <div style={{ maxWidth: 900, margin: "0 auto", padding: "40px 24px" }}>

        {/* Input bar */}
        <div style={{ marginBottom: 32 }}>
          <div style={{
            fontSize: 15, color: C.muted, marginBottom: 12,
            fontFamily: "'JetBrains Mono', monospace",
          }}>
            Paste a Polymarket or Kalshi URL, or type a market name
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && loadMarket()}
              placeholder="https://polymarket.com/event/will-trump-win-2024"
              style={{
                flex: 1, padding: "12px 16px",
                border: `1px solid ${C.border}`, borderRadius: 6,
                fontSize: 15, fontFamily: "'Source Serif 4', Georgia, serif",
                background: C.surface, color: C.dark,
                outline: "none",
              }}
            />
            <button
              onClick={loadMarket}
              disabled={!input.trim() || phase === "loading-market"}
              style={{
                padding: "12px 28px", borderRadius: 6,
                border: "none", background: C.dark, color: C.bg,
                fontSize: 14, fontWeight: 600, cursor: "pointer",
                fontFamily: "'JetBrains Mono', monospace",
                opacity: !input.trim() ? 0.4 : 1,
              }}
            >
              {phase === "loading-market" ? "Loading…" : "Analyze"}
            </button>
          </div>
        </div>

        {/* Loading state */}
        {phase === "loading-market" && (
          <div style={{ textAlign: "center" as const, padding: 60, color: C.muted }}>
            <div style={{
              width: 24, height: 24, border: `2px solid ${C.border}`,
              borderTopColor: C.accent, borderRadius: "50%",
              animation: "spin 0.8s linear infinite",
              margin: "0 auto 16px",
            }} />
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
            Fetching market data…
          </div>
        )}

        {/* Chart + results */}
        {(phase === "chart" || phase === "running-bace" || phase === "result") && (
          <div>
            <div style={{
              fontFamily: "'Newsreader', 'Source Serif 4', Georgia, serif",
              fontSize: 24, fontWeight: 700, marginBottom: 4,
            }}>
              {marketTitle}
            </div>
            <div style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11, color: C.muted, marginBottom: 20,
            }}>
              {prices.length} hours · {spikes.length} spikes detected · Click a spike to attribute
            </div>

            <div style={{
              background: C.surface, border: `1px solid ${C.border}`,
              borderRadius: 8, padding: "16px 12px", marginBottom: 24,
              overflowX: "auto" as const,
            }}>
              <MiniChart
                prices={prices}
                spikes={spikes}
                selectedSpike={selectedSpike}
                onSpikeClick={runBACE}
              />
            </div>

            {selectedSpike && phase === "running-bace" && (
              <div style={{
                background: C.surface, border: `1px solid ${C.border}`,
                borderRadius: 8, padding: "20px 24px",
              }}>
                <div style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 11, fontWeight: 600, textTransform: "uppercase" as const,
                  letterSpacing: 1, color: C.muted, marginBottom: 8,
                }}>
                  Running BACE depth 2 on spike
                </div>
                <div style={{ fontSize: 15, marginBottom: 4 }}>
                  <span style={{
                    color: selectedSpike.direction === "up" ? C.accent : C.info,
                    fontWeight: 700,
                  }}>
                    {selectedSpike.direction === "up" ? "+" : ""}
                    {(selectedSpike.magnitude * 100).toFixed(1)}%
                  </span>
                  {" "}at {new Date(selectedSpike.timestamp).toLocaleString("en-US", {
                    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
                  })}
                </div>
                <BACEProgress step={baceStep} />
              </div>
            )}

            {phase === "result" && attribution && selectedSpike && (
              <ResultPanel attr={attribution} spike={selectedSpike} />
            )}
          </div>
        )}

        {/* Empty state */}
        {phase === "idle" && (
          <div style={{
            textAlign: "center" as const, padding: "80px 0",
            color: C.muted,
          }}>
            <div style={{ fontSize: 48, marginBottom: 16, opacity: 0.3 }}>
              ⚡
            </div>
            <div style={{
              fontFamily: "'Newsreader', 'Source Serif 4', Georgia, serif",
              fontSize: 20, fontWeight: 600, color: C.dark, marginBottom: 8,
            }}>
              Why did this spike happen?
            </div>
            <div style={{ fontSize: 14, maxWidth: 400, margin: "0 auto", lineHeight: 1.6 }}>
              Paste a prediction market URL above. Pythia will show you the price history,
              detect spikes, and tell you what caused each one — with confidence levels
              and evidence from 9 specialized agents.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
