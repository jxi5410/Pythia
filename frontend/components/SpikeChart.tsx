'use client';

import { useMemo, useState } from 'react';

interface SpikeChartProps {
  data: number[];          // probabilityHistory array (30+ points)
  height?: number;
  width?: number;
  showSpikes?: boolean;    // detect and overlay spikes
  spikeThreshold?: number; // min move to mark as spike (0-1)
  positive?: boolean;
  interactive?: boolean;
}

interface DetectedSpike {
  index: number;
  magnitude: number;
  direction: 'up' | 'down';
  priceBefore: number;
  priceAfter: number;
}

function detectSpikes(data: number[], threshold: number = 0.03, windowSize: number = 3): DetectedSpike[] {
  if (!data || data.length < windowSize + 1) return [];
  const spikes: DetectedSpike[] = [];
  let lastSpikeIdx = -999;

  for (let i = windowSize; i < data.length; i++) {
    const windowStart = data[i - windowSize];
    const current = data[i];
    const move = Math.abs(current - windowStart);

    if (move >= threshold && (i - lastSpikeIdx) >= windowSize) {
      spikes.push({
        index: i,
        magnitude: move,
        direction: current > windowStart ? 'up' : 'down',
        priceBefore: windowStart,
        priceAfter: current,
      });
      lastSpikeIdx = i;
    }
  }
  return spikes;
}

function spikeColor(mag: number): string {
  if (mag >= 0.10) return '#ef4444';
  if (mag >= 0.05) return '#f97316';
  if (mag >= 0.03) return '#eab308';
  return '#94a3b8';
}

export default function SpikeChart({
  data,
  height = 160,
  width = 500,
  showSpikes = true,
  spikeThreshold = 0.03,
  positive = true,
  interactive = true,
}: SpikeChartProps) {
  const [hovered, setHovered] = useState<DetectedSpike | null>(null);
  const [mouseX, setMouseX] = useState(0);

  const chart = useMemo(() => {
    if (!data || data.length < 2) return null;

    const pad = { top: 12, right: 8, bottom: 4, left: 8 };
    const cw = width - pad.left - pad.right;
    const ch = height - pad.top - pad.bottom;

    const mn = Math.min(...data);
    const mx = Math.max(...data);
    const range = mx - mn || 0.01;

    const sx = (i: number) => pad.left + (i / (data.length - 1)) * cw;
    const sy = (v: number) => pad.top + ch - ((v - mn) / range) * ch;

    const pts = data.map((v, i) => `${sx(i)},${sy(v)}`);
    const line = `M${pts.join('L')}`;
    const area = `${line}L${sx(data.length - 1)},${pad.top + ch}L${sx(0)},${pad.top + ch}Z`;

    const spikes = showSpikes ? detectSpikes(data, spikeThreshold) : [];
    const spikeMarkers = spikes.map(s => ({
      ...s,
      cx: sx(s.index),
      cy: sy(s.priceAfter),
    }));

    // Y-axis labels (just min and max)
    const yLabels = [
      { y: sy(mx), label: `${(mx * 100).toFixed(0)}%` },
      { y: sy(mn), label: `${(mn * 100).toFixed(0)}%` },
    ];

    return { line, area, spikeMarkers, yLabels, sx, sy, pad, cw, ch, mn, mx };
  }, [data, width, height, showSpikes, spikeThreshold]);

  if (!chart) return null;

  const lineColor = positive ? '#16a34a' : '#dc2626';
  const fillColor = positive ? 'rgba(22,163,74,0.06)' : 'rgba(220,38,38,0.06)';

  return (
    <div style={{ position: 'relative' }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        style={{ width: '100%', height }}
        onMouseMove={interactive ? (e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          setMouseX(e.clientX - rect.left);
        } : undefined}
        onMouseLeave={() => setHovered(null)}
      >
        {/* Y-axis labels */}
        {chart.yLabels.map((yl, i) => (
          <text key={i} x={width - 4} y={yl.y + 3} textAnchor="end"
            fill="#a1a1aa" fontSize={9} fontFamily="'JetBrains Mono', monospace">{yl.label}</text>
        ))}

        {/* Grid lines */}
        <line x1={chart.pad.left} y1={chart.yLabels[0].y} x2={width - 40} y2={chart.yLabels[0].y}
          stroke="#e5e5e8" strokeDasharray="3,4" />
        <line x1={chart.pad.left} y1={chart.yLabels[1].y} x2={width - 40} y2={chart.yLabels[1].y}
          stroke="#e5e5e8" strokeDasharray="3,4" />

        {/* Area + line */}
        <path d={chart.area} fill={fillColor} />
        <path d={chart.line} fill="none" stroke={lineColor} strokeWidth={1.8} strokeLinejoin="round" />

        {/* Spike markers */}
        {chart.spikeMarkers.map((s, i) => (
          <g key={i} style={{ cursor: interactive ? 'pointer' : 'default' }}
            onMouseEnter={() => setHovered(s)}
            onMouseLeave={() => setHovered(null)}>
            {/* Vertical line */}
            <line x1={s.cx} y1={chart.pad.top} x2={s.cx} y2={chart.pad.top + chart.ch}
              stroke={spikeColor(s.magnitude)} strokeWidth={1} strokeOpacity={0.3} strokeDasharray="2,3" />
            {/* Dot */}
            <circle cx={s.cx} cy={s.cy}
              r={s.magnitude >= 0.08 ? 5 : s.magnitude >= 0.04 ? 4 : 3.5}
              fill={spikeColor(s.magnitude)} fillOpacity={0.9}
              stroke="white" strokeWidth={1.5} />
            {/* Arrow */}
            <text x={s.cx} y={s.cy - 8} textAnchor="middle"
              fill={spikeColor(s.magnitude)} fontSize={9} fontWeight="bold">
              {s.direction === 'up' ? '▲' : '▼'}
            </text>
          </g>
        ))}
      </svg>

      {/* Tooltip */}
      {hovered && interactive && (
        <div style={{
          position: 'absolute', left: Math.min(mouseX + 8, width - 160), top: 4,
          background: '#18181b', color: 'white', borderRadius: 8,
          padding: '8px 12px', fontSize: 11, lineHeight: 1.5,
          boxShadow: '0 4px 16px rgba(0,0,0,0.2)', pointerEvents: 'none', zIndex: 10,
        }}>
          <div style={{ fontWeight: 700 }}>
            {hovered.direction === 'up' ? '↑' : '↓'} {(hovered.magnitude * 100).toFixed(1)}pp spike
          </div>
          <div style={{ opacity: 0.7 }}>
            {(hovered.priceBefore * 100).toFixed(1)}% → {(hovered.priceAfter * 100).toFixed(1)}%
          </div>
        </div>
      )}
    </div>
  );
}
