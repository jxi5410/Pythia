'use client';

import { useEffect, useState, useMemo, useCallback } from 'react';
import type { Spike, Attributor, ForwardSignal, PricePoint, MarketAnalysis } from '@/types';

interface SpikeChartProps {
  marketId: string;
  apiBase?: string;
  height?: number;
  onSpikeClick?: (spike: Spike) => void;
  onAttributorClick?: (attributor: Attributor) => void;
}

function spikeColor(mag: number): string {
  if (mag >= 0.10) return '#ef4444';
  if (mag >= 0.05) return '#f97316';
  if (mag >= 0.03) return '#eab308';
  return '#94a3b8';
}

function fmtDate(ts: string) {
  return new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function fmtTime(ts: string) {
  return new Date(ts).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export default function SpikeChart({ marketId, apiBase = '/api/v1', height = 300, onSpikeClick, onAttributorClick }: SpikeChartProps) {
  const [data, setData] = useState<MarketAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [hoveredSpike, setHoveredSpike] = useState<Spike | null>(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });

  useEffect(() => {
    setLoading(true);
    fetch(`${apiBase}/analyze/${encodeURIComponent(marketId)}?hours=720&spike_threshold=0.02`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [marketId, apiBase]);

  const margin = { top: 16, right: 48, bottom: 32, left: 52 };
  const width = 760;
  const cw = width - margin.left - margin.right;
  const ch = height - margin.top - margin.bottom;

  const chart = useMemo(() => {
    if (!data?.price_history?.length) return null;
    const pts = data.price_history.map(p => ({ t: new Date(p.timestamp).getTime(), p: p.yes_price }))
      .filter(p => !isNaN(p.t)).sort((a, b) => a.t - b.t);
    if (pts.length < 2) return null;

    const tMin = pts[0].t, tMax = pts[pts.length - 1].t;
    const pArr = pts.map(p => p.p);
    const pMin = Math.max(0, Math.min(...pArr) - 0.02);
    const pMax = Math.min(1, Math.max(...pArr) + 0.02);
    const sx = (t: number) => ((t - tMin) / (tMax - tMin)) * cw;
    const sy = (p: number) => ch - ((p - pMin) / (pMax - pMin)) * ch;

    const line = 'M' + pts.map(p => `${sx(p.t)},${sy(p.p)}`).join('L');
    const area = `${line}L${sx(tMax)},${ch}L${sx(tMin)},${ch}Z`;

    const spikes = (data.spikes || []).map(s => {
      const st = new Date(s.timestamp).getTime();
      return { ...s, cx: sx(st), cy: sy(s.price_after), color: spikeColor(s.magnitude) };
    }).filter(s => s.cx >= 0 && s.cx <= cw);

    const yTicks: number[] = [];
    for (let i = 0; i <= 4; i++) yTicks.push(pMin + ((pMax - pMin) / 4) * i);

    const xTicks: { t: number; label: string }[] = [];
    for (let i = 0; i <= 5; i++) {
      const t = tMin + ((tMax - tMin) / 5) * i;
      xTicks.push({ t, label: fmtDate(new Date(t).toISOString()) });
    }

    return { line, area, spikes, yTicks, xTicks, sx, sy, pMin, pMax, tMin, tMax };
  }, [data, cw, ch]);

  if (loading) return <div className="flex items-center justify-center" style={{ height }}><div className="loading-spinner" /></div>;
  if (!chart) return <div className="flex items-center justify-center" style={{ height }}><span style={{ color: 'var(--text-muted)', fontSize: 13 }}>No data</span></div>;

  return (
    <div style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', maxHeight: height }}
        onMouseMove={e => { const r = e.currentTarget.getBoundingClientRect(); setMousePos({ x: e.clientX - r.left, y: e.clientY - r.top }); }}
        onMouseLeave={() => setHoveredSpike(null)}>
        <defs>
          <linearGradient id="cg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.10" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.01" />
          </linearGradient>
        </defs>
        <g transform={`translate(${margin.left},${margin.top})`}>
          {chart.yTicks.map((t, i) => {
            const y = ch - ((t - chart.pMin) / (chart.pMax - chart.pMin)) * ch;
            return <g key={i}><line x1={0} y1={y} x2={cw} y2={y} stroke="var(--border-subtle)" strokeDasharray="3,4" /><text x={-6} y={y + 3} textAnchor="end" fill="var(--text-muted)" fontSize={10} fontFamily="var(--font-mono)">{(t * 100).toFixed(0)}%</text></g>;
          })}
          {chart.xTicks.map((t, i) => <text key={i} x={chart.sx(t.t)} y={ch + 22} textAnchor="middle" fill="var(--text-muted)" fontSize={10}>{t.label}</text>)}
          <path d={chart.area} fill="url(#cg)" />
          <path d={chart.line} fill="none" stroke="var(--accent)" strokeWidth={1.5} strokeLinejoin="round" />
          {chart.spikes.map((s, i) => (
            <g key={i} style={{ cursor: 'pointer' }}
              onMouseEnter={() => setHoveredSpike(s)}
              onMouseLeave={() => setHoveredSpike(null)}
              onClick={() => onSpikeClick?.(s)}>
              <line x1={s.cx} y1={0} x2={s.cx} y2={ch} stroke={s.color} strokeWidth={1} strokeOpacity={0.25} strokeDasharray="2,3" />
              <circle cx={s.cx} cy={s.cy} r={s.magnitude >= 0.08 ? 6 : s.magnitude >= 0.04 ? 5 : 4} fill={s.color} fillOpacity={0.85} stroke={s.color} strokeWidth={2} strokeOpacity={0.3} />
              <text x={s.cx} y={s.cy - 10} textAnchor="middle" fill={s.color} fontSize={11} fontWeight="bold">{s.direction === 'up' ? '▲' : '▼'}</text>
            </g>
          ))}
        </g>
      </svg>

      {hoveredSpike && (
        <div style={{
          position: 'absolute', left: Math.min(mousePos.x + 12, 560), top: Math.max(mousePos.y - 70, 4),
          background: 'var(--bg-card)', border: '1px solid var(--border-default)', borderRadius: 'var(--radius-md)',
          padding: '10px 14px', boxShadow: 'var(--shadow-lg)', zIndex: 50, pointerEvents: 'none', minWidth: 180,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: spikeColor(hoveredSpike.magnitude) }} />
            <span style={{ fontWeight: 650, fontSize: 12, color: 'var(--text-primary)' }}>
              {hoveredSpike.direction === 'up' ? '↑' : '↓'} {(hoveredSpike.magnitude * 100).toFixed(1)}pp
            </span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>
            <div>{(hoveredSpike.price_before * 100).toFixed(1)}% → {(hoveredSpike.price_after * 100).toFixed(1)}%</div>
            <div>{fmtTime(hoveredSpike.timestamp)}</div>
          </div>
        </div>
      )}

      {data?.attributors && data.attributors.length > 0 && (
        <div style={{ marginTop: 10, borderTop: '1px solid var(--border-subtle)', paddingTop: 10 }}>
          <div className="data-label" style={{ marginBottom: 6 }}>Attributors</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {data.attributors.slice(0, 5).map(a => (
              <button key={a.id} onClick={() => onAttributorClick?.(a)}
                className="layer-tag" style={{ cursor: 'pointer', opacity: Math.max(0.5, a.confidence_score || 0.5) }}>
                {a.name?.slice(0, 35)}{a.name && a.name.length > 35 ? '…' : ''}
                <span style={{ marginLeft: 4, color: 'var(--text-muted)', fontSize: 10 }}>{a.confidence}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
