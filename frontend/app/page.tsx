'use client';

import { useState, useCallback, useRef, useEffect } from "react";
import BACEGraphAnimation from "@/components/BACEGraphAnimation";
import type { BACEState, BACEGraphState, OntologyEntity, OntologyRelationship, AgentInfo, ProposalHypothesis, DivergencePair } from "@/components/BACEGraphAnimation";
import ScenarioPanel from "@/components/ScenarioPanel";
import type { Scenario, ScenarioAttribution } from "@/components/ScenarioPanel";
import InterrogationChat from "@/components/InterrogationChat";

// ─── Types ───────────────────────────────────────────────────────────
interface PricePoint { t: string; price: number; }

interface MarketResult {
  id: string; question: string; slug: string; conditionId: string;
  clobTokenIds: string[]; outcomes: string[]; outcomePrices: string[];
  volume24hr: number; volume: number; image: string;
  spikeCount?: number;
  exchange?: 'polymarket' | 'kalshi';
  kalshiTicker?: string;
  kalshiEventTicker?: string;
  kalshiSeriesTicker?: string;
}

interface Spike {
  index: number; timestamp: string; magnitude: number;
  direction: "up" | "down"; priceBefore: number; priceAfter: number;
}

interface Evidence {
  source: string; title: string; url: string | null;
  timestamp: string | null; timing: "before" | "concurrent" | "after";
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
  scenarios: Scenario[];
  governance?: { decision: string; reason: string; run_id?: string };
  rawResult?: any; // Full result for interrogation context
}

type Phase = "idle" | "searching" | "pick-market" | "loading-chart" | "chart" | "running-bace" | "result";

// ─── Constants ──────────────────────────────────────────────────────
const C = {
  bg: '#faf9f5', surface: '#FFFFFF', dark: '#141413', accent: '#d97757',
  yes: '#788c5d', muted: '#b0aea5', border: '#e8e6dc', info: '#6a9bcc',
  faint: '#f5f4ef',
};
const mono = "'JetBrains Mono', monospace";
const serif = "'Source Serif 4', Georgia, serif";

// ─── Spike detection ────────────────────────────────────────────────
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
        direction: after > before ? "up" : "down",
        priceBefore: before, priceAfter: after });
    }
  }
  // Deduplicate — keep the largest spike in each 6-point window
  const deduped: Spike[] = [];
  for (const s of spikes) {
    const nearIdx = deduped.findIndex(d => Math.abs(d.index - s.index) < 6);
    if (nearIdx === -1) deduped.push(s);
    else if (s.magnitude > deduped[nearIdx].magnitude) deduped[nearIdx] = s;
  }
  return deduped.sort((a, b) => b.magnitude - a.magnitude);
}

// ─── Mini chart ─────────────────────────────────────────────────────
function MiniChart({ prices, spikes, selectedSpike, onSpikeClick }: {
  prices: PricePoint[]; spikes: Spike[];
  selectedSpike: Spike | null; onSpikeClick: (s: Spike) => void;
}) {
  const width = 860, height = 200;
  const pad = { t: 20, r: 48, b: 28, l: 10 };
  if (prices.length < 2) return null;
  const allP = prices.map(p => p.price);
  const pMin = Math.min(...allP), pMax = Math.max(...allP);
  const pRange = pMax - pMin || 0.01;
  const sx = (i: number) => pad.l + (i / (prices.length - 1)) * (width - pad.l - pad.r);
  const sy = (v: number) => pad.t + (height - pad.t - pad.b) - ((v - pMin) / pRange) * (height - pad.t - pad.b);

  const path = prices.map((p, i) => `${i === 0 ? 'M' : 'L'}${sx(i).toFixed(1)},${sy(p.price).toFixed(1)}`).join(' ');
  const area = path + ` L${sx(prices.length - 1).toFixed(1)},${height - pad.b} L${pad.l},${height - pad.b} Z`;

  const yTicks = Array.from({ length: 5 }, (_, i) => pMin + (pRange * i) / 4);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display: 'block' }}>
      {yTicks.map((v, i) => (
        <g key={i}>
          <line x1={pad.l} y1={sy(v)} x2={width - pad.r} y2={sy(v)} stroke={C.border} strokeWidth={0.5} />
          <text x={width - pad.r + 6} y={sy(v) + 3} fontSize={10} fontFamily={mono} fill={C.muted}>
            {(v * 100).toFixed(0)}¢
          </text>
        </g>
      ))}
      <path d={area} fill={C.accent + '0a'} />
      <path d={path} fill="none" stroke={C.dark} strokeWidth={1.5} />
      {spikes.map((s, i) => {
        const si = s.index, sp = prices[si];
        if (!sp) return null;
        const sxv = sx(si), syv = sy(sp.price);
        const isSel = selectedSpike?.index === si;
        return (
          <g key={i} onClick={() => onSpikeClick(s)} style={{ cursor: 'pointer' }}>
            <circle cx={sxv} cy={syv} r={isSel ? 16 : 12}
              fill={isSel ? C.accent : "transparent"} opacity={isSel ? 0.12 : 0} />
            <circle cx={sxv} cy={syv} r={isSel ? 7 : 5}
              fill={s.direction === "up" ? C.accent : C.info}
              stroke={isSel ? C.dark : "none"} strokeWidth={isSel ? 2 : 0} opacity={0.9} />
            <text x={sxv} y={syv - 12} textAnchor="middle" fontSize={10} fontFamily={mono} fontWeight={700}
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

// ─── Mock generators (fallback when backend unavailable) ────────────

function generateMockAttribution(spike: Spike, question: string): Attribution {
  const hyps: Hypothesis[] = [
    {
      agent: "Macro Policy Analyst", agentRole: "Analyzes monetary policy and macro indicators",
      cause: `FOMC-related sentiment shift detected concurrent with the ${(spike.magnitude*100).toFixed(1)}% spike. Market is repricing rate expectations.`,
      reasoning: `The spike timing aligns with a period of elevated macro uncertainty. FOMC minutes or Fed speaker commentary likely triggered institutional repositioning.`,
      confidence: 0.72, confidenceFactors: "Strong temporal alignment with macro calendar",
      impactSpeed: "fast", impactSpeedExplain: "Rate markets reprice within hours of new information",
      timeToPeak: "2-6 hours", timeToPeakExplain: "Institutional flow typically completes within a trading session",
      evidence: [{ source: "News", title: "Federal Reserve policy analysis", url: null, timestamp: null, timing: "concurrent" }],
      counterfactual: "If this were just noise, reversion would occur within 4 hours. Monitor for sustained directional flow.",
    },
    {
      agent: "Informed Flow Analyst", agentRole: "Detects whale activity and large orders",
      cause: `Large directional order detected — potentially informed flow front-running an expected announcement.`,
      reasoning: "Volume surge pattern consistent with institutional accumulation. Order size suggests sophisticated actor.",
      confidence: 0.58, confidenceFactors: "Moderate — volume is suggestive but not conclusive",
      impactSpeed: "immediate", impactSpeedExplain: "Large orders create immediate price impact",
      timeToPeak: "1-2 hours", timeToPeakExplain: "Whale accumulation typically front-runs news by hours",
      evidence: [{ source: "On-chain", title: "Large order flow analysis", url: null, timestamp: null, timing: "concurrent" }],
      counterfactual: "Check whether large orders appeared across correlated markets simultaneously.",
    },
    {
      agent: "Devil's Advocate", agentRole: "Challenges all hypotheses with alternative explanations",
      cause: `The spike may be a technical artifact — thin orderbook + a single large market order creating outsized price impact.`,
      reasoning: "Prediction markets have limited liquidity. A single $50K order can move prices significantly without any informational content.",
      confidence: 0.25, confidenceFactors: "Low confidence this is 'just noise' — magnitude exceeds 2σ from normal",
      impactSpeed: "immediate", impactSpeedExplain: "Liquidity-driven spikes are instantaneous",
      timeToPeak: "N/A", timeToPeakExplain: "If liquidity-driven, expect partial reversion within hours",
      evidence: [{ source: "Statistical", title: "Volatility analysis", url: null, timestamp: null, timing: "concurrent" }],
      counterfactual: "If purely liquidity-driven, the price should partially revert within 2-4 hours.",
    },
  ];

  const scenarios: Scenario[] = [
    {
      id: 'scenario-macro_policy', label: 'Macro / policy-driven (FOMC sentiment)', mechanism: 'macro_policy',
      tier: 'primary', confidence: 0.72, lead_agent: 'Macro Policy Analyst',
      supporting_agents: ['Macro Policy Analyst', 'Cross-Market Analyst'],
      challenging_agents: ["Devil's Advocate"],
      evidence_chain: ['Federal Reserve policy analysis', 'Institutional order flow concurrent with macro calendar'],
      evidence_urls: [], what_breaks_this: 'If the spike fully reverts within 4 hours, the macro thesis weakens significantly.',
      causal_chain: 'FOMC-related commentary or minutes release triggered institutional repositioning, causing sustained directional flow in prediction markets.',
      temporal_fit: 'Strong — timing aligns with macro event calendar', impact_speed: 'fast', time_to_peak: '2-6 hours',
    },
    {
      id: 'scenario-informed_flow', label: 'Informed flow / whale activity', mechanism: 'informed_flow',
      tier: 'primary', confidence: 0.58, lead_agent: 'Informed Flow Analyst',
      supporting_agents: ['Informed Flow Analyst'], challenging_agents: ['Null Hypothesis'],
      evidence_chain: ['Large directional order detected', 'Volume surge above 3x baseline'],
      evidence_urls: [], what_breaks_this: 'If no correlated activity in adjacent markets, likely just a single large order.',
      causal_chain: 'A sophisticated actor placed a large directional bet, likely with non-public information or a strong analytical edge.',
      temporal_fit: 'Moderate — volume precedes price move', impact_speed: 'immediate', time_to_peak: '1-2 hours',
    },
    {
      id: 'scenario-technical', label: 'Market microstructure (thin orderbook)', mechanism: 'technical',
      tier: 'dismissed', confidence: 0.25, lead_agent: "Devil's Advocate",
      supporting_agents: [], challenging_agents: ['Macro Policy Analyst', 'Informed Flow Analyst'],
      evidence_chain: ['Spike magnitude exceeds 2σ from normal volatility'],
      evidence_urls: [], what_breaks_this: 'Already weakened — statistical tests reject noise hypothesis at p<0.05.',
      causal_chain: 'A single large market order on a thin orderbook created outsized price impact without informational content.',
      temporal_fit: 'Weak — no reversion observed', impact_speed: 'immediate', time_to_peak: 'N/A',
    },
  ];

  return {
    depth: 2, agentsSpawned: 9, hypothesesProposed: hyps.length, debateRounds: 0,
    elapsed: 8.3 + Math.random() * 12, hypotheses: hyps, scenarios,
  };
}

function generateBACEStates(spike: Spike, question: string): BACEState[] {
  const q = question.slice(0, 30);
  const words = question.replace(/[?.,!]/g, "").split(/\s+/);
  const stopwords = new Set(["will", "the", "a", "an", "by", "in", "of", "to", "be", "is", "are", "was", "or", "and", "if", "its", "this", "that", "for", "on", "at", "with", "from", "before", "after", "not", "no", "yes"]);
  const entities = words.filter(w => w.length > 2 && !stopwords.has(w.toLowerCase())).filter((w, i, arr) => arr.indexOf(w) === i).slice(0, 5);

  return [
    { step: 0, entities: [], agentsActive: [], debateLog: ["Classifying market domain…", `Market: "${q}…"`], counterfactualsTested: 0 },
    { step: 1, entities: [], agentsActive: [], debateLog: [`Spike: ${spike.direction === "up" ? "+" : "-"}${(spike.magnitude*100).toFixed(1)}%`, "Extracting causal ontology…"], counterfactualsTested: 0 },
    { step: 2, entities: entities.slice(0, 3), agentsActive: [], debateLog: [`Ontology: ${entities.length} entities extracted`, "Gathering news evidence…"], counterfactualsTested: 0 },
    { step: 3, entities, agentsActive: [], debateLog: ["News evidence: 24 candidates", "Spawning specialist agents…"], counterfactualsTested: 0 },
    { step: 4, entities, agentsActive: ["macro-policy", "informed-flow", "narrative-sentiment"], debateLog: ["Spawned 9 agents", "Gathering domain evidence…"], counterfactualsTested: 0 },
    { step: 5, entities, agentsActive: ["macro-policy", "informed-flow", "narrative-sentiment", "cross-market", "devils-advocate"], debateLog: ["Domain evidence: 37 items", "Agents proposing hypotheses…"], counterfactualsTested: 0 },
    { step: 6, entities, agentsActive: ["macro-policy", "informed-flow", "narrative-sentiment", "cross-market", "geopolitical", "devils-advocate", "null-hypothesis"], debateLog: ["⟫ Macro Policy Analyst", `  "FOMC sentiment shift…" — 72%`, "⟫ Informed Flow Analyst", `  "Whale activity detected…" — 58%`, "Cross-examining hypotheses…"], counterfactualsTested: 0 },
    { step: 7, entities, agentsActive: ["macro-policy", "informed-flow", "narrative-sentiment", "cross-market", "geopolitical", "devils-advocate", "null-hypothesis"], debateLog: ["Interaction: 3 support, 2 challenges", "Clustering into scenarios…", "Scenarios: 2 primary, 1 dismissed"], counterfactualsTested: 3 },
  ];
}

// ─── Main App ───────────────────────────────────────────────────────
export default function PythiaApp() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [searchResults, setSearchResults] = useState<MarketResult[]>([]);
  const [selectedMarket, setSelectedMarket] = useState<MarketResult | null>(null);
  const [prices, setPrices] = useState<PricePoint[]>([]);
  const [spikes, setSpikes] = useState<Spike[]>([]);
  const [selectedSpike, setSelectedSpike] = useState<Spike | null>(null);
  const [attribution, setAttribution] = useState<Attribution | null>(null);
  const [isLive, setIsLive] = useState(false);

  // BACE animation state
  const [baceState, setBaceState] = useState<BACEState>({ step: 0, entities: [], agentsActive: [], debateLog: [], counterfactualsTested: 0 });
  const [graphState, setGraphState] = useState<BACEGraphState>({
    ontologyEntities: [], ontologyRelationships: [],
    agents: [], proposals: new Map(), convergenceGroups: new Map(),
    divergencePairs: [], graphStats: null, scenarioSummary: null, step: 0,
  });

  // Interrogation state
  const [interrogationQuestion, setInterrogationQuestion] = useState<string | undefined>(undefined);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const extractSlug = (url: string): string | null => {
    const m = url.match(/polymarket\.com\/(?:event|market)\/([a-z0-9-]+)/i);
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
      const res = await fetch(`/api/markets/search?${params}`);
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
      let res: Response;
      if (market.exchange === 'kalshi') {
        if (!market.kalshiTicker || !market.kalshiSeriesTicker) {
          setError("Missing Kalshi ticker info"); setPhase("idle"); return;
        }
        res = await fetch(`/api/markets/history?exchange=kalshi&ticker=${encodeURIComponent(market.kalshiTicker)}&series_ticker=${encodeURIComponent(market.kalshiSeriesTicker)}&interval=max&fidelity=60`);
      } else {
        const tokenId = market.clobTokenIds?.[0];
        if (!tokenId) { setError("No CLOB token ID for this market"); setPhase("idle"); return; }
        res = await fetch(`/api/markets/history?exchange=polymarket&tokenId=${encodeURIComponent(tokenId)}&interval=max&fidelity=60`);
      }

      const data = await res.json();
      if (!data.history?.length) {
        setError("No price history available for this market.");
        setPhase("idle"); return;
      }

      setPrices(data.history);
      const allPrices = data.history.map((p: PricePoint) => p.price);
      const priceRange = Math.max(...allPrices) - Math.min(...allPrices);
      const medianPrice = allPrices.sort((a: number, b: number) => a - b)[Math.floor(allPrices.length / 2)] || 0.5;
      const absThreshold = priceRange * 0.15;
      const relThreshold = medianPrice * 0.10;
      const threshold = Math.max(0.005, Math.min(absThreshold, relThreshold));
      setSpikes(detectSpikes(data.history, threshold));
      setPhase("chart");
    } catch (err: any) {
      setError(`Failed to load price history: ${err.message}`);
      setPhase("idle");
    }
  }, []);

  // ─── Run BACE — handles SSE streaming with new event types ────────

  const runBACE = useCallback(async (spike: Spike) => {
    setSelectedSpike(spike);
    setPhase("running-bace");
    setAttribution(null);
    setIsLive(false);
    setInterrogationQuestion(undefined);

    const question = selectedMarket?.question || "";

    // Reset states
    setBaceState({ step: 0, entities: [], agentsActive: [], debateLog: [`Market: "${question.slice(0, 40)}…"`, "Connecting to BACE engine…"], counterfactualsTested: 0 });
    setGraphState({
      ontologyEntities: [], ontologyRelationships: [],
      agents: [], proposals: new Map(), convergenceGroups: new Map(),
      divergencePairs: [], graphStats: null, scenarioSummary: null, step: 0,
    });

    const backendUrl = process.env.NEXT_PUBLIC_PYTHIA_API_URL || "http://localhost:8000";

    // Try SSE streaming
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

      // Accumulate graph state incrementally
      let ontologyEntities: OntologyEntity[] = [];
      let ontologyRelationships: OntologyRelationship[] = [];
      let agents: AgentInfo[] = [];
      const proposals = new Map<string, ProposalHypothesis[]>();
      let convergenceGroups = new Map<string, string[]>();
      let divergencePairs: DivergencePair[] = [];
      let graphStats: { entities: number; relationships: number; facts: number } | null = null;
      let scenarioSummary: { total: number; primary: number; alternative: number; dismissed: number } | null = null;
      let liveScenarios: Scenario[] = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        while (buffer.includes("\n\n")) {
          const idx = buffer.indexOf("\n\n");
          const block = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);

          let eventType = "";
          let eventDataParts: string[] = [];
          for (const line of block.split("\n")) {
            if (line.startsWith("event: ")) eventType = line.slice(7).trim();
            else if (line.startsWith("data: ")) eventDataParts.push(line.slice(6));
            else if (line.startsWith("data:")) eventDataParts.push(line.slice(5));
          }

          const eventData = eventDataParts.join("\n");
          if (!eventData) continue;

          let data: any;
          try {
            data = JSON.parse(eventData);
          } catch {
            if (eventType === "error") throw new Error(eventData);
            continue;
          }

          // ─── Handle each SSE event type ───────────────────────

          if (eventType === "context") {
            currentStep = 0;
            liveLog.push(`Category: ${data.category || "general"}`);
            if (data.entities) {
              for (const e of data.entities) {
                if (!liveEntities.includes(e)) liveEntities.push(e);
              }
            }
          } else if (eventType === "ontology") {
            currentStep = 1;
            liveLog.push(`Ontology: ${data.entity_count} entities, ${data.relationship_count} relationships`);
            // Parse entities from the ontology event
            if (data.entities) {
              for (const name of data.entities) {
                if (!liveEntities.includes(name)) liveEntities.push(name);
              }
              // Build OntologyEntity objects (type info comes from backend ontology)
              ontologyEntities = data.entities.map((name: string, i: number) => ({
                name,
                type: 'Unknown', // Backend only sends names in SSE; we estimate
                relevance: 1 - (i * 0.08), // Decreasing relevance by order
              }));
            }
            // If backend sends full entity/relationship details
            if (data.full_entities) {
              ontologyEntities = data.full_entities.map((e: any) => ({
                name: e.name, type: e.entity_type || e.type || 'Unknown',
                relevance: e.relevance_score || e.relevance || 0.5,
              }));
            }
            if (data.full_relationships) {
              ontologyRelationships = data.full_relationships.map((r: any) => ({
                source: r.source_id || r.source || '',
                target: r.target_id || r.target || '',
                type: r.relationship_type || r.type || 'related',
                strength: r.strength || 0.5,
              }));
            }
            liveLog.push(`Generated ${data.search_queries || 0} search queries`);
          } else if (eventType === "evidence") {
            currentStep = 2;
            liveLog.push(`News evidence: ${data.count} candidates`);
          } else if (eventType === "agents") {
            currentStep = 3;
            agents = (data.agents || []).map((a: any) => ({
              id: a.id, name: a.name, tier: a.tier || 1, domain: a.domain || '',
            }));
            for (const a of agents) {
              if (!liveAgents.includes(a.id)) liveAgents.push(a.id);
            }
            liveLog.push(`Spawned ${data.count || agents.length} agents`);
          } else if (eventType === "domain_evidence") {
            currentStep = 4;
            liveLog.push(`Domain evidence: ${data.count} items`);
          } else if (eventType === "proposal") {
            currentStep = 5;
            const agentName = agents.find(a => a.id === data.agent)?.name || data.agent || "Agent";
            const hyps = data.hypotheses || [];
            proposals.set(data.agent, hyps.map((h: any) => ({
              cause: h.cause || '',
              confidence: h.confidence || 0,
            })));
            for (const h of hyps) {
              liveLog.push(`⟫ ${agentName}`);
              liveLog.push(`  "${(h.cause || "").slice(0, 90)}…" — ${Math.round((h.confidence || 0) * 100)}%`);
            }

          // ─── NEW: interaction event ────────────────────────
          } else if (eventType === "interaction") {
            currentStep = 6;
            const stances = data.stances || {};
            liveLog.push(`Interaction: ${stances.support || 0} support, ${stances.challenge || 0} challenges, ${stances.neutral || 0} neutral`);
            if (data.convergence_groups) {
              liveLog.push(`Convergence: ${data.convergence_groups} groups identified`);
            }
            if (data.divergence_pairs) {
              liveLog.push(`Divergence: ${data.divergence_pairs} conflict pairs`);
            }

            // Parse convergence groups
            if (data.convergence_group_details) {
              convergenceGroups = new Map(Object.entries(data.convergence_group_details));
            }

            // Parse divergence pairs from top challenges
            if (data.top_challenges) {
              divergencePairs = data.top_challenges.map((tc: any) => ({
                hypothesis_id: tc.target || '',
                proposed_by: tc.target?.split('-h')[0] || '',
                challenged_by: tc.challenger?.replace(/\s+/g, '-').toLowerCase() || '',
              }));
            }

          // ─── NEW: scenarios event ──────────────────────────
          } else if (eventType === "scenarios") {
            currentStep = 7;
            const primaryCount = (data.primary || []).length;
            const altCount = (data.alternative || []).length;
            const dismissedCount = (data.dismissed || []).length;
            scenarioSummary = { total: data.total || 0, primary: primaryCount, alternative: altCount, dismissed: dismissedCount };
            liveLog.push(`Scenarios: ${primaryCount} primary, ${altCount} alternative, ${dismissedCount} dismissed`);

            // Build scenario objects from SSE data
            liveScenarios = [
              ...(data.primary || []).map((s: any) => ({ ...s, tier: 'primary' } as Scenario)),
              ...(data.alternative || []).map((s: any) => ({ ...s, tier: 'alternative' } as Scenario)),
              ...(data.dismissed || []).map((s: any) => ({ ...s, tier: 'dismissed' } as Scenario)),
            ];

          // ─── NEW: graph_update event ───────────────────────
          } else if (eventType === "graph_update") {
            graphStats = {
              entities: data.entities || 0,
              relationships: data.relationships || 0,
              facts: data.facts || 0,
            };
            liveLog.push(`Graph memory: ${data.entities} entities, ${data.relationships} rels, ${data.facts} facts`);

          } else if (eventType === "debate") {
            currentStep = 6;
            liveLog.push(`Debate round ${data.round}: ${data.surviving} surviving`);
          } else if (eventType === "counterfactual") {
            currentStep = 7;
            liveLog.push(`Counterfactual testing: ${data.tested} hypotheses tested`);
          } else if (eventType === "result") {
            finalResult = data;
            console.log("[Pythia] Got result event, hypotheses:", data.hypotheses?.length || 0, "scenarios:", data.scenarios?.length || 0);
          } else if (eventType === "done") {
            console.log("[Pythia] SSE done");
          } else if (eventType === "error") {
            throw new Error(data.error || "Backend error");
          }

          // Update animation states
          if (eventType !== "result" && eventType !== "done") {
            setBaceState({
              step: currentStep,
              entities: [...liveEntities],
              agentsActive: [...liveAgents],
              debateLog: liveLog.slice(-14),
              counterfactualsTested: currentStep >= 7 ? 1 : 0,
            });

            setGraphState({
              ontologyEntities: [...ontologyEntities],
              ontologyRelationships: [...ontologyRelationships],
              agents: [...agents],
              proposals: new Map(proposals),
              convergenceGroups: new Map(convergenceGroups),
              divergencePairs: [...divergencePairs],
              graphStats,
              scenarioSummary,
              step: currentStep,
            });
          }
        }
      }

      // Flush remaining buffer
      if (buffer.trim()) {
        try {
          let eventType = "";
          let eventDataParts: string[] = [];
          for (const line of buffer.split("\n")) {
            if (line.startsWith("event: ")) eventType = line.slice(7).trim();
            else if (line.startsWith("data: ")) eventDataParts.push(line.slice(6));
            else if (line.startsWith("data:")) eventDataParts.push(line.slice(5));
          }
          const eventData = eventDataParts.join("\n");
          if (eventType === "result" && eventData) {
            finalResult = JSON.parse(eventData);
          }
        } catch { /* ignore */ }
      }

      // Process final result
      if (finalResult) {
        const rawHyps = finalResult.hypotheses || finalResult.agent_hypotheses || [];
        const hyps: Hypothesis[] = rawHyps.map((h: any) => ({
          agent: h.agent || h.agent_name || "Unknown",
          agentRole: h.agentRole || "",
          cause: h.cause || h.hypothesis || "",
          reasoning: h.reasoning || h.causal_chain || "",
          confidence: typeof h.confidence === "number" ? h.confidence : (typeof h.confidence_score === "number" ? h.confidence_score : 0.5),
          confidenceFactors: h.confidenceFactors || h.temporal_plausibility || "",
          impactSpeed: h.impact_speed || h.impactSpeed || "",
          impactSpeedExplain: h.impactSpeedExplain || h.magnitude_plausibility || "",
          timeToPeak: h.time_to_peak || h.timeToPeak || "",
          timeToPeakExplain: h.timeToPeakExplain || h.temporal_plausibility || "",
          evidence: (h.evidence || []).map((e: any) => ({
            source: e.source || "", title: e.title || e.headline || (typeof e === "string" ? e : ""),
            url: e.url || null, timestamp: e.timestamp || null, timing: e.timing || "concurrent",
          })),
          counterfactual: h.counterfactual || "",
        }));

        // Parse scenarios from final result (full detail) or from SSE
        let scenarios: Scenario[] = [];
        if (finalResult.scenarios?.length) {
          scenarios = finalResult.scenarios.map((s: any) => ({
            id: s.id || `scenario-${s.mechanism}`,
            label: s.label || '',
            mechanism: s.mechanism || 'other',
            tier: s.tier || 'primary',
            confidence: s.confidence || 0,
            lead_agent: s.lead_agent || '',
            supporting_agents: s.supporting_agents || [],
            challenging_agents: s.challenging_agents || [],
            evidence_chain: s.evidence_chain || [],
            evidence_urls: s.evidence_urls || [],
            what_breaks_this: s.what_breaks_this || '',
            causal_chain: s.causal_chain || '',
            temporal_fit: s.temporal_fit || '',
            impact_speed: s.impact_speed || '',
            time_to_peak: s.time_to_peak || '',
          }));
        } else if (liveScenarios.length) {
          scenarios = liveScenarios;
        }

        if (hyps.length > 0) {
          const md = finalResult.bace_metadata || {};
          const gov = finalResult.governance;
          setAttribution({
            depth: md.depth || 2,
            agentsSpawned: md.agents_spawned || hyps.length,
            hypothesesProposed: md.hypotheses_proposed || hyps.length,
            debateRounds: md.debate_rounds || 0,
            elapsed: md.elapsed_seconds || 0,
            hypotheses: hyps,
            scenarios,
            governance: gov ? { decision: gov.decision, reason: gov.reason, run_id: gov.run_id } : undefined,
            rawResult: finalResult,
          });
          setIsLive(true);
          setPhase("result");
          return;
        }
      }
      console.log("[Pythia] SSE completed without usable result");
    } catch (sseErr) {
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

  // ─── Render ───────────────────────────────────────────────────────

  return (
    <div style={{ minHeight: "100vh", background: C.bg, fontFamily: "'Source Serif 4', Georgia, serif", color: C.dark }}>
      <div style={{ padding: "24px 40px", borderBottom: `1px solid ${C.border}`, display: "flex", alignItems: "baseline", gap: 16 }}>
        <span style={{ fontSize: 22, fontWeight: 700, letterSpacing: -0.5, fontFamily: serif }}>Pythia</span>
        <span style={{ fontFamily: mono, fontSize: 11, color: C.muted, letterSpacing: 0.5 }}>BACKWARD ATTRIBUTION CAUSAL ENGINE</span>
      </div>

      <div style={{ maxWidth: 900, margin: "0 auto", padding: "40px 24px" }}>
        {/* Input */}
        <div style={{ marginBottom: 32 }}>
          <div style={{ fontSize: 13, color: C.muted, marginBottom: 12, fontFamily: mono }}>
            Search Polymarket + Kalshi by keyword or paste a URL
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <input type="text" value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAnalyze()}
              placeholder="iran hormuz, trump tariff, bitcoin ETF, fed rate — searches Polymarket + Kalshi"
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
            Searching Polymarket + Kalshi…
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
                  border: `1px solid ${C.border}`, borderRadius: 6, padding: "14px 18px", marginBottom: 8,
                  cursor: "pointer", transition: "border-color 0.2s", opacity: noSpikes ? 0.55 : 1 }}
                  onMouseEnter={(e) => (e.currentTarget.style.borderColor = C.accent)}
                  onMouseLeave={(e) => (e.currentTarget.style.borderColor = C.border)}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                    <span style={{ fontFamily: mono, fontSize: 9, fontWeight: 700,
                      padding: "1px 5px", borderRadius: 3,
                      background: m.exchange === 'kalshi' ? '#eef3ff' : '#f0f5ee',
                      color: m.exchange === 'kalshi' ? '#4a6fa5' : '#5a7a4a',
                      border: `1px solid ${m.exchange === 'kalshi' ? '#c0d0e8' : '#c8dcc0'}`,
                      flexShrink: 0, textTransform: "uppercase" as const, letterSpacing: 0.5,
                    }}>
                      {m.exchange === 'kalshi' ? 'K' : 'PM'}
                    </span>
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
            Fetching price history…
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
              {selectedMarket.exchange === 'kalshi'
                ? <span style={{ color: '#4a6fa5', marginLeft: 8 }}>● Kalshi</span>
                : <span style={{ color: C.yes, marginLeft: 8 }}>● Polymarket</span>
              }
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
                <BACEGraphAnimation baceState={baceState} graphState={graphState} />
              </div>
            )}

            {/* ─── Result Phase: Scenario Panel + Interrogation ─── */}
            {phase === "result" && attribution && (
              <>
                {attribution.scenarios.length > 0 ? (
                  <ScenarioPanel
                    attribution={{
                      depth: attribution.depth,
                      agentsSpawned: attribution.agentsSpawned,
                      hypothesesProposed: attribution.hypothesesProposed,
                      debateRounds: attribution.debateRounds,
                      elapsed: attribution.elapsed,
                      scenarios: attribution.scenarios,
                      governance: attribution.governance,
                    }}
                    isLive={isLive}
                    onAskQuestion={(q) => setInterrogationQuestion(q)}
                  />
                ) : (
                  <LegacyResultPanel attr={attribution} isLive={isLive} />
                )}
                <InterrogationChat
                  attributionContext={attribution.rawResult || attribution}
                  marketTitle={selectedMarket?.question || ''}
                  initialQuestion={interrogationQuestion}
                  onInitialQuestionConsumed={() => setInterrogationQuestion(undefined)}
                />
              </>
            )}
          </div>
        )}

        {phase === "idle" && !error && (
          <div style={{ textAlign: "center" as const, padding: "80px 0", color: C.muted }}>
            <div style={{ fontSize: 48, marginBottom: 16, opacity: 0.3 }}>⚡</div>
            <div style={{ fontFamily: serif, fontSize: 20, fontWeight: 600, color: C.dark, marginBottom: 8 }}>
              Why did this spike happen?
            </div>
            <div style={{ fontSize: 14, maxWidth: 440, margin: "0 auto", lineHeight: 1.6 }}>
              Search Polymarket or Kalshi by keyword or paste a URL. Pythia fetches real price history,
              detects spikes, and attributes their causes using multi-agent causal reasoning.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Legacy Result Panel (flat hypotheses — fallback when no scenarios) ──

function LegacyResultPanel({ attr, isLive }: { attr: Attribution; isLive: boolean }) {
  const [expanded, setExpanded] = useState<number | null>(0);

  return (
    <div style={{ padding: "24px 0" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16, flexWrap: "wrap" as const }}>
        <span style={{ fontFamily: mono, fontSize: 11, color: C.muted }}>
          Depth {attr.depth} · {attr.agentsSpawned} agents · {attr.hypothesesProposed} hypotheses · {attr.elapsed.toFixed(1)}s
        </span>
        <span style={{ fontFamily: mono, fontSize: 10, color: isLive ? C.yes : C.accent }}>
          {isLive ? "● live attribution" : "⚠ simulated — backend not connected"}
        </span>
        {isLive && attr.governance && (
          <span style={{ fontFamily: mono, fontSize: 10, padding: "2px 6px", borderRadius: 3,
            background: attr.governance.decision === "AUTO_RELAY" ? "#eef3e8" : attr.governance.decision === "FLAG_REVIEW" ? "#fdf5e6" : "#fdf0ed",
            color: attr.governance.decision === "AUTO_RELAY" ? C.yes : attr.governance.decision === "FLAG_REVIEW" ? "#b8860b" : C.accent,
          }}>
            {attr.governance.decision === "AUTO_RELAY" ? "✓ Auto-approved" :
             attr.governance.decision === "FLAG_REVIEW" ? "⚠ Flagged" : "✕ Rejected"}
          </span>
        )}
      </div>

      {attr.hypotheses.map((h, i) => {
        const isOpen = expanded === i;
        const confColor = h.confidence >= 0.7 ? C.yes : h.confidence >= 0.4 ? C.accent : C.muted;
        return (
          <div key={i} style={{
            background: C.surface, border: `1px solid ${isOpen ? confColor + "60" : C.border}`,
            borderRadius: 8, marginBottom: 10, overflow: "hidden", transition: "border-color 0.2s",
          }}>
            <div onClick={() => setExpanded(isOpen ? null : i)} style={{ padding: "16px 20px", cursor: "pointer" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
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
              <div style={{ fontSize: 14, lineHeight: 1.5, color: C.dark }}>{h.cause}</div>
            </div>
            {isOpen && (
              <div style={{ padding: "0 20px 20px", borderTop: `1px solid ${C.border}` }}>
                <div style={{ paddingTop: 16, fontSize: 13, lineHeight: 1.7, color: C.dark }}>
                  {h.reasoning}
                </div>
                {h.evidence.length > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <div style={{ fontFamily: mono, fontSize: 10, fontWeight: 600, color: C.muted, textTransform: "uppercase" as const, letterSpacing: 0.5, marginBottom: 6 }}>Evidence</div>
                    {h.evidence.map((ev, ei) => (
                      <div key={ei} style={{ fontSize: 12, color: C.dark, marginBottom: 4, display: "flex", gap: 6 }}>
                        <span style={{ color: C.accent, fontFamily: mono, fontSize: 10 }}>{ev.timing}</span>
                        {ev.url ? <a href={ev.url} target="_blank" rel="noopener noreferrer" style={{ color: C.info, textDecoration: "none" }}>{ev.title}</a> : <span>{ev.title}</span>}
                      </div>
                    ))}
                  </div>
                )}
                {h.counterfactual && (
                  <div style={{ marginTop: 12, padding: "8px 12px", background: C.faint, borderRadius: 4, fontSize: 12, lineHeight: 1.5, color: C.dark }}>
                    <span style={{ fontFamily: mono, fontSize: 10, fontWeight: 600, color: C.muted }}>Counterfactual: </span>
                    {h.counterfactual}
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
