'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { Market, Signal, TrackRecordSummary } from '@/types';

type MarketWithSignal = Market & {
  signal?: Signal & { trackRecord?: TrackRecordSummary } | null;
};

function formatCurrency(value: number): string {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
  return `$${value}`;
}

function ProbabilityChange({ current, previous }: { current: number; previous: number }) {
  const change = current - previous;
  const changeStr = change >= 0 ? `+${(change * 100).toFixed(1)}` : `${(change * 100).toFixed(1)}`;
  const color = change >= 0 ? 'var(--positive)' : 'var(--negative)';
  return (
    <span style={{ fontSize: 'var(--text-xs)', fontFamily: 'var(--font-mono)', color, fontWeight: 600 }}>
      {changeStr}%
    </span>
  );
}

function ProbabilityBar({ probability }: { probability: number }) {
  const pct = probability * 100;
  const yesColor = pct >= 60 ? 'var(--positive)' : pct >= 40 ? 'var(--warning)' : 'var(--negative)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, width: '100%' }}>
      <div style={{
        flex: 1,
        height: 6,
        background: 'var(--bg-surface)',
        borderRadius: 100,
        overflow: 'hidden',
      }}>
        <div style={{
          width: `${pct}%`,
          height: '100%',
          background: yesColor,
          borderRadius: 100,
          transition: 'width 0.6s ease',
        }} />
      </div>
      <div style={{
        display: 'flex',
        gap: 12,
        fontSize: 'var(--text-xs)',
        fontFamily: 'var(--font-mono)',
        fontWeight: 600,
        flexShrink: 0,
      }}>
        <span style={{ color: yesColor }}>YES {pct.toFixed(0)}%</span>
        <span style={{ color: 'var(--text-muted)' }}>NO {(100 - pct).toFixed(0)}%</span>
      </div>
    </div>
  );
}

// SVG sparkline chart with spike areas highlighted
function SparklineChart({ data, width = 200, height = 48 }: { data: number[]; width?: number; height?: number }) {
  if (!data || data.length < 2) return null;

  const padding = 2;
  const chartW = width - padding * 2;
  const chartH = height - padding * 2;
  const min = Math.min(...data) - 0.02;
  const max = Math.max(...data) + 0.02;
  const range = max - min || 0.01;

  const toX = (i: number) => padding + (i / (data.length - 1)) * chartW;
  const toY = (v: number) => padding + chartH - ((v - min) / range) * chartH;

  // Build line path
  const linePath = data.map((v, i) => `${i === 0 ? 'M' : 'L'}${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');

  // Detect spikes: points where abs change from previous > threshold
  const threshold = 0.04;
  const spikeRegions: { startX: number; endX: number; color: string }[] = [];
  for (let i = 1; i < data.length; i++) {
    const change = data[i] - data[i - 1];
    if (Math.abs(change) > threshold) {
      const x1 = toX(Math.max(0, i - 1));
      const x2 = toX(Math.min(data.length - 1, i + 1));
      spikeRegions.push({
        startX: x1,
        endX: x2,
        color: change > 0 ? 'rgba(22, 163, 74, 0.12)' : 'rgba(220, 38, 38, 0.12)',
      });
    }
  }

  // Gradient fill under line
  const areaPath = linePath + ` L${toX(data.length - 1).toFixed(1)},${(height - padding).toFixed(1)} L${padding.toFixed(1)},${(height - padding).toFixed(1)} Z`;

  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      {/* Spike highlight regions */}
      {spikeRegions.map((region, idx) => (
        <rect
          key={idx}
          x={region.startX}
          y={padding}
          width={region.endX - region.startX}
          height={chartH}
          fill={region.color}
          rx={2}
        />
      ))}
      {/* Area fill */}
      <path d={areaPath} fill="rgba(26, 86, 219, 0.06)" />
      {/* Line */}
      <path d={linePath} fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      {/* Current value dot */}
      <circle cx={toX(data.length - 1)} cy={toY(data[data.length - 1])} r="2.5" fill="var(--accent)" />
    </svg>
  );
}

// Track record tooltip content
function TrackRecordTooltip({ trackRecord }: { trackRecord: TrackRecordSummary }) {
  return (
    <div style={{
      position: 'absolute',
      bottom: 'calc(100% + 8px)',
      right: 0,
      background: 'var(--text-primary)',
      color: 'var(--text-inverse)',
      borderRadius: 'var(--radius-sm)',
      padding: '14px 16px',
      width: 320,
      zIndex: 100,
      boxShadow: 'var(--shadow-lg)',
      fontSize: 'var(--text-xs)',
      lineHeight: 1.6,
    }}>
      <div style={{ fontWeight: 600, marginBottom: 10, fontSize: 'var(--text-sm)' }}>
        Signal Track Record
      </div>

      {/* Summary metrics with explanations */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 12 }}>
        <div>
          <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--positive)', fontSize: 'var(--text-md)' }}>
            {trackRecord.hitRate}%
          </div>
          <div style={{ color: 'rgba(255,255,255,0.6)', marginTop: 2 }}>
            Hit Rate
          </div>
          <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: '10px' }}>
            {trackRecord.wins}W / {trackRecord.losses}L of {trackRecord.resolved} resolved
          </div>
        </div>
        <div>
          <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#60a5fa', fontSize: 'var(--text-md)' }}>
            {trackRecord.avgReturn}
          </div>
          <div style={{ color: 'rgba(255,255,255,0.6)', marginTop: 2 }}>
            Avg Return
          </div>
          <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: '10px' }}>
            Mean move when signal hit
          </div>
        </div>
        <div>
          <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#a78bfa', fontSize: 'var(--text-md)' }}>
            {trackRecord.sharpeRatio.toFixed(2)}
          </div>
          <div style={{ color: 'rgba(255,255,255,0.6)', marginTop: 2 }}>
            Sharpe
          </div>
          <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: '10px' }}>
            Risk-adjusted return ratio
          </div>
        </div>
      </div>

      {/* Recent results */}
      <div style={{ borderTop: '1px solid rgba(255,255,255,0.15)', paddingTop: 10 }}>
        <div style={{ fontWeight: 600, marginBottom: 6, color: 'rgba(255,255,255,0.7)' }}>Recent Results</div>
        {trackRecord.recentResults.slice(0, 4).map((r, i) => (
          <div key={i} style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '4px 0',
            borderBottom: i < 3 ? '1px solid rgba(255,255,255,0.08)' : 'none',
          }}>
            <div style={{ flex: 1 }}>
              <span style={{ color: 'rgba(255,255,255,0.5)', fontFamily: 'var(--font-mono)', marginRight: 8 }}>{r.date}</span>
              <span style={{ color: 'rgba(255,255,255,0.8)' }}>{r.event}</span>
            </div>
            <div style={{
              fontFamily: 'var(--font-mono)',
              fontWeight: 600,
              color: r.hit ? 'var(--positive)' : 'var(--negative)',
              marginLeft: 8,
              flexShrink: 0,
            }}>
              {r.hit ? 'HIT' : 'MISS'}
            </div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 10, color: 'rgba(255,255,255,0.4)', fontSize: '10px', lineHeight: 1.5 }}>
        Based on {trackRecord.totalSignals} signals tracked over 30-day forward testing. Past performance does not guarantee future results.
      </div>

      {/* Arrow */}
      <div style={{
        position: 'absolute',
        bottom: -5,
        right: 20,
        width: 10,
        height: 10,
        background: 'var(--text-primary)',
        transform: 'rotate(45deg)',
      }} />
    </div>
  );
}

// Signal analysis panel shown inline next to signal-triggered market cards
function SignalAnalysisPanel({ signal }: { signal: Signal & { trackRecord?: TrackRecordSummary } }) {
  const [showTrackRecord, setShowTrackRecord] = useState(false);

  return (
    <div style={{
      background: `var(--severity-${signal.severity}-bg)`,
      border: `1px solid rgba(${signal.severity === 'critical' ? '220,38,38' : signal.severity === 'high' ? '234,88,12' : signal.severity === 'medium' ? '202,138,4' : '22,163,74'}, 0.15)`,
      borderRadius: 'var(--radius-sm)',
      padding: '14px 16px',
      marginTop: 14,
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: `var(--severity-${signal.severity})`,
            animation: 'pulse-soft 2s ease-in-out infinite',
          }} />
          <span style={{
            fontSize: 'var(--text-xs)',
            fontWeight: 700,
            color: `var(--severity-${signal.severity})`,
            textTransform: 'uppercase',
            letterSpacing: '0.04em',
          }}>
            {signal.severity} Signal Active
          </span>
        </div>
        <Link href={`/signal/${signal.id}`} style={{
          fontSize: '10px',
          fontWeight: 600,
          color: 'var(--accent-text)',
          textDecoration: 'none',
          padding: '3px 10px',
          borderRadius: 100,
          border: '1px solid var(--accent)',
          background: 'var(--accent-muted)',
          transition: 'all 0.15s ease',
        }}>
          FULL ANALYSIS
        </Link>
      </div>

      {/* Metrics row */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 10, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Layers</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: 'var(--text-sm)', color: 'var(--text-primary)' }}>
            {signal.confluenceLayers}/{signal.totalLayers}
          </div>
        </div>
        <div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Hit Rate</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: 'var(--text-sm)', color: 'var(--text-primary)' }}>
            {Math.round(signal.historicalHitRate * 100)}%
          </div>
        </div>
        <div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Edge</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: 'var(--text-sm)', color: 'var(--text-primary)' }}>
            {signal.edgeWindow}
          </div>
        </div>
        <div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Confidence</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: 'var(--text-sm)', color: 'var(--text-primary)' }}>
            {Math.round(signal.confidenceScore * 100)}%
          </div>
        </div>
        {/* Track record hover */}
        {signal.trackRecord && (
          <div style={{ position: 'relative', marginLeft: 'auto' }}>
            <button
              onMouseEnter={() => setShowTrackRecord(true)}
              onMouseLeave={() => setShowTrackRecord(false)}
              style={{
                fontSize: '10px',
                fontWeight: 600,
                color: 'var(--text-secondary)',
                padding: '3px 10px',
                borderRadius: 100,
                border: '1px solid var(--border-default)',
                background: 'var(--bg-card)',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
              </svg>
              TRACK RECORD
            </button>
            {showTrackRecord && <TrackRecordTooltip trackRecord={signal.trackRecord} />}
          </div>
        )}
      </div>

      {/* Asset impacts */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        {signal.assetImpact.slice(0, 3).map((impact, idx) => (
          <div key={idx} style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '4px 10px',
            background: 'var(--bg-card)',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)',
          }}>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 'var(--text-xs)',
              fontWeight: 600,
              color: 'var(--text-primary)',
            }}>
              {impact.asset}
            </span>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 'var(--text-xs)',
              fontWeight: 700,
              color: impact.expectedMove.startsWith('+') ? 'var(--positive)' : 'var(--negative)',
            }}>
              {impact.expectedMove}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function MarketCard({ market }: { market: MarketWithSignal }) {
  const daysLeft = Math.ceil(
    (new Date(market.endDate).getTime() - Date.now()) / (1000 * 60 * 60 * 24)
  );
  const sourceLabel = market.source === 'polymarket' ? 'Polymarket' : 'Kalshi';
  const hasSignal = !!market.signal;

  return (
    <div style={{
      background: 'var(--bg-card)',
      border: hasSignal
        ? `1px solid rgba(${market.signal!.severity === 'critical' ? '220,38,38' : market.signal!.severity === 'high' ? '234,88,12' : '202,138,4'}, 0.25)`
        : '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius-lg)',
      padding: '18px 20px',
      transition: 'all 0.2s ease',
      position: 'relative',
      overflow: 'hidden',
      boxShadow: 'var(--shadow-card)',
    }}
    onMouseEnter={(e) => {
      e.currentTarget.style.borderColor = 'var(--border-default)';
      e.currentTarget.style.boxShadow = 'var(--shadow-md)';
      e.currentTarget.style.transform = 'translateY(-1px)';
    }}
    onMouseLeave={(e) => {
      e.currentTarget.style.borderColor = hasSignal
        ? `rgba(${market.signal!.severity === 'critical' ? '220,38,38' : market.signal!.severity === 'high' ? '234,88,12' : '202,138,4'}, 0.25)`
        : 'var(--border-subtle)';
      e.currentTarget.style.boxShadow = 'var(--shadow-card)';
      e.currentTarget.style.transform = 'translateY(0)';
    }}
    >
      {/* Signal indicator badge */}
      {hasSignal && (
        <div style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: 3,
          background: `var(--severity-${market.signal!.severity})`,
        }} />
      )}

      {/* Trending indicator */}
      {market.trending && !hasSignal && (
        <div style={{
          position: 'absolute',
          top: 0,
          right: 0,
          background: 'var(--accent-muted)',
          borderBottomLeftRadius: 'var(--radius-sm)',
          padding: '3px 10px',
          fontSize: '10px',
          fontWeight: 700,
          color: 'var(--accent-text)',
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
        }}>
          TRENDING
        </div>
      )}

      {/* Main content: question + chart side by side */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        <div style={{ flex: 1 }}>
          {/* Question */}
          <h3 style={{
            fontSize: 'var(--text-md)',
            fontWeight: 600,
            color: 'var(--text-primary)',
            lineHeight: 1.4,
            marginBottom: 14,
            paddingRight: (!hasSignal && market.trending) ? 70 : 0,
            paddingTop: hasSignal ? 4 : 0,
          }}>
            {market.question}
          </h3>

          {/* Probability bar */}
          <div style={{ marginBottom: 14 }}>
            <ProbabilityBar probability={market.probability} />
          </div>
        </div>

        {/* Sparkline chart */}
        {market.probabilityHistory && market.probabilityHistory.length > 0 && (
          <div style={{
            flexShrink: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            paddingTop: hasSignal ? 6 : 0,
          }}>
            <SparklineChart data={market.probabilityHistory} width={140} height={48} />
            <span style={{
              fontSize: '9px',
              color: 'var(--text-muted)',
              marginTop: 2,
              fontFamily: 'var(--font-mono)',
            }}>30d probability</span>
          </div>
        )}
      </div>

      {/* Meta row */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 8,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>24h</span>
            <ProbabilityChange current={market.probability} previous={market.previousProbability} />
          </div>
          <span style={{
            fontSize: 'var(--text-xs)',
            fontFamily: 'var(--font-mono)',
            color: 'var(--text-secondary)',
          }}>
            Vol {formatCurrency(market.volume24h)}
          </span>
          <span style={{
            fontSize: 'var(--text-xs)',
            fontFamily: 'var(--font-mono)',
            color: 'var(--text-muted)',
          }}>
            Liq {formatCurrency(market.liquidity)}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <a
            href={market.sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className={`source-badge source-badge-${market.source}`}
          >
            {sourceLabel}
            <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
          </a>

          <span style={{
            fontSize: 'var(--text-xs)',
            fontFamily: 'var(--font-mono)',
            color: daysLeft <= 7 ? 'var(--warning)' : 'var(--text-muted)',
            fontWeight: daysLeft <= 7 ? 600 : 400,
          }}>
            {daysLeft}d left
          </span>
        </div>
      </div>

      {/* Tags */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 12 }}>
        {market.tags.slice(0, 3).map((tag) => (
          <span key={tag} className="layer-tag" style={{ fontSize: '10px', padding: '2px 8px' }}>
            {tag}
          </span>
        ))}
      </div>

      {/* Signal Analysis Panel (inline, for markets with active signals) */}
      {market.signal && (
        <SignalAnalysisPanel signal={market.signal} />
      )}
    </div>
  );
}

// Consolidated categories across Polymarket + Kalshi
const allCategories = [
  { id: 'all', label: 'All Markets' },
  { id: 'fed', label: 'Economics & Finance' },
  { id: 'tariffs', label: 'Trade & Tariffs' },
  { id: 'crypto', label: 'Crypto & Web3' },
  { id: 'geopolitical', label: 'World Events' },
  { id: 'defense', label: 'Defense & Security' },
];

const sortOptions = [
  { id: 'volume', label: 'Volume' },
  { id: 'change', label: 'Biggest Moves' },
  { id: 'probability', label: 'Highest Odds' },
  { id: 'ending', label: 'Ending Soon' },
];

const selectionCriteria = [
  { label: 'Volume', desc: 'Highest 24h trading volume across Polymarket & Kalshi' },
  { label: 'Liquidity', desc: 'Sufficient market depth for meaningful price signal' },
  { label: 'Signal relevance', desc: 'Markets where Pythia layers can detect edge' },
  { label: 'Expiry window', desc: 'Active markets with meaningful time remaining' },
];

export default function MarketsPage() {
  const [markets, setMarkets] = useState<MarketWithSignal[]>([]);
  const [category, setCategory] = useState('all');
  const [sort, setSort] = useState('volume');
  const [sourceFilter, setSourceFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());
  const [showCriteria, setShowCriteria] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const params = new URLSearchParams();
        if (category !== 'all') params.set('category', category);
        if (sourceFilter !== 'all') params.set('source', sourceFilter);
        params.set('sort', sort);
        const response = await fetch(`/api/markets?${params}`);
        const data = await response.json();
        if (!cancelled) {
          setMarkets(data.markets || []);
          setLastUpdate(new Date());
          setLoading(false);
        }
      } catch {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    const interval = setInterval(load, 30000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [category, sort, sourceFilter]);

  const signalCount = markets.filter(m => m.signal).length;

  return (
    <main style={{ background: 'var(--bg-primary)', minHeight: '100vh' }}>
      {/* Header */}
      <header style={{
        position: 'sticky',
        top: 0,
        zIndex: 50,
        background: 'rgba(255, 255, 255, 0.95)',
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid var(--border-subtle)',
      }}>
        <div style={{ maxWidth: 960, margin: '0 auto', padding: '16px 20px 12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <h1 style={{
                  fontSize: 'var(--text-2xl)',
                  fontWeight: 700,
                  color: 'var(--text-primary)',
                  letterSpacing: '-0.03em',
                  lineHeight: 1,
                }}>
                  Pythia
                </h1>
                <span style={{
                  fontSize: 'var(--text-sm)',
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                  letterSpacing: '0.01em',
                }}>
                  / Markets
                </span>
              </div>
              <p style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--text-muted)',
                marginTop: 4,
              }}>
                Prediction markets with real-time signal detection
              </p>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: 'var(--positive)',
                  boxShadow: '0 0 6px var(--positive)',
                  animation: 'pulse-soft 2s ease-in-out infinite',
                }} />
                <span style={{
                  fontSize: 'var(--text-xs)',
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--positive)',
                  fontWeight: 600,
                }}>LIVE</span>
                <span style={{
                  fontSize: '10px',
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--text-muted)',
                  marginLeft: 4,
                }}>
                  {lastUpdate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
            </div>
          </div>

          {/* Category filters + source filter */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
            <div className="scrollbar-hide" style={{
              display: 'flex',
              gap: 6,
              overflowX: 'auto',
              paddingBottom: 2,
              flex: 1,
            }}>
              {allCategories.map((cat) => (
                <button
                  key={cat.id}
                  onClick={() => setCategory(cat.id)}
                  style={{
                    padding: '6px 14px',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: 'var(--text-sm)',
                    fontWeight: 500,
                    whiteSpace: 'nowrap',
                    border: category === cat.id
                      ? '1px solid var(--accent)'
                      : '1px solid var(--border-subtle)',
                    background: category === cat.id
                      ? 'var(--accent-muted)'
                      : 'var(--bg-card)',
                    color: category === cat.id
                      ? 'var(--accent-text)'
                      : 'var(--text-secondary)',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                >
                  {cat.label}
                </button>
              ))}
            </div>

            {/* Source toggle: All / Polymarket / Kalshi */}
            <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
              {[
                { id: 'all', label: 'All' },
                { id: 'polymarket', label: 'PM' },
                { id: 'kalshi', label: 'Kalshi' },
              ].map((src) => (
                <button
                  key={src.id}
                  onClick={() => setSourceFilter(src.id)}
                  style={{
                    padding: '5px 10px',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '10px',
                    fontWeight: 600,
                    whiteSpace: 'nowrap',
                    border: sourceFilter === src.id
                      ? '1px solid var(--accent)'
                      : '1px solid var(--border-subtle)',
                    background: sourceFilter === src.id
                      ? 'var(--accent-muted)'
                      : 'var(--bg-card)',
                    color: sourceFilter === src.id
                      ? 'var(--accent-text)'
                      : 'var(--text-muted)',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                    textTransform: 'uppercase',
                    letterSpacing: '0.04em',
                  }}
                >
                  {src.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </header>

      {/* Content */}
      <div style={{ maxWidth: 960, margin: '0 auto', padding: '20px 20px 80px' }}>
        {loading ? (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            paddingTop: 100,
          }}>
            <div style={{
              width: 28,
              height: 28,
              border: '2px solid var(--accent)',
              borderTopColor: 'transparent',
              borderRadius: '50%',
              animation: 'spin 0.8s linear infinite',
            }} />
            <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', marginTop: 20 }}>
              Loading markets...
            </p>
          </div>
        ) : (
          <>
            {/* Sort controls + selection criteria */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 16,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <h2 style={{
                  fontSize: 'var(--text-lg)',
                  fontWeight: 600,
                  color: 'var(--text-primary)',
                }}>
                  {category === 'all' ? 'All Markets' : allCategories.find(c => c.id === category)?.label}
                  <span style={{
                    fontSize: 'var(--text-sm)',
                    color: 'var(--text-muted)',
                    fontWeight: 400,
                    marginLeft: 8,
                  }}>
                    ({markets.length})
                  </span>
                </h2>
                {signalCount > 0 && (
                  <span style={{
                    fontSize: '10px',
                    fontWeight: 700,
                    padding: '3px 10px',
                    borderRadius: 100,
                    background: 'var(--severity-high-bg)',
                    color: 'var(--severity-high)',
                    border: '1px solid rgba(234, 88, 12, 0.15)',
                    letterSpacing: '0.04em',
                  }}>
                    {signalCount} SIGNAL{signalCount > 1 ? 'S' : ''} ACTIVE
                  </span>
                )}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {/* Selection criteria button */}
                <div style={{ position: 'relative' }}>
                  <button
                    onClick={() => setShowCriteria(!showCriteria)}
                    style={{
                      padding: '5px 12px',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '10px',
                      fontWeight: 600,
                      whiteSpace: 'nowrap',
                      border: '1px solid var(--border-subtle)',
                      background: showCriteria ? 'var(--accent-muted)' : 'var(--bg-card)',
                      color: showCriteria ? 'var(--accent-text)' : 'var(--text-muted)',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 4,
                    }}
                  >
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="12" r="10" />
                      <path d="M12 16v-4m0-4h.01" />
                    </svg>
                    WHY THESE MARKETS
                  </button>
                  {showCriteria && (
                    <div style={{
                      position: 'absolute',
                      top: 'calc(100% + 8px)',
                      right: 0,
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border-default)',
                      borderRadius: 'var(--radius-md)',
                      padding: '16px',
                      width: 320,
                      boxShadow: 'var(--shadow-lg)',
                      zIndex: 40,
                    }}>
                      <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--text-primary)', marginBottom: 10 }}>
                        Market Selection Criteria
                      </div>
                      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 12, lineHeight: 1.6 }}>
                        Markets are ranked and selected based on a composite score of:
                      </p>
                      {selectionCriteria.map((c, i) => (
                        <div key={i} style={{
                          display: 'flex',
                          gap: 10,
                          marginBottom: 8,
                          alignItems: 'flex-start',
                        }}>
                          <div style={{
                            width: 18,
                            height: 18,
                            borderRadius: '50%',
                            background: 'var(--accent-muted)',
                            color: 'var(--accent-text)',
                            fontSize: '10px',
                            fontWeight: 700,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            flexShrink: 0,
                            marginTop: 1,
                          }}>
                            {i + 1}
                          </div>
                          <div>
                            <div style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-primary)' }}>{c.label}</div>
                            <div style={{ fontSize: '10px', color: 'var(--text-muted)', lineHeight: 1.5 }}>{c.desc}</div>
                          </div>
                        </div>
                      ))}
                      <div style={{
                        marginTop: 12,
                        paddingTop: 10,
                        borderTop: '1px solid var(--border-subtle)',
                        fontSize: '10px',
                        color: 'var(--text-muted)',
                        lineHeight: 1.5,
                      }}>
                        Use the category, source, and sort filters above to customize which markets you see. Markets with active Pythia signals are automatically promoted to the top.
                      </div>
                    </div>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  {sortOptions.map((opt) => (
                    <button
                      key={opt.id}
                      onClick={() => setSort(opt.id)}
                      style={{
                        padding: '5px 12px',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: '10px',
                        fontWeight: 600,
                        whiteSpace: 'nowrap',
                        border: sort === opt.id
                          ? '1px solid var(--accent)'
                          : '1px solid var(--border-subtle)',
                        background: sort === opt.id
                          ? 'var(--accent-muted)'
                          : 'var(--bg-card)',
                        color: sort === opt.id
                          ? 'var(--accent-text)'
                          : 'var(--text-muted)',
                        cursor: 'pointer',
                        transition: 'all 0.15s ease',
                        textTransform: 'uppercase',
                        letterSpacing: '0.04em',
                      }}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Market cards */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {markets.map((market) => (
                <MarketCard key={market.id} market={market} />
              ))}
            </div>

            {/* Footer note */}
            <div style={{
              marginTop: 28,
              background: 'var(--accent-muted)',
              border: '1px solid rgba(26, 86, 219, 0.12)',
              borderRadius: 'var(--radius-lg)',
              padding: '14px 18px',
              display: 'flex',
              alignItems: 'center',
              gap: 12,
            }}>
              <div style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: 'var(--accent-text)',
                flexShrink: 0,
              }} />
              <p style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--accent-text)',
                lineHeight: 1.6,
              }}>
                Market data aggregated from Polymarket CLOB and Kalshi APIs. Categories are consolidated across both platforms. Probabilities reflect current YES token prices. Refreshes every 30 seconds.
              </p>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
