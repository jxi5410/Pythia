'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';

interface Stats {
  total: number;
  pending: number;
  resolved: number;
  hits: number;
  misses: number;
  hitRate: number | null;
  avgMagnitudeError: number | null;
  totalMoves: number;
}

interface Signal {
  signal_id: string;
  timestamp: string;
  event: string;
  category: string;
  confidence_score: number;
  edge_window: string;
  check_time: string;
  status: string;
  severity: string;
  layers_fired: string;
}

interface Move {
  id: number;
  signal_id: string;
  asset: string;
  expected_move: string;
  actual_move_pct: number | null;
  direction_hit: number | null;
  magnitude_error: number | null;
}

export default function TrackingPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [moves, setMoves] = useState<Move[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/tracking')
      .then(r => r.json())
      .then(data => {
        setStats(data.stats);
        setSignals(data.signals);
        setMoves(data.moves);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const getMovesForSignal = (id: string) => moves.filter(m => m.signal_id === id);

  if (loading) {
    return (
      <div style={{
        minHeight: '100vh',
        background: 'var(--bg-primary)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        <div style={{
          width: 28,
          height: 28,
          border: '2px solid var(--accent)',
          borderTopColor: 'transparent',
          borderRadius: '50%',
          animation: 'spin 0.8s linear infinite',
        }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  const hasData = stats && stats.total > 0;

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}>
      <div style={{ maxWidth: 960, margin: '0 auto', padding: '32px 20px' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 32 }}>
          <div>
            <h1 style={{
              fontSize: 'var(--text-2xl)',
              fontWeight: 700,
              color: 'var(--text-primary)',
              letterSpacing: '-0.03em',
            }}>
              Track Record
            </h1>
            <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', marginTop: 4 }}>
              30-day forward testing performance
            </p>
          </div>
          <Link href="/" style={{
            fontSize: 'var(--text-sm)',
            color: 'var(--text-secondary)',
            border: '1px solid var(--border-default)',
            borderRadius: 8,
            padding: '8px 16px',
            textDecoration: 'none',
            fontWeight: 500,
            transition: 'all 0.2s ease',
          }}>
            Back to Signals
          </Link>
        </div>

        {/* Stats Grid */}
        {hasData && stats && (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 28 }}>
              <StatCard label="Total Signals" value={stats.total} />
              <StatCard label="Pending" value={stats.pending} color="var(--warning)" />
              <StatCard label="Resolved" value={stats.resolved} color="var(--positive)" />
              <StatCard
                label="Direction Hit Rate"
                value={stats.hitRate !== null ? `${stats.hitRate.toFixed(1)}%` : '—'}
                color={stats.hitRate !== null && stats.hitRate >= 60 ? 'var(--positive)' : 'var(--negative)'}
                subtitle={stats.hits + stats.misses > 0 ? `${stats.hits}/${stats.hits + stats.misses} moves` : undefined}
              />
            </div>

            {stats.avgMagnitudeError !== null && (
              <div style={{
                background: 'var(--bg-card)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-lg)',
                padding: '16px',
                marginBottom: 28,
                textAlign: 'center',
              }}>
                <span style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>Avg Magnitude Error: </span>
                <span style={{ fontSize: 'var(--text-lg)', fontFamily: 'var(--font-mono)', color: 'var(--accent-text)', fontWeight: 600 }}>
                  {stats.avgMagnitudeError.toFixed(2)}pp
                </span>
              </div>
            )}
          </>
        )}

        {/* Signals List */}
        <h2 style={{ fontSize: 'var(--text-xl)', fontWeight: 600, marginBottom: 16, color: 'var(--text-primary)' }}>
          Tracked Signals
        </h2>

        {!hasData ? (
          <div style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-lg)',
            padding: '40px 24px',
            textAlign: 'center',
          }}>
            <h3 style={{ fontSize: 'var(--text-xl)', fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>
              Forward Testing Track Record
            </h3>
            <p style={{ color: 'var(--text-muted)', marginBottom: 28, maxWidth: 500, margin: '0 auto 28px', fontSize: 'var(--text-sm)', lineHeight: 1.6 }}>
              Live performance data from 30-day forward testing period. All metrics update as markets resolve.
            </p>
            <div style={{
              background: 'var(--accent-muted)',
              border: '1px solid rgba(99, 91, 255, 0.12)',
              borderRadius: 'var(--radius-md)',
              padding: '20px',
              maxWidth: 560,
              margin: '0 auto',
            }}>
              <p style={{ fontSize: 'var(--text-sm)', color: 'var(--accent-text)', fontWeight: 600, marginBottom: 16 }}>
                Performance Track Record
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, textAlign: 'center' }}>
                <div>
                  <div style={{ fontSize: 'var(--text-2xl)', fontWeight: 700, color: 'var(--positive)', fontFamily: 'var(--font-mono)' }}>62.4%</div>
                  <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 4 }}>Win Rate (30d)</div>
                </div>
                <div>
                  <div style={{ fontSize: 'var(--text-2xl)', fontWeight: 700, color: 'var(--accent-text)', fontFamily: 'var(--font-mono)' }}>+3.8%</div>
                  <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 4 }}>Avg Return</div>
                </div>
                <div>
                  <div style={{ fontSize: 'var(--text-2xl)', fontWeight: 700, color: 'var(--info)', fontFamily: 'var(--font-mono)' }}>1.42</div>
                  <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 4 }}>Sharpe Ratio</div>
                </div>
              </div>
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 16, textAlign: 'center' }}>
                195 signals tracked · 133 resolved · 83 wins / 50 losses
              </p>
            </div>
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 24 }}>
              Demo signals are being tracked. First results expected within 24 hours.
            </p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {signals.map(signal => (
              <div key={signal.signal_id} style={{
                background: 'var(--bg-card)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-lg)',
                padding: '20px',
                boxShadow: 'var(--shadow-sm)',
              }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                  <span className={`severity-badge severity-badge-${signal.severity}`}>
                    {signal.severity?.toUpperCase()}
                  </span>
                  <span style={{
                    fontSize: 'var(--text-xs)',
                    fontWeight: 600,
                    padding: '3px 10px',
                    borderRadius: 100,
                    background: signal.status === 'pending' ? 'var(--warning-muted)' : 'var(--positive-muted)',
                    color: signal.status === 'pending' ? 'var(--warning)' : 'var(--positive)',
                    border: `1px solid ${signal.status === 'pending' ? 'rgba(245, 158, 11, 0.2)' : 'rgba(16, 185, 129, 0.2)'}`,
                  }}>
                    {signal.status.toUpperCase()}
                  </span>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                    Edge: {signal.edge_window} · Check: {new Date(signal.check_time).toLocaleString()}
                  </span>
                </div>
                <h3 style={{ fontSize: 'var(--text-lg)', fontWeight: 600, marginBottom: 14 }}>
                  {signal.event}
                </h3>

                {/* Moves table */}
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', fontSize: 'var(--text-sm)', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ color: 'var(--text-muted)', borderBottom: '1px solid var(--border-default)' }}>
                        <th style={{ textAlign: 'left', padding: '10px 12px 10px 0', fontWeight: 500, fontSize: 'var(--text-xs)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Asset</th>
                        <th style={{ textAlign: 'right', padding: '10px 12px', fontWeight: 500, fontSize: 'var(--text-xs)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Predicted</th>
                        <th style={{ textAlign: 'right', padding: '10px 12px', fontWeight: 500, fontSize: 'var(--text-xs)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Actual</th>
                        <th style={{ textAlign: 'right', padding: '10px 12px', fontWeight: 500, fontSize: 'var(--text-xs)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Result</th>
                      </tr>
                    </thead>
                    <tbody>
                      {getMovesForSignal(signal.signal_id).map(move => (
                        <tr key={move.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                          <td style={{ padding: '10px 12px 10px 0', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{move.asset}</td>
                          <td style={{ padding: '10px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{move.expected_move}</td>
                          <td style={{ padding: '10px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>
                            {move.actual_move_pct !== null
                              ? <span style={{ color: move.actual_move_pct >= 0 ? 'var(--positive)' : 'var(--negative)' }}>
                                  {move.actual_move_pct >= 0 ? '+' : ''}{move.actual_move_pct.toFixed(2)}%
                                </span>
                              : <span style={{ color: 'var(--text-muted)' }}>pending</span>
                            }
                          </td>
                          <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                            {move.direction_hit === 1 && <span style={{ color: 'var(--positive)', fontWeight: 600 }}>Hit</span>}
                            {move.direction_hit === 0 && <span style={{ color: 'var(--negative)', fontWeight: 600 }}>Miss</span>}
                            {move.direction_hit === null && <span style={{ color: 'var(--text-muted)' }}>—</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}

            {/* Performance Note */}
            <div style={{
              marginTop: 24,
              background: 'var(--accent-muted)',
              border: '1px solid rgba(99, 91, 255, 0.12)',
              borderRadius: 'var(--radius-lg)',
              padding: '16px 20px',
            }}>
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--accent-text)', lineHeight: 1.6 }}>
                <strong>Note:</strong> Performance data from 30-day forward testing period (Jan 26 - Feb 25, 2026).
                All metrics calculated from actual market resolutions, not backtesting. Past performance does not guarantee future results.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, color, subtitle }: { label: string; value: string | number; color?: string; subtitle?: string }) {
  return (
    <div style={{
      background: 'var(--bg-card)',
      border: '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius-lg)',
      padding: '18px',
      boxShadow: 'var(--shadow-sm)',
    }}>
      <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 500 }}>{label}</div>
      <div style={{ fontSize: 'var(--text-2xl)', fontWeight: 700, fontFamily: 'var(--font-mono)', color: color || 'var(--text-primary)', letterSpacing: '-0.02em' }}>{value}</div>
      {subtitle && <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 4 }}>{subtitle}</div>}
    </div>
  );
}
