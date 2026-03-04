'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { Market } from '@/types';

interface MarketStats {
  totalMarkets: number;
  totalVolume24h: number;
  totalLiquidity: number;
  trendingCount: number;
}

function formatCurrency(value: number): string {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
  return `$${value}`;
}

function formatPct(value: number): string {
  return `${(value * 100).toFixed(0)}%`;
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
        background: 'rgba(255,255,255,0.06)',
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

function MarketCard({ market }: { market: Market }) {
  const daysLeft = Math.ceil(
    (new Date(market.endDate).getTime() - Date.now()) / (1000 * 60 * 60 * 24)
  );

  return (
    <div style={{
      background: 'var(--bg-card)',
      border: '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius-lg)',
      padding: '18px 20px',
      transition: 'all 0.25s ease',
      cursor: 'pointer',
      position: 'relative',
      overflow: 'hidden',
    }}
    onMouseEnter={(e) => {
      e.currentTarget.style.borderColor = 'var(--border-default)';
      e.currentTarget.style.background = 'var(--bg-hover)';
      e.currentTarget.style.transform = 'translateY(-1px)';
      e.currentTarget.style.boxShadow = 'var(--shadow-md)';
    }}
    onMouseLeave={(e) => {
      e.currentTarget.style.borderColor = 'var(--border-subtle)';
      e.currentTarget.style.background = 'var(--bg-card)';
      e.currentTarget.style.transform = 'translateY(0)';
      e.currentTarget.style.boxShadow = 'none';
    }}
    >
      {/* Trending indicator */}
      {market.trending && (
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

      {/* Question */}
      <h3 style={{
        fontSize: 'var(--text-md)',
        fontWeight: 600,
        color: 'var(--text-primary)',
        lineHeight: 1.4,
        marginBottom: 14,
        paddingRight: market.trending ? 70 : 0,
      }}>
        {market.question}
      </h3>

      {/* Probability bar */}
      <div style={{ marginBottom: 14 }}>
        <ProbabilityBar probability={market.probability} />
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
          {/* 24h change */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>24h</span>
            <ProbabilityChange current={market.probability} previous={market.previousProbability} />
          </div>

          {/* Volume */}
          <span style={{
            fontSize: 'var(--text-xs)',
            fontFamily: 'var(--font-mono)',
            color: 'var(--text-secondary)',
          }}>
            Vol {formatCurrency(market.volume24h)}
          </span>

          {/* Liquidity */}
          <span style={{
            fontSize: 'var(--text-xs)',
            fontFamily: 'var(--font-mono)',
            color: 'var(--text-muted)',
          }}>
            Liq {formatCurrency(market.liquidity)}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {/* Source badge */}
          <span style={{
            fontSize: '10px',
            fontWeight: 600,
            padding: '2px 8px',
            borderRadius: 100,
            background: market.source === 'polymarket' ? 'rgba(99, 91, 255, 0.10)' : 'rgba(59, 130, 246, 0.10)',
            color: market.source === 'polymarket' ? 'var(--accent-text)' : 'var(--info)',
            border: `1px solid ${market.source === 'polymarket' ? 'rgba(99, 91, 255, 0.15)' : 'rgba(59, 130, 246, 0.15)'}`,
            textTransform: 'uppercase',
            letterSpacing: '0.04em',
          }}>
            {market.source}
          </span>

          {/* Days left */}
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
    </div>
  );
}

function StatCard({ label, value, subtitle }: { label: string; value: string; subtitle?: string }) {
  return (
    <div style={{
      background: 'var(--bg-card)',
      border: '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius-lg)',
      padding: '16px 18px',
      boxShadow: 'var(--shadow-sm)',
    }}>
      <div style={{
        fontSize: 'var(--text-xs)',
        color: 'var(--text-muted)',
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
        fontWeight: 500,
        marginBottom: 6,
      }}>
        {label}
      </div>
      <div style={{
        fontSize: 'var(--text-2xl)',
        fontWeight: 700,
        fontFamily: 'var(--font-mono)',
        color: 'var(--text-primary)',
        letterSpacing: '-0.02em',
      }}>
        {value}
      </div>
      {subtitle && (
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 4 }}>
          {subtitle}
        </div>
      )}
    </div>
  );
}

export default function MarketsPage() {
  const [markets, setMarkets] = useState<Market[]>([]);
  const [stats, setStats] = useState<MarketStats | null>(null);
  const [category, setCategory] = useState('all');
  const [sort, setSort] = useState('volume');
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const params = new URLSearchParams();
        if (category !== 'all') params.set('category', category);
        params.set('sort', sort);
        const response = await fetch(`/api/markets?${params}`);
        const data = await response.json();
        if (!cancelled) {
          setMarkets(data.markets || []);
          setStats(data.stats || null);
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
  }, [category, sort]);

  const categories = [
    { id: 'all', label: 'All Markets' },
    { id: 'fed', label: 'Fed & Macro' },
    { id: 'tariffs', label: 'Trade & Tariffs' },
    { id: 'crypto', label: 'Crypto' },
    { id: 'geopolitical', label: 'Geopolitical' },
    { id: 'defense', label: 'Defense' },
  ];

  const sortOptions = [
    { id: 'volume', label: 'Volume' },
    { id: 'change', label: 'Biggest Moves' },
    { id: 'probability', label: 'Highest Odds' },
    { id: 'ending', label: 'Ending Soon' },
  ];

  return (
    <main style={{ background: 'var(--bg-primary)', minHeight: '100vh' }}>
      {/* Header */}
      <header style={{
        position: 'sticky',
        top: 0,
        zIndex: 50,
        background: 'rgba(9, 9, 11, 0.92)',
        backdropFilter: 'blur(16px)',
        borderBottom: '1px solid var(--border-subtle)',
      }}>
        <div style={{ maxWidth: 960, margin: '0 auto', padding: '18px 20px 14px' }}>
          {/* Brand row */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <Link href="/" style={{ textDecoration: 'none' }}>
                  <h1 style={{
                    fontSize: 'var(--text-2xl)',
                    fontWeight: 700,
                    color: 'var(--text-primary)',
                    letterSpacing: '-0.03em',
                    lineHeight: 1,
                  }}>
                    Pythia
                  </h1>
                </Link>
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
                marginTop: 6,
                letterSpacing: '0.01em',
              }}>
                Live prediction market overview
              </p>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Link href="/" style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--text-secondary)',
                border: '1px solid var(--border-default)',
                padding: '6px 14px',
                borderRadius: 100,
                textDecoration: 'none',
                fontWeight: 500,
                transition: 'all 0.2s ease',
              }}>
                Signals
              </Link>
              <Link href="/tracking" style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--text-secondary)',
                border: '1px solid var(--border-default)',
                padding: '6px 14px',
                borderRadius: 100,
                textDecoration: 'none',
                fontWeight: 500,
                transition: 'all 0.2s ease',
              }}>
                Track Record
              </Link>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 3 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    background: 'var(--positive)',
                    boxShadow: '0 0 8px var(--positive)',
                    animation: 'pulse-soft 2s ease-in-out infinite',
                  }} />
                  <span style={{
                    fontSize: 'var(--text-xs)',
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--positive)',
                    fontWeight: 500,
                  }}>LIVE</span>
                </div>
                <span style={{
                  fontSize: '10px',
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--text-muted)',
                }}>
                  {lastUpdate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                </span>
              </div>
            </div>
          </div>

          {/* Category filters */}
          <div className="scrollbar-hide" style={{
            display: 'flex',
            gap: 8,
            overflowX: 'auto',
            paddingBottom: 2,
          }}>
            {categories.map((cat) => (
              <button
                key={cat.id}
                onClick={() => setCategory(cat.id)}
                style={{
                  padding: '7px 16px',
                  borderRadius: 100,
                  fontSize: 'var(--text-sm)',
                  fontWeight: 500,
                  whiteSpace: 'nowrap',
                  border: category === cat.id
                    ? '1px solid var(--accent)'
                    : '1px solid var(--border-subtle)',
                  background: category === cat.id
                    ? 'var(--accent-muted)'
                    : 'transparent',
                  color: category === cat.id
                    ? 'var(--accent-text)'
                    : 'var(--text-secondary)',
                  cursor: 'pointer',
                  transition: 'all 0.2s ease',
                }}
              >
                {cat.label}
              </button>
            ))}
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
            {/* Stats overview */}
            {stats && (
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                gap: 12,
                marginBottom: 24,
              }}>
                <StatCard
                  label="Active Markets"
                  value={String(stats.totalMarkets)}
                  subtitle="Across Polymarket & Kalshi"
                />
                <StatCard
                  label="24h Volume"
                  value={formatCurrency(stats.totalVolume24h)}
                  subtitle="Combined trading volume"
                />
                <StatCard
                  label="Total Liquidity"
                  value={formatCurrency(stats.totalLiquidity)}
                  subtitle="Available depth"
                />
                <StatCard
                  label="Trending"
                  value={String(stats.trendingCount)}
                  subtitle="High-activity markets"
                />
              </div>
            )}

            {/* Sort controls */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 16,
            }}>
              <h2 style={{
                fontSize: 'var(--text-lg)',
                fontWeight: 600,
                color: 'var(--text-primary)',
              }}>
                {category === 'all' ? 'All Markets' : categories.find(c => c.id === category)?.label}
                <span style={{
                  fontSize: 'var(--text-sm)',
                  color: 'var(--text-muted)',
                  fontWeight: 400,
                  marginLeft: 8,
                }}>
                  ({markets.length})
                </span>
              </h2>
              <div style={{ display: 'flex', gap: 6 }}>
                {sortOptions.map((opt) => (
                  <button
                    key={opt.id}
                    onClick={() => setSort(opt.id)}
                    style={{
                      padding: '5px 12px',
                      borderRadius: 100,
                      fontSize: '10px',
                      fontWeight: 600,
                      whiteSpace: 'nowrap',
                      border: sort === opt.id
                        ? '1px solid var(--accent)'
                        : '1px solid var(--border-subtle)',
                      background: sort === opt.id
                        ? 'var(--accent-muted)'
                        : 'transparent',
                      color: sort === opt.id
                        ? 'var(--accent-text)'
                        : 'var(--text-muted)',
                      cursor: 'pointer',
                      transition: 'all 0.2s ease',
                      textTransform: 'uppercase',
                      letterSpacing: '0.04em',
                    }}
                  >
                    {opt.label}
                  </button>
                ))}
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
              border: '1px solid rgba(99, 91, 255, 0.12)',
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
                Market data aggregated from Polymarket CLOB and Kalshi APIs. Probabilities reflect current YES token prices. Refreshes every 30 seconds.
              </p>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
