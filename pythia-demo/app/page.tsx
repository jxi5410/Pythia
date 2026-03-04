'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import SignalCard from '@/components/SignalCard';
import { Signal } from '@/types';

export default function Home() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [filter, setFilter] = useState<string>('all');
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const filterParam = filter !== 'all' ? `?category=${filter}` : '';
        const response = await fetch(`/api/signals${filterParam}`);
        const data = await response.json();
        if (!cancelled) {
          setSignals(data.signals || []);
          setLastUpdate(new Date());
          setLoading(false);
        }
      } catch (error) {
        console.error('Error fetching signals:', error);
        if (!cancelled) setLoading(false);
      }
    };
    load();
    const interval = setInterval(load, 30000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [filter]);

  const categories = [
    { id: 'all', label: 'All Signals' },
    { id: 'fed', label: 'Fed & Rates' },
    { id: 'tariffs', label: 'Trade & Tariffs' },
    { id: 'crypto', label: 'Crypto' },
    { id: 'geopolitical', label: 'Geopolitical' },
    { id: 'defense', label: 'Defense' },
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
        <div style={{ maxWidth: 680, margin: '0 auto', padding: '18px 20px 14px' }}>
          {/* Brand row */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
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
                  fontSize: '10px',
                  fontWeight: 600,
                  color: 'var(--accent-text)',
                  background: 'var(--accent-muted)',
                  padding: '3px 10px',
                  borderRadius: 100,
                  letterSpacing: '0.06em',
                  textTransform: 'uppercase',
                }}>
                  Beta
                </span>
              </div>
              <p style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--text-muted)',
                marginTop: 6,
                letterSpacing: '0.01em',
              }}>
                Real-time prediction market intelligence
              </p>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
              <Link href="/markets" style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--accent-text)',
                background: 'var(--accent-muted)',
                padding: '6px 14px',
                borderRadius: 100,
                textDecoration: 'none',
                fontWeight: 600,
                letterSpacing: '0.01em',
                transition: 'all 0.2s ease',
                border: '1px solid rgba(99, 91, 255, 0.15)',
              }}>
                Markets
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
                onClick={() => setFilter(cat.id)}
                style={{
                  padding: '7px 16px',
                  borderRadius: 100,
                  fontSize: 'var(--text-sm)',
                  fontWeight: 500,
                  whiteSpace: 'nowrap',
                  border: filter === cat.id
                    ? '1px solid var(--accent)'
                    : '1px solid var(--border-subtle)',
                  background: filter === cat.id
                    ? 'var(--accent-muted)'
                    : 'transparent',
                  color: filter === cat.id
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

      {/* Feed */}
      <div style={{ maxWidth: 680, margin: '0 auto', padding: '20px 20px 80px' }}>
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
              Scanning data sources...
            </p>
            <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-xs)', marginTop: 8, fontFamily: 'var(--font-mono)', opacity: 0.6 }}>
              Polymarket · News · Twitter · Congressional · On-chain
            </p>
          </div>
        ) : signals.length === 0 ? (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            paddingTop: 80,
            padding: '80px 24px 24px',
          }}>
            <div style={{
              width: 56,
              height: 56,
              borderRadius: '50%',
              background: 'var(--bg-card)',
              border: '1px solid var(--border-subtle)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginBottom: 20,
              boxShadow: 'var(--shadow-md)',
            }}>
              <div style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: 'var(--positive)',
                boxShadow: '0 0 12px var(--positive)',
                animation: 'pulse-soft 2s ease-in-out infinite',
              }} />
            </div>
            <p style={{ color: 'var(--text-primary)', fontSize: 'var(--text-lg)', fontWeight: 600 }}>
              System monitoring active
            </p>
            <p style={{ color: 'var(--text-secondary)', fontSize: 'var(--text-sm)', marginTop: 8, textAlign: 'center', lineHeight: 1.6 }}>
              Tracking 8 data sources in real-time
            </p>
            <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-xs)', marginTop: 16, textAlign: 'center', lineHeight: 1.7, maxWidth: 340 }}>
              High-confidence signals appear when multiple independent layers converge on the same event
            </p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {signals.map((signal) => (
              <SignalCard key={signal.id} signal={signal} />
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
