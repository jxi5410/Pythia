import test from 'node:test';
import assert from 'node:assert/strict';

import { connectRunStream } from './bace-runner';

function makeSSEBlock(event: string, payload: unknown, sequence: number) {
  return [
    `id: ${sequence}`,
    `event: ${event}`,
    `data: ${JSON.stringify({
      event_id: `evt-${sequence}`,
      run_id: 'run-1',
      stage: 'attribution_started',
      event_type: event,
      sequence,
      payload,
      timestamp: new Date().toISOString(),
    })}`,
    '',
  ].join('\n');
}

test('connectRunStream maps canonical progress heartbeats into visible state updates', async () => {
  const originalFetch = globalThis.fetch;
  const chunks = [
    makeSSEBlock('run_started', {
      progress_kind: 'run_started',
      phase: 'preparing_run',
      phase_label: 'Preparing BACE run',
      message: 'Preparing BACE run',
      detail: 'Validating the spike and starting the attribution pipeline.',
      elapsed_seconds: 0,
    }, 0),
    makeSSEBlock('heartbeat', {
      progress_kind: 'heartbeat',
      phase: 'building_spike_context',
      phase_label: 'Building spike context',
      message: 'Scanning recent market context',
      detail: 'Waiting for the first model response.',
      waiting_on: 'model_response',
      elapsed_seconds: 4,
    }, 1),
    makeSSEBlock('run_completed', {
      progress_kind: 'result',
      elapsed_seconds: 4,
      final_result: {
        scenarios: [],
        agent_hypotheses: [],
        attribution: { most_likely_cause: 'No cause survived' },
        bace_metadata: { elapsed_seconds: 4 },
      },
    }, 2),
  ].join('\n') + '\n';

  globalThis.fetch = async () => {
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(chunks));
        controller.close();
      },
    });
    return new Response(stream, { status: 200 });
  };

  const states: any[] = [];
  let completed = false;
  await connectRunStream('run-1', 0, {
    onBaceState: state => states.push(state),
    onGraphState: () => undefined,
    onComplete: () => { completed = true; },
    onError: (message) => {
      throw new Error(message);
    },
  });

  assert.equal(completed, true);
  assert.ok(states.length >= 2);
  const latest = states[states.length - 1];
  assert.equal(latest.currentStageKey, 'building_spike_context');
  assert.equal(latest.currentStageLabel, 'Building spike context');
  assert.equal(latest.waitingOn, 'model_response');
  assert.equal(latest.debateLog.includes('Waiting for model response'), true);

  globalThis.fetch = originalFetch;
});
