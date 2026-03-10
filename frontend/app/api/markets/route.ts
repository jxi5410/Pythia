import { NextResponse } from 'next/server';

import { pmxtService } from '@/lib/pmxt';

export const runtime = 'nodejs';
const LIVE_MARKET_LIMIT = 80;
const OHLCV_ENRICH_LIMIT = 30;
const OHLCV_CONCURRENCY = 8;

// Generate realistic probability history — 200 points with random walk + clustered vol + spikes
function genHistory(current: number, previous: number, points: number = 200): number[] {
  const history: number[] = [];
  const startVal = previous - (current - previous) * 1.5;
  let val = Math.max(0.02, Math.min(0.98, startVal));
  let vol = 0.006; // base volatility

  // Place 2-3 spikes at random positions
  const spikePositions = new Set<number>();
  const numSpikes = 2 + Math.floor(Math.random() * 2);
  for (let s = 0; s < numSpikes; s++) {
    spikePositions.add(Math.floor(0.15 * points + Math.random() * 0.7 * points));
  }

  for (let i = 0; i < points; i++) {
    const progress = i / (points - 1);
    // Gentle drift toward current price
    const drift = (current - val) * 0.003;
    // Clustered volatility — vol changes slowly
    vol = vol * 0.97 + (0.003 + Math.random() * 0.008) * 0.03;
    // Random walk step
    let step = drift + (Math.random() - 0.5) * vol * 2;

    // Spike injection: sharp move over 3-6 points
    if (spikePositions.has(i)) {
      const spikeMag = (0.04 + Math.random() * 0.08) * (Math.random() > 0.5 ? 1 : -1);
      step += spikeMag / 4; // spread over a few points
      vol *= 2.5; // elevated vol after spike
    }
    // Post-spike elevated vol decays
    if (spikePositions.has(i - 1) || spikePositions.has(i - 2) || spikePositions.has(i - 3)) {
      step += (Math.random() - 0.5) * vol;
    }

    val = Math.max(0.01, Math.min(0.99, val + step));
    history.push(val);
  }
  // Pin last point to current
  history[points - 1] = current;
  // Smooth the last few points toward current
  for (let i = points - 5; i < points - 1; i++) {
    const blend = (i - (points - 5)) / 4;
    history[i] = history[i] * (1 - blend * 0.3) + current * (blend * 0.3);
  }
  return history;
}

// Generate realistic volume history — correlated with price moves (spikes = high volume)
function genVolumeHistory(priceHistory: number[], totalVolume: number, points?: number): number[] {
  const n = points || priceHistory.length;
  const vol: number[] = [];
  const avgVol = totalVolume / n;

  for (let i = 0; i < n; i++) {
    // Base volume with random variation
    let v = avgVol * (0.3 + Math.random() * 1.4);
    // Spike correlation: large price moves → volume spike
    if (i > 0 && priceHistory[i] !== undefined && priceHistory[i - 1] !== undefined) {
      const move = Math.abs(priceHistory[i] - priceHistory[i - 1]);
      if (move > 0.02) v *= 2.5 + Math.random() * 2;
      else if (move > 0.01) v *= 1.5 + Math.random();
    }
    vol.push(Math.round(v));
  }
  return vol;
}

// Mock signal data linked to specific markets
const marketSignals: Record<string, {
  id: string;
  timestamp: string;
  event: string;
  category: string;
  confluenceLayers: number;
  totalLayers: number;
  confidenceScore: number;
  historicalHitRate: number;
  assetImpact: { asset: string; expectedMove: string; correlation: number }[];
  edgeWindow: string;
  layersFired: string[];
  severity: 'critical' | 'high' | 'medium' | 'low';
  source: 'polymarket' | 'kalshi';
  sourceUrl: string;
  trackRecord: {
    hitRate: number;
    avgReturn: string;
    sharpeRatio: number;
    totalSignals: number;
    resolved: number;
    wins: number;
    losses: number;
    recentResults: { date: string; event: string; predicted: string; actual: string; hit: boolean }[];
  };
}> = {
  'pm-fed-rate-mar': {
    id: '1',
    timestamp: new Date(Date.now() - 1000 * 60 * 15).toISOString(),
    event: 'Fed Rate Cut - March FOMC',
    category: 'fed',
    confluenceLayers: 3,
    totalLayers: 8,
    confidenceScore: 0.87,
    historicalHitRate: 0.73,
    assetImpact: [
      { asset: 'TLT', expectedMove: '+2.1%', correlation: 0.89 },
      { asset: 'SPY', expectedMove: '+0.8%', correlation: 0.73 },
      { asset: 'DXY', expectedMove: '-0.5%', correlation: -0.68 },
    ],
    edgeWindow: '18hrs',
    layersFired: ['Polymarket', 'Congressional', 'Twitter'],
    severity: 'high',
    source: 'polymarket',
    sourceUrl: 'https://polymarket.com/event/fed-rate-decision-march-2026',
    trackRecord: {
      hitRate: 73,
      avgReturn: '+2.4%',
      sharpeRatio: 1.52,
      totalSignals: 47,
      resolved: 41,
      wins: 30,
      losses: 11,
      recentResults: [
        { date: '2025-12-18', event: 'Dec FOMC rate cut', predicted: 'TLT +2.0%', actual: 'TLT +2.3%', hit: true },
        { date: '2025-11-07', event: 'Nov FOMC hold + dovish', predicted: 'TLT +1.5%', actual: 'TLT +1.8%', hit: true },
        { date: '2025-09-20', event: 'Sep surprise cut', predicted: 'TLT +2.5%', actual: 'TLT +3.1%', hit: true },
        { date: '2025-07-30', event: 'Jul FOMC hold', predicted: 'TLT -0.5%', actual: 'TLT +0.2%', hit: false },
        { date: '2025-06-18', event: 'Jun hawkish hold', predicted: 'DXY +0.3%', actual: 'DXY +0.1%', hit: true },
      ],
    },
  },
  'pm-trump-tariff-china': {
    id: '3',
    timestamp: new Date(Date.now() - 1000 * 60 * 120).toISOString(),
    event: 'China Tariff Escalation Probability',
    category: 'tariffs',
    confluenceLayers: 4,
    totalLayers: 8,
    confidenceScore: 0.91,
    historicalHitRate: 0.81,
    assetImpact: [
      { asset: 'XLI', expectedMove: '-1.5%', correlation: -0.76 },
      { asset: 'FXI', expectedMove: '-2.3%', correlation: -0.82 },
      { asset: 'USDCNY', expectedMove: '+0.4%', correlation: 0.71 },
    ],
    edgeWindow: '24hrs',
    layersFired: ['Polymarket', 'Twitter', 'China Signals', 'Equities'],
    severity: 'critical',
    source: 'polymarket',
    sourceUrl: 'https://polymarket.com/event/china-tariff-escalation',
    trackRecord: {
      hitRate: 81,
      avgReturn: '+3.1%',
      sharpeRatio: 1.68,
      totalSignals: 32,
      resolved: 28,
      wins: 23,
      losses: 5,
      recentResults: [
        { date: '2025-08-15', event: 'Aug tariff announcement', predicted: 'XLI -2.0%', actual: 'XLI -2.1%', hit: true },
        { date: '2025-06-22', event: 'Jun tariff rumors', predicted: 'FXI -2.5%', actual: 'FXI -2.9%', hit: true },
        { date: '2025-04-10', event: 'Apr trade breakdown', predicted: 'XLI -1.5%', actual: 'XLI -1.3%', hit: true },
      ],
    },
  },
  'kal-btc-100k': {
    id: '2',
    timestamp: new Date(Date.now() - 1000 * 60 * 45).toISOString(),
    event: 'Bitcoin ETF Net Flows Spike',
    category: 'crypto',
    confluenceLayers: 2,
    totalLayers: 8,
    confidenceScore: 0.65,
    historicalHitRate: 0.68,
    assetImpact: [
      { asset: 'BTC', expectedMove: '+3.2%', correlation: 0.92 },
      { asset: 'ETH', expectedMove: '+2.8%', correlation: 0.85 },
    ],
    edgeWindow: '6hrs',
    layersFired: ['Polymarket', 'Crypto On-chain'],
    severity: 'medium',
    source: 'kalshi',
    sourceUrl: 'https://kalshi.com/markets/btc/bitcoin-100k',
    trackRecord: {
      hitRate: 68,
      avgReturn: '+2.8%',
      sharpeRatio: 1.31,
      totalSignals: 25,
      resolved: 19,
      wins: 13,
      losses: 6,
      recentResults: [
        { date: '2026-02-10', event: 'ETF inflow surge', predicted: 'BTC +4.0%', actual: 'BTC +5.7%', hit: true },
        { date: '2026-01-15', event: 'ETF flow reversal', predicted: 'BTC +3.5%', actual: 'BTC +4.2%', hit: true },
        { date: '2025-12-20', event: 'Year-end flow spike', predicted: 'BTC +2.0%', actual: 'BTC -0.8%', hit: false },
      ],
    },
  },
};

// Mock market data
const mockMarkets = [
  {
    id: 'pm-fed-rate-mar',
    question: 'Will the Fed cut rates at March 2026 FOMC?',
    category: 'fed',
    probability: 0.72,
    previousProbability: 0.65,
    volume24h: 2_840_000,
    totalVolume: 18_500_000,
    liquidity: 1_200_000,
    endDate: '2026-03-19T18:00:00Z',
    source: 'polymarket' as const,
    sourceUrl: 'https://polymarket.com/event/fed-rate-decision-march-2026',
    trending: true,
    tags: ['Federal Reserve', 'Interest Rates', 'Macro'],
  },
  {
    id: 'pm-trump-tariff-china',
    question: 'Will US impose >50% tariffs on China by April?',
    category: 'tariffs',
    probability: 0.58,
    previousProbability: 0.52,
    volume24h: 1_920_000,
    totalVolume: 12_300_000,
    liquidity: 890_000,
    endDate: '2026-04-30T23:59:59Z',
    source: 'polymarket' as const,
    sourceUrl: 'https://polymarket.com/event/china-tariff-escalation',
    trending: true,
    tags: ['Trade War', 'China', 'Tariffs'],
  },
  {
    id: 'kal-btc-100k',
    question: 'Bitcoin above $100k on March 31?',
    category: 'crypto',
    probability: 0.44,
    previousProbability: 0.48,
    volume24h: 3_150_000,
    totalVolume: 24_000_000,
    liquidity: 2_100_000,
    endDate: '2026-03-31T23:59:59Z',
    source: 'kalshi' as const,
    sourceUrl: 'https://kalshi.com/markets/btc/bitcoin-100k',
    trending: true,
    tags: ['Bitcoin', 'Crypto', 'Price Target'],
  },
  {
    id: 'pm-ukraine-ceasefire',
    question: 'Ukraine-Russia ceasefire agreement by June 2026?',
    category: 'geopolitical',
    probability: 0.23,
    previousProbability: 0.19,
    volume24h: 1_450_000,
    totalVolume: 9_800_000,
    liquidity: 670_000,
    endDate: '2026-06-30T23:59:59Z',
    source: 'polymarket' as const,
    sourceUrl: 'https://polymarket.com/event/ukraine-russia-ceasefire',
    trending: false,
    tags: ['Ukraine', 'Russia', 'Geopolitical'],
  },
  {
    id: 'kal-recession-2026',
    question: 'US enters recession in 2026?',
    category: 'fed',
    probability: 0.31,
    previousProbability: 0.28,
    volume24h: 980_000,
    totalVolume: 7_200_000,
    liquidity: 540_000,
    endDate: '2026-12-31T23:59:59Z',
    source: 'kalshi' as const,
    sourceUrl: 'https://kalshi.com/markets/recession/us-recession-2026',
    trending: false,
    tags: ['Recession', 'Economy', 'Macro'],
  },
  {
    id: 'pm-eth-etf-staking',
    question: 'SEC approves ETH ETF staking by Q2 2026?',
    category: 'crypto',
    probability: 0.38,
    previousProbability: 0.41,
    volume24h: 1_100_000,
    totalVolume: 6_500_000,
    liquidity: 480_000,
    endDate: '2026-06-30T23:59:59Z',
    source: 'polymarket' as const,
    sourceUrl: 'https://polymarket.com/event/eth-etf-staking',
    trending: false,
    tags: ['Ethereum', 'SEC', 'ETF', 'Regulation'],
  },
  {
    id: 'pm-taiwan-strait',
    question: 'Military escalation in Taiwan Strait by 2026?',
    category: 'geopolitical',
    probability: 0.09,
    previousProbability: 0.08,
    volume24h: 620_000,
    totalVolume: 4_100_000,
    liquidity: 310_000,
    endDate: '2026-12-31T23:59:59Z',
    source: 'polymarket' as const,
    sourceUrl: 'https://polymarket.com/event/taiwan-strait-escalation',
    trending: false,
    tags: ['Taiwan', 'China', 'Military', 'Geopolitical'],
  },
  {
    id: 'kal-sp500-ath',
    question: 'S&P 500 hits new all-time high in March?',
    category: 'fed',
    probability: 0.61,
    previousProbability: 0.55,
    volume24h: 1_680_000,
    totalVolume: 8_900_000,
    liquidity: 720_000,
    endDate: '2026-03-31T23:59:59Z',
    source: 'kalshi' as const,
    sourceUrl: 'https://kalshi.com/markets/sp500/sp500-ath-march',
    trending: true,
    tags: ['S&P 500', 'Equities', 'All-Time High'],
  },
  {
    id: 'pm-defense-budget',
    question: 'US defense budget exceeds $900B for FY2027?',
    category: 'defense',
    probability: 0.67,
    previousProbability: 0.64,
    volume24h: 450_000,
    totalVolume: 2_800_000,
    liquidity: 210_000,
    endDate: '2026-09-30T23:59:59Z',
    source: 'polymarket' as const,
    sourceUrl: 'https://polymarket.com/event/us-defense-budget-fy2027',
    trending: false,
    tags: ['Defense', 'Budget', 'Military Spending'],
  },
  {
    id: 'pm-ai-regulation',
    question: 'Major US AI regulation bill signed by 2026?',
    category: 'geopolitical',
    probability: 0.34,
    previousProbability: 0.31,
    volume24h: 870_000,
    totalVolume: 5_400_000,
    liquidity: 390_000,
    endDate: '2026-12-31T23:59:59Z',
    source: 'kalshi' as const,
    sourceUrl: 'https://kalshi.com/markets/ai/ai-regulation-2026',
    trending: false,
    tags: ['AI', 'Regulation', 'Technology', 'Policy'],
  },
];

// Per-spike attributors — different causes for each spike within a market
// Key: market id → spike index → attributors with source URLs
const perSpikeAttributors: Record<string, Record<number, { name: string; confidence: number; url?: string }[]>> = {
  'pm-fed-rate-mar': {
    0: [
      { name: 'FOMC minutes leaked dovish tone', confidence: 0.82, url: 'https://www.reuters.com/markets/us/fed-minutes/' },
      { name: 'PCE inflation undershoots consensus', confidence: 0.71, url: 'https://www.bls.gov/pce/' },
    ],
    1: [
      { name: 'Treasury yield curve inversion deepens', confidence: 0.67, url: 'https://www.treasury.gov/resource-center/data-chart-center/' },
      { name: 'Waller speech hints at March cut', confidence: 0.59, url: 'https://www.federalreserve.gov/newsevents/speech.htm' },
    ],
    2: [
      { name: 'Jobs report: NFP misses by 80K', confidence: 0.74, url: 'https://www.bls.gov/news.release/empsit.nr0.htm' },
    ],
  },
  'pm-trump-tariff-china': {
    0: [
      { name: 'Trump executive order on rare earths', confidence: 0.88, url: 'https://www.whitehouse.gov/presidential-actions/' },
      { name: 'USTR Section 301 investigation expanded', confidence: 0.63, url: 'https://ustr.gov/issue-areas/enforcement/section-301-investigations' },
    ],
    1: [
      { name: 'Retaliatory tariffs from Beijing MoC', confidence: 0.76, url: 'http://english.mofcom.gov.cn/' },
      { name: 'Semiconductor export controls tightened', confidence: 0.68, url: 'https://www.bis.gov/regulations' },
    ],
    2: [
      { name: 'Phase 2 trade talks collapse in Geneva', confidence: 0.81, url: 'https://www.reuters.com/world/china/' },
    ],
  },
  'kal-btc-100k': {
    0: [
      { name: 'BlackRock IBIT record daily inflows ($2.1B)', confidence: 0.79, url: 'https://www.blackrock.com/us/financial-professionals/products/ibit' },
    ],
    1: [
      { name: 'Mt. Gox creditor distribution deadline', confidence: 0.71, url: 'https://www.mtgox.com/' },
      { name: 'Tether attestation report questioned', confidence: 0.52, url: 'https://tether.to/en/transparency/' },
    ],
  },
  'pm-ukraine-ceasefire': {
    0: [
      { name: 'Zelenskyy-Trump bilateral in Ankara', confidence: 0.73, url: 'https://www.reuters.com/world/europe/' },
      { name: 'Minsk III draft circulated at UNSC', confidence: 0.42, url: 'https://www.un.org/securitycouncil/' },
    ],
    1: [
      { name: 'Lavrov signals territorial concession framework', confidence: 0.68, url: 'https://www.reuters.com/world/europe/' },
    ],
  },
  'kal-sp500-ath': {
    0: [
      { name: 'Mega-cap earnings beat cycle (NVDA, MSFT)', confidence: 0.85, url: 'https://finance.yahoo.com/quote/NVDA/' },
    ],
    1: [
      { name: 'VIX sub-12 compression', confidence: 0.61, url: 'https://www.cboe.com/tradable_products/vix/' },
      { name: 'Retail inflows hit 2024 highs', confidence: 0.54, url: 'https://www.reuters.com/markets/us/' },
    ],
  },
};

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const category = searchParams.get('category');
  const sort = searchParams.get('sort') || 'volume';
  const source = searchParams.get('source');
  const dataSourceMode = process.env.PYTHIA_DATA_SOURCE ?? 'live';

  const buildMockResponse = () => {
    let filtered = [...mockMarkets];

    if (category && category !== 'all') {
      filtered = filtered.filter(m => m.category === category);
    }

    if (source && source !== 'all') {
      filtered = filtered.filter(m => m.source === source);
    }

    if (sort === 'volume') {
      filtered.sort((a, b) => b.volume24h - a.volume24h);
    } else if (sort === 'change') {
      filtered.sort((a, b) =>
        Math.abs(b.probability - b.previousProbability) -
        Math.abs(a.probability - a.previousProbability)
      );
    } else if (sort === 'probability') {
      filtered.sort((a, b) => b.probability - a.probability);
    } else if (sort === 'ending') {
      filtered.sort((a, b) =>
        new Date(a.endDate).getTime() - new Date(b.endDate).getTime()
      );
    }

    const marketsWithData = filtered.map(m => {
      const priceHist = genHistory(m.probability, m.previousProbability);
      return {
        ...m,
        probabilityHistory: priceHist,
        volumeHistory: genVolumeHistory(priceHist, m.totalVolume),
        signal: marketSignals[m.id] || null,
        spikeAttributors: perSpikeAttributors[m.id] || {
          0: [{ name: 'Market sentiment shift', confidence: 0.45 }],
          1: [{ name: 'Volume anomaly detected', confidence: 0.32 }],
        },
        dataSource: 'mock' as const,
      };
    });

    // Signal-triggered markets float to top
    marketsWithData.sort((a, b) => {
      if (a.signal && !b.signal) return -1;
      if (!a.signal && b.signal) return 1;
      return 0;
    });

    return NextResponse.json({
      markets: marketsWithData,
      dataSource: 'mock',
      lastUpdated: new Date().toISOString(),
    });
  };

  if (dataSourceMode === 'mock') {
    return buildMockResponse();
  }

  try {
    const liveMarkets = await pmxtService.fetchMarkets({
      category,
      source,
      sort,
      limit: LIVE_MARKET_LIMIT,
    });

    const marketWithHistory = liveMarkets.map((market) => ({
      ...market,
      probabilityHistory: genHistory(market.probability, market.previousProbability),
      signal: (
        Object.values(marketSignals).find(
          (s) => s.category === market.category && s.source === market.source
        ) ?? null
      ),
      dataSource: 'live' as const,
    }));

    // Use cached OHLCV immediately when available.
    const enrichCount = Math.min(OHLCV_ENRICH_LIMIT, marketWithHistory.length);
    for (let i = 0; i < enrichCount; i++) {
      const market = marketWithHistory[i];
      if (!market.outcomeId) continue;
      const cached = pmxtService.getCachedOHLCV(market.source, market.outcomeId);
      if (cached && cached.length) {
        market.probabilityHistory = cached;
      }
    }

    // Background refresh only (do not block request latency).
    setTimeout(() => {
      void (async () => {
        for (let start = 0; start < enrichCount; start += OHLCV_CONCURRENCY) {
          const chunk = marketWithHistory.slice(start, Math.min(start + OHLCV_CONCURRENCY, enrichCount));
          await Promise.all(
            chunk.map(async (market) => {
              if (!market.outcomeId) return;
              pmxtService.prefetchOHLCV(market.source, market.outcomeId);
            })
          );
        }
      })();
    }, 0);

    marketWithHistory.sort((a, b) => {
      if (a.signal && !b.signal) return -1;
      if (!a.signal && b.signal) return 1;
      return 0;
    });

    return NextResponse.json({
      markets: marketWithHistory,
      dataSource: 'live',
      lastUpdated: new Date().toISOString(),
    });
  } catch {
    return buildMockResponse();
  }
}
