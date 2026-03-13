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

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finalResult: any = null;
  let currentStep = 0;
  const liveEntities: string[] = [];
  const liveAgents: string[] = [];
  const liveLog: string[] = [];

  // Accumulated graph state
  let ontologyEntities: OntologyEntity[] = [];
  let ontologyRelationships: OntologyRelationship[] = [];
  let agents: AgentInfo[] = [];
  const proposals = new Map<string, ProposalHypothesis[]>();
  let convergenceGroups = new Map<string, string[]>();
  let divergencePairs: DivergencePair[] = [];
  let graphStats: { entities: number; relationships: number; facts: number } | null = null;
  let scenarioSummary: { total: number; primary: number; alternative: number; dismissed: number } | null = null;
  let liveScenarios: Scenario[] = [];

  function emitState() {
    callbacks.onBaceState({
      step: currentStep,
      entities: [...liveEntities],
      agentsActive: [...liveAgents],
      debateLog: liveLog.slice(-14),
      counterfactualsTested: currentStep >= 7 ? 1 : 0,
    });
    callbacks.onGraphState({
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

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    while (buffer.includes('\n\n')) {
      const idx = buffer.indexOf('\n\n');
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);

      let eventType = '';
      let eventDataParts: string[] = [];
      for (const line of block.split('\n')) {
        if (line.startsWith('event: ')) eventType = line.slice(7).trim();
        else if (line.startsWith('data: ')) eventDataParts.push(line.slice(6));
        else if (line.startsWith('data:')) eventDataParts.push(line.slice(5));
      }
      const eventData = eventDataParts.join('\n');
      if (!eventData) continue;

      let data: any;
      try { data = JSON.parse(eventData); } catch {
        if (eventType === 'error') { callbacks.onError(eventData); return; }
        continue;
      }

      if (eventType === 'context') {
        currentStep = 0;
        liveLog.push(`Category: ${data.category || 'general'}`);
        if (data.entities) for (const e of data.entities) if (!liveEntities.includes(e)) liveEntities.push(e);
      } else if (eventType === 'ontology') {
        currentStep = 1;
        liveLog.push(`Ontology: ${data.entity_count} entities, ${data.relationship_count} rels`);
        if (data.entities) {
          for (const name of data.entities) if (!liveEntities.includes(name)) liveEntities.push(name);
          ontologyEntities = data.entities.map((name: string, i: number) => ({
            name, type: 'Unknown', relevance: 1 - (i * 0.08),
          }));
        }
        if (data.full_entities) {
          ontologyEntities = data.full_entities.map((e: any) => ({
            name: e.name, type: e.entity_type || e.type || 'Unknown',
            relevance: e.relevance_score || e.relevance || 0.5,
          }));
        }
        if (data.full_relationships) {
          ontologyRelationships = data.full_relationships.map((r: any) => ({
            source: r.source_id || r.source || '', target: r.target_id || r.target || '',
            type: r.relationship_type || r.type || 'related', strength: r.strength || 0.5,
          }));
        }
        liveLog.push(`Generated ${data.search_queries || 0} search queries`);
      } else if (eventType === 'evidence') {
        currentStep = 2;
        liveLog.push(`News evidence: ${data.count} candidates`);
      } else if (eventType === 'agents') {
        currentStep = 3;
        agents = (data.agents || []).map((a: any) => ({
          id: a.id, name: a.name, tier: a.tier || 1, domain: a.domain || '',
        }));
        for (const a of agents) if (!liveAgents.includes(a.id)) liveAgents.push(a.id);
        liveLog.push(`Spawned ${data.count || agents.length} agents`);
      } else if (eventType === 'domain_evidence') {
        currentStep = 4;
        liveLog.push(`Domain evidence: ${data.count} items`);
      } else if (eventType === 'proposal') {
        currentStep = 5;
        const agentName = agents.find(a => a.id === data.agent)?.name || data.agent || 'Agent';
        const hyps = data.hypotheses || [];
        proposals.set(data.agent, hyps.map((h: any) => ({ cause: h.cause || '', confidence: h.confidence || 0 })));
        for (const h of hyps) {
          liveLog.push(`⟫ ${agentName}`);
          liveLog.push(`  "${(h.cause || '').slice(0, 90)}…" — ${Math.round((h.confidence || 0) * 100)}%`);
        }
      } else if (eventType === 'interaction') {
        currentStep = 6;
        const stances = data.stances || {};
        liveLog.push(`Interaction: ${stances.support || 0} support, ${stances.challenge || 0} challenges`);
        if (data.convergence_groups) liveLog.push(`Convergence: ${data.convergence_groups} groups`);
        if (data.convergence_group_details) convergenceGroups = new Map(Object.entries(data.convergence_group_details));
        if (data.top_challenges) {
          divergencePairs = data.top_challenges.map((tc: any) => ({
            hypothesis_id: tc.target || '',
            proposed_by: tc.target?.split('-h')[0] || '',
            challenged_by: tc.challenger?.replace(/\s+/g, '-').toLowerCase() || '',
          }));
        }
      // === New multi-round simulation events ===
      } else if (eventType === 'sim_round') {
        currentStep = 6;
        liveLog.push(`━━ Round ${data.round}/${data.total} — ${data.active_hypotheses} active hypotheses ━━`);
      } else if (eventType === 'sim_action') {
        currentStep = 6;
        const icon = data.action === 'CHALLENGE' ? '⚔' : data.action === 'SUPPORT' ? '✓' : data.action === 'REBUT' ? '↩' : data.action === 'CONCEDE' ? '✕' : data.action === 'PRESENT_EVIDENCE' ? '📄' : data.action === 'UPDATE_CONFIDENCE' ? '↕' : data.action === 'SYNTHESIZE' ? '⊕' : data.action === 'CONVERGED' ? '●' : '•';
        const confDelta = data.confidence_after !== data.confidence_before && data.confidence_before > 0
          ? ` (${data.confidence_after > data.confidence_before ? '+' : ''}${((data.confidence_after - data.confidence_before) * 100).toFixed(0)}%)`
          : '';
        liveLog.push(`${icon} [${data.agent_name}] ${data.action}${data.target_hyp ? ' → ' + data.target_hyp : ''}${confDelta}`);
        if (data.content) liveLog.push(`  ${data.content.slice(0, 100)}`);

        // Update divergence from challenges
        if (data.action === 'CHALLENGE' && data.target_agent && data.agent) {
          divergencePairs.push({
            hypothesis_id: data.target_hyp || '',
            proposed_by: data.target_agent || '',
            challenged_by: data.agent || '',
          });
        }
        // Update convergence from supports
        if (data.action === 'SUPPORT' && data.target_hyp) {
          const existing = convergenceGroups.get(data.target_hyp) || [];
          if (!existing.includes(data.agent)) {
            existing.push(data.agent);
            convergenceGroups.set(data.target_hyp, existing);
          }
        }
      } else if (eventType === 'sim_status') {
        currentStep = 6;
        // Status update — don't add to log, just update state
      } else if (eventType === 'sim_complete') {
        currentStep = 7;
        liveLog.push(`Simulation complete: ${data.total_actions} actions over ${data.rounds_completed} rounds`);
        liveLog.push(`${data.active_hypotheses} survived, ${data.conceded_hypotheses} conceded`);
        if (data.convergence_groups > 0) liveLog.push(`${data.convergence_groups} convergence groups, ${data.divergence_pairs} unresolved conflicts`);
      } else if (eventType === 'scenarios') {
        currentStep = 7;
        const pc = (data.primary || []).length;
        const ac = (data.alternative || []).length;
        const dc = (data.dismissed || []).length;
        scenarioSummary = { total: data.total || 0, primary: pc, alternative: ac, dismissed: dc };
        liveLog.push(`Scenarios: ${pc} primary, ${ac} alternative, ${dc} dismissed`);
        liveScenarios = [
          ...(data.primary || []).map((s: any) => ({ ...s, tier: 'primary' as const })),
          ...(data.alternative || []).map((s: any) => ({ ...s, tier: 'alternative' as const })),
          ...(data.dismissed || []).map((s: any) => ({ ...s, tier: 'dismissed' as const })),
        ];
      } else if (eventType === 'graph_update') {
        graphStats = { entities: data.entities || 0, relationships: data.relationships || 0, facts: data.facts || 0 };
        liveLog.push(`Graph memory: ${data.entities} entities, ${data.relationships} rels`);
      } else if (eventType === 'debate') {
        currentStep = 6;
        liveLog.push(`Debate round ${data.round}: ${data.surviving} surviving`);
      } else if (eventType === 'counterfactual') {
        currentStep = 7;
        liveLog.push(`Counterfactual: ${data.tested} tested`);
      } else if (eventType === 'result') {
        finalResult = data;
      } else if (eventType === 'done') {
        // stream complete
      } else if (eventType === 'heartbeat') {
        // keepalive — no UI update needed, just prevents connection timeout
      } else if (eventType === 'error') {
        callbacks.onError(data.error || 'Backend error');
        return;
      }

      if (eventType !== 'result' && eventType !== 'done') emitState();
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
      if (et === 'result' && parts.join('\n')) finalResult = JSON.parse(parts.join('\n'));
    } catch { /* ignore */ }
  }

  if (finalResult) {
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
    } else if (liveScenarios.length) {
      scenarios = liveScenarios;
    }

    const md = finalResult.bace_metadata || {};
    const gov = finalResult.governance;
    callbacks.onComplete({
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
  } else {
    callbacks.onError('SSE completed without result');
  }
}

// ─── Run-centric SSE stream with canonical envelope parsing ──────

export async function connectRunStream(
  runId: string,
  lastEventId: number,
  callbacks: BACECallbacks,
  options?: { replay?: boolean },
): Promise<void> {
  const backendUrl = process.env.NEXT_PUBLIC_PYTHIA_API_URL || 'http://localhost:8000';
  const endpoint = options?.replay
    ? `${backendUrl}/api/runs/${runId}/replay`
    : `${backendUrl}/api/runs/${runId}/stream`;

  const headers: Record<string, string> = {};
  if (!options?.replay && lastEventId > 0) {
    headers['Last-Event-ID'] = String(lastEventId);
  }

  const res = await fetch(endpoint, { headers });
  if (!res.ok || !res.body) throw new Error(`SSE not available (${res.status})`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finalResult: any = null;
  let currentStep = 0;
  const liveEntities: string[] = [];
  const liveAgents: string[] = [];
  const liveLog: string[] = [];

  let ontologyEntities: OntologyEntity[] = [];
  let ontologyRelationships: OntologyRelationship[] = [];
  let agents: AgentInfo[] = [];
  const proposals = new Map<string, ProposalHypothesis[]>();
  let convergenceGroups = new Map<string, string[]>();
  let divergencePairs: DivergencePair[] = [];
  let graphStats: { entities: number; relationships: number; facts: number } | null = null;
  let scenarioSummary: { total: number; primary: number; alternative: number; dismissed: number } | null = null;
  let liveScenarios: Scenario[] = [];

  function emitState() {
    callbacks.onBaceState({
      step: currentStep,
      entities: [...liveEntities],
      agentsActive: [...liveAgents],
      debateLog: liveLog.slice(-14),
      counterfactualsTested: currentStep >= 7 ? 1 : 0,
    });
    callbacks.onGraphState({
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

      // Canonical envelope: { event_id, run_id, stage, event_type, sequence, payload, timestamp }
      // Detect envelope by presence of event_type + payload
      let eventType: string;
      let data: any;
      if (parsed.event_type !== undefined && parsed.payload !== undefined) {
        eventType = parsed.event_type;
        data = parsed.payload;
        if (parsed.sequence !== undefined) {
          callbacks.onSequence?.(parsed.sequence);
        }
      } else {
        // Legacy format — use raw SSE event type and parsed data directly
        eventType = rawEventType;
        data = parsed;
      }

      // All event handling branches below are identical to runBACEStream
      if (eventType === 'context') {
        currentStep = 0;
        liveLog.push(`Category: ${data.category || 'general'}`);
        if (data.entities) for (const e of data.entities) if (!liveEntities.includes(e)) liveEntities.push(e);
      } else if (eventType === 'ontology') {
        currentStep = 1;
        liveLog.push(`Ontology: ${data.entity_count} entities, ${data.relationship_count} rels`);
        if (data.entities) {
          for (const name of data.entities) if (!liveEntities.includes(name)) liveEntities.push(name);
          ontologyEntities = data.entities.map((name: string, i: number) => ({
            name, type: 'Unknown', relevance: 1 - (i * 0.08),
          }));
        }
        if (data.full_entities) {
          ontologyEntities = data.full_entities.map((e: any) => ({
            name: e.name, type: e.entity_type || e.type || 'Unknown',
            relevance: e.relevance_score || e.relevance || 0.5,
          }));
        }
        if (data.full_relationships) {
          ontologyRelationships = data.full_relationships.map((r: any) => ({
            source: r.source_id || r.source || '', target: r.target_id || r.target || '',
            type: r.relationship_type || r.type || 'related', strength: r.strength || 0.5,
          }));
        }
        liveLog.push(`Generated ${data.search_queries || 0} search queries`);
      } else if (eventType === 'evidence') {
        currentStep = 2;
        liveLog.push(`News evidence: ${data.count} candidates`);
      } else if (eventType === 'agents') {
        currentStep = 3;
        agents = (data.agents || []).map((a: any) => ({
          id: a.id, name: a.name, tier: a.tier || 1, domain: a.domain || '',
        }));
        for (const a of agents) if (!liveAgents.includes(a.id)) liveAgents.push(a.id);
        liveLog.push(`Spawned ${data.count || agents.length} agents`);
      } else if (eventType === 'domain_evidence') {
        currentStep = 4;
        liveLog.push(`Domain evidence: ${data.count} items`);
      } else if (eventType === 'proposal') {
        currentStep = 5;
        const agentName = agents.find(a => a.id === data.agent)?.name || data.agent || 'Agent';
        const hyps = data.hypotheses || [];
        proposals.set(data.agent, hyps.map((h: any) => ({ cause: h.cause || '', confidence: h.confidence || 0 })));
        for (const h of hyps) {
          liveLog.push(`\u27EB ${agentName}`);
          liveLog.push(`  "${(h.cause || '').slice(0, 90)}\u2026" \u2014 ${Math.round((h.confidence || 0) * 100)}%`);
        }
      } else if (eventType === 'interaction') {
        currentStep = 6;
        const stances = data.stances || {};
        liveLog.push(`Interaction: ${stances.support || 0} support, ${stances.challenge || 0} challenges`);
        if (data.convergence_groups) liveLog.push(`Convergence: ${data.convergence_groups} groups`);
        if (data.convergence_group_details) convergenceGroups = new Map(Object.entries(data.convergence_group_details));
        if (data.top_challenges) {
          divergencePairs = data.top_challenges.map((tc: any) => ({
            hypothesis_id: tc.target || '',
            proposed_by: tc.target?.split('-h')[0] || '',
            challenged_by: tc.challenger?.replace(/\s+/g, '-').toLowerCase() || '',
          }));
        }
      } else if (eventType === 'sim_round') {
        currentStep = 6;
        liveLog.push(`\u2501\u2501 Round ${data.round}/${data.total} \u2014 ${data.active_hypotheses} active hypotheses \u2501\u2501`);
      } else if (eventType === 'sim_action') {
        currentStep = 6;
        const icon = data.action === 'CHALLENGE' ? '\u2694' : data.action === 'SUPPORT' ? '\u2713' : data.action === 'REBUT' ? '\u21A9' : data.action === 'CONCEDE' ? '\u2715' : data.action === 'PRESENT_EVIDENCE' ? '\uD83D\uDCC4' : data.action === 'UPDATE_CONFIDENCE' ? '\u2195' : data.action === 'SYNTHESIZE' ? '\u2295' : data.action === 'CONVERGED' ? '\u25CF' : '\u2022';
        const confDelta = data.confidence_after !== data.confidence_before && data.confidence_before > 0
          ? ` (${data.confidence_after > data.confidence_before ? '+' : ''}${((data.confidence_after - data.confidence_before) * 100).toFixed(0)}%)`
          : '';
        liveLog.push(`${icon} [${data.agent_name}] ${data.action}${data.target_hyp ? ' \u2192 ' + data.target_hyp : ''}${confDelta}`);
        if (data.content) liveLog.push(`  ${data.content.slice(0, 100)}`);
        if (data.action === 'CHALLENGE' && data.target_agent && data.agent) {
          divergencePairs.push({
            hypothesis_id: data.target_hyp || '',
            proposed_by: data.target_agent || '',
            challenged_by: data.agent || '',
          });
        }
        if (data.action === 'SUPPORT' && data.target_hyp) {
          const existing = convergenceGroups.get(data.target_hyp) || [];
          if (!existing.includes(data.agent)) {
            existing.push(data.agent);
            convergenceGroups.set(data.target_hyp, existing);
          }
        }
      } else if (eventType === 'sim_status') {
        currentStep = 6;
      } else if (eventType === 'sim_complete') {
        currentStep = 7;
        liveLog.push(`Simulation complete: ${data.total_actions} actions over ${data.rounds_completed} rounds`);
        liveLog.push(`${data.active_hypotheses} survived, ${data.conceded_hypotheses} conceded`);
        if (data.convergence_groups > 0) liveLog.push(`${data.convergence_groups} convergence groups, ${data.divergence_pairs} unresolved conflicts`);
      } else if (eventType === 'scenarios') {
        currentStep = 7;
        const pc = (data.primary || []).length;
        const ac = (data.alternative || []).length;
        const dc = (data.dismissed || []).length;
        scenarioSummary = { total: data.total || 0, primary: pc, alternative: ac, dismissed: dc };
        liveLog.push(`Scenarios: ${pc} primary, ${ac} alternative, ${dc} dismissed`);
        liveScenarios = [
          ...(data.primary || []).map((s: any) => ({ ...s, tier: 'primary' as const })),
          ...(data.alternative || []).map((s: any) => ({ ...s, tier: 'alternative' as const })),
          ...(data.dismissed || []).map((s: any) => ({ ...s, tier: 'dismissed' as const })),
        ];
      } else if (eventType === 'graph_update') {
        graphStats = { entities: data.entities || 0, relationships: data.relationships || 0, facts: data.facts || 0 };
        liveLog.push(`Graph memory: ${data.entities} entities, ${data.relationships} rels`);
      } else if (eventType === 'debate') {
        currentStep = 6;
        liveLog.push(`Debate round ${data.round}: ${data.surviving} surviving`);
      } else if (eventType === 'counterfactual') {
        currentStep = 7;
        liveLog.push(`Counterfactual: ${data.tested} tested`);
      } else if (eventType === 'result') {
        finalResult = data;
      } else if (eventType === 'done' || eventType === 'run_completed') {
        // stream complete
      } else if (eventType === 'heartbeat') {
        continue;
      } else if (eventType === 'error') {
        callbacks.onError(data.error || 'Backend error');
        return;
      }

      if (eventType !== 'result' && eventType !== 'done' && eventType !== 'run_completed') emitState();
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
      if (et === 'result' && parts.join('\n')) finalResult = JSON.parse(parts.join('\n'));
    } catch { /* ignore */ }
  }

  if (finalResult) {
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
    } else if (liveScenarios.length) {
      scenarios = liveScenarios;
    }

    const md = finalResult.bace_metadata || {};
    const gov = finalResult.governance;
    callbacks.onComplete({
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
  }
  // For run streams, no result is ok — the run_completed event handles it
}
