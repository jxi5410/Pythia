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

// ================================================================
// Helpers
// ================================================================
function fmtCurrency(v: number): string {
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `$${Math.round(v / 1e3).toLocaleString()}K`;
  return `$${v}`;
}

function fmtDaysLeft(d: string): string {
  const days = Math.max(0, Math.ceil((new Date(d).getTime() - Date.now()) / 86400000));
  if (days === 0) return 'Ends today';
  if (days === 1) return '1 day left';
  return `${days}d left`;
}

function changePp(curr: number, prev: number): number {
  return (curr - prev) * 100;
}

// ================================================================
// Hero Panel — Kalshi-style, FIXED HEIGHT, no auto-rotate
// ================================================================
const HERO_HEIGHT = 420;

function HeroPanel({ market, index, total, onPrev, onNext }: {
  market: MarketData; index: number; total: number;
  onPrev: () => void; onNext: () => void;
}) {
  const change = changePp(market.probability, market.previousProbability);
  const pos = change >= 0;
  const paysYes = market.probability > 0.01 ? (1 / market.probability).toFixed(2) : '—';
  const paysNo = market.probability < 0.99 ? (1 / (1 - market.probability)).toFixed(2) : '—';

  return (
    <div className="hero-panel" style={{
      flexDirection: 'row', padding: 0, overflow: 'hidden',
      height: HERO_HEIGHT, minHeight: HERO_HEIGHT, maxHeight: HERO_HEIGHT,
    }}>
      {/* Left — market info (fixed width) */}
      <div style={{
        flex: '0 0 380px', padding: '24px 24px 20px', display: 'flex',
        flexDirection: 'column', justifyContent: 'space-between',
        borderRight: '1px solid var(--border-subtle)', overflow: 'hidden',
      }}>
        <div>
          <div style={{
            fontSize: 22, fontWeight: 700, letterSpacing: '-0.03em',
            lineHeight: 1.15, color: 'var(--text-primary)', marginBottom: 16,
            display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
          }}>
            {market.question}
          </div>

          {/* Yes / No pricing table */}
          <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 12 }}>
            <thead>
              <tr style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                <td style={{ padding: '0 0 6px' }}>Market</td>
                <td style={{ padding: '0 0 6px', textAlign: 'right' }}>Pays out</td>
                <td style={{ padding: '0 0 6px', textAlign: 'right' }}>Odds</td>
              </tr>
            </thead>
            <tbody style={{ fontSize: 14, fontWeight: 600 }}>
              <tr>
                <td style={{ padding: '7px 0', borderTop: '1px solid var(--border-subtle)' }}>
                  <span style={{ color: 'var(--positive)' }}>Yes</span>
                  <div style={{ height: 3, width: `${market.probability * 100}%`, maxWidth: '100%', background: 'var(--positive)', borderRadius: 2, marginTop: 3 }} />
                </td>
                <td style={{ padding: '7px 0', textAlign: 'right', borderTop: '1px solid var(--border-subtle)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>{paysYes}x</td>
                <td style={{ padding: '7px 0', textAlign: 'right', borderTop: '1px solid var(--border-subtle)' }}>
                  <span style={{ border: '1.5px solid var(--positive)', borderRadius: 6, padding: '3px 10px', fontFamily: 'var(--font-mono)', fontSize: 13 }}>
                    {(market.probability * 100).toFixed(0)}%
                  </span>
                </td>
              </tr>
              <tr>
                <td style={{ padding: '7px 0', borderTop: '1px solid var(--border-subtle)' }}>
                  <span style={{ color: 'var(--accent)' }}>No</span>
                  <div style={{ height: 3, width: `${(1 - market.probability) * 100}%`, maxWidth: '100%', background: 'var(--accent)', borderRadius: 2, marginTop: 3 }} />
                </td>
                <td style={{ padding: '7px 0', textAlign: 'right', borderTop: '1px solid var(--border-subtle)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>{paysNo}x</td>
                <td style={{ padding: '7px 0', textAlign: 'right', borderTop: '1px solid var(--border-subtle)' }}>
                  <span style={{ border: '1.5px solid var(--border-default)', borderRadius: 6, padding: '3px 10px', fontFamily: 'var(--font-mono)', fontSize: 13 }}>
                    {((1 - market.probability) * 100).toFixed(0)}%
                  </span>
                </td>
              </tr>
            </tbody>
          </table>

          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
            {fmtCurrency(market.volume24h)} vol · {fmtDaysLeft(market.endDate)}
          </div>

          {/* Signal badge */}
          {market.signal && (
            <div style={{ padding: '8px 12px', background: 'var(--info-muted)', border: '1px solid rgba(37,99,235,0.15)', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--info)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>
                ⚡ Signal — {market.signal.severity?.toUpperCase()}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                {market.signal.confluenceLayers}/{market.signal.totalLayers} layers · {market.signal.edgeWindow} edge
              </div>
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <span className="venue-chip">{market.source}</span>
          {market.tags.slice(0, 2).map(t => <span key={t} className="layer-tag">{t}</span>)}
        </div>
      </div>

      {/* Right — full chart */}
      <div style={{ flex: 1, padding: '16px 24px 16px 16px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', overflow: 'hidden' }}>
        {/* Top: carousel nav + current price */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4, flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{fmtDaysLeft(market.endDate)}</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
              {(market.probability * 100).toFixed(0)}%
            </span>
            <span className={`price-move ${pos ? 'price-up' : 'price-down'}`} style={{ fontSize: 12 }}>
              {pos ? '+' : ''}{change.toFixed(1)}pp
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{index + 1} of {total}</span>
            <button onClick={onPrev} style={{
              width: 30, height: 30, borderRadius: '50%', border: '1px solid var(--border-default)',
              background: 'var(--bg-card)', cursor: 'pointer', fontSize: 14, color: 'var(--text-secondary)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>‹</button>
            <button onClick={onNext} style={{
              width: 30, height: 30, borderRadius: '50%', border: '1.5px solid var(--accent)',
              background: 'var(--bg-card)', cursor: 'pointer', fontSize: 14, color: 'var(--accent)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>›</button>
          </div>
        </div>

        {/* Chart area — fills remaining space */}
        <div style={{ flex: 1, minHeight: 0 }}>
          <SpikeChart
            data={market.probabilityHistory}
            height={310}
            width={680}
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

  // NO auto-rotate — user clicks arrows only
  const heroMarkets = markets.filter(m => m.trending || m.signal);

  const filtered = markets.filter(m => {
    if (activeCategory !== 'all' && m.category !== activeCategory) return false;
    if (searchQuery && !m.question.toLowerCase().includes(searchQuery.toLowerCase())) return false;
    return true;
  });

  const categories = [...new Set(filtered.map(m => m.category))];

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
            market={selectedMarket}
            index={0} total={1}
            onPrev={() => setSelectedMarket(null)}
            onNext={() => setSelectedMarket(null)}
          />
        </div>
      )}

      {/* Landing */}
      {!selectedMarket && (
        <>
          {/* Hero — manual carousel only */}
          {heroMarkets.length > 0 && (
            <HeroPanel
              market={heroMarkets[heroIdx % heroMarkets.length]}
              index={heroIdx % heroMarkets.length}
              total={heroMarkets.length}
              onPrev={() => setHeroIdx(i => (i - 1 + heroMarkets.length) % heroMarkets.length)}
              onNext={() => setHeroIdx(i => (i + 1) % heroMarkets.length)}
            />
          )}

          {/* Category tabs + search */}
          <div className="control-bar">
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

          {/* Market cards */}
          {activeCategory === 'all' ? (
            categories.map(cat => {
              const catMarkets = filtered.filter(m => m.category === cat);
              if (!catMarkets.length) return null;
              const catLabel = CATEGORIES.find(c => c.id === cat)?.label || cat.charAt(0).toUpperCase() + cat.slice(1);
              return (
                <div key={cat} style={{ maxWidth: 1180, margin: '0 auto 28px' }}>
                  <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: '-0.03em', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
                    {catLabel}
                    <span style={{ fontSize: 13, color: 'var(--text-muted)', fontWeight: 500 }}>›</span>
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
