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
    fetchSignals();
    const interval = setInterval(fetchSignals, 30000);
    return () => clearInterval(interval);
  }, [filter]);

  const fetchSignals = async () => {
    try {
      const filterParam = filter !== 'all' ? `?category=${filter}` : '';
      const response = await fetch(`/api/signals${filterParam}`);
      const data = await response.json();
      setSignals(data.signals || []);
      setLastUpdate(new Date());
      setLoading(false);
    } catch (error) {
      console.error('Error fetching signals:', error);
      setLoading(false);
    }
  };

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
        background: 'rgba(10, 14, 26, 0.95)',
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid var(--border-subtle)',
      }}>
        <div style={{ maxWidth: 640, margin: '0 auto', padding: '16px 16px 12px' }}>
          {/* Brand */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <h1 style={{
                  fontSize: 'var(--text-xl)',
                  fontWeight: 700,
                  color: 'var(--text-primary)',
                  letterSpacing: '-0.02em',
                  lineHeight: 1,
                }}>
                  Pythia
                </h1>
                <span style={{
                  fontSize: 'var(--text-xs)',
                  fontWeight: 600,
                  color: 'var(--accent-text)',
                  background: 'var(--accent-muted)',
                  padding: '2px 8px',
                  borderRadius: 4,
                  letterSpacing: '0.04em',
                  textTransform: 'uppercase',
                }}>
                  Beta
                </span>
              </div>
              <p style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--text-muted)',
                marginTop: 4,
              }}>
                Real-time intelligence • Monitoring 8 data sources
              </p>
              <Link href="/tracking" style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--accent-text)',
                background: 'var(--accent-muted)',
                padding: '4px 10px',
                borderRadius: 6,
                marginTop: 6,
                textDecoration: 'none',
                fontWeight: 600,
                display: 'inline-block',
              }}>
                📊 Signal Tracking →
              </Link>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: 'var(--positive)',
                  boxShadow: '0 0 6px var(--positive)',
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
                Last scan: {lastUpdate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
              </span>
            </div>
          </div>

          {/* Category filters */}
          <div className="scrollbar-hide" style={{
            display: 'flex',
            gap: 6,
            overflowX: 'auto',
            paddingBottom: 2,
          }}>
            {categories.map((cat) => (
              <button
                key={cat.id}
                onClick={() => setFilter(cat.id)}
                style={{
                  padding: '6px 14px',
                  borderRadius: 6,
                  fontSize: 'var(--text-sm)',
                  fontWeight: 500,
                  whiteSpace: 'nowrap',
                  border: filter === cat.id
                    ? '1px solid var(--accent-text)'
                    : '1px solid var(--border-subtle)',
                  background: filter === cat.id
                    ? 'var(--accent-muted)'
                    : 'transparent',
                  color: filter === cat.id
                    ? 'var(--accent-text)'
                    : 'var(--text-secondary)',
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                {cat.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      {/* Feed */}
      <div style={{ maxWidth: 640, margin: '0 auto', padding: '16px 16px 80px' }}>
        {loading ? (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            paddingTop: 80,
          }}>
            <div style={{
              width: 24,
              height: 24,
              border: '2px solid var(--accent)',
              borderTopColor: 'transparent',
              borderRadius: '50%',
              animation: 'spin 0.8s linear infinite',
            }} />
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
            <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', marginTop: 16 }}>
              Scanning data sources...
            </p>
            <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-xs)', marginTop: 8, fontFamily: 'var(--font-mono)' }}>
              Polymarket • News • Twitter • Congressional • On-chain
            </p>
          </div>
        ) : signals.length === 0 ? (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            paddingTop: 60,
            padding: '60px 20px 20px',
          }}>
            <div style={{
              width: 48,
              height: 48,
              borderRadius: '50%',
              background: 'var(--bg-secondary)',
              border: '1px solid var(--border-subtle)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginBottom: 16,
            }}>
              <div style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: 'var(--positive)',
                boxShadow: '0 0 8px var(--positive)',
              }} />
            </div>
            <p style={{ color: 'var(--text-secondary)', fontSize: 'var(--text-md)', fontWeight: 600 }}>
              System monitoring active
            </p>
            <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', marginTop: 6, textAlign: 'center', lineHeight: 1.5 }}>
              Tracking 8 data sources in real-time
            </p>
            <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-xs)', marginTop: 12, textAlign: 'center', lineHeight: 1.6, maxWidth: 320 }}>
              High-confidence signals appear when multiple independent layers converge on the same event
            </p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {signals.map((signal) => (
              <SignalCard key={signal.id} signal={signal} />
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
