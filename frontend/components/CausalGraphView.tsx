'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';

// ----------------------------------------------------------------
// Types
// ----------------------------------------------------------------

export interface CausalNode {
  id: string; label: string; type: string; layer: number;
  confidence?: number; status?: string; reason?: string;
  url?: string; source?: string; magnitude?: number;
  direction?: 'up' | 'down'; lagHours?: number; pValue?: number; score?: number;
}

export interface CausalEdge {
  source: string; target: string;
  type: string;
}

export interface CausalGraphData {
  nodes: CausalNode[];
  edges: CausalEdge[];
  layers?: { id: number; name: string; description: string }[];
}

interface Props {
  data: CausalGraphData;
  width?: number;
  height?: number;
  animated?: boolean;
  onNodeClick?: (node: CausalNode) => void;
}

// ----------------------------------------------------------------
// Design tokens
// ----------------------------------------------------------------

const TYPE_COLORS: Record<string, string> = {
  spike: '#d97757', entity: '#141413', candidate: '#b0aea5',
  eliminated: '#e07060', reasoned: '#6a9bcc', validated: '#788c5d',
  attributor: '#788c5d', forward_signal: '#6a9bcc', correlated: '#b0aea5',
};

const TYPE_RADIUS: Record<string, number> = {
  spike: 22, entity: 10, candidate: 8, eliminated: 7,
  reasoned: 12, validated: 14, attributor: 16,
  forward_signal: 12, correlated: 10,
};

// ----------------------------------------------------------------
// Layout: place nodes in columns by layer
// ----------------------------------------------------------------

function layoutNodes(nodes: CausalNode[], W: number, H: number) {
  const byLayer: Record<number, CausalNode[]> = {};
  for (const n of nodes) {
    (byLayer[n.layer] ??= []).push(n);
  }

  const layers = Object.keys(byLayer).map(Number).sort((a, b) => a - b);
  const colCount = layers.length || 1;
  const colW = W / (colCount + 1);

  const positions: Record<string, { x: number; y: number; r: number }> = {};

  for (const layer of layers) {
    const col = layers.indexOf(layer);
    const x = colW * (col + 1);
    const group = byLayer[layer];
    const rowH = H / (group.length + 1);

    for (let i = 0; i < group.length; i++) {
      const n = group[i];
      const y = rowH * (i + 1);
      const r = TYPE_RADIUS[n.type] || 10;
      positions[n.id] = { x, y, r };
    }
  }

  return positions;
}

// ----------------------------------------------------------------
// Component
// ----------------------------------------------------------------

export default function CausalGraphView({ data, width = 1136, height = 520, animated = true, onNodeClick }: Props) {
  const [visibleLayer, setVisibleLayer] = useState(animated ? 0 : 99);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  // Progressive layer reveal
  useEffect(() => {
    if (!animated) { setVisibleLayer(99); return; }
    setVisibleLayer(0);
    let layer = 0;
    const maxLayer = Math.max(...data.nodes.map(n => n.layer), 0);
    const timer = setInterval(() => {
      layer++;
      setVisibleLayer(layer);
      if (layer >= maxLayer) clearInterval(timer);
    }, 500);
    return () => clearInterval(timer);
  }, [data, animated]);

  const positions = useMemo(() => layoutNodes(data.nodes, width, height), [data.nodes, width, height]);

  const visNodes = useMemo(() => data.nodes.filter(n => n.layer <= visibleLayer), [data.nodes, visibleLayer]);
  const visNodeIds = useMemo(() => new Set(visNodes.map(n => n.id)), [visNodes]);
  const visEdges = useMemo(() => data.edges.filter(e => visNodeIds.has(e.source) && visNodeIds.has(e.target)), [data.edges, visNodeIds]);

  const handleClick = useCallback((node: CausalNode) => {
    setSelectedNode(prev => prev === node.id ? null : node.id);
    onNodeClick?.(node);
  }, [onNodeClick]);

  const activeId = selectedNode ?? hoveredNode;
  const activeNode = activeId ? data.nodes.find(n => n.id === activeId) : null;
  const connectedIds = useMemo(() => {
    if (!activeId) return new Set<string>();
    const s = new Set<string>();
    s.add(activeId);
    for (const e of data.edges) {
      if (e.source === activeId) s.add(e.target);
      if (e.target === activeId) s.add(e.source);
    }
    return s;
  }, [activeId, data.edges]);

  // Layer labels
  const layerLabels = data.layers || [];

  return (
    <div style={{ position: 'relative', fontFamily: "'Source Serif 4', serif" }}>

      {/* Layer headers */}
      <div style={{ display: 'flex', padding: '0 0 4px', overflow: 'hidden' }}>
        {layerLabels.filter(l => {
          // only show labels for layers that have visible nodes
          return data.nodes.some(n => n.layer === l.id) && l.id <= visibleLayer;
        }).map(l => {
          const layers = [...new Set(data.nodes.map(n => n.layer))].sort((a, b) => a - b);
          const colCount = layers.length || 1;
          const colW = width / (colCount + 1);
          const col = layers.indexOf(l.id);
          const x = colW * (col + 1);
          return (
            <div key={l.id} style={{
              position: 'absolute', left: x, transform: 'translateX(-50%)',
              textAlign: 'center', width: colW * 0.9,
              opacity: l.id <= visibleLayer ? 1 : 0,
              transition: 'opacity 0.4s',
            }}>
              <div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.08em', color: '#b0aea5', fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>
                {l.name}
              </div>
            </div>
          );
        })}
      </div>

      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height }}>
        {/* Defs */}
        <defs>
          <marker id="arr-survive" viewBox="0 0 8 6" refX="8" refY="3" markerWidth="6" markerHeight="5" orient="auto">
            <path d="M0,0 L8,3 L0,6 Z" fill="#788c5d" />
          </marker>
          <marker id="arr-elim" viewBox="0 0 8 6" refX="8" refY="3" markerWidth="6" markerHeight="5" orient="auto">
            <path d="M0,0 L8,3 L0,6 Z" fill="#e07060" />
          </marker>
          <marker id="arr-default" viewBox="0 0 8 6" refX="8" refY="3" markerWidth="6" markerHeight="5" orient="auto">
            <path d="M0,0 L8,3 L0,6 Z" fill="#d5d3c9" />
          </marker>
          <marker id="arr-prop" viewBox="0 0 8 6" refX="8" refY="3" markerWidth="6" markerHeight="5" orient="auto">
            <path d="M0,0 L8,3 L0,6 Z" fill="#6a9bcc" />
          </marker>
        </defs>

        {/* Edges */}
        {visEdges.map((edge, i) => {
          const sp = positions[edge.source];
          const tp = positions[edge.target];
          if (!sp || !tp) return null;

          const dx = tp.x - sp.x, dy = tp.y - sp.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const x1 = sp.x + (dx / dist) * sp.r;
          const y1 = sp.y + (dy / dist) * sp.r;
          const x2 = tp.x - (dx / dist) * (tp.r + 5);
          const y2 = tp.y - (dy / dist) * (tp.r + 5);

          const isElim = edge.type === 'eliminated_at';
          const isProp = edge.type === 'propagates_to' || edge.type === 'correlated_with';
          const isSurvive = edge.type === 'survived' || edge.type === 'validated_by';
          const color = isElim ? '#e07060' : isProp ? '#6a9bcc' : isSurvive ? '#788c5d' : '#d5d3c9';
          const marker = isElim ? 'url(#arr-elim)' : isProp ? 'url(#arr-prop)' : isSurvive ? 'url(#arr-survive)' : 'url(#arr-default)';
          const dimmed = activeId && !connectedIds.has(edge.source) && !connectedIds.has(edge.target);

          return (
            <line key={`e${i}`} x1={x1} y1={y1} x2={x2} y2={y2}
              stroke={color} strokeWidth={isElim ? 1 : 1.3}
              strokeDasharray={isElim ? '4,3' : edge.type === 'correlated_with' ? '5,4' : undefined}
              markerEnd={marker}
              opacity={dimmed ? 0.1 : isElim ? 0.4 : 0.6}
              style={{ transition: 'opacity 0.3s' }}
            />
          );
        })}

        {/* Nodes */}
        {visNodes.map(node => {
          const pos = positions[node.id];
          if (!pos) return null;

          const isElim = node.type === 'eliminated';
          const color = TYPE_COLORS[node.type] || '#b0aea5';
          const r = pos.r;
          const isActive = node.id === activeId;
          const dimmed = activeId && !connectedIds.has(node.id);
          const isNewLayer = node.layer === visibleLayer && animated;

          // Icons
          let icon = '';
          if (node.type === 'spike') icon = '⚡';
          else if (node.type === 'entity') icon = '🔍';
          else if (node.type === 'candidate') icon = '📰';
          else if (node.type === 'eliminated') icon = '✗';
          else if (node.type === 'reasoned') icon = node.status === 'unconfirmed' ? '?' : '◎';
          else if (node.type === 'validated') icon = '✓';
          else if (node.type === 'attributor') icon = node.status === 'unconfirmed' ? '?' : 'P';
          else if (node.type === 'forward_signal') icon = '→';
          else if (node.type === 'correlated') icon = '↔';

          return (
            <g key={node.id} style={{ cursor: 'pointer', opacity: dimmed ? 0.15 : 1, transition: 'opacity 0.3s' }}
              onMouseEnter={() => setHoveredNode(node.id)}
              onMouseLeave={() => setHoveredNode(null)}
              onClick={() => handleClick(node)}>

              {/* Pulse for new layer */}
              {isNewLayer && !isElim && (
                <circle cx={pos.x} cy={pos.y} r={r} fill="none" stroke={color} strokeWidth={1.5} opacity={0}>
                  <animate attributeName="r" from={String(r)} to={String(r + 14)} dur="0.5s" fill="freeze" />
                  <animate attributeName="opacity" from="0.5" to="0" dur="0.5s" fill="freeze" />
                </circle>
              )}

              {/* Node */}
              <circle cx={pos.x} cy={pos.y} r={isActive ? r + 2 : r}
                fill={isElim ? 'transparent' : color}
                stroke={isElim ? '#e07060' : isActive ? '#141413' : 'white'}
                strokeWidth={isElim ? 1.5 : isActive ? 2 : 1}
                strokeDasharray={isElim ? '3,2' : undefined}
                style={{ transition: 'r 0.2s' }}>
                {isNewLayer && (
                  <animate attributeName="r" from="0" to={String(r)} dur="0.3s" fill="freeze"
                    calcMode="spline" keySplines="0.34 1.56 0.64 1" />
                )}
              </circle>

              {/* Icon */}
              <text x={pos.x} y={pos.y + (node.type === 'spike' ? 1 : 3.5)}
                textAnchor="middle" fill={isElim ? '#e07060' : 'white'}
                fontSize={node.type === 'spike' ? 15 : node.type === 'entity' ? 8 : 9}
                fontWeight={700} fontFamily="'JetBrains Mono', monospace"
                style={{ pointerEvents: 'none' }}>
                {icon}
              </text>

              {/* Label */}
              <text x={pos.x} y={pos.y + r + 12}
                textAnchor="middle" fill={isElim ? '#b0aea5' : '#141413'}
                fontSize={9} fontFamily="'Source Serif 4', serif" fontWeight={500}
                textDecoration={isElim ? 'line-through' : undefined}
                style={{ pointerEvents: 'none' }}>
                {node.label.length > 30 ? node.label.slice(0, 28) + '…' : node.label}
              </text>

              {/* Source badge for candidates */}
              {node.source && node.type === 'candidate' && (
                <text x={pos.x} y={pos.y - r - 4}
                  textAnchor="middle" fill="#b0aea5"
                  fontSize={7} fontFamily="'JetBrains Mono', monospace"
                  style={{ pointerEvents: 'none' }}>
                  {node.source}
                </text>
              )}

              {/* Confidence badge */}
              {node.confidence !== undefined && node.confidence > 0 && node.type !== 'candidate' && (
                <text x={pos.x + r + 3} y={pos.y - r + 3}
                  textAnchor="start" fill="#b0aea5"
                  fontSize={8} fontFamily="'JetBrains Mono', monospace"
                  style={{ pointerEvents: 'none' }}>
                  {Math.round(node.confidence * 100)}%
                </text>
              )}

              {/* Score badge for candidates */}
              {node.score !== undefined && node.type === 'candidate' && (
                <text x={pos.x + r + 3} y={pos.y + 3}
                  textAnchor="start" fill="#b0aea5"
                  fontSize={7} fontFamily="'JetBrains Mono', monospace"
                  style={{ pointerEvents: 'none' }}>
                  {node.score}/10
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {/* Detail panel */}
      {activeNode && selectedNode && (
        <div style={{
          position: 'absolute', top: 12, right: 12, width: 260,
          background: '#141413', color: '#faf9f5', borderRadius: 10,
          padding: '14px 16px 12px', fontSize: 12, lineHeight: 1.6,
          boxShadow: '0 8px 24px rgba(0,0,0,0.3)', zIndex: 20,
        }}>
          <button onClick={() => setSelectedNode(null)}
            style={{ position: 'absolute', top: 8, right: 10, background: 'none', border: 'none', color: '#b0aea5', cursor: 'pointer', fontSize: 14, lineHeight: 1 }}>✕</button>

          <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', color: '#b0aea5', marginBottom: 4 }}>
            {activeNode.type === 'eliminated' ? 'Eliminated' : activeNode.type.replace('_', ' ')}
            {activeNode.source ? ` · ${activeNode.source}` : ''}
          </div>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8, paddingRight: 20, fontFamily: "'Newsreader', serif" }}>
            {activeNode.label}
          </div>

          {activeNode.reason && (
            <div style={{ fontSize: 11, color: activeNode.type === 'eliminated' ? '#e07060' : '#a3b88c', marginBottom: 6, lineHeight: 1.5, fontStyle: 'italic' }}>
              {activeNode.reason}
            </div>
          )}

          {activeNode.confidence !== undefined && activeNode.confidence > 0 && (
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Confidence</span>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>{Math.round(activeNode.confidence * 100)}%</span>
            </div>
          )}

          {activeNode.pValue !== undefined && (
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>P-value</span>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: activeNode.pValue < 0.05 ? '#a3b88c' : '#e07060' }}>{activeNode.pValue}</span>
            </div>
          )}

          {activeNode.magnitude !== undefined && (
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Move</span>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: activeNode.direction === 'up' ? '#a3b88c' : '#e07060' }}>
                {activeNode.direction === 'up' ? '+' : '-'}{(activeNode.magnitude * 100).toFixed(1)}pp
              </span>
            </div>
          )}

          {activeNode.lagHours !== undefined && (
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Predicted lag</span>
              <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>{activeNode.lagHours}h</span>
            </div>
          )}

          {activeNode.status && (
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Status</span>
              <span style={{ fontFamily: "'JetBrains Mono', monospace",
                color: activeNode.status === 'active' ? '#a3b88c' : activeNode.status === 'eliminated' ? '#e07060' : activeNode.status === 'unconfirmed' ? '#6a9bcc' : '#b0aea5' }}>
                {activeNode.status}
              </span>
            </div>
          )}

          {activeNode.url && (
            <a href={activeNode.url} target="_blank" rel="noopener noreferrer"
              style={{ display: 'block', marginTop: 6, fontSize: 11, color: '#8bb8d9', textDecoration: 'none' }}
              onMouseEnter={e => (e.currentTarget.style.textDecoration = 'underline')}
              onMouseLeave={e => (e.currentTarget.style.textDecoration = 'none')}>
              View source ↗
            </a>
          )}
        </div>
      )}

      {/* Legend */}
      <div style={{ display: 'flex', gap: 12, padding: '6px 0 0', fontSize: 9, color: '#b0aea5', fontFamily: "'JetBrains Mono', monospace", flexWrap: 'wrap' }}>
        {[
          { color: '#d97757', label: 'Spike' }, { color: '#141413', label: 'Entity' },
          { color: '#b0aea5', label: 'Candidate' }, { color: '#e07060', label: 'Eliminated', dashed: true },
          { color: '#6a9bcc', label: 'Reasoned' }, { color: '#788c5d', label: 'Validated / Attributor' },
          { color: '#6a9bcc', label: 'Forward signal' },
        ].map(item => (
          <span key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: item.dashed ? 'transparent' : item.color, border: item.dashed ? `1.5px dashed ${item.color}` : 'none', display: 'inline-block' }} />
            {item.label}
          </span>
        ))}
      </div>
    </div>
  );
}
