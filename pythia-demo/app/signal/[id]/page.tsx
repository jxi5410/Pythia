'use client';

import { use, useState, useEffect } from 'react';
import Link from 'next/link';
import { SignalDetail } from '@/types';

function Tooltip({ label, help }: { label: string; help?: string }) {
  if (!help) return <span className="data-label">{label}</span>;
  return (
    <span className="tooltip-wrap data-label" style={{ cursor: 'help', borderBottom: '1px dotted var(--text-muted)' }}>
      {label}
      <span className="tooltip-text">{help}</span>
    </span>
  );
}

const explanations: Record<string, string> = {
  'Confluence': 'Number of independent data layers that fired simultaneously for this event',
  'Hit Rate': 'Percentage of similar historical setups that moved in the predicted direction',
  'Edge Window': 'Median time before the market fully prices in this type of event',
  'Confidence': 'Model-generated score combining layer quality, recency, and historical accuracy',
  'Correlation': 'How closely this asset tracks the prediction market signal (1.0 = perfect)',
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

const severityExplanations: Record<string, string> = {
  'critical': '4+ layers converged • Highest confidence • Immediate attention',
  'high': '3 layers converged • Strong signal • Act within hours',
  'medium': '2 layers converged • Moderate confidence • Monitor closely',
  'low': '1 layer • Early indicator • Watch for confirmation',
};

export default function SignalDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [signal, setSignal] = useState<SignalDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSignalDetail();
  }, [id]);

  const fetchSignalDetail = async () => {
    try {
      const response = await fetch(`/api/signals/${id}`);
      const data = await response.json();
      setSignal(data);
      setLoading(false);
    } catch (error) {
      console.error('Error fetching signal:', error);
      setLoading(false);
    }
  };

  const handleShare = async () => {
    if (navigator.share && signal) {
      try {
        await navigator.share({
          title: signal.event,
          text: `Pythia Signal: ${signal.event} — ${signal.confluenceLayers}/${signal.totalLayers} layers converged`,
          url: window.location.href
        });
      } catch (err) {
        console.log('Share failed:', err);
      }
    }
  };

  if (loading) {
    return (
      <div style={{ minHeight: '100vh', background: 'var(--bg-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{
          width: 24, height: 24,
          border: '2px solid var(--accent)',
          borderTopColor: 'transparent',
          borderRadius: '50%',
          animation: 'spin 0.8s linear infinite',
        }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  if (!signal) {
    return (
      <div style={{ minHeight: '100vh', background: 'var(--bg-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ textAlign: 'center' }}>
          <p style={{ color: 'var(--text-secondary)', fontSize: 'var(--text-md)' }}>Signal not found</p>
          <Link href="/" style={{ color: 'var(--accent-text)', fontSize: 'var(--text-sm)', marginTop: 8, display: 'inline-block' }}>
            ← Back to feed
          </Link>
        </div>
      </div>
    );
  }

  const sevColors: Record<string, string> = {
    critical: 'var(--severity-critical)',
    high: 'var(--severity-high)',
    medium: 'var(--severity-medium)',
    low: 'var(--severity-low)',
  };

  const sevColor = sevColors[signal.severity];

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-primary)' }}>
      {/* Header */}
      <header style={{
        position: 'sticky',
        top: 0,
        zIndex: 50,
        background: 'rgba(10, 14, 26, 0.95)',
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid var(--border-subtle)',
      }}>
        <div style={{
          maxWidth: 640,
          margin: '0 auto',
          padding: '12px 16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <Link href="/" style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            color: 'var(--text-secondary)',
            textDecoration: 'none',
            fontSize: 'var(--text-sm)',
            fontWeight: 500,
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M15 19l-7-7 7-7" />
            </svg>
            Back
          </Link>
          <button
            onClick={handleShare}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 14px',
              background: 'var(--accent-muted)',
              border: '1px solid var(--accent-text)',
              borderRadius: 6,
              color: 'var(--accent-text)',
              fontSize: 'var(--text-sm)',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
            </svg>
            Share
          </button>
        </div>
      </header>

      <div style={{ maxWidth: 640, margin: '0 auto', padding: '20px 16px 80px' }}>
        {/* Title section */}
        <div style={{ marginBottom: 24 }}>
          <span className="tooltip-wrap" style={{
            display: 'inline-block',
            fontSize: 'var(--text-xs)',
            fontWeight: 700,
            color: sevColor,
            padding: '3px 10px',
            border: `1px solid ${sevColor}`,
            borderRadius: 4,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
            marginBottom: 12,
            cursor: 'help',
          }}>
            {signal.severity} SIGNAL
            <span className="tooltip-text">{severityExplanations[signal.severity]}</span>
          </span>
          <h1 style={{
            fontSize: 'var(--text-2xl)',
            fontWeight: 700,
            color: 'var(--text-primary)',
            lineHeight: 1.3,
            letterSpacing: '-0.02em',
            marginBottom: 8,
          }}>
            {signal.event}
          </h1>
          <p style={{
            fontSize: 'var(--text-sm)',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
          }}>
            {new Date(signal.timestamp).toLocaleString()} · {signal.category}
          </p>
        </div>

        {/* Key Metrics */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 20 }}>
          <div className="section-card">
            <Tooltip label="Confluence" help={explanations['Confluence']} />
            <div className="data-value" style={{ fontSize: 'var(--text-2xl)', marginTop: 6 }}>
              {signal.confluenceLayers}<span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>/{signal.totalLayers}</span>
            </div>
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 4 }}>
              layers fired
            </p>
          </div>
          <div className="section-card">
            <Tooltip label="Hit Rate" help={explanations['Hit Rate']} />
            <div className="data-value" style={{ fontSize: 'var(--text-2xl)', marginTop: 6 }}>
              {Math.round(signal.historicalHitRate * 100)}%
            </div>
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 4 }}>
              n={signal.historicalPrecedent?.length || 47} events
            </p>
          </div>
          <div className="section-card">
            <Tooltip label="Edge Window" help={explanations['Edge Window']} />
            <div className="data-value" style={{ fontSize: 'var(--text-xl)', marginTop: 6 }}>
              {signal.edgeWindow}
            </div>
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 4 }}>
              median lead time
            </p>
          </div>
          <div className="section-card">
            <Tooltip label="Confidence" help={explanations['Confidence']} />
            <div className="data-value" style={{ fontSize: 'var(--text-2xl)', marginTop: 6 }}>
              {Math.round(signal.confidenceScore * 100)}%
            </div>
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 4 }}>
              model score
            </p>
          </div>
        </div>

        {/* Layers Fired */}
        <div className="section-card" style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <h2 style={{ fontSize: 'var(--text-md)', fontWeight: 600, color: 'var(--text-primary)' }}>
              Active Layers
            </h2>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
              Independent data sources that triggered
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(signal.layersWithLinks || signal.layersFired.map((text, i) => ({ text, url: '' }))).map((layer, idx) => (
              <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: 'var(--positive)',
                  flexShrink: 0,
                }} />
                {layer.url ? (
                  <a
                    href={layer.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      fontSize: 'var(--text-base)',
                      color: 'var(--text-secondary)',
                      textDecoration: 'none',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.color = 'var(--accent)'}
                    onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-secondary)'}
                  >
                    <span>{layer.text}</span>
                    <svg style={{ width: 12, height: 12, opacity: 0.5 }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                    </svg>
                  </a>
                ) : (
                  <span style={{ fontSize: 'var(--text-base)', color: 'var(--text-secondary)' }}>{layer.text}</span>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Asset Impact */}
        <div className="section-card" style={{ marginBottom: 12 }}>
          <div style={{ marginBottom: 14 }}>
            <h2 style={{ fontSize: 'var(--text-md)', fontWeight: 600, color: 'var(--text-primary)' }}>
              Expected Asset Moves
            </h2>
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 2 }}>
              Based on historical patterns when similar signals fired
            </p>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {signal.assetImpact.map((asset, idx) => (
              <div key={idx} style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '10px 0',
                borderBottom: idx < signal.assetImpact.length - 1 ? '1px solid var(--border-subtle)' : 'none',
              }}>
                <div>
                  {assetHelp[asset.asset] ? (
                    <div className="tooltip-wrap" style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 'var(--text-md)',
                      fontWeight: 600,
                      color: 'var(--text-primary)',
                      cursor: 'help',
                      borderBottom: '1px dotted var(--text-muted)',
                      display: 'inline-block',
                    }}>
                      {asset.asset}
                      <span className="tooltip-text">{assetHelp[asset.asset]}</span>
                    </div>
                  ) : (
                    <div style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 'var(--text-md)',
                      fontWeight: 600,
                      color: 'var(--text-primary)',
                    }}>
                      {asset.asset}
                    </div>
                  )}
                  <div className="tooltip-wrap" style={{ marginTop: 2 }}>
                    <span style={{
                      fontSize: 'var(--text-xs)',
                      color: 'var(--text-muted)',
                      cursor: 'help',
                      borderBottom: '1px dotted var(--text-muted)',
                    }}>
                      corr: {asset.correlation.toFixed(2)}
                    </span>
                    <span className="tooltip-text">{explanations['Correlation']}</span>
                  </div>
                </div>
                <span style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 'var(--text-lg)',
                  fontWeight: 700,
                  color: asset.expectedMove.startsWith('+') ? 'var(--positive)' : 'var(--negative)',
                }}>
                  {asset.expectedMove}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Historical Precedent */}
        {signal.historicalPrecedent && signal.historicalPrecedent.length > 0 && (
          <div className="section-card" style={{ marginBottom: 12 }}>
            <div style={{ marginBottom: 14 }}>
              <h2 style={{ fontSize: 'var(--text-md)', fontWeight: 600, color: 'var(--text-primary)' }}>
                Historical Precedent
              </h2>
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 2 }}>
                Past events with similar confluence patterns
              </p>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {signal.historicalPrecedent.slice(0, 3).map((event, idx) => (
                <div key={idx} style={{
                  padding: '10px 12px',
                  background: 'rgba(255,255,255,0.02)',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border-subtle)',
                }}>
                  <div style={{
                    fontSize: 'var(--text-xs)',
                    color: 'var(--text-muted)',
                    fontFamily: 'var(--font-mono)',
                    marginBottom: 4,
                  }}>{event.date}</div>
                  <div style={{
                    fontSize: 'var(--text-base)',
                    color: 'var(--text-secondary)',
                    lineHeight: 1.45,
                    marginBottom: 4,
                  }}>{event.outcome}</div>
                  <div style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 'var(--text-sm)',
                    color: 'var(--positive)',
                    fontWeight: 600,
                  }}>{event.assetMove}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Edge Decay */}
        <div style={{
          padding: 16,
          background: 'var(--warning-muted)',
          border: '1px solid rgba(234, 179, 8, 0.2)',
          borderRadius: 'var(--radius-lg)',
        }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
            <span style={{ fontSize: 18, lineHeight: 1 }}>⏱</span>
            <div>
              <h3 style={{
                fontSize: 'var(--text-md)',
                fontWeight: 600,
                color: 'var(--warning)',
                marginBottom: 6,
              }}>
                Edge Window Active
              </h3>
              <p style={{
                fontSize: 'var(--text-sm)',
                color: 'var(--text-secondary)',
                lineHeight: 1.55,
              }}>
                Historically, this signal type gets priced in within <strong style={{ color: 'var(--text-primary)' }}>{signal.edgeWindow}</strong>.
                Detected at {new Date(signal.timestamp).toLocaleTimeString()}.
                Early movers capture the most alpha.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
