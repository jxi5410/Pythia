import type { PricePoint, Spike } from './run-store';

export function detectSpikes(prices: PricePoint[], threshold = 0.05): Spike[] {
  if (prices.length < 8) return [];
  const spikes: Spike[] = [];
  const win = Math.min(4, Math.floor(prices.length / 10));
  for (let i = win; i < prices.length; i++) {
    const before = prices[i - win].price;
    const after = prices[i].price;
    const mag = Math.abs(after - before);
    if (mag >= threshold) {
      spikes.push({
        index: i, timestamp: prices[i].t, magnitude: mag,
        direction: after > before ? 'up' : 'down',
        priceBefore: before, priceAfter: after,
      });
    }
  }
  // Deduplicate — keep largest in each 6-point window
  const deduped: Spike[] = [];
  for (const s of spikes) {
    const nearIdx = deduped.findIndex(d => Math.abs(d.index - s.index) < 6);
    if (nearIdx === -1) deduped.push(s);
    else if (s.magnitude > deduped[nearIdx].magnitude) deduped[nearIdx] = s;
  }
  return deduped.sort((a, b) => b.magnitude - a.magnitude);
}

export function computeThreshold(prices: PricePoint[]): number {
  const allPrices = prices.map(p => p.price);
  const priceRange = Math.max(...allPrices) - Math.min(...allPrices);
  const sorted = [...allPrices].sort((a, b) => a - b);
  const medianPrice = sorted[Math.floor(sorted.length / 2)] || 0.5;
  const absThreshold = priceRange * 0.15;
  const relThreshold = medianPrice * 0.10;
  return Math.max(0.005, Math.min(absThreshold, relThreshold));
}
