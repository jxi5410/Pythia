'use client';

import { createContext, useContext, useState, useCallback, ReactNode } from 'react';
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

export interface RunState {
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
      case 'attribution': return run.selectedSpike !== null;
      case 'scenarios': return run.attribution !== null;
      case 'interrogation': return run.attribution !== null;
      default: return false;
    }
  }, [run.selectedSpike, run.attribution]);

  return (
    <RunStoreContext.Provider value={{ run, setRun, resetRun, canNavigateTo }}>
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
