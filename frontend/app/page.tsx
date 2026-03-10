'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import SpikeChart from '@/components/SpikeChart';
import type { Market, Spike, Attributor, ForwardSignal, Narrative } from '@/types';
import { MARKET_CATEGORIES } from '@/types';

// ================================================================
// API helpers
// ================================================================
const API = '/api/v1';

async function fetchJson<T>(url: string): Promise<T | null> {
  try { const r = await fetch(url); return r.ok ? r.json() : null; } catch { return null; }
}

// ================================================================
// Mock data for demo (replace with live API once backend serves markets)
// ================================================================
function generateMockMarkets(): Market[] {
  const markets: Market[] = [
    { id: 'fed-rate-cut-june', question: 'Will the Fed cut rates by June 2026?', category: 'economics', probability: 0.42, previousProbability: 0.38, volume24h: 890000, totalVolume: 15600000, liquidity: 4200000, endDate: '2026-06-30', source: 'polymarket', sourceUrl: '', trending: true, tags: ['macro', 'fed'], probabilityHistory: [0.35, 0.37, 0.38, 0.42, 0.40, 0.38, 0.42], dataSource: 'mock' },
    { id: 'iran-war-march', question: 'Will Iran conflict escalate before April 2026?', category: 'geopolitical', probability: 0.23, previousProbability: 0.18, volume24h: 560000, totalVolume: 8900000, liquidity: 1800000, endDate: '2026-04-01', source: 'polymarket', sourceUrl: '', trending: true, tags: ['geopolitical', 'conflict'], probabilityHistory: [0.12, 0.15, 0.18, 0.23, 0.20, 0.18, 0.23], dataSource: 'mock' },
    { id: 'btc-150k-march', question: 'Bitcoin above $150K in March?', category: 'crypto', probability: 0.08, previousProbability: 0.12, volume24h: 340000, totalVolume: 5200000, liquidity: 890000, endDate: '2026-03-31', source: 'polymarket', sourceUrl: '', trending: false, tags: ['crypto', 'bitcoin'], probabilityHistory: [0.15, 0.12, 0.10, 0.08, 0.09, 0.12, 0.08], dataSource: 'mock' },
    { id: 'trump-greenland', question: 'Will Trump acquire Greenland before 2027?', category: 'politics', probability: 0.11, previousProbability: 0.09, volume24h: 210000, totalVolume: 3100000, liquidity: 620000, endDate: '2027-01-01', source: 'polymarket', sourceUrl: '', trending: false, tags: ['politics', 'us'], probabilityHistory: [0.08, 0.09, 0.10, 0.11, 0.10, 0.09, 0.11], dataSource: 'mock' },
    { id: 'russia-ukraine-ceasefire', question: 'Russia-Ukraine ceasefire by end of 2026?', category: 'geopolitical', probability: 0.40, previousProbability: 0.35, volume24h: 420000, totalVolume: 7200000, liquidity: 1200000, endDate: '2026-12-31', source: 'polymarket', sourceUrl: '', trending: true, tags: ['geopolitical', 'conflict'], probabilityHistory: [0.30, 0.32, 0.35, 0.40, 0.38, 0.35, 0.40], dataSource: 'mock' },
    { id: 'aliens-2027', question: 'Will the US confirm aliens exist before 2027?', category: 'politics', probability: 0.18, previousProbability: 0.14, volume24h: 180000, totalVolume: 4500000, liquidity: 950000, endDate: '2027-01-01', source: 'polymarket', sourceUrl: '', trending: true, tags: ['politics', 'us'], probabilityHistory: [0.10, 0.12, 0.14, 0.18, 0.16, 0.14, 0.18], dataSource: 'mock' },
    { id: 'newsom-2028', question: 'Will Gavin Newsom win the 2028 Democratic nomination?', category: 'politics', probability: 0.25, previousProbability: 0.22, volume24h: 150000, totalVolume: 2800000, liquidity: 520000, endDate: '2028-08-31', source: 'polymarket', sourceUrl: '', trending: false, tags: ['politics', 'election'], probabilityHistory: [0.20, 0.21, 0.22, 0.25, 0.23, 0.22, 0.25], dataSource: 'mock' },
    { id: 'colorado-stanley', question: 'Will Colorado Avalanche win 2026 Stanley Cup?', category: 'sports', probability: 0.25, previousProbability: 0.22, volume24h: 95000, totalVolume: 1200000, liquidity: 380000, endDate: '2026-06-30', source: 'polymarket', sourceUrl: '', trending: false, tags: ['sports', 'nhl'], probabilityHistory: [0.18, 0.20, 0.22, 0.25, 0.24, 0.22, 0.25], dataSource: 'mock' },
  ];
  return markets.sort((a, b) => b.liquidity - a.liquidity);
}

// ================================================================
// Sub-components
// ================================================================

function MiniChart({ data, positive }: { data: number[]; positive: boolean }) {
  if (!data || data.length < 2) return null;
  const h = 48, w = 120;
  const mn = Math.min(...data), mx = Math.max(...data);
  const range = mx - mn || 0.01;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - mn) / range) * h}`);
  const color = positive ? 'var(--positive)' : 'var(--negative)';
  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: '100%', height: h }}>
      <path d={`M${pts.join('L')}L${w},${h}L0,${h}Z`} fill={color} fillOpacity={0.06} />
      <polyline points={pts.join(' ')} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  );
}

function HeroCarousel({ markets, onSelect }: { markets: Market[]; onSelect: (m: Market) => void }) {
  const [idx, setIdx] = useState(0);
  const featured = markets.filter(m => m.trending).slice(0, 6);

  useEffect(() => {
    if (featured.length <= 1) return;
    const timer = setInterval(() => setIdx(i => (i + 1) % featured.length), 5000);
    return () => clearInterval(timer);
  }, [featured.length]);

  if (!featured.length) return null;
  const m = featured[idx];
  const change = ((m.probability - m.previousProbability) * 100);
  const positive = change >= 0;

  return (
    <div className="hero-panel" style={{ flexDirection: 'column', alignItems: 'stretch', cursor: 'pointer' }} onClick={() => onSelect(m)}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 20 }}>
        <div style={{ flex: 1 }}>
          <div className="hero-kicker">Featured Market</div>
          <div style={{ fontSize: 'clamp(1.4rem, 3.5vw, 2.2rem)', lineHeight: 1.1, letterSpacing: '-0.04em', fontWeight: 700, color: 'var(--text-primary)' }}>
            {m.question}
          </div>
          <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
            <span className="venue-chip">{m.source}</span>
            <span className="venue-chip">{m.category}</span>
            {m.dataSource === 'mock' && <span className="venue-chip" style={{ color: 'var(--warning)' }}>Demo</span>}
          </div>
        </div>
        <div style={{ textAlign: 'right', minWidth: 140 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 42, fontWeight: 700, letterSpacing: '-0.04em', color: 'var(--text-primary)' }}>
            {(m.probability * 100).toFixed(0)}%
          </div>
          <div className={`price-move ${positive ? 'price-up' : 'price-down'}`} style={{ fontSize: 14 }}>
            {positive ? '+' : ''}{change.toFixed(1)}pp
          </div>
          <div style={{ marginTop: 8 }}><MiniChart data={m.probabilityHistory} positive={positive} /></div>
        </div>
      </div>

      {/* Carousel dots */}
      <div style={{ display: 'flex', justifyContent: 'center', gap: 6, marginTop: 14 }}>
        {featured.map((_, i) => (
          <button key={i} onClick={(e) => { e.stopPropagation(); setIdx(i); }}
            style={{ width: i === idx ? 20 : 6, height: 6, borderRadius: 3, border: 'none', cursor: 'pointer',
              background: i === idx ? 'var(--accent)' : 'var(--border-default)', transition: 'all 0.3s ease' }} />
        ))}
      </div>
    </div>
  );
}

function MarketCard({ market, onClick }: { market: Market; onClick: () => void }) {
  const change = (market.probability - market.previousProbability) * 100;
  const positive = change >= 0;
  return (
    <div className="exchange-card" onClick={onClick} style={{ cursor: 'pointer' }}>
      <div className="exchange-card-header">
        <div style={{ display: 'flex', gap: 6 }}>
          <span className="venue-chip">{market.source}</span>
          {market.trending && <span className="signal-chip"><span className="signal-chip-dot" />Active</span>}
        </div>
      </div>
      <div style={{ fontSize: 16, fontWeight: 650, letterSpacing: '-0.02em', lineHeight: 1.25, minHeight: 44, marginBottom: 10, color: 'var(--text-primary)' }}>
        {market.question}
      </div>
      <div className="chart-shell">
        <MiniChart data={market.probabilityHistory} positive={positive} />
        <div className="chart-meta-row" style={{ marginTop: 4 }}>
          <span className="meta-mono">${(market.volume24h / 1000).toFixed(0)}K vol</span>
          <span className={`price-move ${positive ? 'price-up' : 'price-down'}`}>{positive ? '+' : ''}{change.toFixed(1)}pp</span>
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
        <span className="layer-tag">${(market.liquidity / 1e6).toFixed(1)}M liq</span>
        {market.tags.slice(0, 2).map(t => <span key={t} className="layer-tag">{t}</span>)}
      </div>
    </div>
  );
}

function AttributorModal({ attributor, onClose, onSave }: { attributor: Attributor; onClose: () => void; onSave: (a: Attributor) => void }) {
  const [signals, setSignals] = useState<ForwardSignal[]>([]);
  useEffect(() => {
    fetchJson<ForwardSignal[]>(`${API}/signals/forward?min_confidence=0`).then(d => setSignals(d || []));
  }, []);

  const relevantSignals = signals.filter(s => s.attributor_id === attributor.id);

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClose}>
      <div style={{ background: 'var(--bg-card)', borderRadius: 'var(--radius-xl)', padding: 28, maxWidth: 560, width: '90%', maxHeight: '80vh', overflow: 'auto', boxShadow: 'var(--shadow-lg)' }}
        onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text-primary)' }}>{attributor.name}</div>
            <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
              <span className={`severity-badge severity-badge-${attributor.confidence === 'HIGH' ? 'critical' : attributor.confidence === 'MEDIUM' ? 'high' : 'low'}`}>{attributor.confidence}</span>
              <span className="layer-tag">{attributor.category}</span>
              <span className="layer-tag">{attributor.status}</span>
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--text-muted)' }}>✕</button>
        </div>

        {/* Causal chain */}
        {attributor.causal_chain && (
          <div className="section-card" style={{ marginBottom: 14 }}>
            <div className="data-label" style={{ marginBottom: 6 }}>Causal Chain</div>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{attributor.causal_chain}</div>
          </div>
        )}

        {/* Stats */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 14 }}>
          <div className="metric-cell"><div className="data-label">Spikes</div><div className="data-value">{attributor.spike_count}</div></div>
          <div className="metric-cell"><div className="data-label">Avg Move</div><div className="data-value">{(attributor.avg_magnitude * 100).toFixed(1)}%</div></div>
          <div className="metric-cell"><div className="data-label">Confidence</div><div className="data-value">{((attributor.confidence_score || 0) * 100).toFixed(0)}%</div></div>
        </div>

        {/* Forward signals from this attributor */}
        {relevantSignals.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <div className="data-label" style={{ marginBottom: 8 }}>Forward Signals</div>
            {relevantSignals.slice(0, 5).map(s => (
              <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 12 }}>
                <span style={{ color: s.predicted_direction === 'up' ? 'var(--positive)' : 'var(--negative)', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                  {s.predicted_direction === 'up' ? '▲' : '▼'} {(s.predicted_magnitude * 100).toFixed(1)}%
                </span>
                <span style={{ color: 'var(--text-secondary)', flex: 1 }}>{s.target_market_title?.slice(0, 40)}</span>
                <span style={{ color: 'var(--text-muted)' }}>~{s.predicted_lag_hours}h</span>
                <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{(s.confidence_score * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn-primary" onClick={() => onSave(attributor)}>
            ★ Save to Narratives
          </button>
          <button className="btn-primary" style={{ background: 'var(--bg-primary)', color: 'var(--text-primary)', border: '1px solid var(--border-default)' }}
            onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

function SearchBar({ onSearch }: { onSearch: (q: string) => void }) {
  const [query, setQuery] = useState('');
  return (
    <div style={{ position: 'relative', flex: 1, maxWidth: 420 }}>
      <input value={query}
        onChange={e => { setQuery(e.target.value); onSearch(e.target.value); }}
        placeholder='Search events... e.g. "Will Iran war end by March 2026"'
        style={{
          width: '100%', padding: '10px 14px 10px 36px', borderRadius: 'var(--radius-md)',
          border: '1px solid var(--border-subtle)', background: 'var(--bg-card)', fontSize: 13,
          color: 'var(--text-primary)', outline: 'none',
        }}
      />
      <span style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', fontSize: 14 }}>⌕</span>
    </div>
  );
}

function PreferencesPanel({ onClose }: { onClose: () => void }) {
  const [spikeThresh, setSpikeThresh] = useState(2);
  const [attrConf, setAttrConf] = useState(50);
  const [sigConf, setSigConf] = useState(40);

  const save = () => {
    fetch(`${API}/preferences/thresholds`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        spike_detection: spikeThresh / 100,
        attribution_confidence: attrConf / 100,
        forward_signal_confidence: sigConf / 100,
      }),
    });
    onClose();
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div style={{ background: 'var(--bg-card)', borderRadius: 'var(--radius-xl)', padding: 28, maxWidth: 400, width: '90%', boxShadow: 'var(--shadow-lg)' }} onClick={e => e.stopPropagation()}>
        <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 20, color: 'var(--text-primary)' }}>Preferences</div>

        <label style={{ display: 'block', marginBottom: 16 }}>
          <div className="data-label" style={{ marginBottom: 6 }}>Spike Detection Threshold: {spikeThresh}%</div>
          <input type="range" min={1} max={20} value={spikeThresh} onChange={e => setSpikeThresh(+e.target.value)}
            style={{ width: '100%' }} />
        </label>

        <label style={{ display: 'block', marginBottom: 16 }}>
          <div className="data-label" style={{ marginBottom: 6 }}>Attribution Confidence: {attrConf}%</div>
          <input type="range" min={10} max={95} value={attrConf} onChange={e => setAttrConf(+e.target.value)}
            style={{ width: '100%' }} />
        </label>

        <label style={{ display: 'block', marginBottom: 20 }}>
          <div className="data-label" style={{ marginBottom: 6 }}>Signal Confidence: {sigConf}%</div>
          <input type="range" min={10} max={95} value={sigConf} onChange={e => setSigConf(+e.target.value)}
            style={{ width: '100%' }} />
        </label>

        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn-primary" onClick={save}>Save</button>
          <button className="btn-primary" style={{ background: 'var(--bg-primary)', color: 'var(--text-primary)', border: '1px solid var(--border-default)' }} onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

function AuthGate({ onAuth }: { onAuth: () => void }) {
  const [email, setEmail] = useState('');
  const [mode, setMode] = useState<'login' | 'register'>('login');
  return (
    <div className="market-shell" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--bg-card)', borderRadius: 'var(--radius-xl)', padding: 36, maxWidth: 380, width: '90%', boxShadow: 'var(--shadow-lg)', textAlign: 'center' }}>
        <div style={{ fontSize: 28, fontWeight: 700, letterSpacing: '-0.04em', marginBottom: 4 }}>Pythia</div>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 24 }}>Narrative intelligence for prediction markets</div>
        <input value={email} onChange={e => setEmail(e.target.value)} placeholder="Email address"
          style={{ width: '100%', padding: '12px 14px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)', fontSize: 14, marginBottom: 10, boxSizing: 'border-box' }} />
        <input type="password" placeholder="Password"
          style={{ width: '100%', padding: '12px 14px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)', fontSize: 14, marginBottom: 16, boxSizing: 'border-box' }} />
        <button className="btn-primary" style={{ width: '100%', padding: '12px 20px' }} onClick={onAuth}>
          {mode === 'login' ? 'Sign In' : 'Create Account'}
        </button>
        <div style={{ marginTop: 14, fontSize: 12, color: 'var(--text-muted)' }}>
          {mode === 'login' ? (
            <>No account? <button style={{ color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12 }} onClick={() => setMode('register')}>Register</button></>
          ) : (
            <>Have an account? <button style={{ color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12 }} onClick={() => setMode('login')}>Sign in</button></>
          )}
        </div>
      </div>
    </div>
  );
}

// ================================================================
// Main page
// ================================================================

export default function Home() {
  const [authed, setAuthed] = useState(false);
  const [markets, setMarkets] = useState<Market[]>([]);
  const [narratives, setNarratives] = useState<Narrative[]>([]);
  const [activeCategory, setActiveCategory] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedMarket, setSelectedMarket] = useState<Market | null>(null);
  const [selectedAttributor, setSelectedAttributor] = useState<Attributor | null>(null);
  const [showPrefs, setShowPrefs] = useState(false);
  const [savedAttributors, setSavedAttributors] = useState<Attributor[]>([]);
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<'markets' | 'narratives' | 'watchlist'>('markets');

  useEffect(() => {
    // Check if user was previously authed
    if (typeof window !== 'undefined' && window.sessionStorage?.getItem('pythia_auth')) {
      setAuthed(true);
    }
  }, []);

  useEffect(() => {
    if (!authed) return;
    setMarkets(generateMockMarkets());
    fetchJson<Narrative[]>(`${API}/narratives`).then(d => { if (d) setNarratives(d); });
  }, [authed]);

  const handleAuth = () => {
    if (typeof window !== 'undefined') window.sessionStorage?.setItem('pythia_auth', '1');
    setAuthed(true);
  };

  const saveAttributor = (a: Attributor) => {
    setSavedAttributors(prev => prev.some(x => x.id === a.id) ? prev : [...prev, a]);
    setSelectedAttributor(null);
  };

  const toggleWatchlist = (marketId: string) => {
    setWatchlist(prev => prev.includes(marketId) ? prev.filter(x => x !== marketId) : [...prev, marketId]);
  };

  if (!authed) return <AuthGate onAuth={handleAuth} />;

  // Filtered markets
  const filtered = markets.filter(m => {
    if (activeCategory !== 'all' && m.category !== activeCategory) return false;
    if (searchQuery && !m.question.toLowerCase().includes(searchQuery.toLowerCase())) return false;
    return true;
  });

  const watchlistedMarkets = markets.filter(m => watchlist.includes(m.id));

  return (
    <div className="market-shell">
      {/* Top nav */}
      <div style={{ maxWidth: 1180, margin: '0 auto 18px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.04em' }}>Pythia</span>
          <span style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600 }}>Intelligence</span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {(['markets', 'narratives', 'watchlist'] as const).map(tab => (
            <button key={tab} className={`filter-chip ${activeTab === tab ? 'filter-chip-active' : ''}`}
              onClick={() => setActiveTab(tab)}>
              {tab === 'markets' ? '◉ Markets' : tab === 'narratives' ? '📡 Narratives' : `★ Watchlist (${watchlist.length})`}
            </button>
          ))}
          <button className="filter-chip" onClick={() => setShowPrefs(true)}>⚙</button>
        </div>
      </div>

      {/* ================ MARKETS TAB ================ */}
      {activeTab === 'markets' && (
        <>
          {/* Hero carousel */}
          {!selectedMarket && <HeroCarousel markets={markets} onSelect={setSelectedMarket} />}

          {/* Event detail view */}
          {selectedMarket && (
            <div style={{ maxWidth: 1180, margin: '0 auto 18px' }}>
              <button onClick={() => setSelectedMarket(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--accent)', fontSize: 13, fontWeight: 600, marginBottom: 14, display: 'flex', alignItems: 'center', gap: 4 }}>
                ← Back to markets
              </button>
              <div className="section-card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
                  <div>
                    <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.03em', color: 'var(--text-primary)' }}>{selectedMarket.question}</div>
                    <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                      <span className="venue-chip">{selectedMarket.source}</span>
                      <span className="venue-chip">{selectedMarket.category}</span>
                      <button className={`filter-chip ${watchlist.includes(selectedMarket.id) ? 'filter-chip-active' : ''}`}
                        style={{ fontSize: 11, padding: '5px 10px' }}
                        onClick={() => toggleWatchlist(selectedMarket.id)}>
                        {watchlist.includes(selectedMarket.id) ? '★ Saved' : '☆ Watch'}
                      </button>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 36, fontWeight: 700, color: 'var(--text-primary)' }}>
                      {(selectedMarket.probability * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>
                <SpikeChart marketId={selectedMarket.id}
                  onSpikeClick={(s) => { /* could open spike detail */ }}
                  onAttributorClick={setSelectedAttributor} />
              </div>
            </div>
          )}

          {/* Controls bar */}
          {!selectedMarket && (
            <>
              <div className="control-bar">
                <div className="filter-row">
                  {MARKET_CATEGORIES.map(c => (
                    <button key={c.id} className={`filter-chip ${activeCategory === c.id ? 'filter-chip-active' : ''}`}
                      onClick={() => setActiveCategory(c.id)}>
                      {c.icon} {c.label}
                    </button>
                  ))}
                </div>
                <SearchBar onSearch={setSearchQuery} />
              </div>

              {/* Market cards grid */}
              <div className="cards-grid">
                {filtered.map(m => (
                  <MarketCard key={m.id} market={m} onClick={() => setSelectedMarket(m)} />
                ))}
              </div>

              {filtered.length === 0 && (
                <div style={{ textAlign: 'center', padding: 60, color: 'var(--text-muted)' }}>
                  No markets match your search.
                </div>
              )}
            </>
          )}
        </>
      )}

      {/* ================ NARRATIVES TAB ================ */}
      {activeTab === 'narratives' && (
        <div style={{ maxWidth: 1180, margin: '0 auto' }}>
          <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: '-0.03em', marginBottom: 16 }}>📡 Narrative Monitoring</div>

          {/* Saved attributors */}
          {savedAttributors.length > 0 && (
            <div className="section-card" style={{ marginBottom: 16 }}>
              <div className="data-label" style={{ marginBottom: 10 }}>Saved Attributors</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {savedAttributors.map(a => (
                  <button key={a.id} className="layer-tag" onClick={() => setSelectedAttributor(a)} style={{ cursor: 'pointer' }}>
                    ★ {a.name?.slice(0, 30)} <span style={{ color: 'var(--text-muted)', marginLeft: 4 }}>{a.confidence}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* System narratives */}
          {narratives.length > 0 ? narratives.map(n => (
            <div key={n.id} className="exchange-card" style={{ marginBottom: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <div style={{ fontSize: 16, fontWeight: 650, color: 'var(--text-primary)' }}>{n.name}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>{n.description}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div className="data-value">{n.spike_count} spikes</div>
                  <div className="data-label">strength {n.strength?.toFixed(1)}</div>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
                <span className="layer-tag">{n.category}</span>
                <span className="layer-tag">{n.status}</span>
                <span className="layer-tag">{n.attributor_ids?.length || 0} attributors</span>
              </div>
            </div>
          )) : (
            <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>
              No active narratives yet. Save attributors from market analysis to build your narrative monitoring dashboard.
            </div>
          )}
        </div>
      )}

      {/* ================ WATCHLIST TAB ================ */}
      {activeTab === 'watchlist' && (
        <div style={{ maxWidth: 1180, margin: '0 auto' }}>
          <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: '-0.03em', marginBottom: 16 }}>★ Event Watchlist</div>
          {watchlistedMarkets.length > 0 ? (
            <div className="cards-grid">
              {watchlistedMarkets.map(m => (
                <MarketCard key={m.id} market={m} onClick={() => { setSelectedMarket(m); setActiveTab('markets'); }} />
              ))}
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>
              No events in watchlist. Click ☆ Watch on any market to add it here.
            </div>
          )}
        </div>
      )}

      {/* ================ MODALS ================ */}
      {selectedAttributor && (
        <AttributorModal attributor={selectedAttributor} onClose={() => setSelectedAttributor(null)} onSave={saveAttributor} />
      )}
      {showPrefs && <PreferencesPanel onClose={() => setShowPrefs(false)} />}
    </div>
  );
}
