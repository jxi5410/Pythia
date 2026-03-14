'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useRunStore, C, mono, serif } from '@/lib/run-store';
import BACEGraphAnimation from '@/components/BACEGraphAnimation';
import { formatSpikeTimestamp } from '@/lib/run-presentation';

export default function RunAttributionPage() {
  const router = useRouter();
  const { run } = useRunStore();
  const [elapsedSec, setElapsedSec] = useState(0);
  const [watchdogAgeSec, setWatchdogAgeSec] = useState(0);
  const [activityLineIndex, setActivityLineIndex] = useState(0);
  const elapsedRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const watchdogRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const rotateRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Elapsed timer while running
  useEffect(() => {
    if (run.isRunning && !elapsedRef.current) {
      const start = Date.now();
      elapsedRef.current = setInterval(() => {
        setElapsedSec(Math.floor((Date.now() - start) / 1000));
      }, 1000);
    }
    if (!run.isRunning && elapsedRef.current) {
      clearInterval(elapsedRef.current);
      elapsedRef.current = null;
    }
    return () => { if (elapsedRef.current) clearInterval(elapsedRef.current); };
  }, [run.isRunning]);

  useEffect(() => {
    if (run.isRunning && !watchdogRef.current) {
      watchdogRef.current = setInterval(() => {
        const lastEventAt = run.baceState.lastBackendEventAtMs;
        setWatchdogAgeSec(lastEventAt ? Math.floor((Date.now() - lastEventAt) / 1000) : 0);
      }, 1000);
    }
    if (!run.isRunning && watchdogRef.current) {
      clearInterval(watchdogRef.current);
      watchdogRef.current = null;
      setWatchdogAgeSec(0);
    }
    return () => { if (watchdogRef.current) clearInterval(watchdogRef.current); };
  }, [run.isRunning, run.baceState.lastBackendEventAtMs]);

  useEffect(() => {
    rotateRef.current = setInterval(() => {
      setActivityLineIndex(prev => prev + 1);
    }, 3000);
    return () => { if (rotateRef.current) clearInterval(rotateRef.current); };
  }, []);

  const spike = run.selectedSpike;
  const market = run.selectedMarket;
  const showContinue = Boolean(run.attribution && !run.isRunning);
  const failureMessage = run.runErrorSource === 'backend'
    ? (run.runError || 'Attribution failed.')
    : (run.runError || 'Unable to reach the run stream right now.');
  const effectiveElapsedSec = Math.max(elapsedSec, Math.floor(run.baceState.elapsedSeconds || 0));
  const staleHeartbeat = run.isRunning && watchdogAgeSec >= 8;
  const stageKey = run.baceState.currentStageKey || 'preparing_run';
  const stageLabel = run.baceState.currentStageLabel || 'Preparing BACE run';
  const stageDetail = run.baceState.currentDetail || 'Connecting to the attribution stream.';
  const waitingOn = run.baceState.waitingOn;

  const activityLinesByStage: Record<string, string[]> = {
    preparing_run: ['Preparing BACE run', 'Connecting to the attribution stream', 'Loading run state'],
    preparing_context: ['Scanning recent market context', 'Extracting entities from the spike title', 'Classifying the market before evidence search'],
    building_spike_context: ['Scanning recent market context', 'Waiting for model response', 'Still processing evidence'],
    context: ['Scanning recent market context', 'Building candidate causal factors', 'Preparing ontology extraction'],
    context_ready: ['Building candidate causal factors', 'Starting ontology extraction', 'Starting early evidence search'],
    extracting_ontology: ['Building candidate causal factors', 'Waiting for model response', 'Still processing evidence'],
    evidence: ['Comparing supporting vs conflicting evidence', 'Scanning recent market context', 'Reviewing candidate evidence'],
    gathering_evidence: ['Comparing supporting vs conflicting evidence', 'Searching supporting and conflicting reports', 'Still processing evidence'],
    domain_evidence: ['Comparing supporting vs conflicting evidence', 'Gathering specialist evidence', 'Still processing evidence'],
    proposal: ['Asking agents to challenge the lead narrative', 'Comparing supporting vs conflicting evidence', 'Waiting for model response'],
    generating_proposals: ['Asking agents to challenge the lead narrative', 'Waiting for model response', 'Still processing evidence'],
    sim_round: ['Asking agents to challenge the lead narrative', 'Comparing supporting vs conflicting evidence', 'Reviewing agent actions'],
    sim_action: ['Asking agents to challenge the lead narrative', 'Comparing supporting vs conflicting evidence', 'Still processing evidence'],
    interaction: ['Comparing supporting vs conflicting evidence', 'Asking agents to challenge the lead narrative', 'Still processing evidence'],
    scenarios: ['Comparing supporting vs conflicting evidence', 'Clustering surviving narratives', 'Preparing attribution output'],
    graph_update: ['Assembling attribution graph', 'Writing graph updates', 'Preparing final output'],
    result: ['Assembling attribution graph', 'Preparing scenario handoff', 'Finalizing attribution output'],
    still_working: ['Still processing evidence', 'Waiting for backend progress update', 'Waiting for model response'],
  };
  const activityLines = activityLinesByStage[stageKey] || [stageLabel, stageDetail, waitingOn === 'model_response' ? 'Waiting for model response' : 'Still processing evidence'];
  const rotatingActivityLine = activityLines[activityLineIndex % activityLines.length];

  return (
    <div style={{ minHeight: 'calc(100vh - 90px)', background: C.bg, fontFamily: serif, color: C.dark }}>
      <div style={{ maxWidth: 900, margin: '0 auto', padding: '40px 24px' }}>
        {/* Market context */}
        {market && (
          <div style={{ fontFamily: serif, fontSize: 20, fontWeight: 700, marginBottom: 4 }}>
            {market.question}
          </div>
        )}
        <div style={{ fontFamily: mono, fontSize: 11, color: C.muted, marginBottom: 24 }}>
          {spike && (
            <>
              <span style={{ color: spike.direction === 'up' ? C.accent : C.info, fontWeight: 700, fontSize: 14 }}>
                {spike.direction === 'up' ? '+' : '-'}{(spike.magnitude * 100).toFixed(1)}%
              </span>
              {' '}at {formatSpikeTimestamp(spike.timestamp)}
              {' \u00B7 '}
            </>
          )}
          {run.isRunning ? <span style={{ color: C.accent }}>&#x25CF; Running BACE depth 2 &#x2014; {effectiveElapsedSec}s</span> : run.isLive ? <span style={{ color: C.yes }}>&#x25CF; Live</span> : <span style={{ color: C.muted }}>&#x25CF; Simulated</span>}
        </div>

        {(run.runStatus === 'error' || run.runStatus === 'failed') && (
          <div style={{ padding: '12px 16px', background: '#fdf0ed', borderRadius: 6, fontFamily: mono, fontSize: 12, color: C.accent, marginBottom: 16 }}>
            {failureMessage}
          </div>
        )}

        <div style={{
          background: '#f6f3ea',
          border: `1px solid ${staleHeartbeat ? C.accent : C.border}`,
          borderRadius: 8,
          padding: '14px 16px',
          marginBottom: 16,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', marginBottom: 6 }}>
            <div style={{ fontFamily: mono, fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, color: C.muted }}>
              {stageLabel}
            </div>
            <div style={{ fontFamily: mono, fontSize: 11, color: staleHeartbeat ? C.accent : C.muted }}>
              {run.isRunning ? `${effectiveElapsedSec}s elapsed` : 'Idle'}
            </div>
          </div>
          <div style={{ fontFamily: serif, fontSize: 18, fontWeight: 700, marginBottom: 6 }}>
            {rotatingActivityLine}
          </div>
          <div style={{ fontFamily: mono, fontSize: 12, color: C.muted }}>
            {stageDetail}
            {waitingOn && ` Waiting on ${waitingOn.replace(/_/g, ' ')}.`}
          </div>
          {staleHeartbeat && (
            <div style={{ fontFamily: mono, fontSize: 11, color: C.accent, marginTop: 8 }}>
              Still working. No backend event for {watchdogAgeSec}s.
            </div>
          )}
        </div>

        {/* BACE Graph Animation */}
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: '20px 24px' }}>
          <BACEGraphAnimation baceState={run.baceState} graphState={run.graphState} />
        </div>

        {/* Continue button when complete */}
        {showContinue && run.runId && (
          <div style={{ textAlign: 'center' as const, padding: '28px 0' }}>
            <div style={{ fontFamily: mono, fontSize: 12, color: C.yes, marginBottom: 12 }}>
              &#x2713; Attribution complete &#x2014; {run.attribution?.scenarios?.length || 0} scenarios identified
            </div>
            <button
              onClick={() => router.push(`/run/${run.runId}/scenarios`)}
              style={{
                padding: '14px 40px', borderRadius: 6, border: 'none',
                background: C.dark, color: C.bg, fontFamily: mono,
                fontSize: 14, fontWeight: 600, cursor: 'pointer',
                transition: 'all 0.2s',
              }}
            >
              View Scenarios &#x2192;
            </button>
            <div style={{ fontFamily: mono, fontSize: 10, color: C.muted, marginTop: 8 }}>
              {run.isLive ? '&#x25CF; Live attribution from backend' : '&#x26A0; Simulated &#x2014; backend not connected'}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
