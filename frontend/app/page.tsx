'use client';

import { useEffect, useState } from 'react';
import SpikeChart from '@/components/SpikeChart';

// ================================================================
// Types
// ================================================================
interface MarketData {
  id: string;
  question: string;
  category: string;
  probability: number;
  previousProbability: number;
  volume24h: number;
  totalVolume: number;
  liquidity: number;
  endDate: string;
  source: string;
  sourceUrl: string;
  trending: boolean;
  tags: string[];
  probabilityHistory: number[];
  dataSource?: string;
  signal?: any;
  attributors?: { name: string; confidence: number }[];
}

const CATEGORIES = [
  { id: 'all', label: 'Trending' },
  { id: 'fed', label: 'Macro' },
  { id: 'crypto', label: 'Crypto' },
  { id: 'tariffs', label: 'Trade' },
  { id: 'geopolitical', label: 'World' },
  { id: 'defense', label: 'Defense' },
];

const CATEGORY_LABELS: Record<string, string> = {
  fed: 'Economics · Macro',
  crypto: 'Crypto · Digital Assets',
  tariffs: 'Trade · Tariffs',
  geopolitical: 'Geopolitical · World',
  defense: 'Politics · Defense',
};

// ================================================================
// Helpers
// ================================================================
function fmtCurrency(v: number): string {
  if (v >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  if (v >= 1e3) return `$${Math.round(v / 1e3).toLocaleString()}K`;
  return `$${v}`;
}

function fmtEndDate(d: string): string {
  return `Ends ${new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
}

function fmtDaysLeft(d: string): string {
  const days = Math.max(0, Math.ceil((new Date(d).getTime() - Date.now()) / 86400000));
  if (days === 0) return 'Ends today';
  return `${days}d left`;
}

function changePp(c: number, p: number): number { return (c - p) * 100; }

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + '…' : s;
}

// ================================================================
// Source logo
// ================================================================
function SourceLogo({ source }: { source: string }) {
  const isKalshi = source.toLowerCase().includes('kalshi');
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      fontSize: 12, fontWeight: 600, color: 'var(--text-muted)',
    }}>
      <span style={{
        width: 20, height: 20, borderRadius: 4, display: 'inline-flex',
        alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 800,
        background: isKalshi ? '#6a9bcc' : '#d97757', color: 'white', letterSpacing: '-0.02em',
      }}>
        {isKalshi ? 'K' : 'P'}
      </span>
      {isKalshi ? 'Kalshi' : 'Polymarket'}
    </span>
  );
}

// ================================================================
// Hero Panel — Polymarket-style
// ================================================================
const HERO_HEIGHT = 460;

function HeroPanel({ market, index, total, onPrev, onNext, prevName, nextName, bookmarked, onBookmark, onShare }: {
  market: MarketData; index: number; total: number;
  onPrev: () => void; onNext: () => void;
  prevName: string; nextName: string;
  bookmarked: boolean; onBookmark: () => void; onShare: () => void;
}) {
  const change = changePp(market.probability, market.previousProbability);
  const pos = change >= 0;
  const paysYes = market.probability > 0.01 ? (1 / market.probability).toFixed(2) : '—';
  const paysNo = market.probability < 0.99 ? (1 / (1 - market.probability)).toFixed(2) : '—';

  return (
    <div>
      {/* Main panel */}
      <div className="hero-panel" style={{
        flexDirection: 'column', padding: 0, overflow: 'hidden',
        height: HERO_HEIGHT, minHeight: HERO_HEIGHT, maxHeight: HERO_HEIGHT,
      }}>
        {/* Top bar: category + bookmark/share */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '16px 24px 0', flexShrink: 0,
        }}>
          <span style={{ fontSize: 13, color: 'var(--text-muted)', fontWeight: 500 }}>
            {CATEGORY_LABELS[market.category] || market.category}
          </span>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={onShare} title="Share" style={{
              background: 'none', border: '1px solid var(--border-subtle)', borderRadius: 8,
              width: 34, height: 34, cursor: 'pointer', display: 'flex', alignItems: 'center',
              justifyContent: 'center', fontSize: 15, color: 'var(--text-muted)',
            }}>↗</button>
            <button onClick={onBookmark} title="Bookmark" style={{
              background: bookmarked ? 'var(--accent-muted)' : 'none',
              border: `1px solid ${bookmarked ? 'var(--accent)' : 'var(--border-subtle)'}`,
              borderRadius: 8, width: 34, height: 34, cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 15, color: bookmarked ? 'var(--accent)' : 'var(--text-muted)',
            }}>{bookmarked ? '★' : '☆'}</button>
          </div>
        </div>

        {/* Title */}
        <div style={{ padding: '8px 24px 0', flexShrink: 0 }}>
          <div style={{
            fontSize: 24, fontWeight: 700, letterSpacing: '-0.03em', lineHeight: 1.2,
            color: 'var(--text-primary)',
            display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
          }}>
            {market.question}
          </div>
        </div>

        {/* Body: left info + right chart */}
        <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
          {/* Left column — pricing table */}
          <div style={{
            flex: '0 0 300px', padding: '16px 0 0 24px',
            display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
          }}>
            {/* Yes/No table */}
            <div>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    <td style={{ padding: '0 0 6px' }}>Market</td>
                    <td style={{ padding: '0 0 6px', textAlign: 'right' }}>Pays out</td>
                    <td style={{ padding: '0 0 6px', textAlign: 'right' }}>Odds</td>
                  </tr>
                </thead>
                <tbody style={{ fontSize: 14, fontWeight: 600 }}>
                  <tr>
                    <td style={{ padding: '8px 0', borderTop: '1px solid var(--border-subtle)' }}>
                      <span style={{ color: 'var(--positive)' }}>Yes</span>
                      <div style={{ height: 3, width: `${market.probability * 100}%`, maxWidth: '100%', background: 'var(--positive)', borderRadius: 2, marginTop: 3 }} />
                    </td>
                    <td style={{ padding: '8px 0', textAlign: 'right', borderTop: '1px solid var(--border-subtle)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>{paysYes}x</td>
                    <td style={{ padding: '8px 0', textAlign: 'right', borderTop: '1px solid var(--border-subtle)' }}>
                      <span style={{ border: '1.5px solid var(--positive)', borderRadius: 6, padding: '3px 10px', fontFamily: 'var(--font-mono)', fontSize: 13 }}>
                        {(market.probability * 100).toFixed(0)}%
                      </span>
                    </td>
                  </tr>
                  <tr>
                    <td style={{ padding: '8px 0', borderTop: '1px solid var(--border-subtle)' }}>
                      <span style={{ color: 'var(--accent)' }}>No</span>
                      <div style={{ height: 3, width: `${(1 - market.probability) * 100}%`, maxWidth: '100%', background: 'var(--accent)', borderRadius: 2, marginTop: 3 }} />
                    </td>
                    <td style={{ padding: '8px 0', textAlign: 'right', borderTop: '1px solid var(--border-subtle)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>{paysNo}x</td>
                    <td style={{ padding: '8px 0', textAlign: 'right', borderTop: '1px solid var(--border-subtle)' }}>
                      <span style={{ border: '1.5px solid var(--border-default)', borderRadius: 6, padding: '3px 10px', fontFamily: 'var(--font-mono)', fontSize: 13 }}>
                        {((1 - market.probability) * 100).toFixed(0)}%
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>

              {/* Signal badge */}
              {market.signal && (
                <div style={{
                  marginTop: 12, padding: '8px 12px', background: 'var(--info-muted)',
                  border: '1px solid rgba(37,99,235,0.15)', borderRadius: 'var(--radius-sm)',
                }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--info)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>
                    ⚡ Signal — {market.signal.severity?.toUpperCase()}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                    {market.signal.confluenceLayers}/{market.signal.totalLayers} layers · {market.signal.edgeWindow} edge
                  </div>
                </div>
              )}
            </div>

            {/* Bottom: volume, end date, source */}
            <div style={{ padding: '0 0 20px', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, fontSize: 12, color: 'var(--text-muted)' }}>
              <span>{fmtCurrency(market.totalVolume)} Vol</span>
              <span style={{ color: 'var(--border-default)' }}>·</span>
              <span>{fmtEndDate(market.endDate)}</span>
              <span style={{ color: 'var(--border-default)' }}>·</span>
              <SourceLogo source={market.source} />
            </div>
          </div>

          {/* Right column — WIDE chart */}
          <div style={{ flex: 1, padding: '8px 20px 16px 8px', display: 'flex', flexDirection: 'column', minWidth: 0 }}>
            {/* Legend + current prob */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 12, marginBottom: 4, flexShrink: 0 }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: 'var(--text-secondary)' }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: pos ? '#788c5d' : '#c44536', display: 'inline-block' }} />
                Yes {(market.probability * 100).toFixed(0)}%
              </span>
              <span className={`price-move ${pos ? 'price-up' : 'price-down'}`} style={{ fontSize: 12 }}>
                {pos ? '+' : ''}{change.toFixed(1)}pp
              </span>
            </div>

            {/* Chart fills remaining space */}
            <div style={{ flex: 1, minHeight: 0 }}>
              <SpikeChart
                data={market.probabilityHistory}
                height={320}
                width={820}
                showSpikes={true}
                spikeThreshold={0.04}
                positive={pos}
                interactive={true}
                label="Yes"
                attributors={market.attributors}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Below panel: dots + nav buttons with event names */}
      <div style={{
        maxWidth: 1180, margin: '0 auto', display: 'flex',
        justifyContent: 'space-between', alignItems: 'center',
        padding: '12px 4px 0',
      }}>
        {/* Left: carousel dots */}
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {Array.from({ length: total }).map((_, i) => (
            <span key={i} style={{
              width: i === index ? 22 : 7, height: 7, borderRadius: 4,
              background: i === index ? 'var(--accent)' : 'var(--border-default)',
              transition: 'width 0.3s ease, background 0.3s ease',
            }} />
          ))}
        </div>

        {/* Right: prev/next with event names */}
        <div style={{ display: 'flex', gap: 10 }}>
          {prevName && (
            <button onClick={onPrev} style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: '8px 16px',
              border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)',
              background: 'var(--bg-card)', cursor: 'pointer', fontSize: 12,
              color: 'var(--text-secondary)', maxWidth: 260,
            }}>
              <span style={{ fontSize: 14 }}>‹</span>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {truncate(prevName, 30)}
              </span>
            </button>
          )}
          {nextName && (
            <button onClick={onNext} style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: '8px 16px',
              border: '1.5px solid var(--accent)', borderRadius: 'var(--radius-md)',
              background: 'var(--bg-card)', cursor: 'pointer', fontSize: 12,
              color: 'var(--accent)', fontWeight: 600, maxWidth: 260,
            }}>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {truncate(nextName, 30)}
              </span>
              <span style={{ fontSize: 14 }}>›</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ================================================================
// Market Card
// ================================================================
function MarketCard({ market, onClick }: { market: MarketData; onClick: () => void }) {
  const change = changePp(market.probability, market.previousProbability);
  const pos = change >= 0;

  return (
    <div className="exchange-card" onClick={onClick} style={{ cursor: 'pointer' }}>
      <div className="exchange-card-header">
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span className="venue-chip">{market.source.toUpperCase()}</span>
          {market.signal && <span className="signal-chip"><span className="signal-chip-dot" />SIGNAL</span>}
        </div>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{fmtDaysLeft(market.endDate)}</span>
      </div>

      <div style={{ fontSize: 17, fontWeight: 660, letterSpacing: '-0.02em', lineHeight: 1.25, color: 'var(--text-primary)', minHeight: 50, marginBottom: 10 }}>
        {market.question}
      </div>

      <div className="chart-shell">
        <SpikeChart
          data={market.probabilityHistory}
          height={96}
          width={400}
          showSpikes={true}
          spikeThreshold={0.05}
          positive={pos}
          interactive={false}
          attributors={market.attributors}
        />
        <div className="chart-meta-row" style={{ marginTop: 4 }}>
          <span className="meta-mono">{fmtCurrency(market.volume24h)} vol</span>
          <span className={`price-move ${pos ? 'price-up' : 'price-down'}`}>{pos ? '+' : ''}{change.toFixed(1)}pp</span>
        </div>
      </div>

      <div className="price-row" style={{ marginTop: 10 }}>
        <div className="price-box price-box-yes">
          <span className="price-label">Yes</span>
          <span className="price-value">{(market.probability * 100).toFixed(0)}¢</span>
        </div>
        <div className="price-box">
          <span className="price-label">No</span>
          <span className="price-value">{((1 - market.probability) * 100).toFixed(0)}¢</span>
        </div>
      </div>

      <div className="card-foot">
        <span className="layer-tag">{fmtCurrency(market.liquidity)} liq</span>
        {market.tags.slice(0, 2).map(t => <span key={t} className="layer-tag">{t}</span>)}
      </div>

      {market.signal && (
        <div className="edge-strip">
          <div className="edge-strip-head">
            <span className="edge-title">⚡ {market.signal.event}</span>
            <span className={`severity-badge severity-badge-${market.signal.severity}`}>{market.signal.severity?.toUpperCase()}</span>
          </div>
          <div className="edge-strip-grid">
            <div><div className="edge-kicker">Confidence</div><div className="edge-value">{((market.signal.confidenceScore || 0) * 100).toFixed(0)}%</div></div>
            <div><div className="edge-kicker">Layers</div><div className="edge-value">{market.signal.confluenceLayers}/{market.signal.totalLayers}</div></div>
            <div><div className="edge-kicker">Edge</div><div className="edge-value">{market.signal.edgeWindow}</div></div>
          </div>
          {market.signal.assetImpact && (
            <div className="layer-inline-list">
              {market.signal.assetImpact.slice(0, 3).map((a: any, i: number) => (
                <span key={i} className="layer-inline-item">{a.asset} {a.expectedMove}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ================================================================
// Main Page
// ================================================================
export default function Home() {
  const [markets, setMarkets] = useState<MarketData[]>([]);
  const [loading, setLoading] = useState(true);
  const [heroIdx, setHeroIdx] = useState(0);
  const [activeCategory, setActiveCategory] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedMarket, setSelectedMarket] = useState<MarketData | null>(null);
  const [dataSource, setDataSource] = useState('');
  const [bookmarks, setBookmarks] = useState<Set<string>>(new Set());

  useEffect(() => {
    setLoading(true);
    fetch('/api/markets?sort=volume')
      .then(r => r.json())
      .then(data => {
        setMarkets(data.markets || []);
        setDataSource(data.dataSource || '');
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const heroMarkets = markets.filter(m => m.trending || m.signal);

  const toggleBookmark = (id: string) => {
    setBookmarks(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const handleShare = (market: MarketData) => {
    const text = `${market.question} — ${(market.probability * 100).toFixed(0)}% | Pythia Intelligence`;
    if (navigator.share) {
      navigator.share({ title: 'Pythia Signal', text, url: window.location.href }).catch(() => {});
    } else {
      navigator.clipboard?.writeText(text);
    }
  };

  const filtered = markets.filter(m => {
    if (activeCategory !== 'all' && m.category !== activeCategory) return false;
    if (searchQuery && !m.question.toLowerCase().includes(searchQuery.toLowerCase())) return false;
    return true;
  });

  const categories = [...new Set(filtered.map(m => m.category))];

  // Hero nav helpers
  const heroLen = heroMarkets.length;
  const safeIdx = heroLen > 0 ? ((heroIdx % heroLen) + heroLen) % heroLen : 0;
  const prevIdx = heroLen > 0 ? ((safeIdx - 1) + heroLen) % heroLen : 0;
  const nextIdx = heroLen > 0 ? (safeIdx + 1) % heroLen : 0;

  if (loading) {
    return (
      <div className="market-shell">
        <div className="loading-shell">
          <div className="loading-spinner" />
          <div className="loading-text">Loading markets...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="market-shell">
      {/* Detail view */}
      {selectedMarket && (
        <div style={{ maxWidth: 1180, margin: '0 auto' }}>
          <button onClick={() => setSelectedMarket(null)} style={{
            background: 'none', border: 'none', cursor: 'pointer', color: 'var(--accent)',
            fontSize: 13, fontWeight: 600, marginBottom: 14, display: 'flex', alignItems: 'center', gap: 4,
          }}>← Back to markets</button>
          <HeroPanel
            market={selectedMarket} index={0} total={1}
            onPrev={() => setSelectedMarket(null)}
            onNext={() => setSelectedMarket(null)}
            prevName="" nextName=""
            bookmarked={bookmarks.has(selectedMarket.id)}
            onBookmark={() => toggleBookmark(selectedMarket.id)}
            onShare={() => handleShare(selectedMarket)}
          />
        </div>
      )}

      {/* Landing */}
      {!selectedMarket && (
        <>
          {heroMarkets.length > 0 && (
            <HeroPanel
              market={heroMarkets[safeIdx]}
              index={safeIdx} total={heroLen}
              onPrev={() => setHeroIdx(prevIdx)}
              onNext={() => setHeroIdx(nextIdx)}
              prevName={heroMarkets[prevIdx]?.question || ''}
              nextName={heroMarkets[nextIdx]?.question || ''}
              bookmarked={bookmarks.has(heroMarkets[safeIdx]?.id)}
              onBookmark={() => toggleBookmark(heroMarkets[safeIdx]?.id)}
              onShare={() => handleShare(heroMarkets[safeIdx])}
            />
          )}

          {/* Category tabs + search */}
          <div className="control-bar" style={{ marginTop: 20 }}>
            <div className="filter-row">
              {CATEGORIES.map(c => (
                <button key={c.id}
                  className={`filter-chip ${activeCategory === c.id ? 'filter-chip-active' : ''}`}
                  onClick={() => setActiveCategory(c.id)}>{c.label}</button>
              ))}
            </div>
            <div style={{ position: 'relative', flex: '0 1 380px' }}>
              <input value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
                placeholder='Search events...'
                style={{
                  width: '100%', padding: '10px 14px 10px 34px', borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--border-subtle)', background: 'var(--bg-card)', fontSize: 13,
                  color: 'var(--text-primary)', outline: 'none',
                }} />
              <span style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', fontSize: 13 }}>⌕</span>
            </div>
          </div>

          {/* Cards */}
          {activeCategory === 'all' ? (
            categories.map(cat => {
              const catMarkets = filtered.filter(m => m.category === cat);
              if (!catMarkets.length) return null;
              const catLabel = CATEGORIES.find(c => c.id === cat)?.label || cat.charAt(0).toUpperCase() + cat.slice(1);
              return (
                <div key={cat} style={{ maxWidth: 1180, margin: '0 auto 28px' }}>
                  <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: '-0.03em', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
                    {catLabel} <span style={{ fontSize: 13, color: 'var(--text-muted)', fontWeight: 500 }}>›</span>
                  </div>
                  <div className="cards-grid">
                    {catMarkets.map(m => <MarketCard key={m.id} market={m} onClick={() => setSelectedMarket(m)} />)}
                  </div>
                </div>
              );
            })
          ) : (
            <div className="cards-grid">
              {filtered.map(m => <MarketCard key={m.id} market={m} onClick={() => setSelectedMarket(m)} />)}
            </div>
          )}

          {filtered.length === 0 && (
            <div style={{ textAlign: 'center', padding: 60, color: 'var(--text-muted)' }}>No markets found.</div>
          )}

          <div style={{ maxWidth: 1180, margin: '20px auto 0', textAlign: 'center' }}>
            <span className="data-pill">
              {dataSource === 'live' ? '● Live Data' : '◌ Demo Data'} · Powered by Pythia PCE
            </span>
          </div>
        </>
      )}
    </div>
  );
}
