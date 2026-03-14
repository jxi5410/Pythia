export interface RunMetadataLike {
  market_id?: string;
  market_title?: string;
  timestamp?: string;
  magnitude?: number;
  direction?: string;
  price_before?: number;
  price_after?: number;
  spike_event?: {
    market_id?: string;
    magnitude?: number;
    spike_type?: string;
    direction?: string;
    detected_at?: string;
    timestamp?: string;
    metadata?: {
      market_title?: string;
      timestamp?: string;
      price_before?: number;
      price_after?: number;
    };
  };
}

function hasTimezoneSuffix(value: string): boolean {
  return /(?:Z|[+-]\d{2}:\d{2})$/i.test(value);
}

export function normalizeTimestamp(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return null;

  const withSeparator = trimmed.includes('T') ? trimmed : trimmed.replace(' ', 'T');
  const canonical = hasTimezoneSuffix(withSeparator) ? withSeparator : `${withSeparator}Z`;
  const parsed = new Date(canonical);
  return Number.isNaN(parsed.getTime()) ? null : canonical;
}

export function formatSpikeTimestamp(value: unknown, locale = 'en-US'): string {
  const normalized = normalizeTimestamp(value);
  if (!normalized) return 'Unknown time';

  return new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(normalized));
}

export function extractSpikeTimestamp(metadata?: RunMetadataLike | null): string {
  if (!metadata) return '';

  return (
    normalizeTimestamp(metadata.spike_event?.metadata?.timestamp) ??
    normalizeTimestamp(metadata.spike_event?.timestamp) ??
    normalizeTimestamp(metadata.timestamp) ??
    normalizeTimestamp(metadata.spike_event?.detected_at) ??
    ''
  );
}

export function extractSpikeDirection(metadata?: RunMetadataLike | null): 'up' | 'down' {
  const rawDirection = metadata?.spike_event?.direction ?? metadata?.spike_event?.spike_type ?? metadata?.direction;
  return rawDirection === 'down' ? 'down' : 'up';
}
