'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import SpikeChart from '@/components/SpikeChart';
import type { SpikeAttributor } from '@/components/SpikeChart';

interface MarketData {
  id: string; question: string; category: string; probability: number;
  previousProbability: number; volume24h: number; totalVolume: number;
  liquidity: number; endDate: string; source: string; sourceUrl: string;
  trending: boolean; tags: string[]; probabilityHistory: number[];
  dataSource?: string; signal?: any;
  spikeAttributors?: Record<number, SpikeAttributor[]>;
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

const YES_C = '#788c5d', NO_C = '#d97757';

function fmtCurrency(v: number) { return v >= 1e6 ? `$${(v / 1e6).toFixed(0)}M` : v >= 1e3 ? `$${Math.round(v / 1e3).toLocaleString()}K` : `$${v}`; }
function fmtEndDate(d: string) { return `Ends ${new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`; }
function fmtDaysLeft(d: string) { const days = Math.max(0, Math.ceil((new Date(d).getTime() - Date.now()) / 86400000)); return days === 0 ? 'Ends today' : `${days}d left`; }
function changePp(c: number, p: number) { return (c - p) * 100; }
// Smart text shortener — condenses market questions to fit nav buttons
function shorten(s: string, maxLen: number = 42): string {
  if (s.length <= maxLen) return s;
  // Step 1: Remove common filler
  let t = s
    .replace(/^Will (the )?/i, '')
    .replace(/^Does (the )?/i, '')
    .replace(/^Is (the )?/i, '')
    .replace(/ by (the )?end of /i, ' by ')
    .replace(/ before (the )?end of /i, ' before ')
    .replace(/ at (the )?(March|April|May|June|July|August|September|October|November|December|January|February) \d{4} /i, (_, __, m) => ` at ${m.slice(0, 3)} `)
    .replace(/ (January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})/gi, (_, m, y) => ` ${m.slice(0, 3)} ${y}`)
    .replace(/ United States/gi, ' US')
    .replace(/ President /gi, ' Pres. ')
    .replace(/ government /gi, ' gov\'t ')
    .replace(/ percent/gi, '%')
    .replace(/ percentage points/gi, 'pp')
    .replace(/ billion/gi, 'B')
    .replace(/ million/gi, 'M')
    .replace(/ cryptocurrency/gi, ' crypto')
    .replace(/ agreement/gi, ' deal')
    .replace(/ regulation/gi, ' reg.')
    .replace(/ approximately/gi, ' ~')
    .replace(/\?$/, '');
  if (t.length <= maxLen) return t;
  // Step 2: Truncate with ellipsis at word boundary
  const words = t.split(' ');
  let result = '';
  for (const w of words) {
    if ((result + ' ' + w).trim().length > maxLen - 1) break;
    result = (result + ' ' + w).trim();
  }
  return result + '…';
}

function SourceLink({ source, url }: { source: string; url: string }) {
  const isK = source.toLowerCase().includes('kalshi');
  return (
    <a href={url || (isK ? 'https://kalshi.com' : 'https://polymarket.com')} target="_blank" rel="noopener noreferrer"
      style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: 'var(--text-muted)', textDecoration: 'none' }}>
      <span style={{ width: 18, height: 18, borderRadius: 4, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, fontWeight: 800, background: isK ? '#6a9bcc' : NO_C, color: 'white' }}>{isK ? 'K' : 'P'}</span>
      {isK ? 'Kalshi' : 'Polymarket'}
    </a>
  );
}

// ── Live data hook — polls /api/markets every 30s ──
function useLiveMarkets(interval: number = 30000) {
  const [markets, setMarkets] = useState<MarketData[]>([]);
  const [loading, setLoading] = useState(true);
  const [dataSource, setDataSource] = useState('');
  const [lastUpdated, setLastUpdated] = useState<string>(new Date().toISOString());

  const fetchData = useCallback(async () => {
    try {
      const r = await fetch('/api/markets?sort=volume');
      const d = await r.json();
      setMarkets(d.markets || []);
      setDataSource(d.dataSource || '');
      setLastUpdated(d.lastUpdated || new Date().toISOString());
      setLoading(false);
    } catch { setLoading(false); }
  }, []);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, interval);
    return () => clearInterval(timer);
  }, [fetchData, interval]);

  return { markets, loading, dataSource, lastUpdated };
}

// ── Live pulse indicator ──
function LivePulse() {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--text-muted)' }}>
      <span style={{
        width: 7, height: 7, borderRadius: '50%', background: YES_C,
        boxShadow: `0 0 0 2px rgba(120,140,93,0.2)`,
        animation: 'pulse-soft 2s ease-in-out infinite',
      }} />
      Live
    </span>
  );
}

// ================================================================
// Hero Panel
// ================================================================
const HERO_H = 500;

function HeroPanel({ market, index, total, onPrev, onNext, prevName, nextName, bookmarked, onBookmark, onShare, lastUpdated }: {
  market: MarketData; index: number; total: number;
  onPrev: () => void; onNext: () => void;
  prevName: string; nextName: string;
  bookmarked: boolean; onBookmark: () => void; onShare: () => void;
  lastUpdated: string;
}) {
  const prob = market.probability;
  const paysYes = prob > 0.01 ? (1 / prob).toFixed(2) : '—';
  const paysNo = prob < 0.99 ? (1 / (1 - prob)).toFixed(2) : '—';

  return (
    <div>
      <div className="hero-panel" style={{
        flexDirection: 'column', alignItems: 'stretch', justifyContent: 'flex-start',
        padding: 0, overflow: 'visible',
        height: HERO_H, minHeight: HERO_H, maxHeight: HERO_H,
      }}>
        {/* Category + live indicator + icons */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 22px 0', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 13, color: 'var(--text-muted)', fontWeight: 500 }}>{CAT_LABELS[market.category] || market.category}</span>
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <button onClick={onShare} title="Share" style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: 'var(--text-muted)', padding: 0 }}>↗</button>
            <button onClick={onBookmark} title="Bookmark" style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: bookmarked ? NO_C : 'var(--text-muted)', padding: 0 }}>{bookmarked ? '★' : '☆'}</button>
          </div>
        </div>

        {/* Title */}
        <div style={{ padding: '6px 22px 0', flexShrink: 0, textAlign: 'left' }}>
          <div style={{ fontSize: 23, fontWeight: 700, letterSpacing: '-0.03em', lineHeight: 1.2, color: 'var(--text-primary)', fontFamily: 'var(--font-display)', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden', textAlign: 'left' }}>
            {market.question}
          </div>
        </div>

        {/* Body */}
        <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'visible' }}>
          {/* Left */}
          <div style={{ flex: '0 0 280px', padding: '12px 22px 16px', display: 'flex', flexDirection: 'column' }}>
            <div style={{ marginBottom: 10, flexShrink: 0, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}><SourceLink source={market.source} url={market.sourceUrl} /><LivePulse /></div>

            <table style={{ width: '100%', borderCollapse: 'collapse', flexShrink: 0 }}>
              <thead>
                <tr style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)' }}>
                  <td style={{ padding: '0 0 6px' }}>Market</td>
                  <td style={{ padding: '0 0 6px', textAlign: 'right' }}>Pays out</td>
                  <td style={{ padding: '0 0 6px', textAlign: 'right' }}>Odds</td>
                </tr>
              </thead>
              <tbody>
                <tr style={{ color: YES_C, fontWeight: 600, fontSize: 14 }}>
                  <td style={{ padding: '9px 0', borderTop: '1px solid var(--border-subtle)' }}>Yes<div style={{ height: 3, width: `${prob * 100}%`, maxWidth: '100%', background: YES_C, borderRadius: 2, marginTop: 3 }} /></td>
                  <td style={{ padding: '9px 0', textAlign: 'right', borderTop: '1px solid var(--border-subtle)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>{paysYes}x</td>
                  <td style={{ padding: '9px 0', textAlign: 'right', borderTop: '1px solid var(--border-subtle)', fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 700 }}>{(prob * 100).toFixed(0)}%</td>
                </tr>
                <tr style={{ color: NO_C, fontWeight: 600, fontSize: 14 }}>
                  <td style={{ padding: '9px 0', borderTop: '1px solid var(--border-subtle)' }}>No<div style={{ height: 3, width: `${(1 - prob) * 100}%`, maxWidth: '100%', background: NO_C, borderRadius: 2, marginTop: 3 }} /></td>
                  <td style={{ padding: '9px 0', textAlign: 'right', borderTop: '1px solid var(--border-subtle)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>{paysNo}x</td>
                  <td style={{ padding: '9px 0', textAlign: 'right', borderTop: '1px solid var(--border-subtle)', fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 700 }}>{((1 - prob) * 100).toFixed(0)}%</td>
                </tr>
              </tbody>
            </table>

            <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 5, fontSize: 12, color: 'var(--text-muted)', flexShrink: 0 }}>
              <span style={{ fontWeight: 600 }}>{fmtCurrency(market.totalVolume)} Vol</span>
              <span>{fmtEndDate(market.endDate)}</span>
              <span>{fmtDaysLeft(market.endDate)}</span>
            </div>
          </div>

          {/* Right: chart */}
          <div style={{ flex: 1, padding: '12px 16px 14px 0', display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'visible' }}>
            <div style={{ flex: 1, minHeight: 0 }}>
              <SpikeChart data={market.probabilityHistory} height={330} width={860}
                showSpikes spikeThreshold={0.035} interactive
                spikeAttributors={market.spikeAttributors}
                lastUpdated={lastUpdated} />
            </div>
          </div>
        </div>

        {/* Nav row — INSIDE panel at bottom, above rounded corners */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '6px 22px 12px', borderTop: '1px solid var(--border-subtle)',
          flexShrink: 0,
        }}>
          <div style={{ display: 'flex', gap: 6 }}>
            {Array.from({ length: total }).map((_, i) => (
              <span key={i} style={{ width: i === index ? 22 : 7, height: 7, borderRadius: 4, background: i === index ? NO_C : 'var(--border-default)', transition: 'width 0.3s, background 0.3s' }} />
            ))}
          </div>
          <div style={{ display: 'flex', gap: 24 }}>
            {prevName && <button onClick={onPrev} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: 0, background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: 'var(--text-muted)', width: 280, flexShrink: 0 }}><span>‹</span><span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{shorten(prevName)}</span></button>}
            {nextName && <button onClick={onNext} style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 6, padding: 0, background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: NO_C, fontWeight: 600, width: 280, flexShrink: 0 }}><span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{shorten(nextName)}</span><span>›</span></button>}
          </div>
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
        <div style={{ display: 'flex', gap: 6 }}><span className="venue-chip">{market.source.toUpperCase()}</span>{market.signal && <span className="signal-chip"><span className="signal-chip-dot" />SIGNAL</span>}</div>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{fmtDaysLeft(market.endDate)}</span>
      </div>
      <div style={{ fontSize: 17, fontWeight: 660, letterSpacing: '-0.02em', lineHeight: 1.25, color: 'var(--text-primary)', minHeight: 50, marginBottom: 10, fontFamily: 'var(--font-display)' }}>{market.question}</div>
      <div className="chart-shell">
        <SpikeChart data={market.probabilityHistory} height={96} width={400} showSpikes spikeThreshold={0.05} interactive={false} />
        <div className="chart-meta-row" style={{ marginTop: 4 }}>
          <span className="meta-mono">{fmtCurrency(market.volume24h)} vol</span>
          <span className={`price-move ${pos ? 'price-up' : 'price-down'}`}>{pos ? '+' : ''}{change.toFixed(1)}pp</span>
        </div>
      </div>
      <div className="price-row" style={{ marginTop: 10 }}>
        <div className="price-box" style={{ background: 'rgba(120,140,93,0.06)', borderColor: 'rgba(120,140,93,0.18)' }}><span className="price-label" style={{ color: YES_C }}>Yes</span><span className="price-value" style={{ color: YES_C }}>{(market.probability * 100).toFixed(0)}¢</span></div>
        <div className="price-box"><span className="price-label">No</span><span className="price-value">{((1 - market.probability) * 100).toFixed(0)}¢</span></div>
      </div>
      <div className="card-foot"><span className="layer-tag">{fmtCurrency(market.liquidity)} liq</span>{market.tags.slice(0, 2).map(t => <span key={t} className="layer-tag">{t}</span>)}</div>
      {market.signal && (
        <div className="edge-strip">
          <div className="edge-strip-head"><span className="edge-title">⚡ {market.signal.event}</span><span className={`severity-badge severity-badge-${market.signal.severity}`}>{market.signal.severity?.toUpperCase()}</span></div>
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
  const { markets, loading, dataSource, lastUpdated } = useLiveMarkets(30000);
  const [heroIdx, setHeroIdx] = useState(0);
  const [activeCategory, setActiveCategory] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedMarket, setSelectedMarket] = useState<MarketData | null>(null);
  const [bookmarks, setBookmarks] = useState<Set<string>>(new Set());

  // Keep selectedMarket in sync with live updates
  useEffect(() => {
    if (selectedMarket) {
      const fresh = markets.find(m => m.id === selectedMarket.id);
      if (fresh) setSelectedMarket(fresh);
    }
  }, [markets]); // eslint-disable-line react-hooks/exhaustive-deps

  const hm = markets.filter(m => m.trending || m.signal);
  const toggleBM = (id: string) => setBookmarks(p => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const share = (m: MarketData) => { const t = `${m.question} — ${(m.probability * 100).toFixed(0)}% | Pythia`; navigator.share ? navigator.share({ title: 'Pythia', text: t, url: location.href }).catch(() => {}) : navigator.clipboard?.writeText(t); };
  const filtered = markets.filter(m => { if (activeCategory !== 'all' && m.category !== activeCategory) return false; if (searchQuery && !m.question.toLowerCase().includes(searchQuery.toLowerCase())) return false; return true; });
  const cats = [...new Set(filtered.map(m => m.category))];
  const hL = hm.length, sI = hL > 0 ? ((heroIdx % hL) + hL) % hL : 0, pI = hL > 0 ? ((sI - 1) + hL) % hL : 0, nI = hL > 0 ? (sI + 1) % hL : 0;

  if (loading) return <div className="market-shell"><div className="loading-shell"><div className="loading-spinner" /><div className="loading-text">Loading markets...</div></div></div>;

  return (
    <div className="market-shell">
      {selectedMarket ? (
        <div style={{ maxWidth: 1180, margin: '0 auto' }}>
          <button onClick={() => setSelectedMarket(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: NO_C, fontSize: 13, fontWeight: 600, marginBottom: 14 }}>← Back</button>
          <HeroPanel market={selectedMarket} index={0} total={1} onPrev={() => setSelectedMarket(null)} onNext={() => setSelectedMarket(null)} prevName="" nextName="" bookmarked={bookmarks.has(selectedMarket.id)} onBookmark={() => toggleBM(selectedMarket.id)} onShare={() => share(selectedMarket)} lastUpdated={lastUpdated} />
        </div>
      ) : (
        <>
          {hm.length > 0 && <HeroPanel market={hm[sI]} index={sI} total={hL} onPrev={() => setHeroIdx(pI)} onNext={() => setHeroIdx(nI)} prevName={hm[pI]?.question || ''} nextName={hm[nI]?.question || ''} bookmarked={bookmarks.has(hm[sI]?.id)} onBookmark={() => toggleBM(hm[sI]?.id)} onShare={() => share(hm[sI])} lastUpdated={lastUpdated} />}
          <div className="control-bar" style={{ marginTop: 16 }}>
            <div className="filter-row">{CATEGORIES.map(c => <button key={c.id} className={`filter-chip ${activeCategory === c.id ? 'filter-chip-active' : ''}`} onClick={() => setActiveCategory(c.id)}>{c.label}</button>)}</div>
            <div style={{ position: 'relative', flex: '0 1 380px' }}><input value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder="Search events..." style={{ width: '100%', padding: '10px 14px 10px 34px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)', background: 'var(--bg-card)', fontSize: 13, color: 'var(--text-primary)', outline: 'none' }} /><span style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', fontSize: 13 }}>⌕</span></div>
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
