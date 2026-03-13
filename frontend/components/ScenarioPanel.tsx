'use client';

import { useState } from 'react';

// ─── Types ──────────────────────────────────────────────────────────

export interface ScenarioEvidence {
  source: string;
  title: string;
  url: string | null;
  timestamp: string | null;
  timing: 'before' | 'concurrent' | 'after';
}

export interface Scenario {
  id: string;
  label: string;
  mechanism: string;
  tier: 'primary' | 'alternative' | 'dismissed';
  confidence: number;
  lead_agent: string;
  supporting_agents: string[];
  challenging_agents: string[];
  evidence_chain: string[];
  evidence_urls: string[];
  what_breaks_this: string;
  causal_chain: string;
  temporal_fit: string;
  impact_speed: string;
  time_to_peak: string;
  revision_count?: number;
  dismissed_reason?: string;
}

/** Full attribution result with scenarios */
export interface ScenarioAttribution {
  depth: number;
  agentsSpawned: number;
  hypothesesProposed: number;
  debateRounds: number;
  elapsed: number;
  scenarios: Scenario[];
  governance?: { decision: string; reason: string; run_id?: string };
}

// ─── Constants ──────────────────────────────────────────────────────

const C = {
  bg: '#faf9f5', surface: '#FFFFFF', dark: '#141413', accent: '#d97757',
  yes: '#788c5d', muted: '#b0aea5', border: '#e8e6dc', info: '#6a9bcc',
  faint: '#f5f4ef',
};

const mono = "'JetBrains Mono', monospace";
const serif = "'Source Serif 4', Georgia, serif";

const MECHANISM_ICONS: Record<string, string> = {
  'macro_policy': '📊',
  'informed_flow': '🐋',
  'sentiment_narrative': '📡',
  'cross_market': '🔗',
  'geopolitical': '🌍',
  'regulatory': '⚖',
  'technical': '📈',
  'null': 'ℍ',
  'other': '◆',
};

const AGENT_COLORS: Record<string, string> = {
  'macro-policy': '#4a90d9',
  'Macro Policy Analyst': '#4a90d9',
  'informed-flow': '#e8a838',
  'Informed Flow Analyst': '#e8a838',
  'narrative-sentiment': '#9b59b6',
  'Narrative & Sentiment Analyst': '#9b59b6',
  'cross-market': '#2ecc71',
  'Cross-Market Analyst': '#2ecc71',
  'geopolitical': '#e74c3c',
  'Geopolitical Analyst': '#e74c3c',
  'devils-advocate': '#d97757',
  "Devil's Advocate": '#d97757',
  'null-hypothesis': '#95a5a6',
  'Null Hypothesis': '#95a5a6',
  'regulatory': '#1abc9c',
  'Regulatory Analyst': '#1abc9c',
  'technical-microstructure': '#f39c12',
  'Technical Microstructure': '#f39c12',
};

// ─── Component ──────────────────────────────────────────────────────

interface ScenarioPanelProps {
  attribution: ScenarioAttribution;
  isLive: boolean;
  onAskQuestion?: (question: string) => void;
}

export default function ScenarioPanel({ attribution, isLive, onAskQuestion }: ScenarioPanelProps) {
  const { scenarios } = attribution;
  const primary = scenarios.filter(s => s.tier === 'primary');
  const alternative = scenarios.filter(s => s.tier === 'alternative');
  const dismissed = scenarios.filter(s => s.tier === 'dismissed');

  const [activeTab, setActiveTab] = useState<string>(primary[0]?.id || scenarios[0]?.id || '');
  const [showAlternatives, setShowAlternatives] = useState(false);
  const [showDismissed, setShowDismissed] = useState(false);

  const activeScenario = scenarios.find(s => s.id === activeTab);

  return (
    <div style={{ padding: '16px 0' }}>
      {/* Compact run stats — single line */}
      <div style={{ fontFamily: mono, fontSize: 10, color: C.muted, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span>{attribution.agentsSpawned} agents · {attribution.hypothesesProposed} hypotheses · {attribution.elapsed.toFixed(1)}s</span>
        <span style={{ color: isLive ? C.yes : C.accent }}>{isLive ? '● live' : '⚠ simulated'}</span>
        {isLive && attribution.governance && attribution.governance.decision === 'AUTO_RELAY' && (
          <span style={{ color: C.yes }}>✓</span>
        )}
        <span style={{ marginLeft: 'auto' }}>{primary.length} primary · {alternative.length} alt · {dismissed.length} dismissed</span>
      </div>

      {/* Primary scenario selector — inline pills, not tab bar */}
      {primary.length > 1 && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' as const }}>
          {primary.map((s) => {
            const isActive = activeTab === s.id;
            const confColor = s.confidence >= 0.6 ? C.yes : s.confidence >= 0.3 ? C.accent : C.muted;
            return (
              <button
                key={s.id}
                onClick={() => setActiveTab(s.id)}
                style={{
                  padding: '6px 14px',
                  border: `1px solid ${isActive ? confColor + '60' : C.border}`,
                  borderRadius: 20,
                  background: isActive ? confColor + '10' : 'transparent',
                  cursor: 'pointer',
                  fontFamily: mono,
                  fontSize: 11,
                  fontWeight: isActive ? 700 : 400,
                  color: isActive ? C.dark : C.muted,
                  display: 'flex', alignItems: 'center', gap: 5,
                  transition: 'all 0.2s',
                }}
              >
                <span style={{ fontSize: 11 }}>{MECHANISM_ICONS[s.mechanism] || '◆'}</span>
                <span>{s.label.length > 30 ? s.label.slice(0, 27) + '…' : s.label}</span>
                <span style={{ fontWeight: 700, fontSize: 10, color: confColor }}>{Math.round(s.confidence * 100)}%</span>
              </button>
            );
          })}
        </div>
      )}

      {/* Active scenario detail */}
      {activeScenario && activeScenario.tier === 'primary' && (
        <ScenarioDetail scenario={activeScenario} onAskQuestion={onAskQuestion} />
      )}

      {/* Alternative scenarios (expandable) */}
      {alternative.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <button
            onClick={() => setShowAlternatives(!showAlternatives)}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              fontFamily: mono, fontSize: 12, fontWeight: 600, color: C.muted,
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '8px 0',
            }}
          >
            <span style={{ fontSize: 10, transition: 'transform 0.2s', transform: showAlternatives ? 'rotate(90deg)' : 'none' }}>▶</span>
            Alternative scenarios ({alternative.length})
          </button>
          {showAlternatives && (
            <div style={{ display: 'flex', flexDirection: 'column' as const, gap: 8, marginTop: 8 }}>
              {alternative.map((s) => (
                <AlternativeCard
                  key={s.id}
                  scenario={s}
                  isActive={activeTab === s.id}
                  onClick={() => setActiveTab(s.id)}
                />
              ))}
              {activeScenario && activeScenario.tier === 'alternative' && (
                <ScenarioDetail scenario={activeScenario} onAskQuestion={onAskQuestion} />
              )}
            </div>
          )}
        </div>
      )}

      {/* Dismissed scenarios */}
      {dismissed.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <button
            onClick={() => setShowDismissed(!showDismissed)}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              fontFamily: mono, fontSize: 12, fontWeight: 600, color: C.muted,
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '8px 0',
            }}
          >
            <span style={{ fontSize: 10, transition: 'transform 0.2s', transform: showDismissed ? 'rotate(90deg)' : 'none' }}>▶</span>
            Dismissed ({dismissed.length}) — considered and rejected
          </button>
          {showDismissed && (
            <div style={{ display: 'flex', flexDirection: 'column' as const, gap: 6, marginTop: 8 }}>
              {dismissed.map((s) => (
                <DismissedCard key={s.id} scenario={s} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Scenario Detail (full view) ────────────────────────────────────

function ScenarioDetail({ scenario, onAskQuestion }: { scenario: Scenario; onAskQuestion?: (q: string) => void }) {
  const confColor = scenario.confidence >= 0.6 ? C.yes : scenario.confidence >= 0.3 ? C.accent : C.muted;

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${confColor}30`,
      borderRadius: 8,
      padding: '20px 24px',
    }}>
      {/* Confidence + lead agent header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <div style={{ width: 60, height: 8, borderRadius: 4, background: C.border, overflow: 'hidden' }}>
          <div style={{ width: `${scenario.confidence * 100}%`, height: '100%', borderRadius: 4, background: confColor }} />
        </div>
        <span style={{ fontFamily: mono, fontSize: 14, fontWeight: 700, color: confColor }}>
          {Math.round(scenario.confidence * 100)}% confidence
        </span>
        <span style={{ fontFamily: mono, fontSize: 11, color: AGENT_COLORS[scenario.lead_agent] || C.info }}>
          Lead: {scenario.lead_agent}
        </span>
        {scenario.revision_count !== undefined && scenario.revision_count > 0 && (
          <span style={{
            fontFamily: mono, fontSize: 9, padding: '1px 6px', borderRadius: 10,
            background: C.faint, border: `1px solid ${C.border}`, color: C.muted,
          }}>
            {scenario.revision_count} revision{scenario.revision_count !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Causal narrative */}
      {scenario.causal_chain && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontFamily: mono, fontSize: 10, fontWeight: 600, color: C.muted, textTransform: 'uppercase' as const, letterSpacing: 0.5, marginBottom: 6 }}>
            Causal Narrative
          </div>
          <div style={{ fontSize: 14, lineHeight: 1.7, color: C.dark, fontFamily: serif }}>
            {scenario.causal_chain}
          </div>
        </div>
      )}

      {/* Timing */}
      {(scenario.impact_speed || scenario.time_to_peak || scenario.temporal_fit) && (
        <div style={{ display: 'flex', gap: 16, marginBottom: 16, flexWrap: 'wrap' as const }}>
          {scenario.impact_speed && (
            <div style={{ flex: '1 1 140px' }}>
              <div style={{ fontFamily: mono, fontSize: 9, color: C.muted, textTransform: 'uppercase' as const, letterSpacing: 0.5, marginBottom: 3 }}>Impact Speed</div>
              <div style={{ fontFamily: mono, fontSize: 12, color: C.dark }}>{scenario.impact_speed}</div>
            </div>
          )}
          {scenario.time_to_peak && (
            <div style={{ flex: '1 1 140px' }}>
              <div style={{ fontFamily: mono, fontSize: 9, color: C.muted, textTransform: 'uppercase' as const, letterSpacing: 0.5, marginBottom: 3 }}>Time to Peak</div>
              <div style={{ fontFamily: mono, fontSize: 12, color: C.dark }}>{scenario.time_to_peak}</div>
            </div>
          )}
          {scenario.temporal_fit && (
            <div style={{ flex: '1 1 200px' }}>
              <div style={{ fontFamily: mono, fontSize: 9, color: C.muted, textTransform: 'uppercase' as const, letterSpacing: 0.5, marginBottom: 3 }}>Temporal Fit</div>
              <div style={{ fontFamily: mono, fontSize: 12, color: C.dark }}>{scenario.temporal_fit}</div>
            </div>
          )}
        </div>
      )}

      {/* Agent consensus */}
      <div style={{ display: 'flex', gap: 20, marginBottom: 16 }}>
        {scenario.supporting_agents.length > 0 && (
          <div>
            <div style={{ fontFamily: mono, fontSize: 9, color: C.muted, textTransform: 'uppercase' as const, letterSpacing: 0.5, marginBottom: 6 }}>Supporting Agents</div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' as const }}>
              {scenario.supporting_agents.map((a, i) => (
                <span key={i} style={{
                  fontFamily: mono, fontSize: 10, padding: '2px 8px', borderRadius: 10,
                  background: '#eef3e8', border: `1px solid ${C.yes}40`, color: C.yes,
                }}>
                  {a}
                </span>
              ))}
            </div>
          </div>
        )}
        {scenario.challenging_agents.length > 0 && (
          <div>
            <div style={{ fontFamily: mono, fontSize: 9, color: C.muted, textTransform: 'uppercase' as const, letterSpacing: 0.5, marginBottom: 6 }}>Challenging Agents</div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' as const }}>
              {scenario.challenging_agents.map((a, i) => (
                <span key={i} style={{
                  fontFamily: mono, fontSize: 10, padding: '2px 8px', borderRadius: 10,
                  background: '#fdf0ed', border: `1px solid ${C.accent}40`, color: C.accent,
                }}>
                  {a}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Evidence chain */}
      {scenario.evidence_chain.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontFamily: mono, fontSize: 10, fontWeight: 600, color: C.muted, textTransform: 'uppercase' as const, letterSpacing: 0.5, marginBottom: 6 }}>
            Evidence Chain
          </div>
          <div style={{ display: 'flex', flexDirection: 'column' as const, gap: 4 }}>
            {scenario.evidence_chain.map((ev, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'flex-start', gap: 8,
                fontSize: 12, lineHeight: 1.5, color: C.dark,
              }}>
                <span style={{ color: C.accent, fontFamily: mono, fontSize: 10, marginTop: 2, flexShrink: 0 }}>
                  {i + 1}.
                </span>
                <span style={{ fontFamily: serif }}>
                  {typeof ev === 'string' ? ev : (ev as any)?.title || String(ev)}
                </span>
              </div>
            ))}
          </div>
          {scenario.evidence_urls.length > 0 && (
            <div style={{ marginTop: 6, display: 'flex', gap: 8, flexWrap: 'wrap' as const }}>
              {scenario.evidence_urls.slice(0, 3).map((url, i) => (
                <a key={i} href={url} target="_blank" rel="noopener noreferrer"
                  style={{ fontFamily: mono, fontSize: 10, color: C.info, textDecoration: 'none' }}>
                  Source {i + 1} ↗
                </a>
              ))}
            </div>
          )}
        </div>
      )}

      {/* What breaks this scenario */}
      {scenario.what_breaks_this && (
        <div style={{
          background: '#fdf0ed', border: `1px solid ${C.accent}25`,
          borderRadius: 6, padding: '12px 16px', marginBottom: 16,
        }}>
          <div style={{ fontFamily: mono, fontSize: 10, fontWeight: 600, color: C.accent, textTransform: 'uppercase' as const, letterSpacing: 0.5, marginBottom: 4 }}>
            What Breaks This Scenario
          </div>
          <div style={{ fontSize: 13, lineHeight: 1.6, color: C.dark, fontFamily: serif }}>
            {scenario.what_breaks_this}
          </div>
        </div>
      )}

      {/* Quick interrogation shortcuts */}
      {onAskQuestion && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' as const, marginTop: 12 }}>
          {[
            `Why is "${scenario.label}" the top scenario?`,
            scenario.challenging_agents[0] ? `Why did ${scenario.challenging_agents[0]} disagree?` : null,
            `What evidence would change ${scenario.label}?`,
          ].filter(Boolean).map((q, i) => (
            <button
              key={i}
              onClick={() => onAskQuestion(q!)}
              style={{
                background: C.faint, border: `1px solid ${C.border}`,
                borderRadius: 20, padding: '5px 12px',
                fontFamily: mono, fontSize: 10, color: C.info,
                cursor: 'pointer', transition: 'all 0.2s',
              }}
              onMouseEnter={(e) => { (e.target as HTMLElement).style.background = C.border; }}
              onMouseLeave={(e) => { (e.target as HTMLElement).style.background = C.faint; }}
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Alternative scenario card ──────────────────────────────────────

function AlternativeCard({ scenario, isActive, onClick }: { scenario: Scenario; isActive: boolean; onClick: () => void }) {
  const confColor = scenario.confidence >= 0.3 ? C.accent : C.muted;
  return (
    <div
      onClick={onClick}
      style={{
        background: isActive ? C.surface : C.faint,
        border: `1px solid ${isActive ? confColor + '40' : C.border}`,
        borderRadius: 8, padding: '12px 16px', cursor: 'pointer',
        transition: 'all 0.2s',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 14 }}>{MECHANISM_ICONS[scenario.mechanism] || '◆'}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: mono, fontSize: 12, fontWeight: 600, color: C.dark }}>
            {scenario.label}
          </div>
          {scenario.causal_chain && (
            <div style={{ fontFamily: serif, fontSize: 12, color: C.muted, marginTop: 2, lineHeight: 1.4 }}>
              {scenario.causal_chain.slice(0, 100)}{scenario.causal_chain.length > 100 ? '…' : ''}
            </div>
          )}
        </div>
        <div style={{ width: 36, height: 6, borderRadius: 3, background: C.border, overflow: 'hidden', flexShrink: 0 }}>
          <div style={{ width: `${scenario.confidence * 100}%`, height: '100%', borderRadius: 3, background: confColor }} />
        </div>
        <span style={{ fontFamily: mono, fontSize: 11, fontWeight: 700, color: confColor, width: 32 }}>
          {Math.round(scenario.confidence * 100)}%
        </span>
      </div>
    </div>
  );
}

// ─── Dismissed scenario card ────────────────────────────────────────

function DismissedCard({ scenario }: { scenario: Scenario }) {
  return (
    <div style={{
      background: C.faint, border: `1px solid ${C.border}`,
      borderRadius: 6, padding: '10px 14px', opacity: 0.7,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 12, opacity: 0.5 }}>{MECHANISM_ICONS[scenario.mechanism] || '◆'}</span>
        <span style={{ fontFamily: mono, fontSize: 11, color: C.muted, textDecoration: 'line-through' as const }}>
          {scenario.label}
        </span>
        <span style={{ fontFamily: mono, fontSize: 10, color: C.muted, marginLeft: 'auto' }}>
          {Math.round(scenario.confidence * 100)}%
        </span>
      </div>
      {(scenario.dismissed_reason || scenario.what_breaks_this) && (
        <div style={{ fontFamily: serif, fontSize: 11, color: C.muted, marginTop: 4, paddingLeft: 20, lineHeight: 1.4 }}>
          Dismissed: {(scenario.dismissed_reason || scenario.what_breaks_this).slice(0, 120)}{(scenario.dismissed_reason || scenario.what_breaks_this).length > 120 ? '\u2026' : ''}
        </div>
      )}
      {scenario.challenging_agents.length > 0 && (
        <div style={{ fontFamily: mono, fontSize: 10, color: C.muted, marginTop: 2, paddingLeft: 20 }}>
          Challenged by: {scenario.challenging_agents.join(', ')}
        </div>
      )}
    </div>
  );
}
