'use client';

import { useRouter, usePathname } from 'next/navigation';
import { useRunStore, C, mono, serif, type Stage } from '@/lib/run-store';

function getStages(runId: string | null): { id: Stage; label: string; icon: string; path: string }[] {
  return [
    { id: 'market', label: 'Market', icon: '\uD83D\uDD0D', path: '/' },
    { id: 'attribution', label: 'Attribution', icon: '\u26A1', path: runId ? `/run/${runId}` : '/' },
    { id: 'scenarios', label: 'Scenarios', icon: '\uD83C\uDFAF', path: runId ? `/run/${runId}/scenarios` : '/' },
    { id: 'interrogation', label: 'Interrogate', icon: '\uD83D\uDCAC', path: runId ? `/run/${runId}/interrogation` : '/' },
  ];
}

export default function NavHeader() {
  const router = useRouter();
  const pathname = usePathname();
  const { run, canNavigateTo } = useRunStore();
  const STAGES = getStages(run.runId);

  const currentIdx = STAGES.findIndex(s => {
    if (s.id === 'market') return pathname === '/';
    if (s.id === 'attribution') return pathname.match(/^\/run\/[^/]+$/) || pathname === '/attribution';
    if (s.id === 'scenarios') return pathname.match(/^\/run\/[^/]+\/scenarios/) || pathname === '/scenarios';
    if (s.id === 'interrogation') return pathname.match(/^\/run\/[^/]+\/interrogation/) || pathname === '/interrogation';
    return false;
  });

  return (
    <header style={{
      borderBottom: `1px solid ${C.border}`,
      background: C.bg,
    }}>
      {/* Top bar */}
      <div style={{
        padding: '16px 40px',
        display: 'flex',
        alignItems: 'baseline',
        gap: 16,
      }}>
        <span
          onClick={() => router.push('/')}
          style={{
            fontSize: 22, fontWeight: 700, letterSpacing: -0.5,
            fontFamily: serif, cursor: 'pointer',
          }}
        >
          Pythia
        </span>
        <span style={{ fontFamily: mono, fontSize: 11, color: C.muted, letterSpacing: 0.5 }}>
          BACKWARD ATTRIBUTION CAUSAL ENGINE
        </span>
        {run.selectedMarket && (
          <span style={{
            fontFamily: mono, fontSize: 11, color: C.info,
            marginLeft: 'auto',
            maxWidth: 400,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap' as const,
            display: 'flex', alignItems: 'center', gap: 6,
          }}>
            {run.runId && (
              <span style={{
                fontSize: 9, padding: '1px 5px', borderRadius: 3,
                background: run.runStatus === 'completed' ? '#eef3e8' : run.runStatus === 'running' ? '#fdf5ed' : C.faint,
                color: run.runStatus === 'completed' ? C.yes : run.runStatus === 'running' ? C.accent : C.muted,
                border: `1px solid ${run.runStatus === 'completed' ? C.yes + '40' : run.runStatus === 'running' ? C.accent + '40' : C.border}`,
                flexShrink: 0,
              }}>
                {run.runId.slice(0, 8)}
              </span>
            )}
            {run.selectedMarket.question.slice(0, 50)}{run.selectedMarket.question.length > 50 ? '\u2026' : ''}
          </span>
        )}
      </div>

      {/* Stage progress — minimal breadcrumb, not tabs */}
      {currentIdx > 0 && (
        <div style={{
          padding: '0 40px 8px',
          fontFamily: mono,
          fontSize: 11,
          color: C.muted,
          display: 'flex',
          gap: 4,
          alignItems: 'center',
        }}>
          {STAGES.slice(0, currentIdx + 1).map((stage, i) => (
            <span key={stage.id} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              {i > 0 && <span style={{ color: C.border }}>→</span>}
              <span
                onClick={() => {
                  if (i < currentIdx && (canNavigateTo(stage.id) || i === 0)) router.push(stage.path);
                }}
                style={{
                  cursor: i < currentIdx ? 'pointer' : 'default',
                  color: i === currentIdx ? C.dark : C.info,
                  fontWeight: i === currentIdx ? 600 : 400,
                  textDecoration: i < currentIdx ? 'underline' : 'none',
                }}
              >
                {stage.label}
              </span>
            </span>
          ))}
        </div>
      )}
    </header>
  );
}
