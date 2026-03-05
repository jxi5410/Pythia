'use client';

import Link from 'next/link';
import { Signal } from '@/types';

interface SignalCardProps {
  signal: Signal;
}

const severityConfig = {
  critical: { color: 'var(--severity-critical)', label: 'CRITICAL' },
  high: { color: 'var(--severity-high)', label: 'HIGH' },
  medium: { color: 'var(--severity-medium)', label: 'MEDIUM' },
  low: { color: 'var(--severity-low)', label: 'LOW' },
};

export default function SignalCard({ signal }: SignalCardProps) {
  const sev = severityConfig[signal.severity];

  const timeAgo = (timestamp: string) => {
    const now = new Date();
    const past = new Date(timestamp);
    const diffMinutes = Math.floor((now.getTime() - past.getTime()) / 60000);
    if (diffMinutes < 1) return 'Just now';
    if (diffMinutes < 60) return `${diffMinutes}m ago`;
    const diffHours = Math.floor(diffMinutes / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${Math.floor(diffHours / 24)}d ago`;
  };

  const sourceLabel = signal.source === 'polymarket' ? 'Polymarket' : 'Kalshi';

  return (
    <div
      className={`signal-card severity-accent-${signal.severity}`}
      style={{ padding: '18px 20px' }}
    >
      <div style={{ display: 'flex', gap: 16 }}>
        {/* Main content — left side */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Header row */}
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <h3 style={{
                fontSize: 'var(--text-lg)',
                fontWeight: 600,
                color: 'var(--text-primary)',
                lineHeight: 1.4,
                marginBottom: 6,
              }}>
                {signal.event}
              </h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  fontSize: 'var(--text-xs)',
                  color: 'var(--text-muted)',
                  fontFamily: 'var(--font-mono)',
                }}>
                  {timeAgo(signal.timestamp)}
                </span>
                <span style={{ color: 'var(--border-default)', fontSize: 10 }}>|</span>
                <span className="layer-tag" style={{ fontSize: '10px', padding: '1px 8px' }}>
                  {signal.category}
                </span>
              </div>
            </div>
            <span className={`severity-badge severity-badge-${signal.severity}`} style={{
              flexShrink: 0,
              marginLeft: 12,
            }}>
              {sev.label}
            </span>
          </div>

          {/* Asset impact row */}
          {signal.assetImpact && signal.assetImpact.length > 0 && (
            <div style={{
              display: 'flex',
              gap: 16,
              marginBottom: 14,
              flexWrap: 'wrap',
            }}>
              {signal.assetImpact.slice(0, 3).map((asset, idx) => (
                <div key={idx} style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                }}>
                  <span style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 'var(--text-sm)',
                    color: 'var(--text-secondary)',
                    fontWeight: 500,
                  }}>
                    {asset.asset}
                  </span>
                  <span style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 'var(--text-sm)',
                    fontWeight: 600,
                    color: asset.expectedMove.startsWith('+') ? 'var(--positive)' : 'var(--negative)',
                  }}>
                    {asset.expectedMove}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Layer tags */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
            {signal.layersFired.map((layer, idx) => (
              <span key={idx} className="layer-tag">{layer}</span>
            ))}
          </div>

          {/* Bottom row: source link + detail link */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <a
              href={signal.sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className={`source-badge source-badge-${signal.source}`}
            >
              View on {sourceLabel}
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
                <polyline points="15 3 21 3 21 9" />
                <line x1="10" y1="14" x2="21" y2="3" />
              </svg>
            </a>
            <Link href={`/signal/${signal.id}`} style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              padding: '3px 10px',
              borderRadius: 100,
              fontSize: '10px',
              fontWeight: 600,
              color: 'var(--accent-text)',
              background: 'var(--accent-muted)',
              border: '1px solid rgba(26, 86, 219, 0.15)',
              textDecoration: 'none',
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              transition: 'all 0.15s ease',
            }}>
              Full Analysis
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
              </svg>
            </Link>
          </div>
        </div>

        {/* Signal Analysis mini card — right side */}
        <div className="signal-analysis-card">
          <div style={{
            fontSize: '10px',
            fontWeight: 600,
            color: 'var(--text-muted)',
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            marginBottom: 10,
          }}>
            Signal Analysis
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div>
              <div style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--text-muted)',
                marginBottom: 2,
              }}>
                Layers
              </div>
              <div style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 'var(--text-lg)',
                fontWeight: 700,
                color: 'var(--text-primary)',
                lineHeight: 1,
              }}>
                {signal.confluenceLayers}<span style={{ color: 'var(--text-muted)', fontWeight: 400, fontSize: 'var(--text-sm)' }}>/{signal.totalLayers}</span>
              </div>
            </div>

            <div>
              <div style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--text-muted)',
                marginBottom: 2,
              }}>
                Hit Rate
              </div>
              <div style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 'var(--text-lg)',
                fontWeight: 700,
                color: signal.historicalHitRate >= 0.7 ? 'var(--positive)' : 'var(--text-primary)',
                lineHeight: 1,
              }}>
                {Math.round(signal.historicalHitRate * 100)}%
              </div>
            </div>

            <div>
              <div style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--text-muted)',
                marginBottom: 2,
              }}>
                Edge
              </div>
              <div style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 'var(--text-md)',
                fontWeight: 600,
                color: 'var(--text-primary)',
                lineHeight: 1,
              }}>
                {signal.edgeWindow}
              </div>
            </div>

            <div>
              <div style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--text-muted)',
                marginBottom: 2,
              }}>
                Confidence
              </div>
              {/* Confidence bar */}
              <div style={{
                width: '100%',
                height: 4,
                background: 'var(--border-subtle)',
                borderRadius: 100,
                overflow: 'hidden',
              }}>
                <div style={{
                  width: `${signal.confidenceScore * 100}%`,
                  height: '100%',
                  background: signal.confidenceScore >= 0.8 ? 'var(--positive)' : signal.confidenceScore >= 0.6 ? 'var(--warning)' : 'var(--text-muted)',
                  borderRadius: 100,
                  transition: 'width 0.4s ease',
                }} />
              </div>
              <div style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 'var(--text-xs)',
                fontWeight: 600,
                color: 'var(--text-secondary)',
                marginTop: 3,
              }}>
                {Math.round(signal.confidenceScore * 100)}%
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
