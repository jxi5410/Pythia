'use client';

import { useMemo, useState, useRef, useCallback } from 'react';

interface SpikeChartProps {
  data: number[];
  timestamps?: string[];     // ISO timestamps matching data points
  height?: number;
  width?: number;
  showSpikes?: boolean;
  spikeThreshold?: number;
  positive?: boolean;
  label?: string;            // e.g. "Yes" outcome label
  attributors?: { name: string; confidence: number }[];
  interactive?: boolean;     // show crosshair + tooltips on hover
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

function detectSpikes(data: number[], threshold: number = 0.03, windowSize: number = 3): DetectedSpike[] {
  if (!data || data.length < windowSize + 1) return [];
  const spikes: DetectedSpike[] = [];
  let lastEnd = -999;

  for (let i = windowSize; i < data.length; i++) {
    // Look back to find the start of the move
    let bestStart = i - 1;
    let bestMag = 0;
    for (let j = Math.max(0, i - windowSize * 2); j < i; j++) {
      const mag = Math.abs(data[i] - data[j]);
      if (mag > bestMag) {
        bestMag = mag;
        bestStart = j;
      }
    }

    if (bestMag >= threshold && bestStart > lastEnd) {
      spikes.push({
        startIdx: bestStart,
        endIdx: i,
        peakIdx: i,
        magnitude: bestMag,
        direction: data[i] > data[bestStart] ? 'up' : 'down',
        priceBefore: data[bestStart],
        priceAfter: data[i],
        durationPoints: i - bestStart,
      });
      lastEnd = i + 1; // gap before next spike
    }
  }
  return spikes;
}

function spikeShadeColor(dir: 'up' | 'down', mag: number): string {
  if (dir === 'up') {
    if (mag >= 0.08) return 'rgba(22,163,74,0.12)';
    if (mag >= 0.05) return 'rgba(22,163,74,0.08)';
    return 'rgba(22,163,74,0.05)';
  } else {
    if (mag >= 0.08) return 'rgba(220,38,38,0.12)';
    if (mag >= 0.05) return 'rgba(220,38,38,0.08)';
    return 'rgba(220,38,38,0.05)';
  }
}

function spikeEdgeColor(dir: 'up' | 'down'): string {
  return dir === 'up' ? 'rgba(22,163,74,0.3)' : 'rgba(220,38,38,0.3)';
}

function fmtDuration(points: number, totalPoints: number, totalHours: number): string {
  const hoursPerPoint = totalHours / Math.max(totalPoints, 1);
  const totalMin = Math.round(points * hoursPerPoint * 60);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h === 0) return `${m}m`;
  return `${h}h ${m.toString().padStart(2, '0')}m`;
}

export default function SpikeChart({
  data, timestamps, height = 200, width = 600,
  showSpikes = true, spikeThreshold = 0.04,
  positive = true, label = 'Yes', attributors,
  interactive = true,
}: SpikeChartProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [cursor, setCursor] = useState<{ x: number; idx: number } | null>(null);
  const [hoveredSpike, setHoveredSpike] = useState<DetectedSpike | null>(null);

  const pad = { top: 16, right: 48, bottom: 20, left: 8 };
  const cw = width - pad.left - pad.right;
  const ch = height - pad.top - pad.bottom;

  const chart = useMemo(() => {
    if (!data || data.length < 2) return null;

    const mn = Math.min(...data);
    const mx = Math.max(...data);
    const range = mx - mn || 0.01;
    const padRange = range * 0.08;
    const pMin = Math.max(0, mn - padRange);
    const pMax = Math.min(1, mx + padRange);
    const pRange = pMax - pMin || 0.01;

    const sx = (i: number) => pad.left + (i / (data.length - 1)) * cw;
    const sy = (v: number) => pad.top + ch - ((v - pMin) / pRange) * ch;

    const pts = data.map((v, i) => `${sx(i)},${sy(v)}`);
    const line = `M${pts.join('L')}`;
    const area = `${line}L${sx(data.length - 1)},${pad.top + ch}L${sx(0)},${pad.top + ch}Z`;

    const spikes = showSpikes ? detectSpikes(data, spikeThreshold) : [];

    // Y-axis ticks (4 levels)
    const yTicks: { y: number; label: string }[] = [];
    for (let i = 0; i <= 3; i++) {
      const v = pMin + (pRange / 3) * i;
      yTicks.push({ y: sy(v), label: `${(v * 100).toFixed(1)}%` });
    }

    return { line, area, spikes, yTicks, sx, sy, pMin, pMax, pRange };
  }, [data, cw, ch, showSpikes, spikeThreshold, pad]);

  const handleMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (!svgRef.current || !data) return;
    const rect = svgRef.current.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const relX = (mouseX - pad.left) / cw;
    const idx = Math.round(relX * (data.length - 1));
    if (idx >= 0 && idx < data.length) {
      setCursor({ x: mouseX, idx });
    }

    // Check if hovering over a spike region
    if (chart) {
      const hovered = chart.spikes.find(s => idx >= s.startIdx && idx <= s.endIdx);
      setHoveredSpike(hovered || null);
    }
  }, [data, cw, pad.left, chart]);

  if (!chart || !data || data.length < 2) return null;

  const lineColor = positive ? '#16a34a' : '#dc2626';
  const fillColor = positive ? 'rgba(22,163,74,0.04)' : 'rgba(220,38,38,0.04)';
  const totalHours = 30 * 24; // 30 days assumption

  // Cursor readout values
  const cursorVal = cursor ? data[cursor.idx] : null;
  const cursorTs = cursor && timestamps && timestamps[cursor.idx] ? timestamps[cursor.idx] : null;
  const cursorDate = cursorTs
    ? new Date(cursorTs).toLocaleString('en-US', { month: 'numeric', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true })
    : cursor
      ? (() => {
          // Estimate date from index position (30-day range)
          const daysAgo = 30 - (cursor.idx / (data.length - 1)) * 30;
          const d = new Date(Date.now() - daysAgo * 86400000);
          return d.toLocaleString('en-US', { month: 'numeric', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true });
        })()
      : null;

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
              stroke="#e5e5e8" strokeDasharray="3,5" />
            <text x={width - pad.right + 4} y={t.y + 3} fill="#a1a1aa" fontSize={9}
              fontFamily="'JetBrains Mono', monospace">{t.label}</text>
          </g>
        ))}

        {/* Spike shaded regions */}
        {chart.spikes.map((s, i) => {
          const x1 = chart.sx(s.startIdx);
          const x2 = chart.sx(s.endIdx);
          const w = Math.max(x2 - x1, 4);
          return (
            <g key={`spike-${i}`}>
              {/* Shaded area */}
              <rect x={x1} y={pad.top} width={w} height={ch}
                fill={spikeShadeColor(s.direction, s.magnitude)}
                rx={2} />
              {/* Left edge line */}
              <line x1={x1} y1={pad.top} x2={x1} y2={pad.top + ch}
                stroke={spikeEdgeColor(s.direction)} strokeWidth={1} />
              {/* Right edge line */}
              <line x1={x2} y1={pad.top} x2={x2} y2={pad.top + ch}
                stroke={spikeEdgeColor(s.direction)} strokeWidth={1} />
            </g>
          );
        })}

        {/* Area fill */}
        <path d={chart.area} fill={fillColor} />

        {/* Price line */}
        <path d={chart.line} fill="none" stroke={lineColor} strokeWidth={1.8} strokeLinejoin="round" />

        {/* Crosshair cursor */}
        {cursor && cursorVal !== null && (
          <>
            {/* Vertical line */}
            <line x1={cursor.x} y1={pad.top} x2={cursor.x} y2={pad.top + ch}
              stroke="#18181b" strokeWidth={0.8} />
            {/* Dot on line */}
            <circle cx={chart.sx(cursor.idx)} cy={chart.sy(cursorVal)}
              r={4} fill={lineColor} stroke="white" strokeWidth={2} />
          </>
        )}
      </svg>

      {/* Crosshair readout — date + price (positioned above cursor) */}
      {cursor && cursorVal !== null && (
        <div style={{
          position: 'absolute',
          left: Math.min(Math.max(cursor.x - 80, 4), width - 180),
          top: 0,
          background: 'white', border: '1px solid var(--border-subtle)',
          borderRadius: 6, padding: '4px 10px', fontSize: 11,
          boxShadow: 'var(--shadow-sm)', pointerEvents: 'none', zIndex: 10,
          whiteSpace: 'nowrap',
        }}>
          <div style={{ color: 'var(--text-muted)', marginBottom: 2 }}>{cursorDate}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: lineColor, display: 'inline-block' }} />
            <span style={{ fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
              {label} {(cursorVal * 100).toFixed(1)}%
            </span>
          </div>
        </div>
      )}

      {/* Spike hover detail */}
      {hoveredSpike && cursor && (
        <div style={{
          position: 'absolute',
          left: Math.min(chart.sx(hoveredSpike.startIdx) + 8, width - 240),
          top: height - 8,
          background: '#18181b', color: 'white', borderRadius: 10,
          padding: '12px 16px', fontSize: 12, lineHeight: 1.6,
          boxShadow: '0 8px 24px rgba(0,0,0,0.25)', pointerEvents: 'none', zIndex: 20,
          minWidth: 200, maxWidth: 280,
        }}>
          {/* Duration */}
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ color: '#a1a1aa', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Duration
            </span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>
              {fmtDuration(hoveredSpike.durationPoints, data.length, totalHours)}
            </span>
          </div>

          {/* Size */}
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ color: '#a1a1aa', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Move
            </span>
            <span style={{
              fontFamily: "'JetBrains Mono', monospace", fontWeight: 700,
              color: hoveredSpike.direction === 'up' ? '#4ade80' : '#f87171',
            }}>
              {hoveredSpike.direction === 'up' ? '+' : '-'}{(hoveredSpike.magnitude * 100).toFixed(1)}pp
            </span>
          </div>

          {/* Price range */}
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
            <span style={{ color: '#a1a1aa', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Range
            </span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>
              {(hoveredSpike.priceBefore * 100).toFixed(1)}% → {(hoveredSpike.priceAfter * 100).toFixed(1)}%
            </span>
          </div>

          {/* Attributors */}
          {attributors && attributors.length > 0 && (
            <div style={{ borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 6, marginTop: 2 }}>
              <div style={{ color: '#a1a1aa', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>
                Probable Causes
              </div>
              {attributors.slice(0, 3).map((a, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, marginBottom: 2 }}>
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginRight: 8 }}>
                    {a.name}
                  </span>
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", color: '#a1a1aa', flexShrink: 0 }}>
                    {(a.confidence * 100).toFixed(0)}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
