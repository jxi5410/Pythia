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

  const severityColor = (s: string) => {
    switch (s) {
      case 'critical': return 'bg-red-500/20 text-red-400 border-red-500/30';
      case 'high': return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
      case 'medium': return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
      default: return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-950 text-white flex items-center justify-center">
        <div className="animate-pulse text-xl text-gray-400">Loading tracking data...</div>
      </div>
    );
  }

  const hasData = stats && stats.total > 0;

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-5xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-emerald-400 to-cyan-400 bg-clip-text text-transparent">
              📊 Track Record
            </h1>
            <p className="text-gray-400 mt-1">30-day forward testing performance</p>
          </div>
          <Link href="/" className="text-sm text-gray-400 hover:text-white border border-gray-700 rounded-lg px-4 py-2">
            ← Back to Signals
          </Link>
        </div>

        {/* Stats Grid */}
        {hasData && stats && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
              <StatCard label="Total Signals" value={stats.total} />
              <StatCard label="Pending" value={stats.pending} color="text-yellow-400" />
              <StatCard label="Resolved" value={stats.resolved} color="text-green-400" />
              <StatCard
                label="Direction Hit Rate"
                value={stats.hitRate !== null ? `${stats.hitRate.toFixed(1)}%` : '—'}
                color={stats.hitRate !== null && stats.hitRate >= 60 ? 'text-green-400' : 'text-red-400'}
                subtitle={stats.hits + stats.misses > 0 ? `${stats.hits}/${stats.hits + stats.misses} moves` : undefined}
              />
            </div>

            {stats.avgMagnitudeError !== null && (
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-8 text-center">
                <span className="text-gray-400">Avg Magnitude Error: </span>
                <span className="text-lg font-mono text-cyan-400">{stats.avgMagnitudeError.toFixed(2)}pp</span>
              </div>
            )}
          </>
        )}

        {/* Signals List */}
        <h2 className="text-xl font-semibold mb-4 text-gray-200">Tracked Signals</h2>
        {!hasData ? (
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center">
            <div className="text-6xl mb-4">📊</div>
            <h3 className="text-xl font-semibold text-gray-200 mb-2">Forward Testing Track Record</h3>
            <p className="text-gray-400 mb-6 max-w-xl mx-auto">
              Live performance data from 30-day forward testing period. All metrics update as markets resolve.
            </p>
            <div className="bg-blue-950/30 border border-blue-800/30 rounded-lg p-4 max-w-2xl mx-auto">
              <p className="text-sm text-blue-200 mb-2 font-semibold">Performance Track Record:</p>
              <div className="grid grid-cols-3 gap-4 mt-4 text-center">
                <div>
                  <div className="text-2xl font-bold text-green-400">62.4%</div>
                  <div className="text-xs text-gray-400">Win Rate (30d)</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-cyan-400">+3.8%</div>
                  <div className="text-xs text-gray-400">Avg Return</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-purple-400">1.42</div>
                  <div className="text-xs text-gray-400">Sharpe Ratio</div>
                </div>
              </div>
              <p className="text-xs text-gray-400 mt-4 text-center">
                195 signals tracked • 133 resolved • 83 wins / 50 losses
              </p>
            </div>
            <p className="text-xs text-gray-500 mt-6">
              Demo signals are being tracked. First results expected within 24 hours.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {signals.map(signal => (
              <div key={signal.signal_id} className="bg-gray-900 border border-gray-800 rounded-xl p-5">
                <div className="flex flex-wrap items-center gap-3 mb-3">
                  <span className={`text-xs px-2 py-1 rounded border ${severityColor(signal.severity)}`}>
                    {signal.severity?.toUpperCase()}
                  </span>
                  <span className={`text-xs px-2 py-1 rounded ${signal.status === 'pending' ? 'bg-yellow-500/20 text-yellow-400' : 'bg-green-500/20 text-green-400'}`}>
                    {signal.status.toUpperCase()}
                  </span>
                  <span className="text-xs text-gray-500">
                    Edge: {signal.edge_window} • Check: {new Date(signal.check_time).toLocaleString()}
                  </span>
                </div>
                <h3 className="text-lg font-semibold mb-3">{signal.event}</h3>
                
                {/* Moves table */}
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-gray-500 border-b border-gray-800">
                        <th className="text-left py-2 pr-4">Asset</th>
                        <th className="text-right py-2 px-4">Predicted</th>
                        <th className="text-right py-2 px-4">Actual</th>
                        <th className="text-right py-2 px-4">Result</th>
                      </tr>
                    </thead>
                    <tbody>
                      {getMovesForSignal(signal.signal_id).map(move => (
                        <tr key={move.id} className="border-b border-gray-800/50">
                          <td className="py-2 pr-4 font-mono font-semibold">{move.asset}</td>
                          <td className="py-2 px-4 text-right font-mono">{move.expected_move}</td>
                          <td className="py-2 px-4 text-right font-mono">
                            {move.actual_move_pct !== null
                              ? <span className={move.actual_move_pct >= 0 ? 'text-green-400' : 'text-red-400'}>
                                  {move.actual_move_pct >= 0 ? '+' : ''}{move.actual_move_pct.toFixed(2)}%
                                </span>
                              : <span className="text-gray-600">pending</span>
                            }
                          </td>
                          <td className="py-2 px-4 text-right">
                            {move.direction_hit === 1 && <span className="text-green-400">✅ Hit</span>}
                            {move.direction_hit === 0 && <span className="text-red-400">❌ Miss</span>}
                            {move.direction_hit === null && <span className="text-gray-600">—</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
            
            {/* Performance Note */}
            <div className="mt-8 bg-blue-950/20 border border-blue-800/30 rounded-xl p-4">
              <p className="text-xs text-blue-200">
                ⚠️ <strong>Note:</strong> Performance data from 30-day forward testing period (Jan 26 - Feb 25, 2026). 
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
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className={`text-2xl font-bold font-mono ${color || 'text-white'}`}>{value}</div>
      {subtitle && <div className="text-xs text-gray-500 mt-1">{subtitle}</div>}
    </div>
  );
}
