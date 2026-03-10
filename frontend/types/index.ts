export interface Market {
  id: string;
  question: string;
  category: string;
  probability: number;
  previousProbability: number;
  volume24h: number;
  totalVolume: number;
  liquidity: number;
  endDate: string;
  source: 'polymarket' | 'kalshi';
  sourceUrl: string;
  trending: boolean;
  tags: string[];
  probabilityHistory: number[];
  dataSource?: 'live' | 'mock';
}

export interface Spike {
  id: number;
  timestamp: string;
  direction: 'up' | 'down';
  magnitude: number;
  price_before: number;
  price_after: number;
  asset_class: string;
}

export interface Attributor {
  id: string;
  name: string;
  category: string;
  causal_chain: string;
  confidence: 'HIGH' | 'MEDIUM' | 'LOW';
  confidence_score: number;
  status: string;
  spike_count: number;
  avg_magnitude: number;
  market_ids: string[];
  first_seen: string;
  last_active: string;
}

export interface ForwardSignal {
  id: number;
  attributor_id: string;
  source_market_id: string;
  target_market_id: string;
  target_market_title: string;
  predicted_direction: 'up' | 'down';
  predicted_magnitude: number;
  predicted_lag_hours: number;
  confidence_score: number;
  status: string;
  created_at: string;
  expires_at: string;
}

export interface Narrative {
  id: string;
  name: string;
  description: string;
  category: string;
  strength: number;
  spike_count: number;
  attributor_ids: string[];
  market_ids: string[];
  status: string;
}

export interface PricePoint {
  timestamp: string;
  yes_price: number;
  volume?: number;
}

export interface MarketAnalysis {
  market_id: string;
  market_title: string;
  price_history: PricePoint[];
  spikes: Spike[];
  attributors: Attributor[];
  forward_signals: ForwardSignal[];
}

export interface Signal {
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
}

export interface TrackRecordSummary {
  hitRate: number;
  avgReturn: string;
  sharpeRatio: number;
  totalSignals: number;
  resolved: number;
  wins: number;
  losses: number;
  recentResults: { date: string; event: string; predicted: string; actual: string; hit: boolean }[];
}

export const MARKET_CATEGORIES = [
  { id: 'all', label: 'All', icon: '◉' },
  { id: 'politics', label: 'Politics', icon: '🏛' },
  { id: 'economics', label: 'Economics', icon: '📊' },
  { id: 'crypto', label: 'Crypto', icon: '₿' },
  { id: 'geopolitical', label: 'World', icon: '🌍' },
  { id: 'tech', label: 'Tech', icon: '⚡' },
  { id: 'sports', label: 'Sports', icon: '⚽' },
] as const;
