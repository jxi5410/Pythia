import test from 'node:test';
import assert from 'node:assert/strict';

import {
  extractSpikeDirection,
  extractSpikeTimestamp,
  formatSpikeTimestamp,
  normalizeTimestamp,
} from './run-presentation';

test('normalizeTimestamp appends UTC to naive ISO strings for Safari-safe parsing', () => {
  assert.equal(
    normalizeTimestamp('2025-01-15T12:00:00'),
    '2025-01-15T12:00:00Z',
  );
});

test('normalizeTimestamp accepts epoch seconds', () => {
  assert.equal(
    normalizeTimestamp(1736942400),
    '2025-01-15T12:00:00.000Z',
  );
});

test('normalizeTimestamp accepts epoch milliseconds strings', () => {
  assert.equal(
    normalizeTimestamp('1736942400000'),
    '2025-01-15T12:00:00.000Z',
  );
});

test('extractSpikeTimestamp prefers the persisted spike timestamp over detected_at', () => {
  assert.equal(
    extractSpikeTimestamp({
      timestamp: '2025-01-15T12:00:00Z',
      spike_event: {
        detected_at: '2026-03-14T11:22:33Z',
        metadata: {
          timestamp: '2025-01-15T12:00:00Z',
        },
      },
    }),
    '2025-01-15T12:00:00Z',
  );
});

test('extractSpikeDirection maps spike_type into the UI direction enum', () => {
  assert.equal(
    extractSpikeDirection({
      spike_event: { spike_type: 'down' },
    }),
    'down',
  );
});

test('formatSpikeTimestamp returns a stable label for valid timestamps', () => {
  assert.equal(
    formatSpikeTimestamp('2025-01-15T12:00:00', 'en-US'),
    'Jan 15, 12:00 PM',
  );
});

test('formatSpikeTimestamp falls back cleanly for invalid timestamps', () => {
  assert.equal(formatSpikeTimestamp('not-a-date'), 'Unknown time');
});

test('formatSpikeTimestamp falls back cleanly when absent', () => {
  assert.equal(formatSpikeTimestamp(undefined), 'Unknown time');
});
