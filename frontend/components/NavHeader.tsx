'use client';

import { useRouter, usePathname } from 'next/navigation';
import { useRunStore, C, mono, serif, type Stage } from '@/lib/run-store';

const STAGES: { id: Stage; label: string; icon: string; path: string }[] = [
  { id: 'market', label: 'Market', icon: '🔍', path: '/' },
  { id: 'attribution', label: 'Attribution', icon: '⚡', path: '/attribution' },
  { id: 'scenarios', label: 'Scenarios', icon: '🎯', path: '/scenarios' },
  { id: 'interrogation', label: 'Interrogate', icon: '💬', path: '/interrogation' },
];

export default function NavHeader() {
  const router = useRouter();
  const pathname = usePathname();
  const { run, canNavigateTo } = useRunStore();

  const currentIdx = STAGES.findIndex(s => {
    if (s.path === '/') return pathname === '/';
    return pathname.startsWith(s.path);
  });

  return (
    <header style={{
      borderBottom: `1px solid ${C.border}`,
      background: C.bg,
      position: 'sticky' as const,
      top: 0,
      zIndex: 50,
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
            maxWidth: 300,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap' as const,
          }}>
            {run.selectedMarket.question.slice(0, 50)}{run.selectedMarket.question.length > 50 ? '…' : ''}
          </span>
        )}
      </div>

      {/* Stage progress */}
      <div style={{
        padding: '0 40px 0',
        display: 'flex',
        gap: 0,
      }}>
        {STAGES.map((stage, i) => {
          const isActive = i === currentIdx;
          const isCompleted = i < currentIdx;
          const isReachable = canNavigateTo(stage.id);

          return (
            <button
              key={stage.id}
              onClick={() => {
                if (isReachable || isCompleted) router.push(stage.path);
              }}
              disabled={!isReachable && !isCompleted && !isActive}
              style={{
                padding: '10px 20px',
                border: 'none',
                borderBottom: isActive ? `2px solid ${C.accent}` : '2px solid transparent',
                background: 'transparent',
                cursor: (isReachable || isCompleted) ? 'pointer' : 'default',
                fontFamily: mono,
                fontSize: 12,
                fontWeight: isActive ? 700 : 400,
                color: isActive ? C.dark : isCompleted ? C.info : isReachable ? C.muted : C.border,
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                transition: 'all 0.2s',
                opacity: (!isReachable && !isCompleted && !isActive) ? 0.4 : 1,
              }}
            >
              <span style={{ fontSize: 12 }}>{isCompleted ? '✓' : stage.icon}</span>
              <span>{stage.label}</span>
              {i < STAGES.length - 1 && (
                <span style={{
                  color: C.border, fontSize: 10, marginLeft: 8,
                }}>
                  →
                </span>
              )}
            </button>
          );
        })}
      </div>
    </header>
  );
}
