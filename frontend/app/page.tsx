'use client';

import { useEffect, useState } from 'react';

import type { Market, Signal, TrackRecordSummary } from '@/types';

type MarketWithSignal = Market & {
  signal?: Signal & { trackRecord?: TrackRecordSummary } | null;
};

const categories = [
  { id: 'all', label: 'All' },
  { id: 'fed', label: 'Macro' },
  { id: 'crypto', label: 'Crypto' },
  { id: 'tariffs', label: 'Trade' },
  { id: 'geopolitical', label: 'World' },
  { id: 'defense', label: 'Defense' },
];

const sources = [
  { id: 'all', label: 'All Venues' },
  { id: 'polymarket', label: 'Polymarket' },
  { id: 'kalshi', label: 'Kalshi' },
];

function formatCurrency(value: number): string {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `$${Math.round(value / 1_000)}K`;
  return `$${value}`;
}

function formatTimeAgo(timestamp: string): string {
  const diffMinutes = Math.max(0, Math.floor((Date.now() - new Date(timestamp).getTime()) / 60000));
  if (diffMinutes < 1) return 'now';
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${Math.floor(diffHours / 24)}d ago`;
}

function formatDaysLeft(endDate: string): string {
  const daysLeft = Math.max(0, Math.ceil((new Date(endDate).getTime() - Date.now()) / (1000 * 60 * 60 * 24)));
  return daysLeft === 0 ? 'ends today' : `${daysLeft}d left`;
}

function priceChange(current: number, previous: number): number {
  return (current - previous) * 100;
}

function MiniChart({ data }: { data: number[] }) {
  if (!data || data.length < 2) return null;

  const width = 320;
  const height = 96;
  const padX = 4;
  const padY = 8;
  const min = Math.min(...data) - 0.015;
  const max = Math.max(...data) + 0.015;
  const range = Math.max(0.03, max - min);
  const innerWidth = width - padX * 2;
  const innerHeight = height - padY * 2;

  const toX = (index: number) => padX + (index / (data.length - 1)) * innerWidth;
  const toY = (value: number) => padY + innerHeight - ((value - min) / range) * innerHeight;

  const line = data.map((value, index) => `${index === 0 ? 'M' : 'L'} ${toX(index)} ${toY(value)}`).join(' ');
  const area = `${line} L ${toX(data.length - 1)} ${height - padY} L ${padX} ${height - padY} Z`;
  const positive = data[data.length - 1] >= data[0];

  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="market-chart">
      <defs>
        <linearGradient id={`fill-${data.length}-${Math.round(data[data.length - 1] * 1000)}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={positive ? 'rgba(34, 197, 94, 0.22)' : 'rgba(59, 130, 246, 0.20)'} />
          <stop offset="100%" stopColor="rgba(255,255,255,0)" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#fill-${data.length}-${Math.round(data[data.length - 1] * 1000)})`} />
      <path
        d={line}
        fill="none"
        stroke={positive ? 'var(--positive)' : 'var(--accent)'}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle
        cx={toX(data.length - 1)}
        cy={toY(data[data.length - 1])}
        r="3.5"
        fill={positive ? 'var(--positive)' : 'var(--accent)'}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

function MarketCard({ market }: { market: MarketWithSignal }) {
  const change = priceChange(market.probability, market.previousProbability);
  const positiveChange = change >= 0;
  const yes = Math.round(market.probability * 100);
  const no = 100 - yes;
  const sourceLabel = market.source === 'polymarket' ? 'Polymarket' : 'Kalshi';

  return (
    <article className={`exchange-card${market.signal ? ' exchange-card-signal' : ''}`}>
      <div className="exchange-card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span className="venue-chip">{sourceLabel}</span>
          {market.signal ? (
            <span className="signal-chip">
              Pythia Edge
              <span className="signal-chip-dot" />
            </span>
          ) : null}
        </div>
        <span className="meta-mono">{formatDaysLeft(market.endDate)}</span>
      </div>

      <a href={market.sourceUrl} target="_blank" rel="noopener noreferrer" className="question-link">
        {market.question}
      </a>

      <div className="chart-shell">
        <MiniChart data={market.probabilityHistory || []} />
        <div className="chart-meta-row">
          <span className="meta-mono">{formatTimeAgo(market.signal?.timestamp || new Date().toISOString())}</span>
          <span className={`price-move ${positiveChange ? 'price-up' : 'price-down'}`}>
            {positiveChange ? '+' : ''}{change.toFixed(1)} pts
          </span>
        </div>
      </div>

      <div className="price-row">
        <div className="price-box price-box-yes">
          <span className="price-label">Yes</span>
          <span className="price-value">{yes}%</span>
        </div>
        <div className="price-box">
          <span className="price-label">No</span>
          <span className="price-value">{no}%</span>
        </div>
      </div>

      <div className="card-foot">
        <span className="meta-mono">Vol {formatCurrency(market.volume24h)}</span>
        <span className="meta-mono">Liq {formatCurrency(market.liquidity)}</span>
        <span className="meta-mono">{market.category}</span>
      </div>

      {market.signal ? (
        <div className="edge-strip">
          <div className="edge-strip-head">
            <span className="edge-title">Signal context</span>
            <span className="meta-mono">{Math.round(market.signal.confidenceScore * 100)}% conf</span>
          </div>
          <div className="edge-strip-grid">
            <div>
              <div className="edge-kicker">Window</div>
              <div className="edge-value">{market.signal.edgeWindow}</div>
            </div>
            <div>
              <div className="edge-kicker">Layers</div>
              <div className="edge-value">{market.signal.confluenceLayers}/{market.signal.totalLayers}</div>
            </div>
            <div>
              <div className="edge-kicker">Hit rate</div>
              <div className="edge-value">{Math.round(market.signal.historicalHitRate * 100)}%</div>
            </div>
          </div>
          <div className="layer-inline-list">
            {market.signal.layersFired.slice(0, 3).map((layer) => (
              <span key={layer} className="layer-inline-item">{layer}</span>
            ))}
          </div>
        </div>
      ) : null}
    </article>
  );
}

export default function HomePage() {
  const [markets, setMarkets] = useState<MarketWithSignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState('all');
  const [source, setSource] = useState('all');
  const [dataSource, setDataSource] = useState<'live' | 'mock'>('live');
  const [lastUpdated, setLastUpdated] = useState('');

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const params = new URLSearchParams();
        params.set('sort', 'volume');
        if (category !== 'all') params.set('category', category);
        if (source !== 'all') params.set('source', source);

        const response = await fetch(`/api/markets?${params.toString()}`);
        const data = await response.json();
        if (!cancelled) {
          setMarkets(data.markets || []);
          setDataSource(data.dataSource === 'mock' ? 'mock' : 'live');
          setLastUpdated(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
          setLoading(false);
        }
      } catch {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    const interval = setInterval(load, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [category, source]);

  const signaled = markets.filter((market) => market.signal).length;

  return (
    <main className="market-shell">
      <div className="hero-panel">
        <div>
          <div className="hero-kicker">Prediction market terminal</div>
          <h1 className="hero-title">Pythia</h1>
          <p className="hero-subtitle">
            One live market wall. Exchange-style cards first, Pythia signal context inline.
          </p>
        </div>
        <div className="hero-stats">
          <div className="hero-stat">
            <span className="hero-stat-label">Markets</span>
            <span className="hero-stat-value">{markets.length}</span>
          </div>
          <div className="hero-stat">
            <span className="hero-stat-label">Signals</span>
            <span className="hero-stat-value">{signaled}</span>
          </div>
          <div className="hero-stat">
            <span className="hero-stat-label">Updated</span>
            <span className="hero-stat-value">{lastUpdated || '--:--'}</span>
          </div>
        </div>
      </div>

      <section className="control-bar">
        <div className="filter-row">
          {categories.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setCategory(item.id)}
              className={`filter-chip${category === item.id ? ' filter-chip-active' : ''}`}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="filter-row">
          {sources.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setSource(item.id)}
              className={`filter-chip filter-chip-quiet${source === item.id ? ' filter-chip-active' : ''}`}
            >
              {item.label}
            </button>
          ))}
          <span className="data-pill">
            {dataSource === 'mock' ? 'Demo data' : 'Live feed'}
          </span>
        </div>
      </section>

      {loading ? (
        <div className="loading-shell">
          <div className="loading-spinner" />
          <p className="loading-text">Loading market wall</p>
        </div>
      ) : (
        <section className="cards-grid">
          {markets.map((market) => (
            <MarketCard key={market.id} market={market} />
          ))}
        </section>
      )}
    </main>
  );
}
