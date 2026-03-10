import pmxt from 'pmxtjs';

import type { Market } from '@/types';

type ExchangeName = 'polymarket' | 'kalshi';

type CacheEntry<T> = {
  expiry: number;
  value: T;
};

type FetchMarketsOptions = {
  category?: string | null;
  source?: string | null;
  sort?: string | null;
  limit?: number;
  query?: string;
};

type PMXTOutcome = {
  outcomeId?: string;
  label?: string;
  price?: number;
  priceChange24h?: number;
};

type PMXTMarket = {
  marketId?: string;
  title?: string;
  description?: string;
  outcomes?: PMXTOutcome[];
  yes?: PMXTOutcome;
  no?: PMXTOutcome;
  up?: PMXTOutcome;
  down?: PMXTOutcome;
  volume24h?: number;
  volume?: number;
  liquidity?: number;
  resolutionDate?: Date | string;
  category?: string;
  tags?: string[];
  url?: string;
};

type MappedMarket = Market & {
  outcomeId?: string;
};

const MARKET_CACHE_TTL_MS = 60_000;
const OHLCV_CACHE_TTL_MS = 5 * 60_000;
const OHLCV_FAILURE_TTL_MS = 60_000;
const MARKET_FETCH_TIMEOUT_MS = 7_000;

const marketCache = new Map<string, CacheEntry<MappedMarket[]>>();
const ohlcvCache = new Map<string, CacheEntry<number[]>>();
const ohlcvFailureCache = new Map<string, CacheEntry<true>>();
const inFlightMarketRefresh = new Map<string, Promise<MappedMarket[]>>();

let polyClient: InstanceType<typeof pmxt.Polymarket> | null = null;
let kalshiClient: InstanceType<typeof pmxt.Kalshi> | null = null;

function getExchange(source: ExchangeName) {
  if (source === 'polymarket') {
    if (!polyClient) polyClient = new pmxt.Polymarket({ autoStartServer: true });
    return polyClient;
  }
  if (!kalshiClient) kalshiClient = new pmxt.Kalshi({ autoStartServer: true });
  return kalshiClient;
}

function toNumber(value: unknown, fallback = 0): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function clampProbability(value: number): number {
  return Math.max(0.01, Math.min(0.99, value));
}

function textIncludesAny(haystack: string, needles: string[]): boolean {
  const lower = haystack.toLowerCase();
  return needles.some((n) => lower.includes(n));
}

function inferCategory(input: { title: string; tags: string[]; category?: string }): string {
  const merged = `${input.title} ${input.tags.join(' ')} ${input.category ?? ''}`.toLowerCase();

  if (textIncludesAny(merged, ['fed', 'rates', 'fomc', 'recession', 's&p', 'sp500', 'treasury'])) {
    return 'fed';
  }
  if (textIncludesAny(merged, ['tariff', 'trade', 'sanctions', 'china'])) {
    return 'tariffs';
  }
  if (textIncludesAny(merged, ['bitcoin', 'btc', 'eth', 'crypto', 'defi', 'ethereum'])) {
    return 'crypto';
  }
  if (textIncludesAny(merged, ['defense', 'military', 'budget', 'pentagon'])) {
    return 'defense';
  }
  return 'geopolitical';
}

function resolveYesOutcome(market: PMXTMarket): PMXTOutcome | undefined {
  if (market.yes?.price != null) return market.yes;
  if (market.up?.price != null) return market.up;

  const outcomes = market.outcomes ?? [];
  if (!outcomes.length) return undefined;

  const yesish = outcomes.find((o) => {
    const label = (o.label ?? '').toLowerCase();
    return label === 'yes' || label === 'up' || label.startsWith('yes ');
  });
  if (yesish?.price != null) return yesish;

  return outcomes.find((o) => o.price != null);
}

function mapOneMarket(source: ExchangeName, raw: PMXTMarket): MappedMarket | null {
  const outcome = resolveYesOutcome(raw);
  if (!outcome?.price || !raw.title) {
    return null;
  }

  const probability = clampProbability(toNumber(outcome.price, 0.5));
  const change24h = toNumber(outcome.priceChange24h, 0);
  const previousProbability = clampProbability(probability - change24h);
  const volume24h = Math.max(0, toNumber(raw.volume24h, toNumber(raw.volume, 0)));
  const totalVolume = Math.max(volume24h, toNumber(raw.volume, volume24h));
  const liquidity = Math.max(0, toNumber(raw.liquidity, 0));
  const tags = (raw.tags ?? []).filter(Boolean);

  const marketId = `${source}:${raw.marketId ?? raw.title.replace(/\s+/g, '-').toLowerCase()}`;
  const category = inferCategory({ title: raw.title, tags, category: raw.category });

  return {
    id: marketId,
    question: raw.title,
    category,
    probability,
    previousProbability,
    volume24h,
    totalVolume,
    liquidity,
    endDate: raw.resolutionDate ? new Date(raw.resolutionDate).toISOString() : new Date(Date.now() + 30 * 86400_000).toISOString(),
    source,
    sourceUrl: raw.url || '',
    trending: false,
    tags,
    probabilityHistory: [],
    outcomeId: outcome.outcomeId,
  };
}

function mapSort(sort: string | null | undefined): 'volume' | 'liquidity' | 'newest' {
  if (sort === 'ending') return 'newest';
  if (sort === 'probability') return 'liquidity';
  return 'volume';
}

function withTrending(markets: MappedMarket[]): MappedMarket[] {
  if (!markets.length) return markets;
  const sortedVolume = [...markets].sort((a, b) => b.volume24h - a.volume24h);
  const idx = Math.max(0, Math.ceil(sortedVolume.length * 0.2) - 1);
  const volumeCutoff = sortedVolume[idx]?.volume24h ?? 0;

  return markets.map((m) => {
    const change = Math.abs(m.probability - m.previousProbability);
    const trending = change >= 0.05 || m.volume24h >= volumeCutoff;
    return { ...m, trending };
  });
}

async function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return await Promise.race([
    promise,
    new Promise<T>((_, reject) => {
      setTimeout(() => reject(new Error(`Timeout after ${ms}ms`)), ms);
    }),
  ]);
}

async function fetchFromExchange(source: ExchangeName, options: FetchMarketsOptions): Promise<MappedMarket[]> {
  const exchange = getExchange(source);
  const rawMarkets = (await withTimeout(
    exchange.fetchMarkets({
      limit: options.limit ?? 120,
      sort: mapSort(options.sort),
      query: options.query,
    }),
    MARKET_FETCH_TIMEOUT_MS,
  )) as PMXTMarket[];

  return rawMarkets
    .map((raw) => mapOneMarket(source, raw))
    .filter((m): m is MappedMarket => m !== null);
}

async function refreshMarkets(options: FetchMarketsOptions): Promise<MappedMarket[]> {
  const requestedSource = options.source;
  const fetchBoth = !requestedSource || requestedSource === 'all';

  const tasks: Promise<MappedMarket[]>[] = [];
  if (fetchBoth || requestedSource === 'polymarket') tasks.push(fetchFromExchange('polymarket', options));
  if (fetchBoth || requestedSource === 'kalshi') tasks.push(fetchFromExchange('kalshi', options));

  const settled = await Promise.allSettled(tasks);
  const mapped = settled
    .filter((result): result is PromiseFulfilledResult<MappedMarket[]> => result.status === 'fulfilled')
    .flatMap((result) => result.value);

  if (!mapped.length) {
    throw new Error('No live markets fetched from PMXT');
  }

  const merged = withTrending(mapped);
  return applyLocalFilters(merged, options);
}

function applyLocalFilters(markets: MappedMarket[], options: FetchMarketsOptions): MappedMarket[] {
  let filtered = markets;

  if (options.category && options.category !== 'all') {
    filtered = filtered.filter((m) => m.category === options.category);
  }

  if (options.source && options.source !== 'all') {
    filtered = filtered.filter((m) => m.source === options.source);
  }

  if (options.sort === 'change') {
    filtered = [...filtered].sort(
      (a, b) => Math.abs(b.probability - b.previousProbability) - Math.abs(a.probability - a.previousProbability),
    );
  } else if (options.sort === 'probability') {
    filtered = [...filtered].sort((a, b) => b.probability - a.probability);
  } else if (options.sort === 'ending') {
    filtered = [...filtered].sort((a, b) => new Date(a.endDate).getTime() - new Date(b.endDate).getTime());
  } else {
    filtered = [...filtered].sort((a, b) => b.volume24h - a.volume24h);
  }

  return filtered;
}

function cacheKey(prefix: string, keyObj: unknown): string {
  return `${prefix}:${JSON.stringify(keyObj)}`;
}

export const pmxtService = {
  async fetchMarkets(options: FetchMarketsOptions = {}): Promise<MappedMarket[]> {
    const key = cacheKey('markets', options);
    const now = Date.now();
    const cached = marketCache.get(key);
    if (cached && cached.expiry > now) {
      return cached.value;
    }

    // Serve stale data immediately and refresh in background.
    if (cached?.value?.length) {
      if (!inFlightMarketRefresh.has(key)) {
        const refreshPromise = refreshMarkets(options)
          .then((fresh) => {
            marketCache.set(key, { expiry: Date.now() + MARKET_CACHE_TTL_MS, value: fresh });
            return fresh;
          })
          .finally(() => {
            inFlightMarketRefresh.delete(key);
          });
        inFlightMarketRefresh.set(key, refreshPromise);
      }
      return cached.value;
    }

    const fresh = await refreshMarkets(options);
    marketCache.set(key, { expiry: now + MARKET_CACHE_TTL_MS, value: fresh });
    return fresh;
  },

  async fetchOHLCV(source: ExchangeName, outcomeId: string): Promise<number[]> {
    const key = cacheKey('ohlcv', { source, outcomeId });
    const now = Date.now();
    const cached = ohlcvCache.get(key);
    if (cached && cached.expiry > now) {
      return cached.value;
    }
    const failed = ohlcvFailureCache.get(key);
    if (failed && failed.expiry > now) {
      throw new Error(`Recent OHLCV failure cached for ${source}:${outcomeId}`);
    }

    const exchange = getExchange(source);
    const candles = await withTimeout(
      exchange.fetchOHLCV(outcomeId, { resolution: '1h', limit: 30 }),
      12_000,
    );

    const history = (candles ?? [])
      .map((c: { close?: number }) => toNumber(c.close, NaN))
      .filter((x: number) => Number.isFinite(x))
      .map((x: number) => clampProbability(x));

    if (!history.length) {
      ohlcvFailureCache.set(key, { expiry: now + OHLCV_FAILURE_TTL_MS, value: true });
      throw new Error(`No OHLCV history for ${source}:${outcomeId}`);
    }

    ohlcvCache.set(key, { expiry: now + OHLCV_CACHE_TTL_MS, value: history });
    ohlcvFailureCache.delete(key);
    return history;
  },

  async fetchSourceUrlHints(limit = 60): Promise<Record<string, string>> {
    const markets = await this.fetchMarkets({ limit, sort: 'volume' });
    const hints: Record<string, string> = {};
    for (const market of markets) {
      const key = `${market.source}:${market.category}`;
      if (!hints[key] && market.sourceUrl) {
        hints[key] = market.sourceUrl;
      }
    }
    return hints;
  },

  getCachedOHLCV(source: ExchangeName, outcomeId: string): number[] | null {
    const key = cacheKey('ohlcv', { source, outcomeId });
    const cached = ohlcvCache.get(key);
    if (!cached || cached.expiry <= Date.now()) return null;
    return cached.value;
  },

  prefetchOHLCV(source: ExchangeName, outcomeId: string): void {
    void this.fetchOHLCV(source, outcomeId).catch(() => {
      // Best-effort warmup only.
    });
  },
};
