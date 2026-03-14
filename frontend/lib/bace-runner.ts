import type {
  MarketResult, Spike, BACEState, Attribution, Scenario, Hypothesis,
} from './run-store';
import type {
  BACEGraphState, OntologyEntity, OntologyRelationship, AgentInfo,
  ProposalHypothesis, DivergencePair,
} from '@/components/BACEGraphAnimation';

export interface BACECallbacks {
  onBaceState: (state: BACEState) => void;
  onGraphState: (state: BACEGraphState) => void;
  onComplete: (attribution: Attribution) => void;
  onError: (error: string) => void;
  onSequence?: (seq: number) => void;
}

// ─── Error types for stream lifecycle ───────────────────────────────

/** Thrown when the backend emits a terminal SSE `error` event.
 *  The reconnect loop should NOT retry — the run is dead. */
export class StreamTerminalError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'StreamTerminalError';
  }
}

// ─── Shared event-handling state ────────────────────────────────────

export interface EventAccumulator {
  finalResult: any;
  currentStep: number;
  liveEntities: string[];
  liveAgents: string[];
  liveLog: string[];
  currentStageKey: string;
  currentStageLabel: string;
  currentDetail: string;
  waitingOn: string | null;
  elapsedSeconds: number;
  lastBackendEventAtMs: number | null;
  lastHeartbeatSignature: string | null;
  ontologyEntities: OntologyEntity[];
  ontologyRelationships: OntologyRelationship[];
  agents: AgentInfo[];
  proposals: Map<string, ProposalHypothesis[]>;
  convergenceGroups: Map<string, string[]>;
  divergencePairs: DivergencePair[];
  graphStats: { entities: number; relationships: number; facts: number } | null;
  scenarioSummary: { total: number; primary: number; alternative: number; dismissed: number } | null;
  liveScenarios: Scenario[];
}

export function createAccumulator(): EventAccumulator {
  return {
    finalResult: null,
    currentStep: 0,
    liveEntities: [],
    liveAgents: [],
    liveLog: [],
    currentStageKey: 'preparing_run',
    currentStageLabel: 'Preparing BACE run',
    currentDetail: 'Connecting to the attribution stream.',
    waitingOn: null,
    elapsedSeconds: 0,
    lastBackendEventAtMs: null,
    lastHeartbeatSignature: null,
    ontologyEntities: [],
    ontologyRelationships: [],
    agents: [],
    proposals: new Map(),
    convergenceGroups: new Map(),
    divergencePairs: [],
    graphStats: null,
    scenarioSummary: null,
    liveScenarios: [],
  };
}

/** Seed an accumulator from the store's current baceState + graphState.
 *  Used on reconnect so unseen-tail events apply on top of existing state. */
export function seedAccumulator(
  baceState: BACEState,
  graphState: BACEGraphState,
): EventAccumulator {
  return {
    finalResult: null,
    currentStep: baceState.step,
    liveEntities: [...baceState.entities],
    liveAgents: [...baceState.agentsActive],
    liveLog: [...baceState.debateLog],
    currentStageKey: baceState.currentStageKey,
    currentStageLabel: baceState.currentStageLabel,
    currentDetail: baceState.currentDetail,
    waitingOn: baceState.waitingOn,
    elapsedSeconds: baceState.elapsedSeconds,
    lastBackendEventAtMs: baceState.lastBackendEventAtMs,
    lastHeartbeatSignature: null,
    ontologyEntities: [...graphState.ontologyEntities],
    ontologyRelationships: [...graphState.ontologyRelationships],
    agents: [...graphState.agents],
    proposals: new Map(graphState.proposals),
    convergenceGroups: new Map(graphState.convergenceGroups),
    divergencePairs: [...graphState.divergencePairs],
    graphStats: graphState.graphStats ? { ...graphState.graphStats } : null,
    scenarioSummary: graphState.scenarioSummary ? { ...graphState.scenarioSummary } : null,
    liveScenarios: [],
  };
}

function emitState(acc: EventAccumulator, callbacks: BACECallbacks) {
  callbacks.onBaceState({
    step: acc.currentStep,
    entities: [...acc.liveEntities],
    agentsActive: [...acc.liveAgents],
    debateLog: acc.liveLog.slice(-14),
    counterfactualsTested: acc.currentStep >= 7 ? 1 : 0,
    currentStageKey: acc.currentStageKey,
    currentStageLabel: acc.currentStageLabel,
    currentDetail: acc.currentDetail,
    waitingOn: acc.waitingOn,
    elapsedSeconds: acc.elapsedSeconds,
    lastBackendEventAtMs: acc.lastBackendEventAtMs,
  });
  callbacks.onGraphState({
    ontologyEntities: [...acc.ontologyEntities],
    ontologyRelationships: [...acc.ontologyRelationships],
    agents: [...acc.agents],
    proposals: new Map(acc.proposals),
    convergenceGroups: new Map(acc.convergenceGroups),
    divergencePairs: [...acc.divergencePairs],
    graphStats: acc.graphStats,
    scenarioSummary: acc.scenarioSummary,
    step: acc.currentStep,
  });
}

/** Normalize an envelope into { eventType, data, sequence }. Works for both
 *  canonical envelopes ({ event_type, payload, sequence }) and legacy SSE
 *  where eventType comes from the SSE `event:` line. */
function normalizeEvent(
  parsed: any,
  rawEventType: string,
): { eventType: string; data: any; sequence: number | null } {
  if (parsed.event_type !== undefined && parsed.payload !== undefined) {
    return {
      eventType: parsed.payload?.progress_kind || parsed.event_type,
      data: parsed.payload,
      sequence: parsed.sequence ?? null,
    };
  }
  return { eventType: rawEventType, data: parsed, sequence: null };
}

function updateProgress(
  acc: EventAccumulator,
  stageKey: string,
  stageLabel: string,
  detail: string,
  elapsedSeconds = acc.elapsedSeconds,
  waitingOn: string | null = acc.waitingOn,
) {
  acc.currentStageKey = stageKey;
  acc.currentStageLabel = stageLabel;
  acc.currentDetail = detail;
  acc.elapsedSeconds = elapsedSeconds;
  acc.waitingOn = waitingOn;
  acc.lastBackendEventAtMs = Date.now();
}

function appendLogOnce(acc: EventAccumulator, line: string) {
  if (!line) return;
  if (acc.liveLog[acc.liveLog.length - 1] === line) return;
  acc.liveLog.push(line);
}

/**
 * Apply a single event to the accumulator. Returns:
 *  - 'continue' if processing should keep going
 *  - 'terminal_error' if the backend emitted an error event (caller should throw)
 *  - 'skip' for heartbeats/no-ops/result/done
 */
function applyEvent(
  eventType: string,
  data: any,
  acc: EventAccumulator,
  callbacks: BACECallbacks,
): 'continue' | 'terminal_error' | 'skip' {
  if (eventType === 'context') {
    acc.currentStep = 0;
    updateProgress(
      acc,
      'context',
      data.phase_label || 'Building spike context',
      data.detail || data.message || 'Scanning recent market context.',
      data.elapsed_seconds ?? acc.elapsedSeconds,
      data.waiting_on || null,
    );
    appendLogOnce(acc, data.message || 'Scanning recent market context');
    appendLogOnce(acc, `Category: ${data.category || 'general'}`);
    if (data.entities) for (const e of data.entities) if (!acc.liveEntities.includes(e)) acc.liveEntities.push(e);
  } else if (eventType === 'ontology') {
    acc.currentStep = 1;
    updateProgress(
      acc,
      'ontology',
      data.phase_label || 'Building candidate causal factors',
      data.detail || data.message || 'Building candidate causal factors.',
      data.elapsed_seconds ?? acc.elapsedSeconds,
      data.waiting_on || null,
    );
    appendLogOnce(acc, `Ontology: ${data.entity_count} entities, ${data.relationship_count} rels`);
    if (data.entities) {
      for (const name of data.entities) if (!acc.liveEntities.includes(name)) acc.liveEntities.push(name);
      acc.ontologyEntities = data.entities.map((name: string, i: number) => ({
        name, type: 'Unknown', relevance: 1 - (i * 0.08),
      }));
    }
    if (data.full_entities) {
      acc.ontologyEntities = data.full_entities.map((e: any) => ({
        name: e.name, type: e.entity_type || e.type || 'Unknown',
        relevance: e.relevance_score || e.relevance || 0.5,
      }));
    }
    if (data.full_relationships) {
      acc.ontologyRelationships = data.full_relationships.map((r: any) => ({
        source: r.source_id || r.source || '', target: r.target_id || r.target || '',
        type: r.relationship_type || r.type || 'related', strength: r.strength || 0.5,
      }));
    }
    appendLogOnce(acc, `Generated ${data.search_queries || 0} search queries`);
  } else if (eventType === 'evidence') {
    acc.currentStep = 2;
    updateProgress(acc, 'evidence', 'Comparing supporting vs conflicting evidence', 'Comparing supporting vs conflicting evidence.', data.elapsed_seconds ?? acc.elapsedSeconds, data.waiting_on || null);
    appendLogOnce(acc, `News evidence: ${data.count} candidates`);
  } else if (eventType === 'run_started') {
    updateProgress(
      acc,
      data.phase || 'preparing_run',
      data.phase_label || 'Preparing BACE run',
      data.detail || data.message || 'Preparing BACE run.',
      data.elapsed_seconds ?? 0,
      data.waiting_on || null,
    );
    appendLogOnce(acc, data.message || 'Preparing BACE run');
  } else if (eventType === 'agents') {
    acc.currentStep = 3;
    updateProgress(acc, 'agents', 'Building candidate causal factors', 'Spawning specialist agents.', data.elapsed_seconds ?? acc.elapsedSeconds, data.waiting_on || null);
    acc.agents = (data.agents || []).map((a: any) => ({
      id: a.id, name: a.name, tier: a.tier || 1, domain: a.domain || '',
    }));
    for (const a of acc.agents) if (!acc.liveAgents.includes(a.id)) acc.liveAgents.push(a.id);
    appendLogOnce(acc, `Spawned ${data.count || acc.agents.length} agents`);
  } else if (eventType === 'domain_evidence') {
    acc.currentStep = 4;
    updateProgress(acc, 'domain_evidence', 'Comparing supporting vs conflicting evidence', 'Gathering domain-specific evidence.', data.elapsed_seconds ?? acc.elapsedSeconds, data.waiting_on || null);
    appendLogOnce(acc, `Domain evidence: ${data.count} items`);
  } else if (eventType === 'proposal') {
    acc.currentStep = 5;
    updateProgress(acc, 'proposal', 'Asking agents to challenge the lead narrative', 'Reviewing agent proposals.', data.elapsed_seconds ?? acc.elapsedSeconds, data.waiting_on || null);
    const agentName = acc.agents.find(a => a.id === data.agent)?.name || data.agent || 'Agent';
    const hyps = data.hypotheses || [];
    acc.proposals.set(data.agent, hyps.map((h: any) => ({ cause: h.cause || '', confidence: h.confidence || 0 })));
    for (const h of hyps) {
      appendLogOnce(acc, `\u27EB ${agentName}`);
      appendLogOnce(acc, `  "${(h.cause || '').slice(0, 90)}\u2026" \u2014 ${Math.round((h.confidence || 0) * 100)}%`);
    }
  } else if (eventType === 'interaction') {
    acc.currentStep = 6;
    updateProgress(acc, 'interaction', 'Asking agents to challenge the lead narrative', 'Comparing supporting vs conflicting evidence.', data.elapsed_seconds ?? acc.elapsedSeconds, data.waiting_on || null);
    const stances = data.stances || {};
    appendLogOnce(acc, `Interaction: ${stances.support || 0} support, ${stances.challenge || 0} challenges`);
    if (data.convergence_groups) appendLogOnce(acc, `Convergence: ${data.convergence_groups} groups`);
    if (data.convergence_group_details) acc.convergenceGroups = new Map(Object.entries(data.convergence_group_details));
    if (data.top_challenges) {
      acc.divergencePairs = data.top_challenges.map((tc: any) => ({
        hypothesis_id: tc.target || '',
        proposed_by: tc.target?.split('-h')[0] || '',
        challenged_by: tc.challenger?.replace(/\s+/g, '-').toLowerCase() || '',
      }));
    }
  } else if (eventType === 'sim_round') {
    acc.currentStep = 6;
    updateProgress(acc, 'sim_round', 'Asking agents to challenge the lead narrative', 'Running the agent challenge round.', data.elapsed_seconds ?? acc.elapsedSeconds, data.waiting_on || null);
    appendLogOnce(acc, `\u2501\u2501 Round ${data.round}/${data.total} \u2014 ${data.active_hypotheses} active hypotheses \u2501\u2501`);
  } else if (eventType === 'sim_action') {
    acc.currentStep = 6;
    updateProgress(acc, 'sim_action', 'Asking agents to challenge the lead narrative', 'Processing agent actions.', data.elapsed_seconds ?? acc.elapsedSeconds, data.waiting_on || null);
    const icon = data.action === 'CHALLENGE' ? '\u2694' : data.action === 'SUPPORT' ? '\u2713' : data.action === 'REBUT' ? '\u21A9' : data.action === 'CONCEDE' ? '\u2715' : data.action === 'PRESENT_EVIDENCE' ? '\uD83D\uDCC4' : data.action === 'UPDATE_CONFIDENCE' ? '\u2195' : data.action === 'SYNTHESIZE' ? '\u2295' : data.action === 'CONVERGED' ? '\u25CF' : '\u2022';
    const confDelta = data.confidence_after !== data.confidence_before && data.confidence_before > 0
      ? ` (${data.confidence_after > data.confidence_before ? '+' : ''}${((data.confidence_after - data.confidence_before) * 100).toFixed(0)}%)`
      : '';
    appendLogOnce(acc, `${icon} [${data.agent_name}] ${data.action}${data.target_hyp ? ' \u2192 ' + data.target_hyp : ''}${confDelta}`);
    if (data.content) appendLogOnce(acc, `  ${data.content.slice(0, 100)}`);
    if (data.action === 'CHALLENGE' && data.target_agent && data.agent) {
      acc.divergencePairs.push({
        hypothesis_id: data.target_hyp || '',
        proposed_by: data.target_agent || '',
        challenged_by: data.agent || '',
      });
    }
    if (data.action === 'SUPPORT' && data.target_hyp) {
      const existing = acc.convergenceGroups.get(data.target_hyp) || [];
      if (!existing.includes(data.agent)) {
        existing.push(data.agent);
        acc.convergenceGroups.set(data.target_hyp, existing);
      }
    }
  } else if (eventType === 'sim_status') {
    acc.currentStep = 6;
    updateProgress(acc, 'sim_status', 'Asking agents to challenge the lead narrative', data.detail || data.message || 'Still processing evidence.', data.elapsed_seconds ?? acc.elapsedSeconds, data.waiting_on || null);
  } else if (eventType === 'sim_complete') {
    acc.currentStep = 7;
    updateProgress(acc, 'sim_complete', 'Comparing supporting vs conflicting evidence', 'Agent review complete.', data.elapsed_seconds ?? acc.elapsedSeconds, data.waiting_on || null);
    appendLogOnce(acc, `Simulation complete: ${data.total_actions} actions over ${data.rounds_completed} rounds`);
    appendLogOnce(acc, `${data.active_hypotheses} survived, ${data.conceded_hypotheses} conceded`);
    if (data.convergence_groups > 0) appendLogOnce(acc, `${data.convergence_groups} convergence groups, ${data.divergence_pairs} unresolved conflicts`);
  } else if (eventType === 'scenarios') {
    acc.currentStep = 7;
    updateProgress(acc, 'scenarios', 'Comparing supporting vs conflicting evidence', 'Clustering scenarios.', data.elapsed_seconds ?? acc.elapsedSeconds, data.waiting_on || null);
    if (data.title && data.tier) {
      appendLogOnce(acc, `Scenario created: ${data.title} (${data.tier})`);
    } else {
      const pc = (data.primary || []).length;
      const ac = (data.alternative || []).length;
      const dc = (data.dismissed || []).length;
      acc.scenarioSummary = { total: data.total || 0, primary: pc, alternative: ac, dismissed: dc };
      appendLogOnce(acc, `Scenarios: ${pc} primary, ${ac} alternative, ${dc} dismissed`);
      acc.liveScenarios = [
        ...(data.primary || []).map((s: any) => ({ ...s, tier: 'primary' as const })),
        ...(data.alternative || []).map((s: any) => ({ ...s, tier: 'alternative' as const })),
        ...(data.dismissed || []).map((s: any) => ({ ...s, tier: 'dismissed' as const })),
      ];
    }
  } else if (eventType === 'graph_update') {
    updateProgress(acc, 'graph_update', 'Assembling attribution graph', 'Assembling attribution graph.', data.elapsed_seconds ?? acc.elapsedSeconds, data.waiting_on || null);
    acc.graphStats = { entities: data.entities || 0, relationships: data.relationships || 0, facts: data.facts || 0 };
    appendLogOnce(acc, `Graph memory: ${data.entities} entities, ${data.relationships} rels`);
  } else if (eventType === 'debate') {
    acc.currentStep = 6;
    updateProgress(acc, 'debate', 'Asking agents to challenge the lead narrative', 'Running debate rounds.', data.elapsed_seconds ?? acc.elapsedSeconds, data.waiting_on || null);
    appendLogOnce(acc, `Debate round ${data.round}: ${data.surviving} surviving`);
  } else if (eventType === 'counterfactual') {
    acc.currentStep = 7;
    updateProgress(acc, 'counterfactual', 'Comparing supporting vs conflicting evidence', 'Testing counterfactuals.', data.elapsed_seconds ?? acc.elapsedSeconds, data.waiting_on || null);
    appendLogOnce(acc, `Counterfactual: ${data.tested} tested`);
  } else if (eventType === 'result') {
    acc.finalResult = data.final_result || data;
    updateProgress(acc, 'result', 'Assembling attribution graph', 'Finalizing attribution output.', data.elapsed_seconds ?? acc.elapsedSeconds, data.waiting_on || null);
    return 'skip'; // don't emit for result
  } else if (eventType === 'done' || eventType === 'run_completed') {
    return 'skip'; // terminal — handled by caller
  } else if (eventType === 'heartbeat') {
    updateProgress(
      acc,
      data.phase || acc.currentStageKey || 'still_working',
      data.phase_label || acc.currentStageLabel || 'Still working',
      data.detail || data.message || 'Still processing evidence.',
      data.elapsed_seconds ?? data.elapsed ?? acc.elapsedSeconds,
      data.waiting_on || acc.waitingOn,
    );
    const heartbeatSignature = `${acc.currentStageKey}|${acc.currentDetail}|${acc.waitingOn || ''}|${Math.floor(acc.elapsedSeconds)}`;
    if (acc.lastHeartbeatSignature !== heartbeatSignature) {
      appendLogOnce(acc, data.message || 'Still working');
      if (data.waiting_on === 'model_response') {
        appendLogOnce(acc, 'Waiting for model response');
      }
      acc.lastHeartbeatSignature = heartbeatSignature;
    }
  } else if (eventType === 'error') {
    // Notify callback, then signal terminal to caller
    callbacks.onError(data.error || 'Backend error');
    return 'terminal_error';
  } else {
    if (data?.phase_label || data?.message || data?.detail) {
      updateProgress(
        acc,
        data.phase || eventType,
        data.phase_label || acc.currentStageLabel,
        data.detail || data.message || acc.currentDetail,
        data.elapsed_seconds ?? acc.elapsedSeconds,
        data.waiting_on || acc.waitingOn,
      );
      if (data.message) appendLogOnce(acc, data.message);
    }
  }

  emitState(acc, callbacks);
  return 'continue';
}

/** Build an Attribution from accumulated state. */
function buildAttribution(acc: EventAccumulator): Attribution | null {
  const finalResult = acc.finalResult;
  if (!finalResult) return null;

  const rawHyps = finalResult.hypotheses || finalResult.agent_hypotheses || [];
  const hyps: Hypothesis[] = rawHyps.map((h: any) => ({
    agent: h.agent || h.agent_name || 'Unknown',
    agentRole: h.agentRole || '',
    cause: h.cause || h.hypothesis || '',
    reasoning: h.reasoning || h.causal_chain || '',
    confidence: typeof h.confidence === 'number' ? h.confidence : (typeof h.confidence_score === 'number' ? h.confidence_score : 0.5),
    confidenceFactors: h.confidenceFactors || h.temporal_plausibility || '',
    impactSpeed: h.impact_speed || h.impactSpeed || '',
    impactSpeedExplain: h.impactSpeedExplain || h.magnitude_plausibility || '',
    timeToPeak: h.time_to_peak || h.timeToPeak || '',
    timeToPeakExplain: h.timeToPeakExplain || h.temporal_plausibility || '',
    evidence: (h.evidence || []).map((e: any) => ({
      source: e.source || '', title: e.title || e.headline || (typeof e === 'string' ? e : ''),
      url: e.url || null, timestamp: e.timestamp || null, timing: e.timing || 'concurrent',
    })),
    counterfactual: h.counterfactual || '',
  }));

  let scenarios: Scenario[] = [];
  if (finalResult.scenarios?.length) {
    scenarios = finalResult.scenarios.map((s: any) => ({
      id: s.id || `scenario-${s.mechanism}`, label: s.label || '', mechanism: s.mechanism || 'other',
      tier: s.tier || 'primary', confidence: s.confidence || 0, lead_agent: s.lead_agent || '',
      supporting_agents: s.supporting_agents || [], challenging_agents: s.challenging_agents || [],
      evidence_chain: s.evidence_chain || [], evidence_urls: s.evidence_urls || [],
      what_breaks_this: s.what_breaks_this || '', causal_chain: s.causal_chain || '',
      temporal_fit: s.temporal_fit || '', impact_speed: s.impact_speed || '', time_to_peak: s.time_to_peak || '',
    }));
  } else if (acc.liveScenarios.length) {
    scenarios = acc.liveScenarios;
  }

  const md = finalResult.bace_metadata || {};
  const gov = finalResult.governance;
  return {
    depth: md.depth || 2,
    agentsSpawned: md.agents_spawned || hyps.length,
    hypothesesProposed: md.hypotheses_proposed || hyps.length,
    debateRounds: md.debate_rounds || 0,
    elapsed: md.elapsed_seconds || 0,
    hypotheses: hyps,
    scenarios,
    governance: gov ? { decision: gov.decision, reason: gov.reason, run_id: gov.run_id } : undefined,
    rawResult: finalResult,
  };
}

// ─── Legacy SSE stream (unchanged API) ──────────────────────────────

export async function runBACEStream(
  market: MarketResult,
  spike: Spike,
  callbacks: BACECallbacks,
): Promise<void> {
  const backendUrl = process.env.NEXT_PUBLIC_PYTHIA_API_URL || 'http://localhost:8000';
  const question = market.question || '';

  const params = new URLSearchParams({
    market_title: question,
    market_id: market.id || '',
    timestamp: spike.timestamp,
    direction: spike.direction,
    magnitude: spike.magnitude.toString(),
    price_before: spike.priceBefore.toString(),
    price_after: spike.priceAfter.toString(),
    depth: '2',
  });

  const res = await fetch(`${backendUrl}/api/attribute/stream?${params}`);
  if (!res.ok || !res.body) throw new Error('SSE not available');

  const acc = createAccumulator();
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    while (buffer.includes('\n\n')) {
      const idx = buffer.indexOf('\n\n');
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);

      let rawEventType = '';
      let eventDataParts: string[] = [];
      for (const line of block.split('\n')) {
        if (line.startsWith('event: ')) rawEventType = line.slice(7).trim();
        else if (line.startsWith('data: ')) eventDataParts.push(line.slice(6));
        else if (line.startsWith('data:')) eventDataParts.push(line.slice(5));
      }
      const eventData = eventDataParts.join('\n');
      if (!eventData) continue;

      let parsed: any;
      try { parsed = JSON.parse(eventData); } catch {
        if (rawEventType === 'error') { callbacks.onError(eventData); return; }
        continue;
      }

      const { eventType, data } = normalizeEvent(parsed, rawEventType);
      const result = applyEvent(eventType, data, acc, callbacks);
      if (result === 'terminal_error') return;
    }
  }

  // Flush buffer
  if (buffer.trim()) {
    try {
      let et = '', parts: string[] = [];
      for (const l of buffer.split('\n')) {
        if (l.startsWith('event: ')) et = l.slice(7).trim();
        else if (l.startsWith('data: ')) parts.push(l.slice(6));
        else if (l.startsWith('data:')) parts.push(l.slice(5));
      }
      if (et === 'result' && parts.join('\n')) acc.finalResult = JSON.parse(parts.join('\n'));
    } catch { /* ignore */ }
  }

  const attribution = buildAttribution(acc);
  if (attribution) {
    callbacks.onComplete(attribution);
  } else {
    callbacks.onError('SSE completed without result');
  }
}

// ─── Run-centric stream: live SSE or JSON replay ────────────────────

export interface ConnectRunStreamOptions {
  replay?: boolean;
  signal?: AbortSignal;
  /** Seed accumulator from existing store state (for reconnect). */
  initialAccumulator?: EventAccumulator;
}

export async function connectRunStream(
  runId: string,
  lastEventId: number,
  callbacks: BACECallbacks,
  options?: ConnectRunStreamOptions,
): Promise<void> {
  const backendUrl = process.env.NEXT_PUBLIC_PYTHIA_API_URL || 'http://localhost:8000';
  const signal = options?.signal;

  // ── JSON replay path (completed runs) ──
  if (options?.replay) {
    const url = `${backendUrl}/api/runs/${runId}/replay${lastEventId > 0 ? `?after_sequence=${lastEventId}` : ''}`;
    const res = await fetch(url, { signal });
    if (!res.ok) throw new Error(`Replay not available (${res.status})`);
    const body = await res.json();
    const events: any[] = body.events || [];

    const acc = options?.initialAccumulator ?? createAccumulator();
    for (const envelope of events) {
      const { eventType, data, sequence } = normalizeEvent(envelope, '');
      if (sequence !== null) callbacks.onSequence?.(sequence);
      const result = applyEvent(eventType, data, acc, callbacks);
      if (result === 'terminal_error') {
        throw new StreamTerminalError('Backend error during replay');
      }
    }

    // Emit final attribution if a result event was accumulated
    const attribution = buildAttribution(acc);
    if (attribution) callbacks.onComplete(attribution);
    return;
  }

  // ── Live SSE path (running runs) ──
  const headers: Record<string, string> = {};
  if (lastEventId > 0) {
    headers['Last-Event-ID'] = String(lastEventId);
  }

  const res = await fetch(`${backendUrl}/api/runs/${runId}/stream`, { headers, signal });
  if (!res.ok || !res.body) throw new Error(`SSE not available (${res.status})`);

  const acc = options?.initialAccumulator ?? createAccumulator();
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  // If the signal aborts, cancel the reader so reader.read() rejects
  const onAbort = () => { reader.cancel(); };
  signal?.addEventListener('abort', onAbort);

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      while (buffer.includes('\n\n')) {
        const idx = buffer.indexOf('\n\n');
        const block = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);

        let rawEventType = '';
        let eventDataParts: string[] = [];
        for (const line of block.split('\n')) {
          if (line.startsWith('event: ')) rawEventType = line.slice(7).trim();
          else if (line.startsWith('data: ')) eventDataParts.push(line.slice(6));
          else if (line.startsWith('data:')) eventDataParts.push(line.slice(5));
        }
        const eventData = eventDataParts.join('\n');
        if (!eventData) continue;

        let parsed: any;
        try { parsed = JSON.parse(eventData); } catch {
          if (rawEventType === 'error') {
            callbacks.onError(eventData);
            throw new StreamTerminalError(eventData);
          }
          continue;
        }

        const { eventType, data, sequence } = normalizeEvent(parsed, rawEventType);
        if (sequence !== null) callbacks.onSequence?.(sequence);
        const result = applyEvent(eventType, data, acc, callbacks);
        if (result === 'terminal_error') {
          throw new StreamTerminalError(data?.error || 'Backend error');
        }
      }
    }
  } finally {
    signal?.removeEventListener('abort', onAbort);
  }

  // Flush buffer
  if (buffer.trim()) {
    try {
      let et = '', parts: string[] = [];
      for (const l of buffer.split('\n')) {
        if (l.startsWith('event: ')) et = l.slice(7).trim();
        else if (l.startsWith('data: ')) parts.push(l.slice(6));
        else if (l.startsWith('data:')) parts.push(l.slice(5));
      }
      if (et === 'result' && parts.join('\n')) acc.finalResult = JSON.parse(parts.join('\n'));
    } catch { /* ignore */ }
  }

  const attribution = buildAttribution(acc);
  if (attribution) callbacks.onComplete(attribution);
  // For run streams, no result is ok — the run_completed event handles it
}
