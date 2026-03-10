'use client';

import { useMemo, useState, useRef, useCallback } from 'react';

export interface SpikeAttributor {
  name: string;
  confidence: number;
  url?: string;  // link to source for more details
}

export interface SpikeData {
  startIdx: number;
  endIdx: number;
  magnitude: number;
  direction: 'up' | 'down';
  priceBefore: number;
  priceAfter: number;
  durationPoints: number;
  attributors: SpikeAttributor[];  // per-spike attributors
}

interface SpikeChartProps {
  data: number[];
  height?: number;
  width?: number;
  showSpikes?: boolean;
  spikeThreshold?: number;
  interactive?: boolean;
  spikeAttributors?: Record<number, SpikeAttributor[]>;  // keyed by spike index
  defaultAttributors?: SpikeAttributor[];  // fallback
}

function detectSpikes(data: number[], threshold: number, ws: number = 3): SpikeData[] {
  if (!data || data.length < ws + 1) return [];
  const out: SpikeData[] = [];
  let lastEnd = -999;
  for (let i = ws; i < data.length; i++) {
    let bs = i - 1, bm = 0;
    for (let j = Math.max(0, i - ws * 2); j < i; j++) {
      const m = Math.abs(data[i] - data[j]);
      if (m > bm) { bm = m; bs = j; }
    }
    if (bm >= threshold && bs > lastEnd) {
      out.push({
        startIdx: bs, endIdx: i, magnitude: bm,
        direction: data[i] > data[bs] ? 'up' : 'down',
        priceBefore: data[bs], priceAfter: data[i],
        durationPoints: i - bs, attributors: [],
      });
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
  interactive = true, spikeAttributors, defaultAttributors,
}: SpikeChartProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [cursor, setCursor] = useState<{ x: number; idx: number } | null>(null);
  const [hoveredSpikeIdx, setHoveredSpikeIdx] = useState<number | null>(null);
  const [pinnedSpikeIdx, setPinnedSpikeIdx] = useState<number | null>(null);

  const pad = { top: 10, right: 48, bottom: 36, left: 10 };
  const cw = width - pad.left - pad.right;
  const ch = height - pad.top - pad.bottom;

  const chart = useMemo(() => {
    if (!data || data.length < 2) return null;

    // Dynamic y-axis: data min/max rounded to nearest 5%
    const rawMin = Math.min(...data);
    const rawMax = Math.max(...data);
    const pMin = Math.max(0, Math.floor(rawMin * 20) / 20);  // round down to 5%
    const pMax = Math.min(1, Math.ceil(rawMax * 20) / 20);    // round up to 5%
    const pRange = pMax - pMin || 0.05;

    const sx = (i: number) => pad.left + (i / (data.length - 1)) * cw;
    const sy = (v: number) => pad.top + ch - ((v - pMin) / pRange) * ch;

    const pts = data.map((v, i) => `${sx(i)},${sy(v)}`);
    const line = `M${pts.join('L')}`;
    const area = `${line}L${sx(data.length - 1)},${pad.top + ch}L${sx(0)},${pad.top + ch}Z`;

    let spikes = showSpikes ? detectSpikes(data, spikeThreshold) : [];

    // Attach per-spike attributors
    spikes = spikes.map((s, i) => ({
      ...s,
      attributors: spikeAttributors?.[i] || defaultAttributors || [],
    }));

    // Y-ticks: evenly spaced within dynamic range, at 5% increments
    const yTicks: { y: number; label: string }[] = [];
    const step = pRange <= 0.15 ? 0.05 : pRange <= 0.35 ? 0.05 : 0.10;
    for (let v = pMin; v <= pMax + 0.001; v += step) {
      yTicks.push({ y: sy(v), label: `${Math.round(v * 100)}%` });
    }

    const xTicks: { x: number; label: string }[] = [];
    for (let i = 0; i <= 5; i++) {
      const idx = Math.round((i / 5) * (data.length - 1));
      const daysAgo = 30 - (idx / (data.length - 1)) * 30;
      const d = new Date(Date.now() - daysAgo * 86400000);
      xTicks.push({ x: sx(idx), label: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) });
    }

    return { line, area, spikes, yTicks, xTicks, sx, sy, pMin, pMax };
  }, [data, cw, ch, showSpikes, spikeThreshold, pad, spikeAttributors, defaultAttributors]);

  const handleMM = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (!svgRef.current || !data || pinnedSpikeIdx !== null) return;
    const rect = svgRef.current.getBoundingClientRect();
    const scale = width / rect.width;
    const svgX = (e.clientX - rect.left) * scale;
    const rel = (svgX - pad.left) / cw;
    const idx = Math.round(Math.max(0, Math.min(1, rel)) * (data.length - 1));
    setCursor({ x: svgX, idx });
    if (chart) {
      const found = chart.spikes.findIndex(s => idx >= s.startIdx && idx <= s.endIdx);
      setHoveredSpikeIdx(found >= 0 ? found : null);
    } else {
      setHoveredSpikeIdx(null);
    }
  }, [data, cw, pad.left, chart, width, pinnedSpikeIdx]);

  const handleClick = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (!chart || !interactive) return;
    // If already pinned, clicking anywhere on chart closes it
    if (pinnedSpikeIdx !== null) {
      setPinnedSpikeIdx(null);
      return;
    }
    // If hovering a spike, pin it
    if (hoveredSpikeIdx !== null) {
      setPinnedSpikeIdx(hoveredSpikeIdx);
    }
  }, [chart, interactive, pinnedSpikeIdx, hoveredSpikeIdx]);

  if (!chart || !data || data.length < 2) return null;

  const cv = cursor ? data[cursor.idx] : null;
  const cd = cursor ? (() => {
    const da = 30 - (cursor.idx / (data.length - 1)) * 30;
    return new Date(Date.now() - da * 86400000).toLocaleString('en-US', { month: 'numeric', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true });
  })() : null;

  const activeSpikeIdx = pinnedSpikeIdx ?? hoveredSpikeIdx;
  const activeSpike = activeSpikeIdx !== null ? chart.spikes[activeSpikeIdx] : null;

  return (
    <div style={{ position: 'relative', userSelect: 'none' }}>
      <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`}
        style={{ width: '100%', height, cursor: interactive ? 'crosshair' : 'default' }}
        onMouseMove={interactive ? handleMM : undefined}
        onMouseLeave={interactive && pinnedSpikeIdx === null ? () => { setCursor(null); setHoveredSpikeIdx(null); } : undefined}
        onClick={interactive ? handleClick : undefined}>

        {/* Y-axis on RIGHT — dynamic range */}
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
          const isActive = i === activeSpikeIdx;
          return (
            <g key={`s-${i}`} style={{ cursor: interactive ? 'pointer' : 'default' }}>
              <rect x={x1} y={pad.top} width={Math.max(x2 - x1, 4)} height={ch}
                fill={up ? `rgba(120,140,93,${isActive ? 0.18 : 0.10})` : `rgba(196,69,54,${isActive ? 0.18 : 0.10})`} rx={2} />
              <line x1={x1} y1={pad.top} x2={x1} y2={pad.top + ch}
                stroke={up ? 'rgba(120,140,93,0.4)' : 'rgba(196,69,54,0.4)'} strokeWidth={isActive ? 1.5 : 1} />
              <line x1={x2} y1={pad.top} x2={x2} y2={pad.top + ch}
                stroke={up ? 'rgba(120,140,93,0.4)' : 'rgba(196,69,54,0.4)'} strokeWidth={isActive ? 1.5 : 1} />
            </g>
          );
        })}

        {/* Line + area */}
        <path d={chart.area} fill="rgba(217,119,87,0.06)" />
        <path d={chart.line} fill="none" stroke={C} strokeWidth={1.8} strokeLinejoin="round" />

        {/* Crosshair */}
        {interactive && cursor && cv !== null && pinnedSpikeIdx === null && (
          <>
            <line x1={cursor.x} y1={pad.top} x2={cursor.x} y2={pad.top + ch} stroke="#141413" strokeWidth={0.8} />
            <circle cx={chart.sx(cursor.idx)} cy={chart.sy(cv)} r={4} fill={C} stroke="white" strokeWidth={2} />
          </>
        )}
      </svg>

      {/* Crosshair readout — only when not pinned */}
      {interactive && cursor && cv !== null && pinnedSpikeIdx === null && (
        <div style={{
          position: 'absolute', left: Math.min(Math.max((cursor.x / width) * 100, 3), 72) + '%',
          top: 0, background: 'white', border: '1px solid #e8e6dc',
          borderRadius: 6, padding: '4px 10px', fontSize: 11,
          boxShadow: '0 2px 8px rgba(0,0,0,0.06)', pointerEvents: 'none', zIndex: 10, whiteSpace: 'nowrap',
        }}>
          <div style={{ color: '#b0aea5', marginBottom: 2 }}>{cd}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: C, display: 'inline-block' }} />
            <span style={{ fontWeight: 700, color: '#141413', fontFamily: "'JetBrains Mono', monospace" }}>{(cv * 100).toFixed(1)}%</span>
          </div>
        </div>
      )}

      {/* Spike detail popup — pinned or hovered, interactive (user can click links inside) */}
      {interactive && activeSpike && (
        <div style={{
          position: 'absolute',
          left: Math.min(Math.max((chart.sx(activeSpike.endIdx) / width) * 100 + 1, 5), 55) + '%',
          top: '20%',
          background: '#141413', color: '#faf9f5', borderRadius: 10,
          padding: '14px 16px 12px', fontSize: 12, lineHeight: 1.6,
          boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
          pointerEvents: pinnedSpikeIdx !== null ? 'auto' : 'none',
          zIndex: 20, minWidth: 220, maxWidth: 300,
        }}>
          {/* Close button — only when pinned */}
          {pinnedSpikeIdx !== null && (
            <button onClick={(e) => { e.stopPropagation(); setPinnedSpikeIdx(null); }}
              style={{ position: 'absolute', top: 8, right: 10, background: 'none', border: 'none', color: '#b0aea5', cursor: 'pointer', fontSize: 14, lineHeight: 1 }}>✕</button>
          )}

          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Duration</span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>{fmtDur(activeSpike.durationPoints, data.length, 30 * 24)}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Move</span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: activeSpike.direction === 'up' ? '#a3b88c' : '#e07060' }}>
              {activeSpike.direction === 'up' ? '+' : '-'}{(activeSpike.magnitude * 100).toFixed(1)}pp
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
            <span style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Range</span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>
              {(activeSpike.priceBefore * 100).toFixed(1)}% → {(activeSpike.priceAfter * 100).toFixed(1)}%
            </span>
          </div>

          {/* Per-spike attributors with clickable links */}
          {activeSpike.attributors && activeSpike.attributors.length > 0 && (
            <div style={{ borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 6, marginTop: 2 }}>
              <div style={{ color: '#b0aea5', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Probable Causes</div>
              {activeSpike.attributors.slice(0, 4).map((a, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, marginBottom: 3 }}>
                  {a.url ? (
                    <a href={a.url} target="_blank" rel="noopener noreferrer"
                      style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginRight: 8, color: '#8bb8d9', textDecoration: 'none' }}
                      onMouseEnter={e => (e.currentTarget.style.textDecoration = 'underline')}
                      onMouseLeave={e => (e.currentTarget.style.textDecoration = 'none')}>
                      {a.name}
                    </a>
                  ) : (
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginRight: 8 }}>{a.name}</span>
                  )}
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", color: '#b0aea5', flexShrink: 0 }}>{(a.confidence * 100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          )}

          {pinnedSpikeIdx !== null && (
            <div style={{ marginTop: 6, fontSize: 10, color: '#706f6b', textAlign: 'center' }}>
              Click attributor for source · Click chart to close
            </div>
          )}
        </div>
      )}
    </div>
  );
}
