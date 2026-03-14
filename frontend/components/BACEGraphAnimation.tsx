'use client';

import { useEffect, useState, useRef, useMemo, useCallback } from 'react';

// ─── Types ──────────────────────────────────────────────────────────

export interface BACEState {
  step: number;
  entities: string[];
  agentsActive: string[];
  debateLog: string[];
  counterfactualsTested: number;
  currentStageKey?: string;
  currentStageLabel?: string;
  currentDetail?: string;
  waitingOn?: string | null;
  elapsedSeconds?: number;
  lastBackendEventAtMs?: number | null;
}

/** Enriched state from new SSE events */
export interface BACEGraphState {
  // From ontology event
  ontologyEntities: OntologyEntity[];
  ontologyRelationships: OntologyRelationship[];
  // From agents event
  agents: AgentInfo[];
  // From proposal events — hypotheses per agent
  proposals: Map<string, ProposalHypothesis[]>;
  // From interaction event — convergence/divergence
  convergenceGroups: Map<string, string[]>; // label → [agent_ids]
  divergencePairs: DivergencePair[];
  // From graph_update event
  graphStats: { entities: number; relationships: number; facts: number } | null;
  // From scenarios event
  scenarioSummary: { total: number; primary: number; alternative: number; dismissed: number } | null;
  // Current step
  step: number;
}

export interface OntologyEntity {
  name: string;
  type: string; // Person, Organization, Policy, etc.
  relevance: number;
}

export interface OntologyRelationship {
  source: string;
  target: string;
  type: string; // announced, triggers, correlates_with, etc.
  strength: number;
}

export interface AgentInfo {
  id: string;
  name: string;
  tier: number;
  domain: string;
}

export interface ProposalHypothesis {
  cause: string;
  confidence: number;
}

export interface DivergencePair {
  hypothesis_id: string;
  proposed_by: string;
  challenged_by: string;
}

// ─── Constants ──────────────────────────────────────────────────────

const C = {
  bg: '#faf9f5', surface: '#FFFFFF', dark: '#141413', accent: '#d97757',
  yes: '#788c5d', muted: '#b0aea5', border: '#e8e6dc', info: '#6a9bcc',
  faint: '#f5f4ef',
};

const mono = "'JetBrains Mono', monospace";

const ENTITY_TYPE_COLORS: Record<string, string> = {
  'Person': '#e8a838',
  'Organization': '#4a90d9',
  'Policy': '#9b59b6',
  'DataRelease': '#2ecc71',
  'Market': '#e74c3c',
  'GeopoliticalEvent': '#1abc9c',
  'Narrative': '#f39c12',
  'FinancialInstrument': '#95a5a6',
  'TechEvent': '#3498db',
};

const ENTITY_TYPE_ICONS: Record<string, string> = {
  'Person': '👤',
  'Organization': '🏛',
  'Policy': '📜',
  'DataRelease': '📊',
  'Market': '📈',
  'GeopoliticalEvent': '🌍',
  'Narrative': '💬',
  'FinancialInstrument': '💰',
  'TechEvent': '⚙',
};

const AGENT_COLORS: Record<string, string> = {
  'macro-policy': '#4a90d9',
  'informed-flow': '#e8a838',
  'narrative-sentiment': '#9b59b6',
  'cross-market': '#2ecc71',
  'geopolitical': '#e74c3c',
  'devils-advocate': '#d97757',
  'null-hypothesis': '#95a5a6',
  'regulatory': '#1abc9c',
  'technical-microstructure': '#f39c12',
};

const RELATIONSHIP_COLORS: Record<string, string> = {
  'triggers': '#e74c3c',
  'announced': '#4a90d9',
  'correlates_with': '#2ecc71',
  'influences': '#9b59b6',
  'responded_to': '#e8a838',
  'preceded': '#95a5a6',
  'regulates': '#1abc9c',
  'contradicts': '#d97757',
  'amplifies': '#f39c12',
};

const STEP_LABELS = [
  'Building spike context',
  'Extracting causal ontology',
  'Gathering evidence',
  'Spawning agents',
  'Domain evidence',
  'Proposing hypotheses',
  'Agent cross-examination',
  'Scenario synthesis',
];

// ─── Force-directed simulation ──────────────────────────────────────

interface SimNode {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  fx: number;
  fy: number;
  type: 'spike' | 'entity' | 'agent' | 'hypothesis';
  label: string;
  color: string;
  radius: number;
  opacity: number;
  entityType?: string;
  agentId?: string;
  confidence?: number;
  isAdversarial?: boolean;
  // For convergence clustering
  clusterId?: string;
}

interface SimEdge {
  source: string;
  target: string;
  type: 'ontology' | 'agent-entity' | 'proposal' | 'convergence' | 'divergence';
  label: string;
  color: string;
  opacity: number;
  strength: number;
}

const W = 860;
const H = 480;
const CX = W / 2;
const CY = H / 2;

function clamp(val: number, min: number, max: number) {
  return Math.max(min, Math.min(max, val));
}

/** Simple force-directed tick — repulsion between all nodes, attraction along edges */
function forceTick(nodes: SimNode[], edges: SimEdge[], alpha: number = 0.3) {
  const nodeMap = new Map(nodes.map(n => [n.id, n]));

  // Repulsion — all pairs
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      let dx = b.x - a.x;
      let dy = b.y - a.y;
      let dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const minDist = (a.radius + b.radius) * 3;
      if (dist < minDist) {
        const force = (minDist - dist) / dist * 0.5 * alpha;
        const fx = dx * force;
        const fy = dy * force;
        a.vx -= fx; a.vy -= fy;
        b.vx += fx; b.vy += fy;
      }
      // Longer range repulsion
      const repForce = 800 * alpha / (dist * dist + 100);
      a.vx -= (dx / dist) * repForce;
      a.vy -= (dy / dist) * repForce;
      b.vx += (dx / dist) * repForce;
      b.vy += (dy / dist) * repForce;
    }
  }

  // Attraction along edges
  for (const edge of edges) {
    const s = nodeMap.get(edge.source);
    const t = nodeMap.get(edge.target);
    if (!s || !t) continue;
    let dx = t.x - s.x;
    let dy = t.y - s.y;
    let dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const idealDist = edge.type === 'ontology' ? 100 : edge.type === 'convergence' ? 60 : 120;
    const force = (dist - idealDist) / dist * 0.08 * alpha * edge.strength;
    const fx = dx * force;
    const fy = dy * force;
    s.vx += fx; s.vy += fy;
    t.vx -= fx; t.vy -= fy;
  }

  // Gravity toward center
  for (const n of nodes) {
    const dx = CX - n.x;
    const dy = CY - n.y;
    n.vx += dx * 0.002 * alpha;
    n.vy += dy * 0.002 * alpha;
  }

  // Apply velocity with damping
  for (const n of nodes) {
    // Fixed nodes (spike)
    if (n.type === 'spike') { n.x = CX; n.y = CY; n.vx = 0; n.vy = 0; continue; }
    n.vx *= 0.85;
    n.vy *= 0.85;
    n.x += n.vx;
    n.y += n.vy;
    // Boundary clamping
    n.x = clamp(n.x, 40, W - 40);
    n.y = clamp(n.y, 30, H - 30);
  }
}

// ─── Component ──────────────────────────────────────────────────────

interface BACEGraphAnimationProps {
  baceState: BACEState;
  graphState?: BACEGraphState;
}

export default function BACEGraphAnimation({ baceState, graphState }: BACEGraphAnimationProps) {
  const [nodes, setNodes] = useState<SimNode[]>([]);
  const [edges, setEdges] = useState<SimEdge[]>([]);
  const [statusText, setStatusText] = useState('');
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const nodesRef = useRef<SimNode[]>([]);
  const edgesRef = useRef<SimEdge[]>([]);
  const frameRef = useRef<number>(0);
  const tickRef = useRef(0);

  // Build graph incrementally from state
  useEffect(() => {
    const newNodes: SimNode[] = [...nodesRef.current];
    const newEdges: SimEdge[] = [...edgesRef.current];
    const existingIds = new Set(newNodes.map(n => n.id));
    const existingEdgeIds = new Set(newEdges.map(e => `${e.source}->${e.target}`));

    // Always ensure spike node
    if (!existingIds.has('spike')) {
      newNodes.push({
        id: 'spike', x: CX, y: CY, vx: 0, vy: 0, fx: 0, fy: 0,
        type: 'spike', label: '⚡ Spike', color: C.accent,
        radius: 18, opacity: 1,
      });
      existingIds.add('spike');
    }

    // === Ontology entities (from enriched graphState) ===
    if (graphState?.ontologyEntities) {
      for (const ent of graphState.ontologyEntities) {
        const nodeId = `ent-${ent.name.replace(/\s+/g, '-').toLowerCase()}`;
        if (existingIds.has(nodeId)) continue;
        const angle = Math.random() * Math.PI * 2;
        const dist = 80 + Math.random() * 60;
        newNodes.push({
          id: nodeId,
          x: CX + Math.cos(angle) * dist,
          y: CY + Math.sin(angle) * dist,
          vx: (Math.random() - 0.5) * 2,
          vy: (Math.random() - 0.5) * 2,
          fx: 0, fy: 0,
          type: 'entity',
          label: ent.name,
          color: ENTITY_TYPE_COLORS[ent.type] || C.dark,
          radius: 6 + ent.relevance * 6,
          opacity: 0.3 + ent.relevance * 0.7,
          entityType: ent.type,
        });
        existingIds.add(nodeId);
        // Connect to spike
        const edgeId = `spike->${nodeId}`;
        if (!existingEdgeIds.has(edgeId)) {
          newEdges.push({
            source: 'spike', target: nodeId, type: 'ontology',
            label: '', color: ENTITY_TYPE_COLORS[ent.type] || C.border,
            opacity: 0.2 + ent.relevance * 0.3, strength: 0.5 + ent.relevance * 0.5,
          });
          existingEdgeIds.add(edgeId);
        }
      }
    }

    // === Ontology relationships (entity-to-entity edges) ===
    if (graphState?.ontologyRelationships) {
      for (const rel of graphState.ontologyRelationships) {
        const srcId = `ent-${rel.source.replace(/\s+/g, '-').toLowerCase()}`;
        const tgtId = `ent-${rel.target.replace(/\s+/g, '-').toLowerCase()}`;
        if (!existingIds.has(srcId) || !existingIds.has(tgtId)) continue;
        const edgeId = `${srcId}->${tgtId}`;
        if (existingEdgeIds.has(edgeId)) continue;
        newEdges.push({
          source: srcId, target: tgtId, type: 'ontology',
          label: rel.type,
          color: RELATIONSHIP_COLORS[rel.type] || C.muted,
          opacity: 0.3 + rel.strength * 0.4,
          strength: rel.strength,
        });
        existingEdgeIds.add(edgeId);
      }
    }

    // === Agents ===
    if (graphState?.agents) {
      for (let i = 0; i < graphState.agents.length; i++) {
        const ag = graphState.agents[i];
        const nodeId = `agent-${ag.id}`;
        if (existingIds.has(nodeId)) continue;
        const angle = (i / graphState.agents.length) * Math.PI * 2 - Math.PI / 2;
        const dist = 180 + Math.random() * 40;
        newNodes.push({
          id: nodeId,
          x: CX + Math.cos(angle) * dist,
          y: CY + Math.sin(angle) * dist,
          vx: 0, vy: 0, fx: 0, fy: 0,
          type: 'agent',
          label: ag.name,
          color: AGENT_COLORS[ag.id] || C.info,
          radius: ag.tier === 1 ? 12 : 9,
          opacity: 0.9,
          agentId: ag.id,
          isAdversarial: ag.id === 'devils-advocate' || ag.id === 'null-hypothesis',
        });
        existingIds.add(nodeId);
      }
    }

    // === Proposals — add hypothesis nodes near their agent ===
    if (graphState?.proposals) {
      graphState.proposals.forEach((hyps, agentId) => {
        const agentNodeId = `agent-${agentId}`;
        const agentNode = newNodes.find(n => n.id === agentNodeId);
        if (!agentNode) return;

        hyps.forEach((hyp, hi) => {
          const nodeId = `hyp-${agentId}-${hi}`;
          if (existingIds.has(nodeId)) return;
          const offset = (hi - (hyps.length - 1) / 2) * 25;
          newNodes.push({
            id: nodeId,
            x: agentNode.x + 30 + Math.random() * 20,
            y: agentNode.y + offset,
            vx: (Math.random() - 0.5), vy: (Math.random() - 0.5),
            fx: 0, fy: 0,
            type: 'hypothesis',
            label: hyp.cause.length > 40 ? hyp.cause.slice(0, 37) + '…' : hyp.cause,
            color: hyp.confidence >= 0.6 ? C.yes : hyp.confidence >= 0.3 ? C.accent : C.muted,
            radius: 5 + hyp.confidence * 4,
            opacity: 0.5 + hyp.confidence * 0.5,
            confidence: hyp.confidence,
            agentId,
          });
          existingIds.add(nodeId);
          // Edge from agent to hypothesis
          const edgeId = `${agentNodeId}->${nodeId}`;
          if (!existingEdgeIds.has(edgeId)) {
            newEdges.push({
              source: agentNodeId, target: nodeId, type: 'proposal',
              label: `${Math.round(hyp.confidence * 100)}%`,
              color: AGENT_COLORS[agentId] || C.info,
              opacity: 0.4, strength: 0.8,
            });
            existingEdgeIds.add(edgeId);
          }
        });
      });
    }

    // === Convergence — pull agreeing agents together ===
    if (graphState?.convergenceGroups) {
      graphState.convergenceGroups.forEach((agentIds, label) => {
        for (let i = 0; i < agentIds.length; i++) {
          for (let j = i + 1; j < agentIds.length; j++) {
            const srcId = `agent-${agentIds[i]}`;
            const tgtId = `agent-${agentIds[j]}`;
            if (!existingIds.has(srcId) || !existingIds.has(tgtId)) continue;
            const edgeId = `${srcId}->${tgtId}`;
            if (existingEdgeIds.has(edgeId)) continue;
            newEdges.push({
              source: srcId, target: tgtId, type: 'convergence',
              label: 'agree',
              color: C.yes,
              opacity: 0.3,
              strength: 1.5, // Strong pull
            });
            existingEdgeIds.add(edgeId);
          }
        }
      });
    }

    // === Divergence — show conflict edges ===
    if (graphState?.divergencePairs) {
      for (const pair of graphState.divergencePairs) {
        const srcId = `agent-${pair.challenged_by}`;
        const tgtId = `agent-${pair.proposed_by}`;
        if (!existingIds.has(srcId) || !existingIds.has(tgtId)) continue;
        const edgeId = `${srcId}->${tgtId}`;
        if (existingEdgeIds.has(edgeId)) continue;
        newEdges.push({
          source: srcId, target: tgtId, type: 'divergence',
          label: 'challenges',
          color: C.accent,
          opacity: 0.5,
          strength: 0.3, // Weak — pushes apart implicitly via repulsion
        });
        existingEdgeIds.add(edgeId);
      }
    }

    // === Fallback: use basic baceState for entities/agents if no graphState ===
    if (!graphState && baceState.step >= 1) {
      for (const entName of baceState.entities) {
        const nodeId = `ent-${entName.replace(/\s+/g, '-').toLowerCase()}`;
        if (existingIds.has(nodeId)) continue;
        const angle = Math.random() * Math.PI * 2;
        const dist = 80 + Math.random() * 60;
        newNodes.push({
          id: nodeId,
          x: CX + Math.cos(angle) * dist,
          y: CY + Math.sin(angle) * dist,
          vx: (Math.random() - 0.5) * 2, vy: (Math.random() - 0.5) * 2,
          fx: 0, fy: 0,
          type: 'entity', label: entName,
          color: C.dark, radius: 8, opacity: 0.7,
        });
        existingIds.add(nodeId);
        if (!existingEdgeIds.has(`spike->${nodeId}`)) {
          newEdges.push({
            source: 'spike', target: nodeId, type: 'ontology',
            label: '', color: C.border, opacity: 0.3, strength: 0.7,
          });
          existingEdgeIds.add(`spike->${nodeId}`);
        }
      }
      for (let i = 0; i < baceState.agentsActive.length; i++) {
        const ag = baceState.agentsActive[i];
        const nodeId = `agent-${ag}`;
        if (existingIds.has(nodeId)) continue;
        const angle = (i / Math.max(baceState.agentsActive.length, 1)) * Math.PI * 2 - Math.PI / 2;
        newNodes.push({
          id: nodeId,
          x: CX + Math.cos(angle) * 200,
          y: CY + Math.sin(angle) * 140,
          vx: 0, vy: 0, fx: 0, fy: 0,
          type: 'agent', label: ag,
          color: AGENT_COLORS[ag] || C.info,
          radius: 10, opacity: 0.9, agentId: ag,
        });
        existingIds.add(nodeId);
      }
    }

    nodesRef.current = newNodes;
    edgesRef.current = newEdges;
    setNodes([...newNodes]);
    setEdges([...newEdges]);
  }, [baceState, graphState]);

  // Update status text
  useEffect(() => {
    setStatusText(STEP_LABELS[baceState.step] || 'Processing…');
  }, [baceState.step]);

  // Force simulation animation loop
  useEffect(() => {
    let running = true;
    const tick = () => {
      if (!running) return;
      tickRef.current++;
      const alpha = Math.max(0.01, 0.3 * Math.pow(0.995, tickRef.current));
      forceTick(nodesRef.current, edgesRef.current, alpha);
      // Only update React state every 2 frames for perf
      if (tickRef.current % 2 === 0) {
        setNodes([...nodesRef.current]);
      }
      frameRef.current = requestAnimationFrame(tick);
    };
    frameRef.current = requestAnimationFrame(tick);
    return () => { running = false; cancelAnimationFrame(frameRef.current); };
  }, []);

  // Reset tick counter when graph changes significantly
  useEffect(() => {
    tickRef.current = 0;
  }, [baceState.step]);

  const nodeMap = useMemo(() => {
    const map: Record<string, SimNode> = {};
    for (const n of nodes) map[n.id] = n;
    return map;
  }, [nodes]);

  const hoveredInfo = useMemo(() => {
    if (!hoveredNode) return null;
    const n = nodeMap[hoveredNode];
    if (!n) return null;
    // Find connected edges
    const connected = edges.filter(e => e.source === n.id || e.target === n.id);
    return { node: n, edges: connected };
  }, [hoveredNode, nodeMap, edges]);

  return (
    <div style={{ padding: '20px 0' }}>
      {/* Step progress bar */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20 }}>
        {STEP_LABELS.map((_, i) => (
          <div key={i} style={{
            flex: 1, height: 3, borderRadius: 2,
            background: i <= baceState.step ? C.accent : C.border,
            transition: 'background 0.3s',
          }} />
        ))}
      </div>

      {/* Status */}
      <div style={{
        fontFamily: mono, fontSize: 12, fontWeight: 600, color: C.accent,
        marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <span style={{
          width: 7, height: 7, borderRadius: '50%', background: C.accent,
          animation: 'pulse 1s infinite',
        }} />
        {statusText}
        {graphState?.graphStats && (
          <span style={{ color: C.muted, fontWeight: 400, marginLeft: 12 }}>
            Graph: {graphState.graphStats.entities} entities · {graphState.graphStats.relationships} rels
          </span>
        )}
        <style>{`@keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:0.3 } }`}</style>
      </div>

      {/* Graph SVG */}
      <div style={{
        background: C.surface,
        border: `1px solid ${C.border}`,
        borderRadius: 8,
        overflow: 'hidden',
        position: 'relative' as const,
      }}>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block' }}>
          <defs>
            <filter id="spike-glow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur in="SourceGraphic" stdDeviation="6" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
            <filter id="agent-glow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
            <marker id="arrow-conflict" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6" fill={C.accent} opacity={0.6} />
            </marker>
            <marker id="arrow-rel" markerWidth="5" markerHeight="5" refX="4" refY="2.5" orient="auto">
              <path d="M0,0 L5,2.5 L0,5" fill={C.muted} opacity={0.4} />
            </marker>
          </defs>

          {/* Background dots */}
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <circle cx="20" cy="20" r="0.5" fill={C.border} opacity={0.3} />
          </pattern>
          <rect width={W} height={H} fill="url(#grid)" />

          {/* Scanning/radar animation when waiting for data */}
          {nodes.length <= 1 && baceState.step <= 1 && (
            <>
              <circle cx={CX} cy={CY} r={60} fill="none" stroke={C.accent} strokeWidth={0.5} opacity={0.15}>
                <animate attributeName="r" from="20" to="140" dur="3s" repeatCount="indefinite" />
                <animate attributeName="opacity" from="0.3" to="0" dur="3s" repeatCount="indefinite" />
              </circle>
              <circle cx={CX} cy={CY} r={40} fill="none" stroke={C.accent} strokeWidth={0.5} opacity={0.15}>
                <animate attributeName="r" from="20" to="140" dur="3s" begin="1s" repeatCount="indefinite" />
                <animate attributeName="opacity" from="0.3" to="0" dur="3s" begin="1s" repeatCount="indefinite" />
              </circle>
              <circle cx={CX} cy={CY} r={20} fill="none" stroke={C.accent} strokeWidth={0.5} opacity={0.15}>
                <animate attributeName="r" from="20" to="140" dur="3s" begin="2s" repeatCount="indefinite" />
                <animate attributeName="opacity" from="0.3" to="0" dur="3s" begin="2s" repeatCount="indefinite" />
              </circle>
              <text x={CX} y={CY + 50} textAnchor="middle" fontSize={11} fontFamily={mono} fill={C.muted} opacity={0.6}>
                Scanning causal landscape…
              </text>
            </>
          )}

          {/* Edges */}
          {edges.map((edge, i) => {
            const src = nodeMap[edge.source];
            const tgt = nodeMap[edge.target];
            if (!src || !tgt) return null;

            const isConvergence = edge.type === 'convergence';
            const isDivergence = edge.type === 'divergence';
            const isOntology = edge.type === 'ontology';
            const isHighlighted = hoveredNode && (edge.source === hoveredNode || edge.target === hoveredNode);

            return (
              <g key={`e-${i}`}>
                <line
                  x1={src.x} y1={src.y} x2={tgt.x} y2={tgt.y}
                  stroke={isHighlighted ? edge.color : edge.color}
                  strokeWidth={isDivergence ? 1.5 : isConvergence ? 2 : isOntology && edge.label ? 1 : 0.8}
                  strokeOpacity={isHighlighted ? Math.min(edge.opacity + 0.3, 1) : edge.opacity}
                  strokeDasharray={isDivergence ? '4 3' : isConvergence ? '6 3' : isOntology && edge.label ? '2 2' : 'none'}
                  markerEnd={isDivergence ? 'url(#arrow-conflict)' : isOntology && edge.label ? 'url(#arrow-rel)' : undefined}
                />
                {/* Relationship label on ontology edges */}
                {isOntology && edge.label && (
                  <text
                    x={(src.x + tgt.x) / 2}
                    y={(src.y + tgt.y) / 2 - 4}
                    textAnchor="middle"
                    fontSize={8}
                    fontFamily={mono}
                    fill={edge.color}
                    opacity={isHighlighted ? 0.8 : 0.4}
                  >
                    {edge.label}
                  </text>
                )}
                {/* Convergence label */}
                {isConvergence && (
                  <text
                    x={(src.x + tgt.x) / 2}
                    y={(src.y + tgt.y) / 2 - 4}
                    textAnchor="middle"
                    fontSize={8}
                    fontFamily={mono}
                    fill={C.yes}
                    opacity={0.6}
                  >
                    ●
                  </text>
                )}
              </g>
            );
          })}

          {/* Nodes */}
          {nodes.map((node) => {
            const isSpike = node.type === 'spike';
            const isAgent = node.type === 'agent';
            const isEntity = node.type === 'entity';
            const isHyp = node.type === 'hypothesis';
            const isHovered = hoveredNode === node.id;

            return (
              <g
                key={node.id}
                onMouseEnter={() => setHoveredNode(node.id)}
                onMouseLeave={() => setHoveredNode(null)}
                style={{ cursor: 'pointer' }}
              >
                {/* Glow ring on hover */}
                {isHovered && (
                  <circle cx={node.x} cy={node.y} r={node.radius + 6}
                    fill="none" stroke={node.color} strokeWidth={1.5} opacity={0.3} />
                )}
                {/* Node circle */}
                <circle
                  cx={node.x} cy={node.y} r={node.radius}
                  fill={node.color}
                  opacity={node.opacity}
                  filter={isSpike ? 'url(#spike-glow)' : isAgent ? 'url(#agent-glow)' : undefined}
                  stroke={node.isAdversarial ? C.accent : 'none'}
                  strokeWidth={node.isAdversarial ? 2 : 0}
                  strokeDasharray={node.isAdversarial ? '3 2' : 'none'}
                />
                {/* Entity type icon */}
                {isEntity && node.entityType && (
                  <text x={node.x} y={node.y + 3} textAnchor="middle" fontSize={node.radius * 1.2}>
                    {ENTITY_TYPE_ICONS[node.entityType] || '•'}
                  </text>
                )}
                {/* Spike icon */}
                {isSpike && (
                  <text x={node.x} y={node.y + 5} textAnchor="middle" fontSize={16}>⚡</text>
                )}
                {/* Label — show on hover or for agents */}
                {(isHovered || isAgent || isSpike) && (
                  <text
                    x={node.x}
                    y={node.y + node.radius + 12}
                    textAnchor="middle"
                    fontSize={isAgent ? 10 : 9}
                    fontFamily={mono}
                    fontWeight={isAgent ? 600 : 400}
                    fill={C.dark}
                  >
                    {node.label.length > 24 ? node.label.slice(0, 21) + '…' : node.label}
                  </text>
                )}
                {/* Confidence badge for hypothesis nodes */}
                {isHyp && node.confidence !== undefined && (
                  <text
                    x={node.x + node.radius + 3}
                    y={node.y + 3}
                    fontSize={8}
                    fontFamily={mono}
                    fontWeight={700}
                    fill={node.color}
                  >
                    {Math.round(node.confidence * 100)}%
                  </text>
                )}
              </g>
            );
          })}
        </svg>

        {/* Hover tooltip */}
        {hoveredInfo && hoveredInfo.node.type !== 'spike' && (
          <div style={{
            position: 'absolute' as const,
            top: 8, right: 8,
            background: 'rgba(26,26,25,0.92)',
            color: '#e0ddd4',
            padding: '8px 12px',
            borderRadius: 6,
            fontFamily: mono,
            fontSize: 11,
            maxWidth: 240,
            pointerEvents: 'none' as const,
            lineHeight: 1.5,
            zIndex: 10,
          }}>
            <div style={{ fontWeight: 700, color: hoveredInfo.node.color, marginBottom: 2 }}>
              {hoveredInfo.node.label}
            </div>
            {hoveredInfo.node.entityType && (
              <div style={{ color: '#888' }}>{hoveredInfo.node.entityType}</div>
            )}
            {hoveredInfo.node.confidence !== undefined && (
              <div>Confidence: {Math.round(hoveredInfo.node.confidence * 100)}%</div>
            )}
            {hoveredInfo.edges.length > 0 && (
              <div style={{ marginTop: 4, color: '#777' }}>
                {hoveredInfo.edges.length} connection{hoveredInfo.edges.length !== 1 ? 's' : ''}
              </div>
            )}
          </div>
        )}

        {/* Legend */}
        <div style={{
          position: 'absolute' as const,
          bottom: 8, left: 8,
          display: 'flex', gap: 10, flexWrap: 'wrap' as const,
          fontFamily: mono, fontSize: 9, color: C.muted,
        }}>
          <span>⚡ Spike</span>
          <span style={{ color: C.dark }}>● Entity</span>
          <span style={{ color: C.info }}>● Agent</span>
          <span style={{ color: C.yes }}>— Agree</span>
          <span style={{ color: C.accent }}>⇢ Challenge</span>
        </div>
      </div>

      {/* Live log */}
      <div style={{
        background: '#1a1a19', borderRadius: 6, padding: '14px 16px',
        fontFamily: mono, fontSize: 12, lineHeight: 1.8,
        maxHeight: 240, overflowY: 'auto' as const, marginTop: 12,
      }}>
        {baceState.debateLog.length === 0 && (
          <div style={{ color: '#555', fontStyle: 'italic' as const }}>
            <span style={{ color: '#444', marginRight: 8 }}>{'>'}</span>
            Connecting to BACE engine — LLM warming up…
          </div>
        )}
        {baceState.debateLog.map((line, i) => {
          const isAgentName = line.startsWith('⟫ ');
          const isHypothesis = line.startsWith('  "') || line.startsWith('  ');
          const isRoundHeader = line.startsWith('━━');
          const isSimAction = /^[⚔✓↩✕📄↕⊕●•]/.test(line);
          const isChallenge = line.includes('CHALLENGE');
          const isSupport = line.includes('SUPPORT') || line.startsWith('✓');
          const isRebut = line.includes('REBUT');
          const isConcede = line.includes('CONCEDE') || line.includes('CONVERGED');
          const isResult = line.startsWith('Result:') || line.startsWith('Final') || line.startsWith('Simulation complete') || line.startsWith('Scenarios:');
          const isStatus = line.startsWith('Ontology:') || line.startsWith('News ') || line.startsWith('Spawned') || line.startsWith('Domain') || line.startsWith('Category') || line.startsWith('Generated') || line.startsWith('Initial') || line.startsWith('Debate') || line.startsWith('Graph ') || line.startsWith('Interaction') || line.startsWith('Convergence') || line.startsWith('Divergence');
          return (
            <div key={i} style={{
              color: isRoundHeader ? '#e8a838' :
                     isChallenge ? '#e8736a' :
                     isSupport ? '#a8c77a' :
                     isRebut ? '#7cb8e8' :
                     isConcede ? '#888' :
                     isAgentName ? '#7cb8e8' :
                     isSimAction ? '#c8c0a8' :
                     isHypothesis ? '#c8c0a8' :
                     isResult ? C.accent :
                     isStatus ? '#a8c77a' : '#7a7a6e',
              fontWeight: isAgentName || isRoundHeader ? 700 : isSimAction ? 500 : 400,
              fontStyle: (isHypothesis && !isSimAction) ? 'italic' as const : 'normal' as const,
              paddingLeft: isHypothesis && !isSimAction ? 12 : 0,
              marginTop: isAgentName || isRoundHeader ? 6 : 0,
              borderTop: isRoundHeader ? '1px solid #333' : 'none',
              paddingTop: isRoundHeader ? 6 : 0,
            }}>
              {!isAgentName && !isHypothesis && !isSimAction && !isRoundHeader && <span style={{ color: '#444', marginRight: 8 }}>{'>'}</span>}
              {isAgentName && <span style={{ color: '#556', marginRight: 6 }}>●</span>}
              {line.replace('⟫ ', '')}
            </div>
          );
        })}
        <span style={{ color: '#555', animation: 'blink 1s infinite' }}>▊</span>
        <style>{`@keyframes blink { 0%,100% { opacity:1 } 50% { opacity:0 } }`}</style>
      </div>
    </div>
  );
}
