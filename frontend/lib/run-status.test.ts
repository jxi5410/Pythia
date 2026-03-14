import test from 'node:test';
import assert from 'node:assert/strict';

import {
  applyBackendHydratedStatus,
  applyBackendRunFailure,
  applyClientRunError,
  shouldTreatAsIntentionalAbort,
  type RunErrorState,
} from './run-status';

function baseState(): RunErrorState {
  return {
    runStatus: 'running',
    runError: null,
    runErrorSource: null,
    isRunning: true,
  };
}

test('hydration fetch failure is client-only error state', () => {
  const next = applyClientRunError(baseState(), 'Failed to load run');
  assert.equal(next.runStatus, 'error');
  assert.equal(next.runErrorSource, 'client');
});

test('reconnect exhaustion is client-only error state', () => {
  const next = applyClientRunError(baseState(), 'Lost connection to the attribution stream.');
  assert.equal(next.runStatus, 'error');
  assert.equal(next.runErrorSource, 'client');
});

test('backend terminal SSE failure is backend failed state', () => {
  const next = applyBackendRunFailure(baseState(), 'RuntimeError: backend failed');
  assert.equal(next.runStatus, 'failed');
  assert.equal(next.runErrorSource, 'backend');
});

test('backend failed status on hydration stays backend failed even without error text yet', () => {
  const next = applyBackendHydratedStatus(baseState(), 'failed', null);
  assert.equal(next.runStatus, 'failed');
  assert.equal(next.runErrorSource, 'backend');
});

test('AbortError is treated as intentional abort with no error state transition', () => {
  const err = new Error('aborted');
  err.name = 'AbortError';
  assert.equal(shouldTreatAsIntentionalAbort(err, false), true);
});

test('explicit aborted signal is treated as intentional abort with no error state transition', () => {
  assert.equal(shouldTreatAsIntentionalAbort(new Error('ignored'), true), true);
});
