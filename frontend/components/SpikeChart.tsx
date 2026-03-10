'use client';

import { useMemo, useState, useRef, useCallback } from 'react';

interface SpikeChartProps {
  data: number[];
  height?: number;
  width?: number;
  showSpikes?: boolean;
  spikeThreshold?: number;
  interactive?: boolean;
  attributors?: { name: string; confidence: number }[];
}

interface DetectedSpike {
  startIdx: number; endIdx: number; magnitude: number;
  direction: 'up' | 'down'; priceBefore: number; priceAfter: number;
  durationPoints: number;
}

function detectSpikes(data: number[], threshold: number, ws: number = 3): DetectedSpike[] {
  if (!data || data.length < ws + 1) return [];
  const out: DetectedSpike[] = [];
  let lastEnd = -999;
  for (let i = ws; i < data.length; i++) {
    let bs = i - 1, bm = 0;
    for (let j = Math.max(0, i - ws * 2); j < i; j++) {
      const m = Math.abs(data[i] - data[j]);
      if (m > bm) { bm = m; bs = j; }
    }
    if (bm >= threshold && bs > lastEnd) {
      out.push({ startIdx: bs, endIdx: i, magnitude: bm, direction: data[i] > data[bs] ? 'up' : 'down', priceBefore: data[bs], priceAfter: data[i], durationPoints: i - bs });
      lastEnd = i + 1;
    }
  }
  return out;
}

function fmtDur(pts: number, total: number, hours: number): string {
  const m = Math.round(pts * (hours / Math.max(total, 1)) * 60);
  const h = Math.floor(m / 60);
  return h === 0 ? `${m}m` : `${h}h ${(m % 60).toString().padStart(2, '0')}m`;
}

const C = '#d97757';

export default function SpikeChart({
  data, height = 200, width = 600,
  showSpikes = true, spikeThreshold = 0.04,
  interactive = true, attributors,
}: SpikeChartProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [cursor, setCursor] = useState<{ x: number; idx: number } | null>(null);
  const [hSpike, setHSpike] = useState<DetectedSpike | null>(null);

  // Padding: y-axis on RIGHT, bottom has room for x-axis + spacing
  const pad = { top: 10, right: 48, bottom: 36, left: 10 };
  const cw = width - pad.left - pad.right;
  const ch = height - pad.top - pad.bottom;

  const chart = useMemo(() => {
    if (!data || data.length < 2) return null;
    const sx = (i: number) => pad.left + (i / (data.length - 1)) * cw;
    const sy = (v: number) => pad.top + ch - v * ch; // 0-1 mapped to 0-100%

    const pts = data.map((v, i) => `${sx(i)},${sy(v)}`);
    const line = `M${pts.join('L')}`;
    const area = `${line}L${sx(data.length - 1)},${pad.top + ch}L${sx(0)},${pad.top + ch}Z`;
    const spikes = showSpikes ? detectSpikes(data, spikeThreshold) : [];

    const yTicks = [0, 0.25, 0.50, 0.75, 1.0].map(v => ({
      y: sy(v), label: `${Math.round(v * 100)}%`,
    }));

    const xTicks: { x: number; label: string }[] = [];
    for (let i = 0; i <= 5; i++) {
      const idx = Math.round((i / 5) * (data.length - 1));
      const daysAgo = 30 - (idx / (data.length - 1)) * 30;
      const d = new Date(Date.now() - daysAgo * 86400000);
      xTicks.push({ x: sx(idx), label: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) });
    }

    return { line, area, spikes, yTicks, xTicks, sx, sy };
  }, [data, cw, ch, showSpikes, spikeThreshold, pad]);

  const handleMM = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (!svgRef.current || !data) return;
    const rect = svgRef.current.getBoundingClientRect();
    const scale = width / rect.width;
    const svgX = (e.clientX - rect.left) * scale;
    const rel = (svgX - pad.left) / cw;
    const idx = Math.round(Math.max(0, Math.min(1, rel)) * (data.length - 1));
    setCursor({ x: svgX, idx });
    if (chart) setHSpike(chart.spikes.find(s => idx >= s.startIdx && idx <= s.endIdx) || null);
  }, [data, cw, pad.left, chart, width]);

  if (!chart || !data || data.length < 2) return null;

  const cv = cursor ? data[cursor.idx] : null;
  const cd = cursor ? (() => {
    const da = 30 - (cursor.idx / (data.length - 1)) * 30;
    return new Date(Date.now() - da * 86400000).toLocaleString('en-US', { month: 'numeric', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true });
  })() : null;

  return (
    <div style={{ position: 'relative', userSelect: 'none' }}>
      <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`}
        style={{ width: '100%', height, cursor: interactive ? 'crosshair' : 'default' }}
        onMouseMove={interactive ? handleMM : undefined}
        onMouseLeave={interactive ? () => { setCursor(null); setHSpike(null); } : undefined}>

        {/* Y-axis on RIGHT */}
        {chart.yTicks.map((t, i) => (
          <g key={i}>
            <line x1={pad.left} y1={t.y} x2={width - pad.right} y2={t.y} stroke="#e8e6dc" strokeDasharray="3,5" />
            <text x={width - pad.right + 6} y={t.y + 4} textAnchor="start" fill="#b0aea5"
              fontSize={11} fontFamily="'JetBrains Mono', monospace" fontWeight={500}>{t.label}</text>
          </g>
        ))}

        {/* X-axis */}
        <line x1={pad.left} y1={pad.top + ch} x2={width - pad.right} y2={pad.top + ch} stroke="#d5d3c9" strokeWidth={1} />
        {chart.xTicks.map((t, i) => (
          <text key={i} x={t.x} y={pad.top + ch + 16} textAnchor="middle" fill="#b0aea5"
            fontSize={10} fontFamily="'Source Serif 4', serif">{t.label}</text>
        ))}

        {/* Spike shaded regions */}
        {chart.spikes.map((s, i) => {
          const x1 = chart.sx(s.startIdx), x2 = chart.sx(s.endIdx);
          const up = s.direction === 'up';
          return (
            <g key={`s-${i}`}>
              <rect x={x1} y={pad.top} width={Math.max(x2 - x1, 4)} height={ch}
                fill={up ? 'rgba(120,140,93,0.12)' : 'rgba(196,69,54,0.12)'} rx={2} />
              <line x1={x1} y1={pad.top} x2={x1} y2={pad.top + ch}
                stroke={up ? 'rgba(120,140,93,0.35)' : 'rgba(196,69,54,0.35)'} strokeWidth={1} />
              <line x1={x2} y1={pad.top} x2={x2} y2={pad.top + ch}
                stroke={up ? 'rgba(120,140,93,0.35)' : 'rgba(196,69,54,0.35)'} strokeWidth={1} />
            </g>
          );
        })}

        {/* Line + area */}
        <path d={chart.area} fill="rgba(217,119,87,0.06)" />
        <path d={chart.line} fill="none" stroke={C} strokeWidth={1.8} strokeLinejoin="round" />

        {/* Crosshair */}
        {interactive && cursor && cv !== null && (
          <>
            <line x1={cursor.x} y1={pad.top} x2={cursor.x} y2={pad.top + ch} stroke="#141413" strokeWidth={0.8} />
            <circle cx={chart.sx(cursor.idx)} cy={chart.sy(cv)} r={4} fill={C} stroke="white" strokeWidth={2} />
          </>
        )}
      </svg>

      {/* Crosshair readout */}
      {interactive && cursor && cv !== null && (
        <div style={{
          position: 'absolute',
          left: Math.min(Math.max((cursor.x / width) * 100, 3), 72) + '%',
          top: 0, background: 'white', border: '1px solid #e8e6dc',
          borderRadius: 6, padding: '4px 10px', fontSize: 11,
          boxShadow: '0 2px 8px rgba(0,0,0,0.06)', pointerEvents: 'none', zIndex: 10,
          whiteSpace: 'nowrap',
        }}>
          <div style={{ color: '#b0aea5', marginBottom: 2 }}>{cd}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: C, display: 'inline-block' }} />
            <span style={{ fontWeight: 700, color: '#141413', fontFamily: "'JetBrains Mono', monospace" }}>
              {(cv * 100).toFixed(1)}%
            </span>
          </div>
        </div>
      )}

      {/* Spike hover — positioned INSIDE the chart area, not below */}
      {interactive && hSpike && cursor && (
        <div style={{
          position: 'absolute',
          left: Math.min(Math.max((chart.sx(hSpike.endIdx) / width) * 100 + 1, 5), 58) + '%',
          top: '30%',
          background: '#141413', color: '#faf9f5', borderRadius: 10,
          padding: '12px 16px', fontSize: 12, lineHeight: 1.6,
          boxShadow: '0 8px 24px rgba(0,0,0,0.25)', pointerEvents: 'none', zIndex: 20,
          minWidth: 210, maxWidth: 280,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Duration</span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>
              {fmtDur(hSpike.durationPoints, data.length, 30 * 24)}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Move</span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: hSpike.direction === 'up' ? '#a3b88c' : '#e07060' }}>
              {hSpike.direction === 'up' ? '+' : '-'}{(hSpike.magnitude * 100).toFixed(1)}pp
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
            <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Range</span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>
              {(hSpike.priceBefore * 100).toFixed(1)}% → {(hSpike.priceAfter * 100).toFixed(1)}%
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
