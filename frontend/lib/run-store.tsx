'use client';

import { createContext, useContext, useState, useCallback, useRef, ReactNode } from 'react';
import { connectRunStream } from './bace-runner';
import type { BACEGraphState, OntologyEntity, OntologyRelationship, AgentInfo, ProposalHypothesis, DivergencePair } from '@/components/BACEGraphAnimation';

// ─── Core types ─────────────────────────────────────────────────────

export interface PricePoint { t: string; price: number; }

export interface MarketResult {
  id: string; question: string; slug: string; conditionId: string;
  clobTokenIds: string[]; outcomes: string[]; outcomePrices: string[];
  volume24hr: number; volume: number; image: string;
  spikeCount?: number;
  exchange?: 'polymarket' | 'kalshi';
  kalshiTicker?: string;
  kalshiEventTicker?: string;
  kalshiSeriesTicker?: string;
}

export interface Spike {
  index: number; timestamp: string; magnitude: number;
  direction: 'up' | 'down'; priceBefore: number; priceAfter: number;
}

export interface Evidence {
  source: string; title: string; url: string | null;
  timestamp: string | null; timing: 'before' | 'concurrent' | 'after';
}

export interface Hypothesis {
  agent: string; agentRole: string; cause: string; reasoning: string;
  confidence: number; confidenceFactors: string;
  impactSpeed: string; impactSpeedExplain: string;
  timeToPeak: string; timeToPeakExplain: string;
  evidence: Evidence[];
  counterfactual: string;
}

export interface Scenario {
  id: string; label: string; mechanism: string;
  tier: 'primary' | 'alternative' | 'dismissed';
  confidence: number; lead_agent: string;
  supporting_agents: string[]; challenging_agents: string[];
  evidence_chain: string[]; evidence_urls: string[];
  what_breaks_this: string; causal_chain: string;
  temporal_fit: string; impact_speed: string; time_to_peak: string;
}

export interface Attribution {
  depth: number; agentsSpawned: number;
  hypothesesProposed: number; debateRounds: number; elapsed: number;
  hypotheses: Hypothesis[];
  scenarios: Scenario[];
  governance?: { decision: string; reason: string; run_id?: string };
  rawResult?: any;
}

export interface BACEState {
  step: number;
  entities: string[];
  agentsActive: string[];
  debateLog: string[];
  counterfactualsTested: number;
}

// Stage progression
export type Stage = 'market' | 'attribution' | 'scenarios' | 'interrogation';

// ─── Run Store ──────────────────────────────────────────────────────

export type RunStatus = 'idle' | 'created' | 'running' | 'completed' | 'failed' | 'error';

export interface RunState {
  // Run identity
  runId: string | null;
  runStatus: RunStatus;
  lastEventSequence: number;

  // Stage 1: Market
  searchResults: MarketResult[];
  selectedMarket: MarketResult | null;
  prices: PricePoint[];
  spikes: Spike[];

  // Stage 2: Attribution
  selectedSpike: Spike | null;
  baceState: BACEState;
  graphState: BACEGraphState;
  isRunning: boolean;
  isLive: boolean;

  // Stage 3: Scenarios
  attribution: Attribution | null;

  // Stage 4: Interrogation
  interrogationQuestion?: string;

  // Navigation
  currentStage: Stage;
  completedStages: Set<Stage>;
}

const defaultBACEState: BACEState = {
  step: 0, entities: [], agentsActive: [], debateLog: [], counterfactualsTested: 0,
};

const defaultGraphState: BACEGraphState = {
  ontologyEntities: [], ontologyRelationships: [],
  agents: [], proposals: new Map(), convergenceGroups: new Map(),
  divergencePairs: [], graphStats: null, scenarioSummary: null, step: 0,
};

const defaultRunState: RunState = {
  runId: null,
  runStatus: 'idle',
  lastEventSequence: 0,
  searchResults: [],
  selectedMarket: null,
  prices: [],
  spikes: [],
  selectedSpike: null,
  baceState: defaultBACEState,
  graphState: defaultGraphState,
  isRunning: false,
  isLive: false,
  attribution: null,
  interrogationQuestion: undefined,
  currentStage: 'market',
  completedStages: new Set(),
};

// ─── Context ────────────────────────────────────────────────────────

interface RunStoreContextValue {
  run: RunState;
  setRun: (updater: Partial<RunState> | ((prev: RunState) => Partial<RunState>)) => void;
  resetRun: () => void;
  canNavigateTo: (stage: Stage) => boolean;
  initRun: (runId: string) => Promise<void>;
}

const RunStoreContext = createContext<RunStoreContextValue | null>(null);

export function RunStoreProvider({ children }: { children: ReactNode }) {
  const [run, setRunState] = useState<RunState>(defaultRunState);

  const setRun = useCallback((updater: Partial<RunState> | ((prev: RunState) => Partial<RunState>)) => {
    setRunState(prev => {
      const updates = typeof updater === 'function' ? updater(prev) : updater;
      return { ...prev, ...updates };
    });
  }, []);

  const resetRun = useCallback(() => {
    setRunState(defaultRunState);
  }, []);

  const canNavigateTo = useCallback((stage: Stage): boolean => {
    switch (stage) {
      case 'market': return true;
      case 'attribution': return run.runId !== null || run.selectedSpike !== null;
      case 'scenarios': return run.runId !== null && (run.runStatus === 'completed' || run.attribution !== null);
      case 'interrogation': return run.runId !== null && (run.runStatus === 'completed' || run.attribution !== null);
      default: return false;
    }
  }, [run.runId, run.runStatus, run.selectedSpike, run.attribution]);

  const initRunRef = useRef<string | null>(null);

  const initRun = useCallback(async (runId: string) => {
    // Prevent duplicate init for the same runId
    if (initRunRef.current === runId) return;
    initRunRef.current = runId;

    setRunState(prev => ({ ...prev, runId, runStatus: 'running' }));

    const backendUrl = process.env.NEXT_PUBLIC_PYTHIA_API_URL || 'http://localhost:8000';

    try {
      const res = await fetch(`${backendUrl}/api/runs/${runId}`);
      if (!res.ok) throw new Error(`Run not found (${res.status})`);
      const data = await res.json();
      const runData = data.run || data;

      // Map spike event from metadata
      const spikeEvent = runData.metadata?.spike_event;
      const selectedSpike: Spike | null = spikeEvent ? {
        index: 0,
        timestamp: spikeEvent.timestamp || runData.metadata?.timestamp || '',
        magnitude: spikeEvent.magnitude || runData.metadata?.magnitude || 0,
        direction: spikeEvent.direction || runData.metadata?.direction || 'up',
        priceBefore: spikeEvent.price_before || runData.metadata?.price_before || 0,
        priceAfter: spikeEvent.price_after || runData.metadata?.price_after || 0,
      } : (runData.metadata ? {
        index: 0,
        timestamp: runData.metadata.timestamp || '',
        magnitude: runData.metadata.magnitude || 0,
        direction: runData.metadata.direction || 'up',
        priceBefore: runData.metadata.price_before || 0,
        priceAfter: runData.metadata.price_after || 0,
      } : null);

      const selectedMarket: MarketResult | null = runData.metadata?.market_title ? {
        id: runData.metadata.market_id || '',
        question: runData.metadata.market_title,
        slug: '', conditionId: '', clobTokenIds: [], outcomes: [], outcomePrices: [],
        volume24hr: 0, volume: 0, image: '',
      } : null;

      // Map backend status to our status
      const statusMap: Record<string, RunStatus> = {
        'pending': 'created', 'running': 'running', 'completed': 'completed',
        'failed': 'failed', 'error': 'error',
      };
      const mappedStatus: RunStatus = statusMap[runData.status] || 'running';

      // Build attribution from scenarios/evidence if completed
      let attribution: Attribution | null = null;
      if (data.scenarios?.length || data.actions?.length) {
        const scenarios: Scenario[] = (data.scenarios || []).map((s: any) => ({
          id: s.id || `scenario-${s.mechanism}`, label: s.label || '', mechanism: s.mechanism || 'other',
          tier: s.tier || 'primary', confidence: s.confidence || 0, lead_agent: s.lead_agent || '',
          supporting_agents: s.supporting_agents || [], challenging_agents: s.challenging_agents || [],
          evidence_chain: s.evidence_chain || [], evidence_urls: s.evidence_urls || [],
          what_breaks_this: s.what_breaks_this || '', causal_chain: s.causal_chain || '',
          temporal_fit: s.temporal_fit || '', impact_speed: s.impact_speed || '', time_to_peak: s.time_to_peak || '',
        }));
        attribution = {
          depth: runData.metadata?.depth || 2,
          agentsSpawned: data.actions?.length || 0,
          hypothesesProposed: scenarios.length,
          debateRounds: 0,
          elapsed: runData.metadata?.elapsed_seconds || 0,
          hypotheses: [],
          scenarios,
          rawResult: data,
        };
      }

      const updates: Partial<RunState> = {
        runId,
        runStatus: mappedStatus,
        selectedSpike,
        selectedMarket,
        currentStage: mappedStatus === 'completed' ? 'scenarios' : 'attribution',
        completedStages: new Set(mappedStatus === 'completed' ? ['market', 'attribution'] as Stage[] : ['market'] as Stage[]),
        isLive: true,
      };
      if (attribution) {
        updates.attribution = attribution;
        updates.completedStages = new Set(['market', 'attribution'] as Stage[]);
      }

      setRunState(prev => ({ ...prev, ...updates }));

      // Connect to SSE stream for live updates or replay
      const streamCallbacks = {
        onBaceState: (state: BACEState) => setRunState(prev => ({ ...prev, baceState: state })),
        onGraphState: (state: BACEGraphState) => setRunState(prev => ({ ...prev, graphState: state })),
        onComplete: (attr: Attribution) => {
          setRunState(prev => ({
            ...prev,
            attribution: attr,
            isRunning: false,
            isLive: true,
            runStatus: 'completed' as RunStatus,
            currentStage: 'scenarios' as Stage,
            completedStages: new Set(['market', 'attribution'] as Stage[]),
          }));
        },
        onError: (err: string) => {
          console.error('[Pythia] Stream error:', err);
          setRunState(prev => ({ ...prev, runStatus: 'error' as RunStatus, isRunning: false }));
        },
        onSequence: (seq: number) => {
          setRunState(prev => ({ ...prev, lastEventSequence: Math.max(prev.lastEventSequence, seq) }));
        },
      };

      if (mappedStatus === 'running') {
        setRunState(prev => ({ ...prev, isRunning: true }));
        connectRunStream(runId, 0, streamCallbacks).catch(err => {
          console.error('[Pythia] Stream connect error:', err);
        });
      } else if (mappedStatus === 'completed') {
        connectRunStream(runId, 0, streamCallbacks, { replay: true }).catch(err => {
          console.error('[Pythia] Replay connect error:', err);
        });
      }
    } catch (err: any) {
      console.error('[Pythia] initRun failed:', err);
      setRunState(prev => ({ ...prev, runId, runStatus: 'error' }));
      throw err;
    }
  }, []);

  return (
    <RunStoreContext.Provider value={{ run, setRun, resetRun, canNavigateTo, initRun }}>
      {children}
    </RunStoreContext.Provider>
  );
}

export function useRunStore() {
  const ctx = useContext(RunStoreContext);
  if (!ctx) throw new Error('useRunStore must be inside RunStoreProvider');
  return ctx;
}

// ─── Constants (shared across stages) ───────────────────────────────

export const C = {
  bg: '#faf9f5', surface: '#FFFFFF', dark: '#141413', accent: '#d97757',
  yes: '#788c5d', muted: '#b0aea5', border: '#e8e6dc', info: '#6a9bcc',
  faint: '#f5f4ef',
};

export const mono = "'JetBrains Mono', monospace";
export const serif = "'Source Serif 4', Georgia, serif";
