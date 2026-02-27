'use client';

import Link from 'next/link';
import { Signal } from '@/types';

interface SignalCardProps {
  signal: Signal;
}

const jargonHelp: Record<string, string> = {
  'Confluence': 'How many independent data sources agree on this signal',
  'Hit Rate': 'How often similar past signals led to the predicted move',
  'Edge Window': 'Estimated time before the market prices this in',
  'Layers': 'Independent data sources (polymarket, news, on-chain, etc.)',
};

const severityExplanations: Record<string, string> = {
  'critical': '4+ layers converged · Highest confidence · Immediate attention',
  'high': '3 layers converged · Strong signal · Act within hours',
  'medium': '2 layers converged · Moderate confidence · Monitor closely',
  'low': '1 layer · Early indicator · Watch for confirmation',
};

const assetHelp: Record<string, string> = {
  'TLT': '20+ Year Treasury Bond ETF',
  'SPY': 'S&P 500 ETF',
  'DXY': 'US Dollar Index',
  'BTC': 'Bitcoin',
  'ETH': 'Ethereum',
  'XLI': 'Industrial Sector ETF',
  'FXI': 'China Large-Cap ETF',
  'USDCNY': 'USD/CNY Exchange Rate',
  'XLF': 'Financial Sector ETF',
  'COIN': 'Coinbase Stock',
};

function Tooltip({ label, help }: { label: string; help?: string }) {
  if (!help) return <span className="data-label">{label}</span>;
  return (
    <span className="tooltip-wrap data-label" style={{ cursor: 'help', borderBottom: '1px dotted var(--text-muted)' }}>
      {label}
      <span className="tooltip-text">{help}</span>
    </span>
  );
}

export default function SignalCard({ signal }: SignalCardProps) {
  const severityConfig = {
    critical: { color: 'var(--severity-critical)', label: 'CRITICAL' },
    high: { color: 'var(--severity-high)', label: 'HIGH' },
    medium: { color: 'var(--severity-medium)', label: 'MEDIUM' },
    low: { color: 'var(--severity-low)', label: 'LOW' },
  };

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

  return (
    <div
      className={`signal-card severity-accent-${signal.severity}`}
      style={{ padding: '16px 18px' }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 14 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h3 style={{
            fontSize: 'var(--text-md)',
            fontWeight: 600,
            color: 'var(--text-primary)',
            lineHeight: 1.4,
            marginBottom: 5,
          }}>
            {signal.event}
          </h3>
          <span style={{
            fontSize: 'var(--text-xs)',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
          }}>
            {timeAgo(signal.timestamp)} · {signal.category}
          </span>
        </div>
        <span className={`severity-badge severity-badge-${signal.severity}`} style={{
          flexShrink: 0,
          marginLeft: 14,
          cursor: 'help',
        }}>
          <span className="tooltip-wrap">
            {sev.label}
            <span className="tooltip-text">{severityExplanations[signal.severity]}</span>
          </span>
        </span>
      </div>

      {/* Metrics row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 14 }}>
        <div className="metric-cell">
          <Tooltip label="Layers" help={jargonHelp['Confluence']} />
          <div className="data-value" style={{ fontSize: 'var(--text-lg)', marginTop: 3 }}>
            {signal.confluenceLayers}<span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>/{signal.totalLayers}</span>
          </div>
        </div>
        <div className="metric-cell">
          <Tooltip label="Hit Rate" help={jargonHelp['Hit Rate']} />
          <div className="data-value" style={{ fontSize: 'var(--text-lg)', marginTop: 3 }}>
            {Math.round(signal.historicalHitRate * 100)}%
          </div>
        </div>
        <div className="metric-cell">
          <Tooltip label="Edge" help={jargonHelp['Edge Window']} />
          <div className="data-value" style={{ fontSize: 'var(--text-base)', marginTop: 5 }}>
            {signal.edgeWindow}
          </div>
        </div>
      </div>

      {/* Asset impact */}
      {signal.assetImpact && signal.assetImpact.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          {signal.assetImpact.slice(0, 2).map((asset, idx) => (
            <div key={idx} style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '5px 0',
            }}>
              {assetHelp[asset.asset] ? (
                <span className="tooltip-wrap" style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 'var(--text-sm)',
                  color: 'var(--text-secondary)',
                  fontWeight: 500,
                  cursor: 'help',
                  borderBottom: '1px dotted var(--text-muted)',
                }}>
                  {asset.asset}
                  <span className="tooltip-text">{assetHelp[asset.asset]}</span>
                </span>
              ) : (
                <span style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 'var(--text-sm)',
                  color: 'var(--text-secondary)',
                  fontWeight: 500,
                }}>
                  {asset.asset}
                </span>
              )}
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

      {/* CTA */}
      <Link href={`/signal/${signal.id}`} style={{ textDecoration: 'none', display: 'block' }}>
        <div style={{
          padding: '11px 18px',
          background: 'var(--accent-muted)',
          border: '1px solid rgba(99, 91, 255, 0.15)',
          borderRadius: 8,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 8,
          cursor: 'pointer',
          transition: 'all 0.2s ease',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = 'rgba(99, 91, 255, 0.18)';
          e.currentTarget.style.borderColor = 'var(--accent)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = 'var(--accent-muted)';
          e.currentTarget.style.borderColor = 'rgba(99, 91, 255, 0.15)';
        }}>
          <span style={{
            fontSize: 'var(--text-sm)',
            color: 'var(--accent-text)',
            fontWeight: 600,
          }}>
            View Full Analysis
          </span>
          <svg style={{ width: 14, height: 14, color: 'var(--accent-text)' }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </div>
      </Link>
    </div>
  );
}
