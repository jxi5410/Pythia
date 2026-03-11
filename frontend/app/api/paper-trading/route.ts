import { NextResponse } from 'next/server';

export const runtime = 'nodejs';

// ----------------------------------------------------------------
// Mock paper-trading data — mirrors src/trading/paper_trading.py schema
// ----------------------------------------------------------------

interface PaperTrade {
  id: number;
  signal_id: number;
  market_id: string;
  market_title: string;
  trade_type: 'maker' | 'taker';
  side: 'yes' | 'no';
  entry_price: number;
  exit_price: number | null;
  position_size: number;
  expected_return: number;
  actual_return: number | null;
  status: 'executed' | 'closed' | 'cancelled';
  opened_at: string;
  closed_at: string | null;
  attributor: string;
}

function daysAgo(n: number, h = 0): string {
  const d = new Date(Date.now() - n * 86400000 - h * 3600000);
  return d.toISOString();
}

const mockTrades: PaperTrade[] = [
  // Closed — winning
  { id: 1, signal_id: 101, market_id: 'pm-fed-rate-mar', market_title: 'Fed cuts rates in March FOMC?', trade_type: 'taker', side: 'yes', entry_price: 0.68, exit_price: 0.76, position_size: 520, expected_return: 0.077, actual_return: 0.118, status: 'closed', opened_at: daysAgo(12, 9), closed_at: daysAgo(10, 14), attributor: 'FOMC minutes leaked dovish tone' },
  { id: 2, signal_id: 102, market_id: 'pm-trump-tariff-china', market_title: 'Trump 60% tariff on China by April?', trade_type: 'maker', side: 'yes', entry_price: 0.42, exit_price: 0.51, position_size: 340, expected_return: 0.089, actual_return: 0.214, status: 'closed', opened_at: daysAgo(11, 3), closed_at: daysAgo(8, 18), attributor: 'Trump executive order on rare earths' },
  { id: 3, signal_id: 103, market_id: 'kal-btc-100k', market_title: 'Bitcoin above $100K end of March?', trade_type: 'taker', side: 'yes', entry_price: 0.55, exit_price: 0.62, position_size: 410, expected_return: 0.063, actual_return: 0.127, status: 'closed', opened_at: daysAgo(10, 7), closed_at: daysAgo(7, 11), attributor: 'BlackRock IBIT record daily inflows' },
  // Closed — losing
  { id: 4, signal_id: 104, market_id: 'pm-ukraine-ceasefire', market_title: 'Ukraine ceasefire agreement by April?', trade_type: 'taker', side: 'yes', entry_price: 0.31, exit_price: 0.22, position_size: 280, expected_return: 0.052, actual_return: -0.290, status: 'closed', opened_at: daysAgo(9, 14), closed_at: daysAgo(6, 8), attributor: 'Zelenskyy-Trump bilateral in Ankara' },
  { id: 5, signal_id: 105, market_id: 'kal-recession-2026', market_title: 'US recession declared by Q3 2026?', trade_type: 'maker', side: 'no', entry_price: 0.78, exit_price: 0.82, position_size: 190, expected_return: 0.042, actual_return: -0.182, status: 'closed', opened_at: daysAgo(8, 2), closed_at: daysAgo(5, 16), attributor: 'ISM Manufacturing contraction deepens' },
  // Closed — winning
  { id: 6, signal_id: 106, market_id: 'pm-eth-etf-staking', market_title: 'ETH ETF staking approved by SEC?', trade_type: 'taker', side: 'yes', entry_price: 0.38, exit_price: 0.47, position_size: 310, expected_return: 0.071, actual_return: 0.237, status: 'closed', opened_at: daysAgo(7, 5), closed_at: daysAgo(4, 19), attributor: 'SEC commissioner signals staking openness' },
  { id: 7, signal_id: 107, market_id: 'kal-sp500-ath', market_title: 'S&P 500 new ATH by end March?', trade_type: 'taker', side: 'yes', entry_price: 0.71, exit_price: 0.79, position_size: 450, expected_return: 0.059, actual_return: 0.113, status: 'closed', opened_at: daysAgo(6, 8), closed_at: daysAgo(3, 12), attributor: 'Mega-cap earnings beat cycle' },
  // Closed — losing
  { id: 8, signal_id: 108, market_id: 'pm-defense-budget', market_title: 'US defense budget exceeds $900B?', trade_type: 'maker', side: 'yes', entry_price: 0.62, exit_price: 0.55, position_size: 220, expected_return: 0.048, actual_return: -0.113, status: 'closed', opened_at: daysAgo(5, 1), closed_at: daysAgo(2, 15), attributor: 'Congressional defense hawks markup push' },
  // Open positions
  { id: 9, signal_id: 109, market_id: 'pm-ai-regulation', market_title: 'US federal AI regulation bill by June?', trade_type: 'taker', side: 'no', entry_price: 0.34, exit_price: null, position_size: 260, expected_return: 0.065, actual_return: null, status: 'executed', opened_at: daysAgo(2, 6), closed_at: null, attributor: 'Senate Commerce Committee hearing scheduled' },
  { id: 10, signal_id: 110, market_id: 'pm-taiwan-strait', market_title: 'Major Taiwan Strait incident in 2026?', trade_type: 'taker', side: 'no', entry_price: 0.18, exit_price: null, position_size: 150, expected_return: 0.039, actual_return: null, status: 'executed', opened_at: daysAgo(1, 3), closed_at: null, attributor: 'PLA exercises scale down per satellite data' },
];

// Equity curve — daily snapshots
function buildEquityCurve(trades: PaperTrade[], initialCapital: number) {
  const days = 14;
  const curve: { date: string; capital: number; exposure: number; openPositions: number; dailyPnl: number }[] = [];
  let capital = initialCapital;

  for (let d = days; d >= 0; d--) {
    const dateStr = new Date(Date.now() - d * 86400000).toISOString().slice(0, 10);
    const closedToday = trades.filter(t =>
      t.status === 'closed' && t.closed_at && t.closed_at.slice(0, 10) === dateStr
    );
    const dailyPnl = closedToday.reduce((sum, t) =>
      sum + (t.actual_return ?? 0) * t.position_size, 0
    );
    capital += dailyPnl;

    const openToday = trades.filter(t =>
      t.status === 'executed' || (t.status === 'closed' && t.closed_at && t.closed_at.slice(0, 10) >= dateStr)
    );
    const exposure = openToday.reduce((sum, t) => sum + t.position_size, 0);

    curve.push({
      date: dateStr,
      capital: Math.round(capital * 100) / 100,
      exposure: Math.round(exposure * 100) / 100,
      openPositions: openToday.filter(t => t.status === 'executed').length,
      dailyPnl: Math.round(dailyPnl * 100) / 100,
    });
  }
  return curve;
}

function computeStats(trades: PaperTrade[], initialCapital: number) {
  const closed = trades.filter(t => t.status === 'closed');
  const wins = closed.filter(t => (t.actual_return ?? 0) > 0);
  const losses = closed.filter(t => (t.actual_return ?? 0) <= 0);
  const open = trades.filter(t => t.status === 'executed');

  const totalPnl = closed.reduce((s, t) => s + (t.actual_return ?? 0) * t.position_size, 0);
  const currentCapital = initialCapital + totalPnl;
  const returns = closed.map(t => t.actual_return ?? 0);
  const avgReturn = returns.length > 0 ? returns.reduce((a, b) => a + b, 0) / returns.length : 0;
  const stdReturn = returns.length > 1
    ? Math.sqrt(returns.reduce((s, r) => s + (r - avgReturn) ** 2, 0) / (returns.length - 1))
    : 0;
  const sharpe = stdReturn > 0 ? (avgReturn / stdReturn) * Math.sqrt(252) : 0;

  // Max drawdown from equity curve
  const curve = buildEquityCurve(trades, initialCapital);
  let peak = initialCapital;
  let maxDD = 0;
  for (const pt of curve) {
    if (pt.capital > peak) peak = pt.capital;
    const dd = (peak - pt.capital) / peak;
    if (dd > maxDD) maxDD = dd;
  }

  return {
    initialCapital,
    currentCapital: Math.round(currentCapital * 100) / 100,
    totalPnl: Math.round(totalPnl * 100) / 100,
    totalReturn: Math.round((currentCapital / initialCapital - 1) * 10000) / 100,
    totalTrades: closed.length,
    openPositions: open.length,
    winRate: Math.round((wins.length / Math.max(closed.length, 1)) * 10000) / 100,
    avgReturn: Math.round(avgReturn * 10000) / 100,
    sharpeRatio: Math.round(sharpe * 100) / 100,
    maxDrawdown: Math.round(maxDD * 10000) / 100,
    exposure: open.reduce((s, t) => s + t.position_size, 0),
    wins: wins.length,
    losses: losses.length,
    bestTrade: Math.round(Math.max(...returns, 0) * 10000) / 100,
    worstTrade: Math.round(Math.min(...returns, 0) * 10000) / 100,
  };
}

const INITIAL_CAPITAL = 10000;

export async function GET() {
  const stats = computeStats(mockTrades, INITIAL_CAPITAL);
  const equityCurve = buildEquityCurve(mockTrades, INITIAL_CAPITAL);

  return NextResponse.json({
    trades: mockTrades,
    stats,
    equityCurve,
    lastUpdated: new Date().toISOString(),
  });
}
