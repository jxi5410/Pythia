'use client';

import { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useRunStore, C, mono, serif } from '@/lib/run-store';
import type { MarketResult, PricePoint, Spike } from '@/lib/run-store';
import { detectSpikes, computeThreshold } from '@/lib/spike-detection';

function MiniChart({ prices, spikes, selectedSpike, onSpikeClick }: {
  prices: PricePoint[]; spikes: Spike[];
  selectedSpike: Spike | null; onSpikeClick: (s: Spike) => void;
}) {
  const width = 860, height = 200;
  const pad = { t: 20, r: 48, b: 28, l: 10 };
  if (prices.length < 2) return null;
  const allP = prices.map(p => p.price);
  const pMin = Math.min(...allP), pMax = Math.max(...allP);
  const pRange = pMax - pMin || 0.01;
  const sx = (i: number) => pad.l + (i / (prices.length - 1)) * (width - pad.l - pad.r);
  const sy = (v: number) => pad.t + (height - pad.t - pad.b) - ((v - pMin) / pRange) * (height - pad.t - pad.b);
  const path = prices.map((p, i) => `${i === 0 ? 'M' : 'L'}${sx(i).toFixed(1)},${sy(p.price).toFixed(1)}`).join(' ');
  const area = path + ` L${sx(prices.length - 1).toFixed(1)},${height - pad.b} L${pad.l},${height - pad.b} Z`;
  const yTicks = Array.from({ length: 5 }, (_, i) => pMin + (pRange * i) / 4);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display: 'block' }}>
      {yTicks.map((v, i) => (<g key={i}><line x1={pad.l} y1={sy(v)} x2={width - pad.r} y2={sy(v)} stroke={C.border} strokeWidth={0.5} /><text x={width - pad.r + 6} y={sy(v) + 3} fontSize={10} fontFamily={mono} fill={C.muted}>{(v * 100).toFixed(0)}¢</text></g>))}
      <path d={area} fill={C.accent + '0a'} /><path d={path} fill="none" stroke={C.dark} strokeWidth={1.5} />
      {spikes.map((s, i) => { const sp = prices[s.index]; if (!sp) return null; const sxv = sx(s.index), syv = sy(sp.price); const isSel = selectedSpike?.index === s.index;
        return (<g key={i} onClick={() => onSpikeClick(s)} style={{ cursor: 'pointer' }}><circle cx={sxv} cy={syv} r={isSel ? 16 : 12} fill={isSel ? C.accent : 'transparent'} opacity={isSel ? 0.12 : 0} /><circle cx={sxv} cy={syv} r={isSel ? 7 : 5} fill={s.direction === 'up' ? C.accent : C.info} stroke={isSel ? C.dark : 'none'} strokeWidth={isSel ? 2 : 0} opacity={0.9} /><text x={sxv} y={syv - 12} textAnchor="middle" fontSize={10} fontFamily={mono} fontWeight={700} fill={s.direction === 'up' ? C.accent : C.info}>{s.direction === 'up' ? '+' : '-'}{(s.magnitude * 100).toFixed(1)}%</text></g>); })}
      <text x={pad.l} y={height - 6} fontSize={10} fontFamily={mono} fill={C.muted}>{new Date(prices[0]?.t).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</text>
      <text x={width - pad.r} y={height - 6} textAnchor="end" fontSize={10} fontFamily={mono} fill={C.muted}>{new Date(prices[prices.length - 1]?.t).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</text>
    </svg>
  );
}

type Phase = 'idle' | 'searching' | 'pick-market' | 'loading-chart' | 'chart';

export default function MarketPage() {
  const router = useRouter();
  const { run, setRun } = useRunStore();
  const [phase, setPhase] = useState<Phase>(run.selectedMarket ? 'chart' : 'idle');
  const [input, setInput] = useState('');
  const [error, setError] = useState('');
  const [localResults, setLocalResults] = useState<MarketResult[]>(run.searchResults);
  const [localMarket, setLocalMarket] = useState<MarketResult | null>(run.selectedMarket);
  const [localPrices, setLocalPrices] = useState<PricePoint[]>(run.prices);
  const [localSpikes, setLocalSpikes] = useState<Spike[]>(run.spikes);
  const [localSelectedSpike, setLocalSelectedSpike] = useState<Spike | null>(null);

  const extractSlug = (url: string): string | null => { const m = url.match(/polymarket\.com\/(?:event|market)\/([a-z0-9-]+)/i); return m ? m[1] : null; };

  const handleAnalyze = useCallback(async () => {
    if (!input.trim()) return;
    setPhase('searching'); setError(''); setLocalResults([]); setLocalMarket(null); setLocalPrices([]); setLocalSpikes([]);
    try {
      const slug = extractSlug(input);
      const params = slug ? `slug=${encodeURIComponent(slug)}` : `q=${encodeURIComponent(input.trim())}`;
      const res = await fetch(`/api/markets/search?${params}`);
      const data = await res.json();
      if (!data.markets?.length) { setError('No markets found.'); setPhase('idle'); return; }
      if (data.markets.length === 1) { await loadChart(data.markets[0]); setLocalResults(data.markets); }
      else { setLocalResults(data.markets); setPhase('pick-market'); }
    } catch (err: any) { setError(`Search failed: ${err.message}`); setPhase('idle'); }
  }, [input]);

  const loadChart = useCallback(async (market: MarketResult) => {
    setLocalMarket(market); setPhase('loading-chart');
    try {
      let res: Response;
      if (market.exchange === 'kalshi') {
        if (!market.kalshiTicker || !market.kalshiSeriesTicker) { setError('Missing Kalshi ticker'); setPhase('idle'); return; }
        res = await fetch(`/api/markets/history?exchange=kalshi&ticker=${encodeURIComponent(market.kalshiTicker)}&series_ticker=${encodeURIComponent(market.kalshiSeriesTicker)}&interval=max&fidelity=60`);
      } else {
        const tokenId = market.clobTokenIds?.[0];
        if (!tokenId) { setError('No CLOB token ID'); setPhase('idle'); return; }
        res = await fetch(`/api/markets/history?exchange=polymarket&tokenId=${encodeURIComponent(tokenId)}&interval=max&fidelity=60`);
      }
      const data = await res.json();
      if (!data.history?.length) { setError('No price history.'); setPhase('idle'); return; }
      const prices = data.history; const threshold = computeThreshold(prices); const spikes = detectSpikes(prices, threshold);
      setLocalPrices(prices); setLocalSpikes(spikes); setPhase('chart');
    } catch (err: any) { setError(`Failed: ${err.message}`); setPhase('idle'); }
  }, []);

  const handleSpikeClick = useCallback((spike: Spike) => {
    setLocalSelectedSpike(spike);
    setRun({ searchResults: localResults, selectedMarket: localMarket, prices: localPrices, spikes: localSpikes, selectedSpike: spike, currentStage: 'attribution', completedStages: new Set(['market']) });
    router.push('/attribution');
  }, [localResults, localMarket, localPrices, localSpikes, setRun, router]);

  const currentPrice = localMarket?.outcomePrices?.[0] ? `${(parseFloat(localMarket.outcomePrices[0]) * 100).toFixed(1)}¢` : null;

  return (
    <div style={{ minHeight: 'calc(100vh - 90px)', background: C.bg, fontFamily: serif, color: C.dark }}>
      <div style={{ maxWidth: 900, margin: '0 auto', padding: '40px 24px' }}>
        <div style={{ marginBottom: 32 }}>
          <div style={{ fontSize: 13, color: C.muted, marginBottom: 12, fontFamily: mono }}>Search Polymarket + Kalshi by keyword or paste a URL</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <input type="text" value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleAnalyze()}
              placeholder="iran hormuz, trump tariff, bitcoin ETF, fed rate"
              style={{ flex: 1, padding: '12px 16px', border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 15, fontFamily: serif, background: C.surface, color: C.dark, outline: 'none' }} />
            <button onClick={handleAnalyze} disabled={!input.trim() || phase === 'searching'}
              style={{ padding: '12px 28px', borderRadius: 6, border: 'none', background: C.dark, color: C.bg, fontSize: 14, fontWeight: 600, cursor: 'pointer', fontFamily: mono, opacity: !input.trim() ? 0.4 : 1 }}>
              {phase === 'searching' ? 'Searching…' : 'Analyze'}
            </button>
          </div>
          {error && <div style={{ marginTop: 8, fontSize: 13, color: C.accent }}>{error}</div>}
        </div>

        {phase === 'searching' && (<div style={{ textAlign: 'center' as const, padding: 60, color: C.muted }}><div style={{ width: 24, height: 24, border: `2px solid ${C.border}`, borderTopColor: C.accent, borderRadius: '50%', animation: 'spin 0.8s linear infinite', margin: '0 auto 16px' }} /><style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>Searching Polymarket + Kalshi…</div>)}

        {phase === 'pick-market' && localResults.length > 0 && (<div>
          <div style={{ fontFamily: mono, fontSize: 11, fontWeight: 600, textTransform: 'uppercase' as const, letterSpacing: 1, color: C.muted, marginBottom: 12 }}>{localResults.length} markets found — select one</div>
          {localResults.map((m, i) => { const sc = m.spikeCount; const hasSpikes = sc !== undefined && sc > 0; const noSpikes = sc === 0;
            return (<div key={i} onClick={() => loadChart(m)} style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 6, padding: '14px 18px', marginBottom: 8, cursor: 'pointer', transition: 'border-color 0.2s', opacity: noSpikes ? 0.55 : 1 }}
              onMouseEnter={(e) => (e.currentTarget.style.borderColor = C.accent)} onMouseLeave={(e) => (e.currentTarget.style.borderColor = C.border)}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                <span style={{ fontFamily: mono, fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: m.exchange === 'kalshi' ? '#eef3ff' : '#f0f5ee', color: m.exchange === 'kalshi' ? '#4a6fa5' : '#5a7a4a', border: `1px solid ${m.exchange === 'kalshi' ? '#c0d0e8' : '#c8dcc0'}`, flexShrink: 0, textTransform: 'uppercase' as const, letterSpacing: 0.5 }}>{m.exchange === 'kalshi' ? 'K' : 'PM'}</span>
                <span style={{ fontSize: 15, fontWeight: 600, flex: 1 }}>{m.question}</span>
                {hasSpikes && <span style={{ fontFamily: mono, fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 10, background: C.accent, color: '#fff', flexShrink: 0 }}>{sc} spike{sc !== 1 ? 's' : ''}</span>}
              </div>
              <div style={{ fontFamily: mono, fontSize: 11, color: C.muted }}>Yes: {(parseFloat(m.outcomePrices?.[0] || '0') * 100).toFixed(1)}¢ · Vol 24h: ${(m.volume24hr / 1000).toFixed(0)}K</div>
            </div>); })}
        </div>)}

        {phase === 'loading-chart' && (<div style={{ textAlign: 'center' as const, padding: 60, color: C.muted }}><div style={{ width: 24, height: 24, border: `2px solid ${C.border}`, borderTopColor: C.accent, borderRadius: '50%', animation: 'spin 0.8s linear infinite', margin: '0 auto 16px' }} />Fetching price history…</div>)}

        {phase === 'chart' && localMarket && (<div>
          {localResults.length > 1 && (<button onClick={() => { setPhase('pick-market'); setLocalMarket(null); setLocalPrices([]); setLocalSpikes([]); }} style={{ fontFamily: mono, fontSize: 11, color: C.info, background: 'none', border: 'none', cursor: 'pointer', padding: '0 0 12px', display: 'flex', alignItems: 'center', gap: 4 }}>← Back to results ({localResults.length})</button>)}
          <div style={{ fontFamily: serif, fontSize: 24, fontWeight: 700, marginBottom: 4 }}>{localMarket.question}</div>
          <div style={{ fontFamily: mono, fontSize: 11, color: C.muted, marginBottom: 20 }}>
            {currentPrice && <span style={{ color: C.dark, fontWeight: 600 }}>{currentPrice} Yes</span>}
            {' · '}{localPrices.length} pts · {localSpikes.length} spike{localSpikes.length !== 1 ? 's' : ''}
            {' · '}Vol: ${(localMarket.volume24hr / 1000).toFixed(0)}K
            {localMarket.exchange === 'kalshi' ? <span style={{ color: '#4a6fa5', marginLeft: 8 }}>● Kalshi</span> : <span style={{ color: C.yes, marginLeft: 8 }}>● Polymarket</span>}
          </div>
          <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: '16px 12px', marginBottom: 24 }}>
            <MiniChart prices={localPrices} spikes={localSpikes} selectedSpike={localSelectedSpike} onSpikeClick={handleSpikeClick} />
            {localSpikes.length === 0 && <div style={{ textAlign: 'center' as const, padding: '12px 0', fontFamily: mono, fontSize: 12, color: C.muted }}>No significant spikes detected</div>}
          </div>
          {localSpikes.length > 0 && <div style={{ fontFamily: mono, fontSize: 12, color: C.muted, textAlign: 'center' as const, padding: '8px 0' }}>Click any spike dot to run BACE attribution →</div>}
        </div>)}

        {phase === 'idle' && !error && (<div style={{ textAlign: 'center' as const, padding: '80px 0', color: C.muted }}>
          <div style={{ fontSize: 48, marginBottom: 16, opacity: 0.3 }}>⚡</div>
          <div style={{ fontFamily: serif, fontSize: 20, fontWeight: 600, color: C.dark, marginBottom: 8 }}>Why did this spike happen?</div>
          <div style={{ fontSize: 14, maxWidth: 440, margin: '0 auto', lineHeight: 1.6 }}>Search Polymarket or Kalshi by keyword or paste a URL. Pythia fetches real price history, detects spikes, and attributes their causes using multi-agent causal reasoning.</div>
        </div>)}
      </div>
    </div>
  );
}
