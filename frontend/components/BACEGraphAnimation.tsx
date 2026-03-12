'use client';

import { useEffect, useState, useRef, useMemo, useCallback } from 'react';

// ─── Types ──────────────────────────────────────────────────────────

interface BACEState {
  step: number;
  entities: string[];
  agentsActive: string[];
  debateLog: string[];
  counterfactualsTested: number;
}

interface GraphNode {
  id: string;
  label: string;
  type: 'spike' | 'entity' | 'agent' | 'hypothesis' | 'evidence';
  x: number;
  y: number;
  radius: number;
  color: string;
  opacity: number;
  domain?: string;
  confidence?: number;
  isAdversarial?: boolean;
  agentId?: string;
}

interface GraphEdge {
  source: string;
  target: string;
  type: 'entity-link' | 'agent-entity' | 'proposal' | 'debate' | 'evidence-link';
  color: string;
  opacity: number;
  animated?: boolean;
  label?: string;
}

// ─── Constants ──────────────────────────────────────────────────────

const C = {
  bg: '#faf9f5', surface: '#FFFFFF', dark: '#141413', accent: '#d97757',
  yes: '#788c5d', muted: '#b0aea5', border: '#e8e6dc', info: '#6a9bcc',
  faint: '#f5f4ef',
};

const mono = "'JetBrains Mono', monospace";

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

const AGENT_ICONS: Record<string, string> = {
  'macro-policy': '📊',
  'informed-flow': '🐋',
  'narrative-sentiment': '📡',
  'cross-market': '🔗',
  'geopolitical': '🌍',
  'devils-advocate': '⚔',
  'null-hypothesis': 'ℍ',
  'regulatory': '⚖',
  'technical-microstructure': '📈',
};

const STEP_LABELS = [
  'Building spike context',
  'Extracting causal ontology',
  'Gathering evidence',
  'Spawning agents',
  'Domain evidence',
  'Proposing hypotheses',
  'Cross-examination',
  'Scoring & synthesis',
];

// ─── Layout helpers ─────────────────────────────────────────────────

const W = 860;
const H = 480;
const CX = W / 2;
const CY = H / 2;

function entityPosition(index: number, total: number): { x: number; y: number } {
  // Entities orbit the spike node in an ellipse
  const angle = (index / Math.max(total, 1)) * Math.PI * 2 - Math.PI / 2;
  const rx = 120;
  const ry = 80;
  return {
    x: CX + Math.cos(angle) * rx,
    y: CY + Math.sin(angle) * ry,
  };
}

function agentPosition(index: number, total: number): { x: number; y: number } {
  // Agents form a wider ring
  const angle = (index / Math.max(total, 1)) * Math.PI * 2 - Math.PI / 2;
  const rx = 280;
  const ry = 180;
  return {
    x: CX + Math.cos(angle) * rx,
    y: CY + Math.sin(angle) * ry,
  };
}

function hypothesisPosition(agentX: number, agentY: number, index: number): { x: number; y: number } {
  // Hypotheses appear near their agent, offset outward
  const dx = agentX - CX;
  const dy = agentY - CY;
  const dist = Math.sqrt(dx * dx + dy * dy) || 1;
  const nx = dx / dist;
  const ny = dy / dist;
  // Stagger multiple hypotheses
  const perpX = -ny;
  const perpY = nx;
  const offset = (index - 0.5) * 30;
  return {
    x: agentX + nx * 55 + perpX * offset,
    y: agentY + ny * 55 + perpY * offset,
  };
}

// ─── Component ──────────────────────────────────────────────────────

export default function BACEGraphAnimation({ baceState }: { baceState: BACEState }) {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [particles, setParticles] = useState<{ id: string; edge: string; progress: number }[]>([]);
  const [statusText, setStatusText] = useState('');
  const prevStepRef = useRef(-1);
  const animFrameRef = useRef<number>(0);

  // Build graph from BACE state
  useEffect(() => {
    const newNodes: GraphNode[] = [];
    const newEdges: GraphEdge[] = [];

    // Central spike node — always present
    newNodes.push({
      id: 'spike',
      label: '⚡ Spike',
      type: 'spike',
      x: CX,
      y: CY,
      radius: 18,
      color: C.accent,
      opacity: 1,
    });

    // Entities (step >= 1)
    if (baceState.step >= 1 && baceState.entities.length > 0) {
      baceState.entities.forEach((ent, i) => {
        const pos = entityPosition(i, baceState.entities.length);
        const nodeId = `entity-${i}`;
        newNodes.push({
          id: nodeId,
          label: ent,
          type: 'entity',
          ...pos,
          radius: 8,
          color: C.dark,
          opacity: baceState.step >= 2 ? 1 : 0.6,
        });
        newEdges.push({
          source: 'spike',
          target: nodeId,
          type: 'entity-link',
          color: C.border,
          opacity: 0.5,
        });
      });
    }

    // Agents (step >= 3)
    if (baceState.step >= 3 && baceState.agentsActive.length > 0) {
      baceState.agentsActive.forEach((agentName, i) => {
        const pos = agentPosition(i, baceState.agentsActive.length);
        const agentId = agentName.toLowerCase().replace(/[^a-z]+/g, '-');
        const isAdv = agentName === "Devil's Advocate" || agentName === 'Null Hypothesis';

        newNodes.push({
          id: `agent-${i}`,
          label: agentName,
          type: 'agent',
          ...pos,
          radius: 14,
          color: AGENT_COLORS[agentId] || (isAdv ? C.accent : C.info),
          opacity: 1,
          domain: agentId,
          isAdversarial: isAdv,
          agentId,
        });

        // Connect agents to most relevant entity
        if (baceState.entities.length > 0) {
          const entIdx = i % baceState.entities.length;
          newEdges.push({
            source: `agent-${i}`,
            target: `entity-${entIdx}`,
            type: 'agent-entity',
            color: AGENT_COLORS[agentId] || C.info,
            opacity: 0.3,
            animated: baceState.step >= 5,
          });
        }
      });
    }

    // Parse hypotheses from debateLog (step >= 5)
    if (baceState.step >= 5) {
      let hypIdx = 0;
      baceState.debateLog.forEach((line) => {
        if (line.startsWith('⟫ ')) {
          const agentName = line.replace('⟫ ', '');
          const agentIdx = baceState.agentsActive.findIndex(a => a === agentName);
          if (agentIdx >= 0) {
            const agentPos = agentPosition(agentIdx, baceState.agentsActive.length);
            const hypPos = hypothesisPosition(agentPos.x, agentPos.y, hypIdx);
            const agentId = agentName.toLowerCase().replace(/[^a-z]+/g, '-');

            newNodes.push({
              id: `hyp-${hypIdx}`,
              label: `H${hypIdx + 1}`,
              type: 'hypothesis',
              ...hypPos,
              radius: 7,
              color: AGENT_COLORS[agentId] || C.info,
              opacity: 0.8,
              agentId,
            });

            newEdges.push({
              source: `agent-${agentIdx}`,
              target: `hyp-${hypIdx}`,
              type: 'proposal',
              color: AGENT_COLORS[agentId] || C.info,
              opacity: 0.5,
              animated: true,
            });

            hypIdx++;
          }
        }
      });

      // Debate connections (step >= 6): adversarial agents challenge others
      if (baceState.step >= 6) {
        const adversarialIndices = baceState.agentsActive
          .map((a, i) => ({ name: a, idx: i }))
          .filter(a => a.name === "Devil's Advocate" || a.name === 'Null Hypothesis');

        const normalIndices = baceState.agentsActive
          .map((a, i) => ({ name: a, idx: i }))
          .filter(a => a.name !== "Devil's Advocate" && a.name !== 'Null Hypothesis');

        for (const adv of adversarialIndices) {
          for (const norm of normalIndices) {
            newEdges.push({
              source: `agent-${adv.idx}`,
              target: `agent-${norm.idx}`,
              type: 'debate',
              color: C.accent + '60',
              opacity: 0.3,
              animated: true,
              label: '⚔',
            });
          }
        }
      }
    }

    setNodes(newNodes);
    setEdges(newEdges);
    setStatusText(`Step ${baceState.step + 1}/8: ${STEP_LABELS[baceState.step] || 'Processing'}`);
    prevStepRef.current = baceState.step;
  }, [baceState]);

  // Particle animation for active edges
  useEffect(() => {
    let running = true;
    const animate = () => {
      if (!running) return;
      setParticles(prev => {
        const animatedEdges = edges.filter(e => e.animated);
        if (animatedEdges.length === 0) return [];

        // Generate particles for animated edges
        const next = animatedEdges.map((e, i) => {
          const existing = prev.find(p => p.edge === `${e.source}-${e.target}`);
          const progress = existing ? (existing.progress + 0.008) % 1 : (i * 0.15) % 1;
          return {
            id: `p-${e.source}-${e.target}`,
            edge: `${e.source}-${e.target}`,
            progress,
          };
        });
        return next;
      });
      animFrameRef.current = requestAnimationFrame(animate);
    };
    animFrameRef.current = requestAnimationFrame(animate);
    return () => { running = false; cancelAnimationFrame(animFrameRef.current); };
  }, [edges]);

  // Find node position by id
  const nodeMap = useMemo(() => {
    const m: Record<string, GraphNode> = {};
    for (const n of nodes) m[n.id] = n;
    return m;
  }, [nodes]);

  return (
    <div style={{ padding: '20px 0' }}>
      {/* Step progress bar */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
        {STEP_LABELS.map((_, i) => (
          <div key={i} style={{
            flex: 1, height: 3, borderRadius: 2,
            background: i <= baceState.step ? C.accent : C.border,
            transition: 'background 0.3s',
          }} />
        ))}
      </div>

      {/* Status label */}
      <div style={{
        fontFamily: mono, fontSize: 12, fontWeight: 600, color: C.accent,
        marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <span style={{
          width: 7, height: 7, borderRadius: '50%', background: C.accent,
          animation: 'pulse 1s infinite',
        }} />
        {statusText}
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
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          style={{ display: 'block' }}
        >
          <defs>
            {/* Glow filter for spike node */}
            <filter id="spike-glow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur in="SourceGraphic" stdDeviation="6" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>

            {/* Pulse animation for active nodes */}
            <filter id="agent-glow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>

            {/* Arrow marker for debate edges */}
            <marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6" fill={C.accent} opacity={0.4} />
            </marker>
          </defs>

          {/* Background grid pattern */}
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <circle cx="20" cy="20" r="0.5" fill={C.border} opacity={0.3} />
          </pattern>
          <rect width={W} height={H} fill="url(#grid)" />

          {/* Edges */}
          {edges.map((edge, i) => {
            const src = nodeMap[edge.source];
            const tgt = nodeMap[edge.target];
            if (!src || !tgt) return null;

            const isDebate = edge.type === 'debate';

            return (
              <g key={`e-${i}`}>
                <line
                  x1={src.x} y1={src.y} x2={tgt.x} y2={tgt.y}
                  stroke={edge.color}
                  strokeWidth={isDebate ? 1 : edge.type === 'proposal' ? 1.5 : 1}
                  strokeOpacity={edge.opacity}
                  strokeDasharray={isDebate ? '4 4' : edge.type === 'agent-entity' ? '2 3' : 'none'}
                  markerEnd={isDebate ? 'url(#arrow)' : undefined}
                  style={{
                    transition: 'all 0.5s ease-out',
                  }}
                />
              </g>
            );
          })}

          {/* Particles traveling along animated edges */}
          {particles.map(p => {
            const [srcId, tgtId] = p.edge.split('-').length === 2
              ? p.edge.split('-')
              : (() => {
                  // Handle compound IDs like "agent-0" -> split on first dash after edge format
                  const parts = p.edge.match(/^(.+?)-(.+)$/);
                  return parts ? [parts[1], parts[2]] : ['', ''];
                })();
            // Re-derive source and target from edges
            const matchEdge = edges.find(e => `${e.source}-${e.target}` === p.edge);
            if (!matchEdge) return null;
            const src = nodeMap[matchEdge.source];
            const tgt = nodeMap[matchEdge.target];
            if (!src || !tgt) return null;

            const px = src.x + (tgt.x - src.x) * p.progress;
            const py = src.y + (tgt.y - src.y) * p.progress;

            return (
              <circle
                key={p.id}
                cx={px} cy={py} r={2}
                fill={matchEdge.color}
                opacity={0.7}
              />
            );
          })}

          {/* Nodes */}
          {nodes.map((node) => {
            const isSpike = node.type === 'spike';
            const isAgent = node.type === 'agent';
            const isHyp = node.type === 'hypothesis';

            return (
              <g key={node.id} style={{
                transition: 'transform 0.6s cubic-bezier(0.16, 1, 0.3, 1)',
                animation: isSpike ? undefined :
                  `fadeInNode 0.5s ease-out`,
              }}>
                {/* Node circle */}
                <circle
                  cx={node.x} cy={node.y} r={node.radius}
                  fill={isSpike ? C.accent : isAgent ? node.color : isHyp ? node.color : C.dark}
                  opacity={node.opacity}
                  filter={isSpike ? 'url(#spike-glow)' : isAgent ? 'url(#agent-glow)' : undefined}
                  stroke={isAgent && node.isAdversarial ? C.accent : 'none'}
                  strokeWidth={isAgent && node.isAdversarial ? 2 : 0}
                  strokeDasharray={isAgent && node.isAdversarial ? '3 2' : 'none'}
                />

                {/* Agent icon */}
                {isAgent && node.agentId && (
                  <text
                    x={node.x} y={node.y + 1}
                    textAnchor="middle" dominantBaseline="central"
                    fontSize={11}
                    style={{ pointerEvents: 'none' }}
                  >
                    {AGENT_ICONS[node.agentId] || '🤖'}
                  </text>
                )}

                {/* Spike icon */}
                {isSpike && (
                  <text
                    x={node.x} y={node.y + 1}
                    textAnchor="middle" dominantBaseline="central"
                    fontSize={14} fill="#fff"
                    style={{ pointerEvents: 'none' }}
                  >
                    ⚡
                  </text>
                )}

                {/* Hypothesis label */}
                {isHyp && (
                  <text
                    x={node.x} y={node.y + 1}
                    textAnchor="middle" dominantBaseline="central"
                    fontSize={8} fontFamily={mono} fontWeight={700}
                    fill="#fff"
                    style={{ pointerEvents: 'none' }}
                  >
                    {node.label}
                  </text>
                )}

                {/* Node label */}
                <text
                  x={node.x}
                  y={node.y + node.radius + 12}
                  textAnchor="middle"
                  fontSize={isAgent ? 10 : isSpike ? 11 : 9}
                  fontFamily={mono}
                  fontWeight={isAgent || isSpike ? 600 : 400}
                  fill={isSpike ? C.accent : isAgent ? node.color : C.muted}
                  opacity={node.opacity}
                  style={{ pointerEvents: 'none' }}
                >
                  {node.label.length > 20 ? node.label.slice(0, 18) + '…' : node.label}
                </text>
              </g>
            );
          })}

          <style>{`
            @keyframes fadeInNode {
              from { opacity: 0; transform: scale(0.5); }
              to { opacity: 1; transform: scale(1); }
            }
          `}</style>
        </svg>
      </div>

      {/* Entity & agent pills below the graph */}
      <div style={{ marginTop: 12, display: 'flex', gap: 16, flexWrap: 'wrap' as const }}>
        {/* Entities */}
        {baceState.entities.length > 0 && (
          <div style={{ flex: '1 1 200px' }}>
            <div style={{
              fontFamily: mono, fontSize: 10,
              textTransform: 'uppercase' as const, letterSpacing: 1,
              color: C.muted, marginBottom: 6,
            }}>
              Entities ({baceState.entities.length})
            </div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' as const }}>
              {baceState.entities.map((e, i) => (
                <span key={i} style={{
                  fontFamily: mono, fontSize: 10, padding: '2px 6px', borderRadius: 3,
                  background: C.faint, border: `1px solid ${C.border}`, color: C.dark,
                }}>
                  {e}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Active agents */}
        {baceState.agentsActive.length > 0 && (
          <div style={{ flex: '1 1 300px' }}>
            <div style={{
              fontFamily: mono, fontSize: 10,
              textTransform: 'uppercase' as const, letterSpacing: 1,
              color: C.muted, marginBottom: 6,
            }}>
              Active agents ({baceState.agentsActive.length})
            </div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' as const }}>
              {baceState.agentsActive.map((a, i) => {
                const id = a.toLowerCase().replace(/[^a-z]+/g, '-');
                const isAdv = a === "Devil's Advocate" || a === 'Null Hypothesis';
                const color = AGENT_COLORS[id] || (isAdv ? C.accent : C.info);
                return (
                  <span key={i} style={{
                    fontFamily: mono, fontSize: 10, padding: '2px 6px', borderRadius: 3,
                    background: `${color}15`, border: `1px solid ${color}30`, color,
                  }}>
                    {AGENT_ICONS[id] || '🤖'} {a}
                  </span>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Compact live log */}
      {baceState.debateLog.length > 0 && (
        <div style={{
          marginTop: 12,
          background: '#1a1a19', borderRadius: 6, padding: '10px 14px',
          fontFamily: mono, fontSize: 11, lineHeight: 1.7,
          maxHeight: 140, overflowY: 'auto' as const,
        }}>
          {baceState.debateLog.slice(-8).map((line, i) => {
            const isAgent = line.startsWith('⟫ ');
            const isHyp = line.startsWith('  "');
            return (
              <div key={i} style={{
                color: isAgent ? '#7cb8e8' : isHyp ? '#c8c0a8' : '#7a7a6e',
                fontWeight: isAgent ? 700 : 400,
              }}>
                {!isAgent && <span style={{ color: '#444', marginRight: 6 }}>{'>'}</span>}
                {isAgent && <span style={{ color: '#556', marginRight: 4 }}>●</span>}
                {line.replace('⟫ ', '')}
              </div>
            );
          })}
          <span style={{ color: '#555', animation: 'blink 1s infinite' }}>▊</span>
          <style>{`@keyframes blink { 0%,100% { opacity:1 } 50% { opacity:0 } }`}</style>
        </div>
      )}
    </div>
  );
}
