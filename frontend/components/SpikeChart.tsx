'use client';

import { useMemo, useState, useRef, useCallback } from 'react';

interface SpikeChartProps {
  data: number[];
  timestamps?: string[];
  height?: number;
  width?: number;
  showSpikes?: boolean;
  spikeThreshold?: number;
  interactive?: boolean;
  attributors?: { name: string; confidence: number }[];
}

interface DetectedSpike {
  startIdx: number;
  endIdx: number;
  peakIdx: number;
  magnitude: number;
  direction: 'up' | 'down';
  priceBefore: number;
  priceAfter: number;
  durationPoints: number;
}

function detectSpikes(data: number[], threshold: number, windowSize: number = 3): DetectedSpike[] {
  if (!data || data.length < windowSize + 1) return [];
  const spikes: DetectedSpike[] = [];
  let lastEnd = -999;
  for (let i = windowSize; i < data.length; i++) {
    let bestStart = i - 1, bestMag = 0;
    for (let j = Math.max(0, i - windowSize * 2); j < i; j++) {
      const mag = Math.abs(data[i] - data[j]);
      if (mag > bestMag) { bestMag = mag; bestStart = j; }
    }
    if (bestMag >= threshold && bestStart > lastEnd) {
      spikes.push({
        startIdx: bestStart, endIdx: i, peakIdx: i, magnitude: bestMag,
        direction: data[i] > data[bestStart] ? 'up' : 'down',
        priceBefore: data[bestStart], priceAfter: data[i],
        durationPoints: i - bestStart,
      });
      lastEnd = i + 1;
    }
  }
  return spikes;
}

function fmtDuration(pts: number, totalPts: number, totalHours: number): string {
  const min = Math.round(pts * (totalHours / Math.max(totalPts, 1)) * 60);
  const h = Math.floor(min / 60), m = min % 60;
  return h === 0 ? `${m}m` : `${h}h ${m.toString().padStart(2, '0')}m`;
}

const LINE_COLOR = '#d97757';
const SHADE_UP = 'rgba(120,140,93,0.12)';
const SHADE_DOWN = 'rgba(196,69,54,0.12)';
const EDGE_UP = 'rgba(120,140,93,0.35)';
const EDGE_DOWN = 'rgba(196,69,54,0.35)';

export default function SpikeChart({
  data, timestamps, height = 200, width = 600,
  showSpikes = true, spikeThreshold = 0.04,
  interactive = true, attributors,
}: SpikeChartProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [cursor, setCursor] = useState<{ x: number; idx: number } | null>(null);
  const [hoveredSpike, setHoveredSpike] = useState<DetectedSpike | null>(null);

  const pad = { top: 12, right: 6, bottom: 28, left: 42 };
  const cw = width - pad.left - pad.right;
  const ch = height - pad.top - pad.bottom;

  const chart = useMemo(() => {
    if (!data || data.length < 2) return null;
    // Fixed 0–100% y-axis
    const pMin = 0, pMax = 1;
    const sx = (i: number) => pad.left + (i / (data.length - 1)) * cw;
    const sy = (v: number) => pad.top + ch - (v / 1) * ch;

    const pts = data.map((v, i) => `${sx(i)},${sy(v)}`);
    const line = `M${pts.join('L')}`;
    const area = `${line}L${sx(data.length - 1)},${pad.top + ch}L${sx(0)},${pad.top + ch}Z`;
    const spikes = showSpikes ? detectSpikes(data, spikeThreshold) : [];

    // Y-axis: 0%, 25%, 50%, 75%, 100%
    const yTicks = [0, 0.25, 0.50, 0.75, 1.0].map(v => ({ y: sy(v), label: `${Math.round(v * 100)}%` }));

    // X-axis: ~5 date labels
    const xTicks: { x: number; label: string }[] = [];
    const count = 5;
    for (let i = 0; i <= count; i++) {
      const idx = Math.round((i / count) * (data.length - 1));
      const daysAgo = 30 - (idx / (data.length - 1)) * 30;
      const d = new Date(Date.now() - daysAgo * 86400000);
      xTicks.push({ x: sx(idx), label: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) });
    }

    return { line, area, spikes, yTicks, xTicks, sx, sy };
  }, [data, cw, ch, showSpikes, spikeThreshold, pad]);

  const handleMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (!svgRef.current || !data) return;
    const rect = svgRef.current.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const svgScale = width / rect.width;
    const svgX = mouseX * svgScale;
    const relX = (svgX - pad.left) / cw;
    const idx = Math.round(Math.max(0, Math.min(1, relX)) * (data.length - 1));
    setCursor({ x: svgX, idx });
    if (chart) {
      setHoveredSpike(chart.spikes.find(s => idx >= s.startIdx && idx <= s.endIdx) || null);
    }
  }, [data, cw, pad.left, chart, width]);

  if (!chart || !data || data.length < 2) return null;

  const cursorVal = cursor ? data[cursor.idx] : null;
  const cursorDate = cursor ? (() => {
    const daysAgo = 30 - (cursor.idx / (data.length - 1)) * 30;
    const d = new Date(Date.now() - daysAgo * 86400000);
    return d.toLocaleString('en-US', { month: 'numeric', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true });
  })() : null;
  const totalHours = 30 * 24;

  return (
    <div style={{ position: 'relative', userSelect: 'none' }}>
      <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`}
        style={{ width: '100%', height, cursor: interactive ? 'crosshair' : 'default' }}
        onMouseMove={interactive ? handleMouseMove : undefined}
        onMouseLeave={interactive ? () => { setCursor(null); setHoveredSpike(null); } : undefined}>

        {/* Y-axis grid + labels */}
        {chart.yTicks.map((t, i) => (
          <g key={i}>
            <line x1={pad.left} y1={t.y} x2={width - pad.right} y2={t.y}
              stroke="#e8e6dc" strokeDasharray="3,5" />
            <text x={pad.left - 6} y={t.y + 4} textAnchor="end" fill="#b0aea5"
              fontSize={11} fontFamily="'JetBrains Mono', monospace" fontWeight={500}>{t.label}</text>
          </g>
        ))}

        {/* X-axis labels */}
        {chart.xTicks.map((t, i) => (
          <text key={i} x={t.x} y={height - 4} textAnchor="middle" fill="#b0aea5"
            fontSize={10} fontFamily="'Source Serif 4', serif">{t.label}</text>
        ))}
        {/* X-axis baseline */}
        <line x1={pad.left} y1={pad.top + ch} x2={width - pad.right} y2={pad.top + ch}
          stroke="#d5d3c9" strokeWidth={1} />

        {/* Spike shaded regions */}
        {chart.spikes.map((s, i) => {
          const x1 = chart.sx(s.startIdx), x2 = chart.sx(s.endIdx);
          return (
            <g key={`s-${i}`}>
              <rect x={x1} y={pad.top} width={Math.max(x2 - x1, 4)} height={ch}
                fill={s.direction === 'up' ? SHADE_UP : SHADE_DOWN} rx={2} />
              <line x1={x1} y1={pad.top} x2={x1} y2={pad.top + ch} stroke={s.direction === 'up' ? EDGE_UP : EDGE_DOWN} strokeWidth={1} />
              <line x1={x2} y1={pad.top} x2={x2} y2={pad.top + ch} stroke={s.direction === 'up' ? EDGE_UP : EDGE_DOWN} strokeWidth={1} />
            </g>
          );
        })}

        {/* Area + line — always #d97757 */}
        <path d={chart.area} fill="rgba(217,119,87,0.06)" />
        <path d={chart.line} fill="none" stroke={LINE_COLOR} strokeWidth={1.8} strokeLinejoin="round" />

        {/* Crosshair */}
        {interactive && cursor && cursorVal !== null && (
          <>
            <line x1={cursor.x} y1={pad.top} x2={cursor.x} y2={pad.top + ch}
              stroke="#141413" strokeWidth={0.8} />
            <circle cx={chart.sx(cursor.idx)} cy={chart.sy(cursorVal)}
              r={4} fill={LINE_COLOR} stroke="white" strokeWidth={2} />
          </>
        )}
      </svg>

      {/* Crosshair readout */}
      {interactive && cursor && cursorVal !== null && (
        <div style={{
          position: 'absolute',
          left: Math.min(Math.max((cursor.x / width) * 100, 5), 70) + '%',
          top: 0, background: 'white', border: '1px solid #e8e6dc',
          borderRadius: 6, padding: '4px 10px', fontSize: 11,
          boxShadow: '0 2px 8px rgba(0,0,0,0.06)', pointerEvents: 'none', zIndex: 10,
          whiteSpace: 'nowrap',
        }}>
          <div style={{ color: '#b0aea5', marginBottom: 2 }}>{cursorDate}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: LINE_COLOR, display: 'inline-block' }} />
            <span style={{ fontWeight: 700, color: '#141413', fontFamily: "'JetBrains Mono', monospace" }}>
              {(cursorVal * 100).toFixed(1)}%
            </span>
          </div>
        </div>
      )}

      {/* Spike hover detail */}
      {interactive && hoveredSpike && cursor && (
        <div style={{
          position: 'absolute',
          left: Math.min((chart.sx(hoveredSpike.startIdx) / width) * 100 + 2, 60) + '%',
          top: '100%', marginTop: 4,
          background: '#141413', color: '#faf9f5', borderRadius: 10,
          padding: '12px 16px', fontSize: 12, lineHeight: 1.6,
          boxShadow: '0 8px 24px rgba(0,0,0,0.25)', pointerEvents: 'none', zIndex: 20,
          minWidth: 200, maxWidth: 280,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Duration</span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>
              {fmtDuration(hoveredSpike.durationPoints, data.length, totalHours)}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Move</span>
            <span style={{
              fontFamily: "'JetBrains Mono', monospace", fontWeight: 700,
              color: hoveredSpike.direction === 'up' ? '#a3b88c' : '#e07060',
            }}>
              {hoveredSpike.direction === 'up' ? '+' : '-'}{(hoveredSpike.magnitude * 100).toFixed(1)}pp
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
            <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Range</span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>
              {(hoveredSpike.priceBefore * 100).toFixed(1)}% → {(hoveredSpike.priceAfter * 100).toFixed(1)}%
            </span>
          </div>
          {attributors && attributors.length > 0 && (
            <div style={{ borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 6, marginTop: 2 }}>
              <div style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Probable Causes</div>
              {attributors.slice(0, 3).map((a, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 2 }}>
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginRight: 8 }}>{a.name}</span>
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", color: '#b0aea5', flexShrink: 0 }}>{(a.confidence * 100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
