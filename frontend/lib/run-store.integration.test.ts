import test from 'node:test';
import assert from 'node:assert/strict';

import { StreamTerminalError } from './bace-runner.ts';
import { createRunStoreTestHarness } from './run-store.tsx';

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => body,
  } as Response;
}

async function flushMicrotasks(times = 5) {
  for (let i = 0; i < times; i++) {
    await Promise.resolve();
  }
}

test('store flow: hydration failure stays client-only', async () => {
  const harness = createRunStoreTestHarness({
    fetchImpl: async () => {
      throw new Error('network down');
    },
  });

  await assert.rejects(() => harness.initRun('run-1'));
  const state = harness.getState();
  assert.equal(state.runStatus, 'error');
  assert.equal(state.runErrorSource, 'client');
});

test('store flow: backend failed hydration stays backend-only failed state', async () => {
  const harness = createRunStoreTestHarness({
    fetchImpl: async (input) => {
      const url = String(input);
      if (url.endsWith('/api/runs/run-2')) {
        return jsonResponse({
          run: {
            status: 'failed_terminal',
            error_message: 'RuntimeError: persisted failure',
            metadata: {},
          },
          scenarios: [],
          actions: [],
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    },
    connectRunStreamImpl: async () => undefined,
  });

  await harness.initRun('run-2');
  const state = harness.getState();
  assert.equal(state.runStatus, 'failed');
  assert.equal(state.runErrorSource, 'backend');
  assert.equal(state.runError, 'RuntimeError: persisted failure');
});

test('store flow: reconnect exhaustion stays client-only', async () => {
  const harness = createRunStoreTestHarness({
    fetchImpl: async (input) => {
      const url = String(input);
      if (url.endsWith('/api/runs/run-3')) {
        return jsonResponse({
          run: { status: 'running', metadata: {} },
          scenarios: [],
          actions: [],
        });
      }
      throw new Error('status fetch failed');
    },
    connectRunStreamImpl: async () => {
      throw new Error('socket closed');
    },
    sleepImpl: async () => undefined,
    maxReconnectAttempts: 2,
  });

  await harness.initRun('run-3');
  await flushMicrotasks(10);
  const state = harness.getState();
  assert.equal(state.runStatus, 'error');
  assert.equal(state.runErrorSource, 'client');
});

test('store flow: backend SSE terminal failure stays backend failed state', async () => {
  const harness = createRunStoreTestHarness({
    fetchImpl: async (input) => {
      const url = String(input);
      if (url.endsWith('/api/runs/run-4')) {
        return jsonResponse({
          run: { status: 'running', metadata: {} },
          scenarios: [],
          actions: [],
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    },
    connectRunStreamImpl: async (_runId, _lastEventId, callbacks) => {
      callbacks.onError('RuntimeError: backend failed');
      throw new StreamTerminalError('RuntimeError: backend failed');
    },
  });

  await harness.initRun('run-4');
  await flushMicrotasks();
  const state = harness.getState();
  assert.equal(state.runStatus, 'failed');
  assert.equal(state.runErrorSource, 'backend');
  assert.equal(state.runError, 'RuntimeError: backend failed');
});

test('store flow: AbortError/navigation does not write an error state', async () => {
  const abortErr = new Error('aborted');
  abortErr.name = 'AbortError';

  const harness = createRunStoreTestHarness({
    fetchImpl: async (input) => {
      const url = String(input);
      if (url.endsWith('/api/runs/run-5')) {
        return jsonResponse({
          run: { status: 'running', metadata: {} },
          scenarios: [],
          actions: [],
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    },
    connectRunStreamImpl: async () => {
      throw abortErr;
    },
  });

  await harness.initRun('run-5');
  await flushMicrotasks();
  const state = harness.getState();
  assert.equal(state.runStatus, 'running');
  assert.equal(state.runErrorSource, null);
  assert.equal(state.runError, null);
});
