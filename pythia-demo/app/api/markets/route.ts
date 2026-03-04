import { NextResponse } from 'next/server';

// Mock market data — in production this pulls from Polymarket CLOB + Kalshi APIs
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
    trending: false,
    tags: ['AI', 'Regulation', 'Technology', 'Policy'],
  },
];

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const category = searchParams.get('category');
  const sort = searchParams.get('sort') || 'volume';

  let filtered = [...mockMarkets];

  if (category && category !== 'all') {
    filtered = filtered.filter(m => m.category === category);
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

  // Summary stats
  const totalVolume24h = mockMarkets.reduce((sum, m) => sum + m.volume24h, 0);
  const totalLiquidity = mockMarkets.reduce((sum, m) => sum + m.liquidity, 0);
  const trendingCount = mockMarkets.filter(m => m.trending).length;

  return NextResponse.json({
    markets: filtered,
    stats: {
      totalMarkets: mockMarkets.length,
      totalVolume24h,
      totalLiquidity,
      trendingCount,
    },
    lastUpdated: new Date().toISOString(),
  });
}
