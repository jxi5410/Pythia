'use client';

import { useEffect, useState, useMemo } from 'react';

/**
 * SpikeChart — 30-day price chart with spike markers and attributor labels.
 *
 * Features:
 * - Line chart showing probability over time
 * - Colored spike markers overlaid at detection timestamps
 * - Hover tooltips showing attributor name, confidence, magnitude
 * - Confidence shading (lighter = lower confidence)
 * - Forward signal indicators
 *
 * Props:
 *   marketId: string — market to display
 *   apiBase: string — base URL for Pythia API (default /api/v1)
 */

interface PricePoint {
  timestamp: string;
  yes_price: number;
  volume?: number;
}

interface Spike {
  id: number;
  timestamp: string;
  direction: string;
  magnitude: number;
  price_before: number;
  price_after: number;
  asset_class: string;
}

interface Attributor {
  id: string;
  name: string;
  category: string;
  confidence: string;
  confidence_score: number;
  spike_count: number;
}

interface ForwardSignal {
  id: number;
  predicted_direction: string;
  predicted_magnitude: number;
  predicted_lag_hours: number;
  confidence_score: number;
  target_market_title: string;
  created_at: string;
}

interface AnalysisData {
  market_id: string;
  market_title: string;
  price_history: PricePoint[];
  spikes: Spike[];
  attributors: Attributor[];
  forward_signals: ForwardSignal[];
}

interface SpikeChartProps {
  marketId: string;
  apiBase?: string;
  height?: number;
}

// Color mapping for spike severity based on magnitude
function spikeColor(magnitude: number): string {
  if (magnitude >= 0.10) return '#ef4444'; // red — major
  if (magnitude >= 0.05) return '#f97316'; // orange — significant
  if (magnitude >= 0.03) return '#eab308'; // yellow — moderate
  return '#6b7280'; // gray — minor
}

function confidenceOpacity(score: number): number {
  return Math.max(0.3, Math.min(1.0, score));
}

function formatDate(ts: string): string {
  const d = new Date(ts);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function formatTime(ts: string): string {
  const d = new Date(ts);
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function SpikeChart({
  marketId,
  apiBase = '/api/v1',
  height = 320,
}: SpikeChartProps) {
  const [data, setData] = useState<AnalysisData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hoveredSpike, setHoveredSpike] = useState<Spike | null>(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });

  useEffect(() => {
    setLoading(true);
    setError(null);

    fetch(`${apiBase}/analyze/${encodeURIComponent(marketId)}?hours=720&spike_threshold=0.02`)
      .then((r) => {
        if (!r.ok) throw new Error(`API error: ${r.status}`);
        return r.json();
      })
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, [marketId, apiBase]);

  // Chart dimensions
  const margin = { top: 20, right: 60, bottom: 40, left: 60 };
  const width = 800;
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;

  // Compute chart data
  const chartData = useMemo(() => {
    if (!data?.price_history?.length) return null;

    const prices = data.price_history
      .map((p) => ({
        t: new Date(p.timestamp).getTime(),
        p: p.yes_price,
      }))
      .filter((p) => !isNaN(p.t) && !isNaN(p.p))
      .sort((a, b) => a.t - b.t);

    if (prices.length < 2) return null;

    const tMin = prices[0].t;
    const tMax = prices[prices.length - 1].t;
    const pMin = Math.max(0, Math.min(...prices.map((p) => p.p)) - 0.02);
    const pMax = Math.min(1, Math.max(...prices.map((p) => p.p)) + 0.02);

    const scaleX = (t: number) => ((t - tMin) / (tMax - tMin)) * chartWidth;
    const scaleY = (p: number) => chartHeight - ((p - pMin) / (pMax - pMin)) * chartHeight;

    // Build SVG path
    const pathPoints = prices.map((p) => `${scaleX(p.t)},${scaleY(p.p)}`);
    const linePath = `M${pathPoints.join('L')}`;

    // Area fill path
    const areaPath = `${linePath}L${scaleX(prices[prices.length - 1].t)},${chartHeight}L${scaleX(prices[0].t)},${chartHeight}Z`;

    // Spike positions
    const spikeMarkers = (data.spikes || []).map((s) => {
      const st = new Date(s.timestamp).getTime();
      return {
        ...s,
        cx: scaleX(st),
        cy: scaleY(s.price_after),
        color: spikeColor(s.magnitude),
      };
    }).filter((s) => s.cx >= 0 && s.cx <= chartWidth);

    // Y-axis ticks
    const yTicks: number[] = [];
    const step = (pMax - pMin) / 4;
    for (let i = 0; i <= 4; i++) {
      yTicks.push(pMin + step * i);
    }

    // X-axis ticks (5-6 date labels)
    const xTicks: { t: number; label: string }[] = [];
    const tStep = (tMax - tMin) / 5;
    for (let i = 0; i <= 5; i++) {
      const t = tMin + tStep * i;
      xTicks.push({ t, label: formatDate(new Date(t).toISOString()) });
    }

    return {
      prices,
      linePath,
      areaPath,
      spikeMarkers,
      yTicks,
      xTicks,
      scaleX,
      scaleY,
      tMin,
      tMax,
      pMin,
      pMax,
    };
  }, [data, chartWidth, chartHeight]);

  if (loading) {
    return (
      <div
        className="flex items-center justify-center bg-gray-900 rounded-lg border border-gray-800"
        style={{ height }}
      >
        <div className="text-gray-400 text-sm">Loading chart...</div>
      </div>
    );
  }

  if (error || !chartData) {
    return (
      <div
        className="flex items-center justify-center bg-gray-900 rounded-lg border border-gray-800"
        style={{ height }}
      >
        <div className="text-gray-500 text-sm">
          {error || 'No price data available'}
        </div>
      </div>
    );
  }

  const { linePath, areaPath, spikeMarkers, yTicks, xTicks, scaleX } = chartData;

  return (
    <div className="relative bg-gray-900 rounded-lg border border-gray-800 p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-white text-sm font-medium truncate max-w-md">
            {data?.market_title || marketId}
          </h3>
          <div className="flex items-center gap-3 mt-1">
            <span className="text-gray-400 text-xs">30d price history</span>
            {data?.spikes?.length ? (
              <span className="text-orange-400 text-xs">
                {data.spikes.length} spike{data.spikes.length !== 1 ? 's' : ''} detected
              </span>
            ) : null}
            {data?.forward_signals?.length ? (
              <span className="text-blue-400 text-xs">
                {data.forward_signals.length} forward signal{data.forward_signals.length !== 1 ? 's' : ''}
              </span>
            ) : null}
          </div>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-red-500" /> Major
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-orange-500" /> Significant
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-yellow-500" /> Moderate
          </span>
        </div>
      </div>

      {/* SVG Chart */}
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ maxHeight: height }}
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          setMousePos({
            x: e.clientX - rect.left,
            y: e.clientY - rect.top,
          });
        }}
        onMouseLeave={() => setHoveredSpike(null)}
      >
        <defs>
          <linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.15" />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity="0.02" />
          </linearGradient>
        </defs>

        <g transform={`translate(${margin.left},${margin.top})`}>
          {/* Grid lines */}
          {yTicks.map((tick, i) => {
            const y = chartHeight - ((tick - chartData.pMin) / (chartData.pMax - chartData.pMin)) * chartHeight;
            return (
              <g key={`y-${i}`}>
                <line
                  x1={0}
                  y1={y}
                  x2={chartWidth}
                  y2={y}
                  stroke="#1f2937"
                  strokeDasharray="4,4"
                />
                <text x={-8} y={y + 4} textAnchor="end" fill="#6b7280" fontSize={10}>
                  {(tick * 100).toFixed(0)}%
                </text>
              </g>
            );
          })}

          {/* X axis labels */}
          {xTicks.map((tick, i) => {
            const x = scaleX(tick.t);
            return (
              <text
                key={`x-${i}`}
                x={x}
                y={chartHeight + 25}
                textAnchor="middle"
                fill="#6b7280"
                fontSize={10}
              >
                {tick.label}
              </text>
            );
          })}

          {/* Area fill */}
          <path d={areaPath} fill="url(#areaGradient)" />

          {/* Price line */}
          <path
            d={linePath}
            fill="none"
            stroke="#3b82f6"
            strokeWidth={1.5}
            strokeLinejoin="round"
          />

          {/* Spike markers */}
          {spikeMarkers.map((spike, i) => (
            <g
              key={`spike-${i}`}
              onMouseEnter={() => setHoveredSpike(spike)}
              onMouseLeave={() => setHoveredSpike(null)}
              style={{ cursor: 'pointer' }}
            >
              {/* Vertical line at spike time */}
              <line
                x1={spike.cx}
                y1={0}
                x2={spike.cx}
                y2={chartHeight}
                stroke={spike.color}
                strokeWidth={1}
                strokeOpacity={0.3}
                strokeDasharray="2,3"
              />
              {/* Spike dot */}
              <circle
                cx={spike.cx}
                cy={spike.cy}
                r={spike.magnitude >= 0.08 ? 6 : spike.magnitude >= 0.04 ? 5 : 4}
                fill={spike.color}
                fillOpacity={0.8}
                stroke={spike.color}
                strokeWidth={2}
                strokeOpacity={0.4}
              />
              {/* Direction arrow */}
              <text
                x={spike.cx}
                y={spike.cy - 10}
                textAnchor="middle"
                fill={spike.color}
                fontSize={12}
                fontWeight="bold"
              >
                {spike.direction === 'up' ? '▲' : '▼'}
              </text>
            </g>
          ))}

          {/* Forward signal indicators */}
          {data?.forward_signals?.map((sig, i) => {
            const now = Date.now();
            const lagMs = (sig.predicted_lag_hours || 1) * 3600 * 1000;
            const targetTime = new Date(sig.created_at).getTime() + lagMs;
            if (targetTime < chartData.tMin || targetTime > chartData.tMax + lagMs) return null;
            const x = Math.min(scaleX(targetTime), chartWidth - 5);
            return (
              <g key={`fwd-${i}`}>
                <line
                  x1={x}
                  y1={0}
                  x2={x}
                  y2={chartHeight}
                  stroke="#60a5fa"
                  strokeWidth={1}
                  strokeOpacity={0.4}
                  strokeDasharray="3,3"
                />
                <text
                  x={x}
                  y={12}
                  textAnchor="middle"
                  fill="#60a5fa"
                  fontSize={10}
                >
                  ⚡
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {/* Tooltip */}
      {hoveredSpike && (
        <div
          className="absolute z-50 bg-gray-800 border border-gray-700 rounded-lg p-3 shadow-xl pointer-events-none"
          style={{
            left: Math.min(mousePos.x + 10, width - 220),
            top: mousePos.y - 80,
            minWidth: 200,
          }}
        >
          <div className="flex items-center gap-2 mb-1">
            <span
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: spikeColor(hoveredSpike.magnitude) }}
            />
            <span className="text-white text-xs font-medium">
              {hoveredSpike.direction === 'up' ? '↑' : '↓'}{' '}
              {(hoveredSpike.magnitude * 100).toFixed(1)}pp spike
            </span>
          </div>
          <div className="text-gray-400 text-xs space-y-0.5">
            <div>
              {(hoveredSpike.price_before * 100).toFixed(1)}% →{' '}
              {(hoveredSpike.price_after * 100).toFixed(1)}%
            </div>
            <div>{formatTime(hoveredSpike.timestamp)}</div>
            {hoveredSpike.asset_class && (
              <div className="text-gray-500">{hoveredSpike.asset_class}</div>
            )}
          </div>
        </div>
      )}

      {/* Attributors list below chart */}
      {data?.attributors && data.attributors.length > 0 && (
        <div className="mt-3 border-t border-gray-800 pt-3">
          <div className="text-gray-400 text-xs mb-2 font-medium">Active Attributors</div>
          <div className="flex flex-wrap gap-2">
            {data.attributors.slice(0, 5).map((attr) => (
              <div
                key={attr.id}
                className="bg-gray-800 rounded px-2 py-1 text-xs border border-gray-700"
                style={{
                  opacity: confidenceOpacity(attr.confidence_score || 0.5),
                }}
              >
                <span className="text-white">{attr.name?.slice(0, 40)}</span>
                <span className="text-gray-500 ml-1">
                  {attr.confidence} · {attr.spike_count} spike
                  {attr.spike_count !== 1 ? 's' : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Forward signals below */}
      {data?.forward_signals && data.forward_signals.length > 0 && (
        <div className="mt-2 border-t border-gray-800 pt-2">
          <div className="text-blue-400 text-xs mb-1 font-medium">⚡ Forward Signals</div>
          <div className="space-y-1">
            {data.forward_signals.slice(0, 3).map((sig) => (
              <div
                key={sig.id}
                className="text-xs text-gray-400 flex items-center gap-2"
              >
                <span className={sig.predicted_direction === 'up' ? 'text-green-400' : 'text-red-400'}>
                  {sig.predicted_direction === 'up' ? '▲' : '▼'}
                  {(sig.predicted_magnitude * 100).toFixed(1)}%
                </span>
                <span>in ~{sig.predicted_lag_hours}h</span>
                <span className="text-gray-600">
                  conf: {(sig.confidence_score * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
