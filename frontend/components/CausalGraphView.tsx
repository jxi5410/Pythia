'use client';

import { useEffect, useRef, useState, useCallback, useMemo } from 'react';

// ----------------------------------------------------------------
// Types
// ----------------------------------------------------------------

export interface CausalNode {
  id: string;
  label: string;
  type: 'spike' | 'attributor' | 'forward_signal' | 'correlated' | 'narrative';
  confidence?: number;
  status?: 'active' | 'unconfirmed' | 'predicted' | 'observed';
  url?: string;
  magnitude?: number;
  direction?: 'up' | 'down';
  lagHours?: number;
  // Force simulation positions (mutated by tick)
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number | null;
  fy?: number | null;
  // Animation
  born?: number; // timestamp when node was added
  radius?: number;
}

export interface CausalEdge {
  source: string;
  target: string;
  strength?: number;
  type: 'caused_by' | 'propagates_to' | 'correlated_with';
  born?: number;
}

export interface CausalGraphData {
  nodes: CausalNode[];
  edges: CausalEdge[];
}

interface CausalGraphViewProps {
  data: CausalGraphData;
  width?: number;
  height?: number;
  animated?: boolean;
  onNodeClick?: (node: CausalNode) => void;
}

// ----------------------------------------------------------------
// Colors matching Pythia design system
// ----------------------------------------------------------------

const COLORS: Record<string, string> = {
  spike: '#d97757',
  attributor: '#788c5d',
  forward_signal: '#6a9bcc',
  correlated: '#b0aea5',
  narrative: '#141413',
  unconfirmed: '#6a9bcc',
  bg: '#faf9f5',
  edge_default: '#d5d3c9',
  edge_causal: '#788c5d',
  edge_propagation: '#6a9bcc',
  edge_correlation: '#b0aea5',
  text: '#141413',
  text_muted: '#b0aea5',
};

const NODE_RADIUS: Record<string, number> = {
  spike: 28,
  attributor: 20,
  forward_signal: 16,
  correlated: 14,
  narrative: 24,
};

const EDGE_COLORS: Record<string, string> = {
  caused_by: COLORS.edge_causal,
  propagates_to: COLORS.edge_propagation,
  correlated_with: COLORS.edge_correlation,
};

// ----------------------------------------------------------------
// Simple force simulation (no d3 import needed — pure math)
// ----------------------------------------------------------------

function forceSimulation(
  nodes: CausalNode[],
  edges: CausalEdge[],
  width: number,
  height: number,
  iterations: number = 120,
) {
  const cx = width / 2;
  const cy = height / 2;

  // Initialize positions
  nodes.forEach((n, i) => {
    if (n.x === undefined) {
      const angle = (i / nodes.length) * Math.PI * 2;
      const r = 80 + Math.random() * 60;
      n.x = cx + Math.cos(angle) * r;
      n.y = cy + Math.sin(angle) * r;
    }
    n.vx = 0;
    n.vy = 0;
    n.radius = NODE_RADIUS[n.type] || 16;
  });

  // Pin spike node at center
  const spikeNode = nodes.find(n => n.type === 'spike');
  if (spikeNode) {
    spikeNode.fx = cx;
    spikeNode.fy = cy;
    spikeNode.x = cx;
    spikeNode.y = cy;
  }

  const nodeMap = new Map(nodes.map(n => [n.id, n]));

  for (let iter = 0; iter < iterations; iter++) {
    const alpha = 1 - iter / iterations;
    const decay = 0.3 * alpha;

    // Repulsion between all nodes
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = (b.x ?? 0) - (a.x ?? 0);
        let dy = (b.y ?? 0) - (a.y ?? 0);
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const minDist = (a.radius! + b.radius!) * 2.5;
        if (dist < minDist) {
          const force = ((minDist - dist) / dist) * 0.5 * decay;
          const fx = dx * force;
          const fy = dy * force;
          a.vx! -= fx; a.vy! -= fy;
          b.vx! += fx; b.vy! += fy;
        }
      }
    }

    // Attraction along edges
    for (const edge of edges) {
      const a = nodeMap.get(edge.source);
      const b = nodeMap.get(edge.target);
      if (!a || !b) continue;
      const dx = (b.x ?? 0) - (a.x ?? 0);
      const dy = (b.y ?? 0) - (a.y ?? 0);
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const idealDist = (a.radius! + b.radius!) * 3.5;
      const force = (dist - idealDist) * 0.02 * decay;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx! += fx; a.vy! += fy;
      b.vx! -= fx; b.vy! -= fy;
    }

    // Center gravity
    for (const n of nodes) {
      n.vx! += (cx - (n.x ?? 0)) * 0.005 * decay;
      n.vy! += (cy - (n.y ?? 0)) * 0.005 * decay;
    }

    // Apply velocities
    for (const n of nodes) {
      if (n.fx !== undefined && n.fx !== null) { n.x = n.fx; n.vx = 0; }
      else { n.vx! *= 0.7; n.x = (n.x ?? 0) + n.vx!; }
      if (n.fy !== undefined && n.fy !== null) { n.y = n.fy; n.vy = 0; }
      else { n.vy! *= 0.7; n.y = (n.y ?? 0) + n.vy!; }
      // Clamp to bounds
      n.x = Math.max(40, Math.min(width - 40, n.x!));
      n.y = Math.max(40, Math.min(height - 40, n.y!));
    }
  }

  return nodes;
}

// ----------------------------------------------------------------
// Component
// ----------------------------------------------------------------

export default function CausalGraphView({
  data,
  width = 700,
  height = 500,
  animated = true,
  onNodeClick,
}: CausalGraphViewProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [visibleCount, setVisibleCount] = useState(animated ? 1 : data.nodes.length);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  // Progressive reveal animation
  useEffect(() => {
    if (!animated) { setVisibleCount(data.nodes.length); return; }
    setVisibleCount(1);
    let count = 1;
    const interval = setInterval(() => {
      count++;
      setVisibleCount(count);
      if (count >= data.nodes.length) clearInterval(interval);
    }, 280);
    return () => clearInterval(interval);
  }, [data.nodes.length, animated]);

  // Run force layout on visible nodes
  const layout = useMemo(() => {
    const visNodes = data.nodes.slice(0, visibleCount).map(n => ({ ...n }));
    const visNodeIds = new Set(visNodes.map(n => n.id));
    const visEdges = data.edges.filter(e => visNodeIds.has(e.source) && visNodeIds.has(e.target));
    forceSimulation(visNodes, visEdges, width, height, 150);
    return { nodes: visNodes, edges: visEdges };
  }, [data, visibleCount, width, height]);

  const handleNodeClick = useCallback((node: CausalNode) => {
    setSelectedNode(prev => prev === node.id ? null : node.id);
    onNodeClick?.(node);
  }, [onNodeClick]);

  // Arrow marker IDs
  const markerIds = useMemo(() => ({
    caused_by: 'arrow-causal',
    propagates_to: 'arrow-prop',
    correlated_with: 'arrow-corr',
  }), []);

  const activeNode = selectedNode ?? hoveredNode;
  const activeData = activeNode ? data.nodes.find(n => n.id === activeNode) : null;

  return (
    <div style={{ position: 'relative', fontFamily: "'Source Serif 4', serif" }}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        style={{ width: '100%', height, background: 'transparent' }}
      >
        {/* Defs — arrow markers */}
        <defs>
          {Object.entries(EDGE_COLORS).map(([type, color]) => (
            <marker key={type} id={markerIds[type as keyof typeof markerIds]}
              viewBox="0 0 10 6" refX="10" refY="3" markerWidth="8" markerHeight="6"
              orient="auto-start-reverse">
              <path d="M0,0 L10,3 L0,6 Z" fill={color} />
            </marker>
          ))}
        </defs>

        {/* Edges */}
        {layout.edges.map((edge, i) => {
          const source = layout.nodes.find(n => n.id === edge.source);
          const target = layout.nodes.find(n => n.id === edge.target);
          if (!source || !target) return null;

          const dx = (target.x ?? 0) - (source.x ?? 0);
          const dy = (target.y ?? 0) - (source.y ?? 0);
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const sr = source.radius ?? 16;
          const tr = target.radius ?? 16;
          const x1 = (source.x ?? 0) + (dx / dist) * sr;
          const y1 = (source.y ?? 0) + (dy / dist) * sr;
          const x2 = (target.x ?? 0) - (dx / dist) * (tr + 6);
          const y2 = (target.y ?? 0) - (dy / dist) * (tr + 6);

          const edgeColor = EDGE_COLORS[edge.type] || COLORS.edge_default;
          const markerId = markerIds[edge.type as keyof typeof markerIds];
          const isDashed = edge.type === 'correlated_with';
          const isHighlighted = activeNode && (edge.source === activeNode || edge.target === activeNode);

          return (
            <line key={`e-${i}`}
              x1={x1} y1={y1} x2={x2} y2={y2}
              stroke={edgeColor}
              strokeWidth={isHighlighted ? 2 : 1.2}
              strokeDasharray={isDashed ? '5,4' : undefined}
              markerEnd={edge.type !== 'correlated_with' ? `url(#${markerId})` : undefined}
              opacity={activeNode ? (isHighlighted ? 1 : 0.2) : 0.6}
              style={{
                transition: 'opacity 0.3s, stroke-width 0.2s',
              }}
            />
          );
        })}

        {/* Nodes */}
        {layout.nodes.map((node, i) => {
          const r = node.radius ?? 16;
          const isActive = node.id === activeNode;
          const isConnected = activeNode && data.edges.some(
            e => (e.source === activeNode && e.target === node.id) ||
                 (e.target === activeNode && e.source === node.id)
          );
          const dimmed = activeNode && !isActive && !isConnected;

          let fillColor = COLORS[node.type] || '#b0aea5';
          if (node.status === 'unconfirmed') fillColor = COLORS.unconfirmed;
          const isNew = i === visibleCount - 1 && animated;

          // Node icon/label
          let icon = '';
          if (node.type === 'spike') icon = '⚡';
          else if (node.type === 'attributor') icon = node.status === 'unconfirmed' ? '?' : 'P';
          else if (node.type === 'forward_signal') icon = '→';
          else if (node.type === 'correlated') icon = '↔';
          else if (node.type === 'narrative') icon = 'N';

          return (
            <g key={node.id}
              style={{
                cursor: 'pointer',
                opacity: dimmed ? 0.25 : 1,
                transition: 'opacity 0.3s',
              }}
              onMouseEnter={() => setHoveredNode(node.id)}
              onMouseLeave={() => setHoveredNode(null)}
              onClick={() => handleNodeClick(node)}
            >
              {/* Pulse ring for new nodes */}
              {isNew && (
                <circle cx={node.x} cy={node.y} r={r + 8}
                  fill="none" stroke={fillColor} strokeWidth={1.5}
                  opacity={0}>
                  <animate attributeName="r" from={String(r)} to={String(r + 18)} dur="0.6s" fill="freeze" />
                  <animate attributeName="opacity" from="0.6" to="0" dur="0.6s" fill="freeze" />
                </circle>
              )}

              {/* Node circle */}
              <circle cx={node.x} cy={node.y} r={isActive ? r + 3 : r}
                fill={fillColor}
                stroke={isActive ? '#141413' : 'white'}
                strokeWidth={isActive ? 2 : 1.5}
                style={{ transition: 'r 0.2s' }}
              >
                {isNew && (
                  <animate attributeName="r" from="0" to={String(r)} dur="0.35s" fill="freeze"
                    calcMode="spline" keySplines="0.34 1.56 0.64 1" />
                )}
              </circle>

              {/* Icon text */}
              <text x={node.x} y={(node.y ?? 0) + (node.type === 'spike' ? 1 : 4)}
                textAnchor="middle" fill="white"
                fontSize={node.type === 'spike' ? 18 : 11}
                fontWeight={700}
                fontFamily="'JetBrains Mono', monospace"
                style={{ pointerEvents: 'none' }}>
                {icon}
              </text>

              {/* Label below */}
              <text x={node.x} y={(node.y ?? 0) + r + 14}
                textAnchor="middle" fill={COLORS.text}
                fontSize={10}
                fontFamily="'Source Serif 4', serif"
                fontWeight={500}
                style={{ pointerEvents: 'none' }}>
                {node.label.length > 28 ? node.label.slice(0, 26) + '…' : node.label}
              </text>

              {/* Confidence badge */}
              {node.confidence !== undefined && node.confidence > 0 && (
                <text x={(node.x ?? 0) + r + 4} y={(node.y ?? 0) - r + 4}
                  textAnchor="start" fill={COLORS.text_muted}
                  fontSize={9}
                  fontFamily="'JetBrains Mono', monospace"
                  style={{ pointerEvents: 'none' }}>
                  {Math.round(node.confidence * 100)}%
                </text>
              )}

              {/* Direction arrow for spikes and forward signals */}
              {node.direction && (
                <text x={(node.x ?? 0) - r - 6} y={(node.y ?? 0) + 4}
                  textAnchor="end"
                  fill={node.direction === 'up' ? '#788c5d' : '#d97757'}
                  fontSize={14} fontWeight={700}
                  style={{ pointerEvents: 'none' }}>
                  {node.direction === 'up' ? '▲' : '▼'}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {/* Detail panel — shows on node selection */}
      {activeData && selectedNode && (
        <div style={{
          position: 'absolute', top: 12, right: 12, width: 240,
          background: '#141413', color: '#faf9f5', borderRadius: 10,
          padding: '14px 16px 12px', fontSize: 12, lineHeight: 1.6,
          boxShadow: '0 8px 24px rgba(0,0,0,0.3)', zIndex: 20,
        }}>
          <button onClick={() => setSelectedNode(null)}
            style={{ position: 'absolute', top: 8, right: 10, background: 'none', border: 'none', color: '#b0aea5', cursor: 'pointer', fontSize: 14, lineHeight: 1 }}>✕</button>

          <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', color: '#b0aea5', marginBottom: 4 }}>
            {activeData.type.replace('_', ' ')}
          </div>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8, paddingRight: 20, fontFamily: "'Newsreader', serif" }}>
            {activeData.label}
          </div>

          {activeData.confidence !== undefined && (
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Confidence</span>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>
                {Math.round(activeData.confidence * 100)}%
              </span>
            </div>
          )}

          {activeData.status && (
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Status</span>
              <span style={{
                fontFamily: "'JetBrains Mono', monospace",
                color: activeData.status === 'active' ? '#a3b88c' :
                       activeData.status === 'unconfirmed' ? '#6a9bcc' :
                       activeData.status === 'predicted' ? '#6a9bcc' : '#b0aea5',
              }}>{activeData.status}</span>
            </div>
          )}

          {activeData.magnitude !== undefined && (
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Move</span>
              <span style={{
                fontFamily: "'JetBrains Mono', monospace", fontWeight: 700,
                color: activeData.direction === 'up' ? '#a3b88c' : '#e07060',
              }}>
                {activeData.direction === 'up' ? '+' : '-'}{(activeData.magnitude * 100).toFixed(1)}pp
              </span>
            </div>
          )}

          {activeData.lagHours !== undefined && (
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Lag</span>
              <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>{activeData.lagHours}h</span>
            </div>
          )}

          {activeData.url && (
            <a href={activeData.url} target="_blank" rel="noopener noreferrer"
              style={{ display: 'block', marginTop: 6, fontSize: 11, color: '#8bb8d9', textDecoration: 'none' }}
              onMouseEnter={e => (e.currentTarget.style.textDecoration = 'underline')}
              onMouseLeave={e => (e.currentTarget.style.textDecoration = 'none')}>
              View source ↗
            </a>
          )}
        </div>
      )}

      {/* Legend */}
      <div style={{
        position: 'absolute', bottom: 8, left: 12,
        display: 'flex', gap: 14, fontSize: 10, color: COLORS.text_muted,
        fontFamily: "'JetBrains Mono', monospace",
      }}>
        {[
          { color: COLORS.spike, label: 'Spike' },
          { color: COLORS.attributor, label: 'Attributor' },
          { color: COLORS.forward_signal, label: 'Forward signal' },
          { color: COLORS.correlated, label: 'Correlated' },
        ].map(item => (
          <span key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: item.color, display: 'inline-block' }} />
            {item.label}
          </span>
        ))}
      </div>
    </div>
  );
}
