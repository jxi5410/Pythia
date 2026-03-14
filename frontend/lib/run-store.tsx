'use client';

import { createContext, useContext, useState, useCallback, useRef, ReactNode } from 'react';
import {
  connectRunStream,
  StreamTerminalError,
  seedAccumulator,
  type BACECallbacks,
} from './bace-runner';
import type { BACEGraphState } from '@/components/BACEGraphAnimation';
import { extractSpikeDirection, extractSpikeTimestamp, type RunMetadataLike } from './run-presentation';
import {
  applyBackendHydratedStatus,
  applyBackendRunFailure,
  applyClientRunError,
  isBackendStatusStreamable,
  isBackendStatusTerminal,
  isTerminalReplayableStatus,
  mapBackendStatus,
  shouldTreatAsIntentionalAbort,
  type RunErrorSource,
  type RunStatus,
} from './run-status';

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
  rawResult?: unknown;
}

interface ScenarioPayload {
  id?: string;
  label?: string;
  mechanism?: string;
  tier?: Scenario['tier'];
  confidence?: number;
  lead_agent?: string;
  supporting_agents?: string[];
  challenging_agents?: string[];
  evidence_chain?: string[];
  evidence_urls?: string[];
  what_breaks_this?: string;
  causal_chain?: string;
  temporal_fit?: string;
  impact_speed?: string;
  time_to_peak?: string;
}

function getErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message;
  return fallback;
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

// ─── Shared backend → frontend status mapping ───────────────────────
// Invariant:
// - `runStatus === 'failed'` means a backend terminal run state
// - `runStatus === 'error'` means a client-only hydration/transport issue
// - intentional aborts must not write either state

// ─── Run Store ──────────────────────────────────────────────────────

export interface RunState {
  // Run identity
  runId: string | null;
  runStatus: RunStatus;
  runError: string | null;
  runErrorSource: RunErrorSource;
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

  // Hydration gate — true only after initRun fully resolves
  hydrated: boolean;
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
  runError: null,
  runErrorSource: null,
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
  hydrated: false,
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

// Reconnect config
const RECONNECT_DELAY_MS = 2000;
const MAX_RECONNECT_ATTEMPTS = 10;

interface RunStoreRuntimeDeps {
  fetchImpl?: typeof fetch;
  connectRunStreamImpl?: typeof connectRunStream;
  sleepImpl?: (ms: number) => Promise<void>;
  maxReconnectAttempts?: number;
}

interface RunStoreRuntimeRefs {
  streamAbortRef: { current: AbortController | null };
  activeInitRef: { current: string | null };
  lastSeqRef: { current: number };
  stateRef: { current: { baceState: BACEState; graphState: BACEGraphState } };
}

function createRunStoreRuntime(
  setRunState: React.Dispatch<React.SetStateAction<RunState>>,
  refs: RunStoreRuntimeRefs,
  deps: RunStoreRuntimeDeps = {},
) {
  const fetchImpl = deps.fetchImpl ?? fetch;
  const connectRunStreamImpl = deps.connectRunStreamImpl ?? connectRunStream;
  const sleepImpl = deps.sleepImpl ?? ((ms: number) => new Promise(resolve => setTimeout(resolve, ms)));
  const maxReconnectAttempts = deps.maxReconnectAttempts ?? MAX_RECONNECT_ATTEMPTS;

  const startStreamWithReconnect = (
    runId: string,
    callbacks: BACECallbacks,
  ) => {
    let attempt = 0;

    const connect = async () => {
      while (attempt < maxReconnectAttempts) {
        if (refs.activeInitRef.current !== runId) return;

        const controller = new AbortController();
        refs.streamAbortRef.current = controller;

        try {
          const initialAccumulator = attempt > 0
            ? seedAccumulator(refs.stateRef.current.baceState, refs.stateRef.current.graphState)
            : undefined;

          await connectRunStreamImpl(runId, refs.lastSeqRef.current, callbacks, {
            signal: controller.signal,
            initialAccumulator,
          });
          return;
        } catch (err: unknown) {
          if (shouldTreatAsIntentionalAbort(err, controller.signal.aborted)) {
            return;
          }

          if (err instanceof StreamTerminalError) {
            console.error('[Pythia] Terminal stream error, not retrying:', err.message);
            return;
          }

          if (refs.activeInitRef.current !== runId) return;

          attempt++;
          console.warn(`[Pythia] Stream disconnected (attempt ${attempt}/${maxReconnectAttempts}), reconnecting in ${RECONNECT_DELAY_MS}ms...`);

          try {
            const backendUrl = process.env.NEXT_PUBLIC_PYTHIA_API_URL || 'http://localhost:8000';
            const statusRes = await fetchImpl(`${backendUrl}/api/runs/${runId}/status`);
            if (statusRes.ok) {
              const statusData = await statusRes.json();

              if (isBackendStatusTerminal(statusData.status)) {
                const mappedStatus = mapBackendStatus(statusData.status);
                setRunState(prev => {
                  if (prev.runId !== runId) return prev;
                  return {
                    ...prev,
                    ...applyBackendHydratedStatus(
                      prev,
                      mappedStatus,
                      statusData.error_message || prev.runError,
                    ),
                  };
                });

                if (isTerminalReplayableStatus(statusData.status)) {
                  const replayAcc = seedAccumulator(
                    refs.stateRef.current.baceState,
                    refs.stateRef.current.graphState,
                  );
                  connectRunStreamImpl(runId, refs.lastSeqRef.current, callbacks, {
                    replay: true,
                    initialAccumulator: replayAcc,
                  }).catch(err => {
                    if (!(err instanceof StreamTerminalError)) {
                      console.error('[Pythia] Replay after terminal status failed:', err);
                    }
                  });
                }
                return;
              }
            }
          } catch {
            // Status check failed — still try to reconnect the stream
          }

          await sleepImpl(RECONNECT_DELAY_MS);
        }
      }

      if (refs.activeInitRef.current === runId) {
        console.error('[Pythia] Stream reconnect failed after max attempts');
        setRunState(prev => {
          if (prev.runId !== runId) return prev;
          return { ...prev, ...applyClientRunError(prev, 'Lost connection to the attribution stream.') };
        });
      }
    };

    void connect();
  };

  const initRun = async (runId: string): Promise<void> => {
    refs.streamAbortRef.current?.abort();
    refs.streamAbortRef.current = null;

    refs.activeInitRef.current = runId;
    refs.lastSeqRef.current = 0;
    refs.stateRef.current = { baceState: defaultBACEState, graphState: defaultGraphState };

    setRunState(prev => ({
      ...prev,
      runId,
      runStatus: 'running',
      runError: null,
      runErrorSource: null,
      hydrated: false,
      lastEventSequence: 0,
      baceState: defaultBACEState,
      graphState: defaultGraphState,
      attribution: null,
      isRunning: false,
      isLive: false,
    }));

    const backendUrl = process.env.NEXT_PUBLIC_PYTHIA_API_URL || 'http://localhost:8000';

    try {
      const res = await fetchImpl(`${backendUrl}/api/runs/${runId}`);
      if (!res.ok) throw new Error(`Run not found (${res.status})`);

      if (refs.activeInitRef.current !== runId) return;

      const data = await res.json();
      const runData = data.run || data;
      const metadata = (runData.metadata || {}) as RunMetadataLike;

      const spikeEvent = metadata.spike_event;
      const spikeTimestamp = extractSpikeTimestamp(metadata);
      const selectedSpike: Spike | null = spikeEvent ? {
        index: 0,
        timestamp: spikeTimestamp,
        magnitude: spikeEvent.magnitude || metadata.magnitude || 0,
        direction: extractSpikeDirection(metadata),
        priceBefore: spikeEvent.metadata?.price_before || metadata.price_before || 0,
        priceAfter: spikeEvent.metadata?.price_after || metadata.price_after || 0,
      } : (runData.metadata ? {
        index: 0,
        timestamp: spikeTimestamp,
        magnitude: metadata.magnitude || 0,
        direction: extractSpikeDirection(metadata),
        priceBefore: metadata.price_before || 0,
        priceAfter: metadata.price_after || 0,
      } : null);

      const marketTitle = metadata.market_title || spikeEvent?.metadata?.market_title || '';
      const selectedMarket: MarketResult | null = marketTitle ? {
        id: metadata.market_id || runData.market_id || '',
        question: marketTitle,
        slug: '', conditionId: '', clobTokenIds: [], outcomes: [], outcomePrices: [],
        volume24hr: 0, volume: 0, image: '',
      } : null;

      const mappedStatus = mapBackendStatus(runData.status);

      let attribution: Attribution | null = null;
      if (data.scenarios?.length || data.actions?.length) {
        const scenarios: Scenario[] = (data.scenarios || []).map((s: ScenarioPayload) => ({
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

      if (refs.activeInitRef.current !== runId) return;

      const updates: Partial<RunState> = {
        runId,
        selectedSpike,
        selectedMarket,
        currentStage: mappedStatus === 'completed' ? 'scenarios' : 'attribution',
        completedStages: new Set(mappedStatus === 'completed' ? ['market', 'attribution'] as Stage[] : ['market'] as Stage[]),
        isLive: true,
      };
      Object.assign(updates, applyBackendHydratedStatus({
        runStatus: 'idle',
        runError: null,
        runErrorSource: null,
        isRunning: false,
      }, mappedStatus, runData.error_message || null));
      if (attribution) {
        updates.attribution = attribution;
        updates.completedStages = new Set(['market', 'attribution'] as Stage[]);
      }

      const streamCallbacks: BACECallbacks = {
        onBaceState: (state: BACEState) => setRunState(prev => {
          if (prev.runId !== runId) return prev;
          refs.stateRef.current = { ...refs.stateRef.current, baceState: state };
          return { ...prev, baceState: state };
        }),
        onGraphState: (state: BACEGraphState) => setRunState(prev => {
          if (prev.runId !== runId) return prev;
          refs.stateRef.current = { ...refs.stateRef.current, graphState: state };
          return { ...prev, graphState: state };
        }),
        onComplete: (attr: Attribution) => {
          setRunState(prev => {
            if (prev.runId !== runId) return prev;
            return {
              ...prev,
              attribution: attr,
              isRunning: false,
              isLive: true,
              runStatus: 'completed' as RunStatus,
              runError: null,
              runErrorSource: null,
              currentStage: 'scenarios' as Stage,
              completedStages: new Set(['market', 'attribution'] as Stage[]),
            };
          });
        },
        onError: (err: string) => {
          console.error('[Pythia] Stream error:', err);
          setRunState(prev => {
            if (prev.runId !== runId) return prev;
            return { ...prev, ...applyBackendRunFailure(prev, err) };
          });
        },
        onSequence: (seq: number) => {
          refs.lastSeqRef.current = Math.max(refs.lastSeqRef.current, seq);
          setRunState(prev => {
            if (prev.runId !== runId) return prev;
            return { ...prev, lastEventSequence: Math.max(prev.lastEventSequence, seq) };
          });
        },
      };

      if (isBackendStatusStreamable(runData.status)) {
        setRunState(prev => ({ ...prev, ...updates, isRunning: true, hydrated: true }));
        startStreamWithReconnect(runId, streamCallbacks);
      } else if (isTerminalReplayableStatus(runData.status)) {
        setRunState(prev => ({ ...prev, ...updates, hydrated: true }));
        connectRunStreamImpl(runId, 0, streamCallbacks, { replay: true }).catch(err => {
          if (!(err instanceof StreamTerminalError)) {
            console.error('[Pythia] Replay error:', err);
          }
        });
      } else {
        setRunState(prev => ({ ...prev, ...updates, hydrated: true }));
      }
    } catch (err: unknown) {
      if (refs.activeInitRef.current === runId) {
        console.error('[Pythia] initRun failed:', err);
        setRunState(prev => ({
          ...applyClientRunError(prev, getErrorMessage(err, 'Failed to load run')),
          runId,
          hydrated: true,
        }));
      }
      throw err;
    }
  };

  return { initRun };
}

export function createRunStoreTestHarness(deps: RunStoreRuntimeDeps = {}) {
  let state: RunState = { ...defaultRunState };
  const refs: RunStoreRuntimeRefs = {
    streamAbortRef: { current: null },
    activeInitRef: { current: null },
    lastSeqRef: { current: 0 },
    stateRef: { current: { baceState: defaultBACEState, graphState: defaultGraphState } },
  };

  const setRunState: React.Dispatch<React.SetStateAction<RunState>> = (updater) => {
    state = typeof updater === 'function'
      ? (updater as (prev: RunState) => RunState)(state)
      : updater;
  };

  const runtime = createRunStoreRuntime(setRunState, refs, deps);
  return {
    getState: () => state,
    initRun: runtime.initRun,
    abortActiveRun: () => {
      refs.streamAbortRef.current?.abort();
    },
  };
}

export function RunStoreProvider({ children }: { children: ReactNode }) {
  const [run, setRunState] = useState<RunState>(defaultRunState);

  // Track active stream abort controller for cleanup
  const streamAbortRef = useRef<AbortController | null>(null);

  const setRun = useCallback((updater: Partial<RunState> | ((prev: RunState) => Partial<RunState>)) => {
    setRunState(prev => {
      const updates = typeof updater === 'function' ? updater(prev) : updater;
      return { ...prev, ...updates };
    });
  }, []);

  const resetRun = useCallback(() => {
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
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

  // Ref to track which runId init is in-flight so we can abort stale ones
  const activeInitRef = useRef<string | null>(null);
  // Ref to access latest lastEventSequence inside reconnect loop
  const lastSeqRef = useRef(0);
  // Ref to access latest baceState/graphState for accumulator seeding on reconnect
  const stateRef = useRef<{ baceState: BACEState; graphState: BACEGraphState }>({
    baceState: defaultBACEState,
    graphState: defaultGraphState,
  });
  const runtimeRef = useRef<ReturnType<typeof createRunStoreRuntime> | null>(null);
  const getRuntime = useCallback(() => {
    if (runtimeRef.current == null) {
      runtimeRef.current = createRunStoreRuntime(setRunState, {
        streamAbortRef,
        activeInitRef,
        lastSeqRef,
        stateRef,
      });
    }
    return runtimeRef.current;
  }, []);
  const initRun = useCallback((runId: string) => getRuntime().initRun(runId), [getRuntime]);

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
