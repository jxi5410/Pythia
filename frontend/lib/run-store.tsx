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

export type RunStatus = 'idle' | 'created' | 'running' | 'completed' | 'failed' | 'error';

/** Map any backend run status string to the frontend RunStatus enum.
 *  Single source of truth — used in initRun hydration, reconnect fallback,
 *  and any status polling. */
export function mapBackendStatus(backendStatus: string): RunStatus {
  switch (backendStatus) {
    // Created / pending
    case 'created':
    case 'pending':
      return 'created';

    // Active / in-progress
    case 'running':
    case 'market_snapshot_complete':
    case 'attribution_started':
    case 'attribution_streaming':
    case 'scenario_clustering_complete':
    case 'graph_persisted':
      return 'running';

    // Completed variants — all usable states
    case 'completed':
    case 'interrogation_ready':
    case 'partial_complete':
      return 'completed';

    // Terminal failure variants
    case 'failed':
    case 'failed_terminal':
    case 'failed_retryable':
    case 'error':
      return 'failed';

    // Cancelled
    case 'cancelled':
      return 'failed';

    default:
      // Unknown status — treat as running (optimistic) if not clearly terminal
      return 'running';
  }
}

/** Check if a backend status represents a terminal state (no more events expected). */
export function isBackendStatusTerminal(backendStatus: string): boolean {
  switch (backendStatus) {
    case 'completed':
    case 'interrogation_ready':
    case 'partial_complete':
    case 'failed':
    case 'failed_terminal':
    case 'failed_retryable':
    case 'error':
    case 'cancelled':
      return true;
    default:
      return false;
  }
}

/** Check if a backend status represents a completed-ish state (has usable results). */
function isBackendStatusCompleted(backendStatus: string): boolean {
  switch (backendStatus) {
    case 'completed':
    case 'interrogation_ready':
    case 'partial_complete':
      return true;
    default:
      return false;
  }
}

function isBackendStatusStreamable(backendStatus: string): boolean {
  switch (backendStatus) {
    case 'created':
    case 'pending':
    case 'running':
    case 'market_snapshot_complete':
    case 'attribution_started':
    case 'attribution_streaming':
    case 'scenario_clustering_complete':
    case 'graph_persisted':
      return true;
    default:
      return false;
  }
}

// ─── Run Store ──────────────────────────────────────────────────────

export interface RunState {
  // Run identity
  runId: string | null;
  runStatus: RunStatus;
  runError: string | null;
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

  const initRun = useCallback(async (runId: string) => {
    // Abort any previous stream connection
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;

    // Mark this as the active init — any prior in-flight init becomes stale
    activeInitRef.current = runId;
    lastSeqRef.current = 0;
    stateRef.current = { baceState: defaultBACEState, graphState: defaultGraphState };

    // Clear run-specific state before hydrating (prevents stale data flash)
    setRunState(prev => ({
      ...prev,
      runId,
      runStatus: 'running',
      runError: null,
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
      const res = await fetch(`${backendUrl}/api/runs/${runId}`);
      if (!res.ok) throw new Error(`Run not found (${res.status})`);

      // Check if we're still the active init (user may have navigated to another run)
      if (activeInitRef.current !== runId) return;

      const data = await res.json();
      const runData = data.run || data;
      const metadata = (runData.metadata || {}) as RunMetadataLike;

      // Map spike event from metadata
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

      // Build attribution from scenarios/evidence if completed
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

      // Check staleness again before applying
      if (activeInitRef.current !== runId) return;

      const updates: Partial<RunState> = {
        runId,
        runStatus: mappedStatus,
        runError: runData.error_message || null,
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

      // Create stream callbacks (shared between initial connect and reconnect).
      // These callbacks guard against stale runId and update the stateRef so
      // the reconnect loop can seed accumulators from current store state.
      const streamCallbacks: BACECallbacks = {
        onBaceState: (state: BACEState) => setRunState(prev => {
          if (prev.runId !== runId) return prev;
          stateRef.current = { ...stateRef.current, baceState: state };
          return { ...prev, baceState: state };
        }),
        onGraphState: (state: BACEGraphState) => setRunState(prev => {
          if (prev.runId !== runId) return prev;
          stateRef.current = { ...stateRef.current, graphState: state };
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
              currentStage: 'scenarios' as Stage,
              completedStages: new Set(['market', 'attribution'] as Stage[]),
            };
          });
        },
        onError: (err: string) => {
          console.error('[Pythia] Stream error:', err);
          // Terminal SSE errors set the store to failed.
          // The StreamTerminalError throw in connectRunStream ensures
          // the reconnect loop also stops.
          setRunState(prev => {
            if (prev.runId !== runId) return prev;
            return { ...prev, runStatus: 'failed', runError: err, isRunning: false };
          });
        },
        onSequence: (seq: number) => {
          lastSeqRef.current = Math.max(lastSeqRef.current, seq);
          setRunState(prev => {
            if (prev.runId !== runId) return prev;
            return { ...prev, lastEventSequence: Math.max(prev.lastEventSequence, seq) };
          });
        },
      };

      if (isBackendStatusStreamable(runData.status)) {
        setRunState(prev => ({ ...prev, ...updates, isRunning: true, hydrated: true }));

        // Start stream with reconnect loop
        startStreamWithReconnect(runId, streamCallbacks);
      } else if (mappedStatus === 'completed') {
        // Replay is a one-shot JSON fetch — no reconnect needed
        setRunState(prev => ({ ...prev, ...updates, hydrated: true }));
        connectRunStream(runId, 0, streamCallbacks, { replay: true }).catch(err => {
          console.error('[Pythia] Replay error:', err);
        });
      } else {
        // failed/error/created — just set the state
        setRunState(prev => ({ ...prev, ...updates, hydrated: true }));
      }
    } catch (err: unknown) {
      // Only set error if this init is still active
      if (activeInitRef.current === runId) {
        console.error('[Pythia] initRun failed:', err);
        setRunState(prev => ({
          ...prev,
          runId,
          runStatus: 'error',
          runError: getErrorMessage(err, 'Failed to load run'),
          hydrated: true,
        }));
      }
      throw err;
    }
  }, []);

  /** Connect to live SSE with automatic reconnect on failure.
   *  Distinguishes:
   *  - StreamTerminalError → backend error event, stop immediately
   *  - AbortError → intentional navigation/reset, stop silently
   *  - Other errors → network failure, retry with status check */
  function startStreamWithReconnect(
    runId: string,
    callbacks: BACECallbacks,
  ) {
    let attempt = 0;

    const connect = async () => {
      while (attempt < MAX_RECONNECT_ATTEMPTS) {
        // Bail if this run is no longer active
        if (activeInitRef.current !== runId) return;

        // Create a fresh AbortController for this connection attempt
        const controller = new AbortController();
        streamAbortRef.current = controller;

        try {
          // Seed accumulator from current store state so reconnect
          // applies unseen-tail events on top of existing data
          const initialAccumulator = attempt > 0
            ? seedAccumulator(stateRef.current.baceState, stateRef.current.graphState)
            : undefined;

          await connectRunStream(runId, lastSeqRef.current, callbacks, {
            signal: controller.signal,
            initialAccumulator,
          });
          // Stream ended normally (done/run_completed) — no reconnect needed
          return;
        } catch (err: unknown) {
          // Intentional abort (navigation/reset) — stop silently
          if ((err instanceof Error && err.name === 'AbortError') || controller.signal.aborted) {
            return;
          }

          // Terminal SSE error from backend — store already updated by onError
          if (err instanceof StreamTerminalError) {
            console.error('[Pythia] Terminal stream error, not retrying:', err.message);
            return;
          }

          // Bail if run is no longer active (checked after await)
          if (activeInitRef.current !== runId) return;

          attempt++;
          console.warn(`[Pythia] Stream disconnected (attempt ${attempt}/${MAX_RECONNECT_ATTEMPTS}), reconnecting in ${RECONNECT_DELAY_MS}ms...`);

          // Check if run reached a terminal state while we were disconnected
          try {
            const backendUrl = process.env.NEXT_PUBLIC_PYTHIA_API_URL || 'http://localhost:8000';
            const statusRes = await fetch(`${backendUrl}/api/runs/${runId}/status`);
            if (statusRes.ok) {
              const statusData = await statusRes.json();

              if (isBackendStatusTerminal(statusData.status)) {
                const mappedStatus = mapBackendStatus(statusData.status);
                setRunState(prev => {
                  if (prev.runId !== runId) return prev;
                  return {
                    ...prev,
                    runStatus: mappedStatus,
                    runError: statusData.error_message || prev.runError,
                    isRunning: false,
                  };
                });

                // If it completed, replay to fill in any missing state
                if (isBackendStatusCompleted(statusData.status)) {
                  const replayAcc = seedAccumulator(
                    stateRef.current.baceState,
                    stateRef.current.graphState,
                  );
                  connectRunStream(runId, lastSeqRef.current, callbacks, {
                    replay: true,
                    initialAccumulator: replayAcc,
                  }).catch(() => {});
                }
                return;
              }
            }
          } catch {
            // Status check failed — still try to reconnect the stream
          }

          await new Promise(resolve => setTimeout(resolve, RECONNECT_DELAY_MS));
        }
      }

      // Exhausted retries
      if (activeInitRef.current === runId) {
        console.error('[Pythia] Stream reconnect failed after max attempts');
        setRunState(prev => {
          if (prev.runId !== runId) return prev;
          return {
            ...prev,
            runStatus: 'error',
            runError: 'Lost connection to the attribution stream.',
            isRunning: false,
          };
        });
      }
    };

    connect();
  }

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
