'use client';

import { useEffect, useState } from 'react';
import SpikeChart from '@/components/SpikeChart';

interface MarketData {
  id: string; question: string; category: string; probability: number;
  previousProbability: number; volume24h: number; totalVolume: number;
  liquidity: number; endDate: string; source: string; sourceUrl: string;
  trending: boolean; tags: string[]; probabilityHistory: number[];
  dataSource?: string; signal?: any;
  attributors?: { name: string; confidence: number }[];
}

const CATEGORIES = [
  { id: 'all', label: 'Trending' }, { id: 'fed', label: 'Macro' },
  { id: 'crypto', label: 'Crypto' }, { id: 'tariffs', label: 'Trade' },
  { id: 'geopolitical', label: 'World' }, { id: 'defense', label: 'Defense' },
];
const CAT_LABELS: Record<string, string> = {
  fed: 'Economics · Macro', crypto: 'Crypto · Digital Assets',
  tariffs: 'Trade · Tariffs', geopolitical: 'Geopolitical · World',
  defense: 'Politics · Defense',
};

const YES_COLOR = '#788c5d';
const NO_COLOR = '#d97757';

function fmtCurrency(v: number) { return v >= 1e6 ? `$${(v / 1e6).toFixed(0)}M` : v >= 1e3 ? `$${Math.round(v / 1e3).toLocaleString()}K` : `$${v}`; }
function fmtEndDate(d: string) { return `Ends ${new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`; }
function fmtDaysLeft(d: string) { const days = Math.max(0, Math.ceil((new Date(d).getTime() - Date.now()) / 86400000)); return days === 0 ? 'Ends today' : `${days}d left`; }
function changePp(c: number, p: number) { return (c - p) * 100; }
function truncate(s: string, n: number) { return s.length > n ? s.slice(0, n) + '…' : s; }

function SourceLink({ source, url }: { source: string; url: string }) {
  const isK = source.toLowerCase().includes('kalshi');
  return (
    <a href={url || (isK ? 'https://kalshi.com' : 'https://polymarket.com')} target="_blank" rel="noopener noreferrer"
      style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: 'var(--text-muted)', textDecoration: 'none' }}>
      <span style={{ width: 18, height: 18, borderRadius: 4, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, fontWeight: 800, background: isK ? '#6a9bcc' : '#d97757', color: 'white' }}>
        {isK ? 'K' : 'P'}
      </span>
      {isK ? 'Kalshi' : 'Polymarket'}
    </a>
  );
}

// ================================================================
// Hero Panel
// ================================================================
const HERO_H = 460;

function HeroPanel({ market, index, total, onPrev, onNext, prevName, nextName, bookmarked, onBookmark, onShare }: {
  market: MarketData; index: number; total: number;
  onPrev: () => void; onNext: () => void;
  prevName: string; nextName: string;
  bookmarked: boolean; onBookmark: () => void; onShare: () => void;
}) {
  const prob = market.probability;
  const paysYes = prob > 0.01 ? (1 / prob).toFixed(2) : '—';
  const paysNo = prob < 0.99 ? (1 / (1 - prob)).toFixed(2) : '—';

  return (
    <div>
      <div className="hero-panel" style={{
        flexDirection: 'column', alignItems: 'stretch', justifyContent: 'flex-start',
        padding: 0, overflow: 'hidden',
        height: HERO_H, minHeight: HERO_H, maxHeight: HERO_H,
      }}>
        {/* Row 1: category LEFT + share/bookmark RIGHT */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 22px 0', flexShrink: 0 }}>
          <span style={{ fontSize: 13, color: 'var(--text-muted)', fontWeight: 500 }}>
            {CAT_LABELS[market.category] || market.category}
          </span>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <button onClick={onShare} title="Share" style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: 'var(--text-muted)', padding: 0, lineHeight: 1 }}>↗</button>
            <button onClick={onBookmark} title="Bookmark" style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: bookmarked ? NO_COLOR : 'var(--text-muted)', padding: 0, lineHeight: 1 }}>{bookmarked ? '★' : '☆'}</button>
          </div>
        </div>

        {/* Row 2: title LEFT aligned */}
        <div style={{ padding: '6px 22px 0', flexShrink: 0, textAlign: 'left' }}>
          <div style={{
            fontSize: 23, fontWeight: 700, letterSpacing: '-0.03em', lineHeight: 1.2,
            color: 'var(--text-primary)', fontFamily: 'var(--font-display)',
            display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
            textAlign: 'left',
          }}>
            {market.question}
          </div>
        </div>

        {/* Row 3: left column + right chart */}
        <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'visible' }}>
          {/* Left column: logo → odds → supplemental */}
          <div style={{ flex: '0 0 280px', padding: '12px 22px 16px', display: 'flex', flexDirection: 'column' }}>

            {/* Source logo — FIXED at top of left column */}
            <div style={{ marginBottom: 10, flexShrink: 0 }}>
              <SourceLink source={market.source} url={market.sourceUrl} />
            </div>

            {/* Odds table */}
            <table style={{ width: '100%', borderCollapse: 'collapse', flexShrink: 0 }}>
              <thead>
                <tr style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)' }}>
                  <td style={{ padding: '0 0 6px' }}>Market</td>
                  <td style={{ padding: '0 0 6px', textAlign: 'right' }}>Pays out</td>
                  <td style={{ padding: '0 0 6px', textAlign: 'right' }}>Odds</td>
                </tr>
              </thead>
              <tbody>
                {/* Yes row — #788c5d */}
                <tr style={{ color: YES_COLOR, fontWeight: 600, fontSize: 14 }}>
                  <td style={{ padding: '9px 0', borderTop: '1px solid var(--border-subtle)' }}>
                    Yes
                    <div style={{ height: 3, width: `${prob * 100}%`, maxWidth: '100%', background: YES_COLOR, borderRadius: 2, marginTop: 3 }} />
                  </td>
                  <td style={{ padding: '9px 0', textAlign: 'right', borderTop: '1px solid var(--border-subtle)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>{paysYes}x</td>
                  <td style={{ padding: '9px 0', textAlign: 'right', borderTop: '1px solid var(--border-subtle)', fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 700 }}>{(prob * 100).toFixed(0)}%</td>
                </tr>
                {/* No row — #d97757 */}
                <tr style={{ color: NO_COLOR, fontWeight: 600, fontSize: 14 }}>
                  <td style={{ padding: '9px 0', borderTop: '1px solid var(--border-subtle)' }}>
                    No
                    <div style={{ height: 3, width: `${(1 - prob) * 100}%`, maxWidth: '100%', background: NO_COLOR, borderRadius: 2, marginTop: 3 }} />
                  </td>
                  <td style={{ padding: '9px 0', textAlign: 'right', borderTop: '1px solid var(--border-subtle)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>{paysNo}x</td>
                  <td style={{ padding: '9px 0', textAlign: 'right', borderTop: '1px solid var(--border-subtle)', fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 700 }}>{((1 - prob) * 100).toFixed(0)}%</td>
                </tr>
              </tbody>
            </table>

            {/* Supplemental info — each in its own fixed row below odds */}
            <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 5, fontSize: 12, color: 'var(--text-muted)', flexShrink: 0 }}>
              <span style={{ fontWeight: 600 }}>{fmtCurrency(market.totalVolume)} Vol</span>
              <span>{fmtEndDate(market.endDate)}</span>
              <span>{fmtDaysLeft(market.endDate)}</span>
            </div>

            {/* Signal badge */}
            {market.signal && (
              <div style={{ marginTop: 'auto', padding: '7px 10px', background: 'var(--info-muted)', border: '1px solid rgba(106,155,204,0.15)', borderRadius: 'var(--radius-sm)' }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--info)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>⚡ Signal — {market.signal.severity?.toUpperCase()}</div>
                <div style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.4, marginTop: 2 }}>{market.signal.confluenceLayers}/{market.signal.totalLayers} layers · {market.signal.edgeWindow} edge</div>
              </div>
            )}
          </div>

          {/* Right: chart — overflow visible so spike popup shows */}
          <div style={{ flex: 1, padding: '12px 16px 24px 0', display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'visible' }}>
            <div style={{ flex: 1, minHeight: 0 }}>
              <SpikeChart data={market.probabilityHistory} height={340} width={860} showSpikes spikeThreshold={0.04} interactive attributors={market.attributors} />
            </div>
          </div>
        </div>
      </div>

      {/* Below panel — closer to panel */}
      <div style={{ maxWidth: 1180, margin: '4px auto 0', display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0 4px' }}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {Array.from({ length: total }).map((_, i) => (
            <span key={i} style={{ width: i === index ? 22 : 7, height: 7, borderRadius: 4, background: i === index ? NO_COLOR : 'var(--border-default)', transition: 'width 0.3s, background 0.3s' }} />
          ))}
        </div>
        <div style={{ display: 'flex', gap: 16 }}>
          {prevName && (
            <button onClick={onPrev} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: 0, background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: 'var(--text-muted)', maxWidth: 240 }}>
              <span>‹</span><span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{truncate(prevName, 28)}</span>
            </button>
          )}
          {nextName && (
            <button onClick={onNext} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: 0, background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: NO_COLOR, fontWeight: 600, maxWidth: 240 }}>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{truncate(nextName, 28)}</span><span>›</span>
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
        <div style={{ display: 'flex', gap: 6 }}>
          <span className="venue-chip">{market.source.toUpperCase()}</span>
          {market.signal && <span className="signal-chip"><span className="signal-chip-dot" />SIGNAL</span>}
        </div>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{fmtDaysLeft(market.endDate)}</span>
      </div>
      <div style={{ fontSize: 17, fontWeight: 660, letterSpacing: '-0.02em', lineHeight: 1.25, color: 'var(--text-primary)', minHeight: 50, marginBottom: 10, fontFamily: 'var(--font-display)' }}>{market.question}</div>
      <div className="chart-shell">
        <SpikeChart data={market.probabilityHistory} height={96} width={400} showSpikes spikeThreshold={0.05} interactive={false} attributors={market.attributors} />
        <div className="chart-meta-row" style={{ marginTop: 4 }}>
          <span className="meta-mono">{fmtCurrency(market.volume24h)} vol</span>
          <span className={`price-move ${pos ? 'price-up' : 'price-down'}`}>{pos ? '+' : ''}{change.toFixed(1)}pp</span>
        </div>
      </div>
      <div className="price-row" style={{ marginTop: 10 }}>
        <div className="price-box" style={{ background: 'rgba(120,140,93,0.06)', borderColor: 'rgba(120,140,93,0.18)' }}>
          <span className="price-label" style={{ color: YES_COLOR }}>Yes</span>
          <span className="price-value" style={{ color: YES_COLOR }}>{(market.probability * 100).toFixed(0)}¢</span>
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
        </div>
      )}
    </div>
  );
}

// ================================================================
// Main
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
    fetch('/api/markets?sort=volume').then(r => r.json())
      .then(d => { setMarkets(d.markets || []); setDataSource(d.dataSource || ''); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const heroMarkets = markets.filter(m => m.trending || m.signal);
  const toggleBM = (id: string) => setBookmarks(p => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const share = (m: MarketData) => { const t = `${m.question} — ${(m.probability * 100).toFixed(0)}% | Pythia`; navigator.share ? navigator.share({ title: 'Pythia', text: t, url: location.href }).catch(() => {}) : navigator.clipboard?.writeText(t); };
  const filtered = markets.filter(m => { if (activeCategory !== 'all' && m.category !== activeCategory) return false; if (searchQuery && !m.question.toLowerCase().includes(searchQuery.toLowerCase())) return false; return true; });
  const cats = [...new Set(filtered.map(m => m.category))];
  const hL = heroMarkets.length, sI = hL > 0 ? ((heroIdx % hL) + hL) % hL : 0, pI = hL > 0 ? ((sI - 1) + hL) % hL : 0, nI = hL > 0 ? (sI + 1) % hL : 0;

  if (loading) return <div className="market-shell"><div className="loading-shell"><div className="loading-spinner" /><div className="loading-text">Loading markets...</div></div></div>;

  return (
    <div className="market-shell">
      {selectedMarket ? (
        <div style={{ maxWidth: 1180, margin: '0 auto' }}>
          <button onClick={() => setSelectedMarket(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: NO_COLOR, fontSize: 13, fontWeight: 600, marginBottom: 14 }}>← Back</button>
          <HeroPanel market={selectedMarket} index={0} total={1} onPrev={() => setSelectedMarket(null)} onNext={() => setSelectedMarket(null)} prevName="" nextName="" bookmarked={bookmarks.has(selectedMarket.id)} onBookmark={() => toggleBM(selectedMarket.id)} onShare={() => share(selectedMarket)} />
        </div>
      ) : (
        <>
          {heroMarkets.length > 0 && <HeroPanel market={heroMarkets[sI]} index={sI} total={hL} onPrev={() => setHeroIdx(pI)} onNext={() => setHeroIdx(nI)} prevName={heroMarkets[pI]?.question || ''} nextName={heroMarkets[nI]?.question || ''} bookmarked={bookmarks.has(heroMarkets[sI]?.id)} onBookmark={() => toggleBM(heroMarkets[sI]?.id)} onShare={() => share(heroMarkets[sI])} />}
          <div className="control-bar" style={{ marginTop: 16 }}>
            <div className="filter-row">
              {CATEGORIES.map(c => <button key={c.id} className={`filter-chip ${activeCategory === c.id ? 'filter-chip-active' : ''}`} onClick={() => setActiveCategory(c.id)}>{c.label}</button>)}
            </div>
            <div style={{ position: 'relative', flex: '0 1 380px' }}>
              <input value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder="Search events..." style={{ width: '100%', padding: '10px 14px 10px 34px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)', background: 'var(--bg-card)', fontSize: 13, color: 'var(--text-primary)', outline: 'none' }} />
              <span style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', fontSize: 13 }}>⌕</span>
            </div>
          </div>
          {activeCategory === 'all' ? cats.map(cat => {
            const cm = filtered.filter(m => m.category === cat); if (!cm.length) return null;
            const lb = CATEGORIES.find(c => c.id === cat)?.label || cat.charAt(0).toUpperCase() + cat.slice(1);
            return <div key={cat} style={{ maxWidth: 1180, margin: '0 auto 28px' }}><div style={{ fontSize: 20, fontWeight: 700, letterSpacing: '-0.03em', marginBottom: 14, fontFamily: 'var(--font-display)' }}>{lb} <span style={{ fontSize: 13, color: 'var(--text-muted)', fontWeight: 500 }}>›</span></div><div className="cards-grid">{cm.map(m => <MarketCard key={m.id} market={m} onClick={() => setSelectedMarket(m)} />)}</div></div>;
          }) : <div className="cards-grid">{filtered.map(m => <MarketCard key={m.id} market={m} onClick={() => setSelectedMarket(m)} />)}</div>}
          {filtered.length === 0 && <div style={{ textAlign: 'center', padding: 60, color: 'var(--text-muted)' }}>No markets found.</div>}
          <div style={{ maxWidth: 1180, margin: '20px auto 0', textAlign: 'center' }}><span className="data-pill">{dataSource === 'live' ? '● Live' : '◌ Demo'} · Pythia PCE</span></div>
        </>
      )}
    </div>
  );
}
