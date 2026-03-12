'use client';

import { useState, useRef, useEffect, useCallback } from 'react';

// ─── Types ──────────────────────────────────────────────────────────

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
}

interface InterrogationChatProps {
  /** Full attribution result context to send with each question */
  attributionContext: any;
  /** Market question/title */
  marketTitle: string;
  /** Pre-filled question (from scenario panel quick-ask buttons) */
  initialQuestion?: string;
  /** Clear the initial question after it's been sent */
  onInitialQuestionConsumed?: () => void;
}

// ─── Constants ──────────────────────────────────────────────────────

const C = {
  bg: '#faf9f5', surface: '#FFFFFF', dark: '#141413', accent: '#d97757',
  yes: '#788c5d', muted: '#b0aea5', border: '#e8e6dc', info: '#6a9bcc',
  faint: '#f5f4ef',
};

const mono = "'JetBrains Mono', monospace";
const serif = "'Source Serif 4', Georgia, serif";

// ─── Component ──────────────────────────────────────────────────────

export default function InterrogationChat({
  attributionContext,
  marketTitle,
  initialQuestion,
  onInitialQuestionConsumed,
}: InterrogationChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const initialSent = useRef(false);

  // Handle initial question from scenario panel
  useEffect(() => {
    if (initialQuestion && !initialSent.current) {
      initialSent.current = true;
      setIsOpen(true);
      sendQuestion(initialQuestion);
      onInitialQuestionConsumed?.();
    }
  }, [initialQuestion]);

  // Reset initial sent flag when initialQuestion changes
  useEffect(() => {
    if (!initialQuestion) initialSent.current = false;
  }, [initialQuestion]);

  // Auto-scroll
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  // Focus input when opened
  useEffect(() => {
    if (isOpen) inputRef.current?.focus();
  }, [isOpen]);

  const sendQuestion = useCallback(async (question: string) => {
    if (!question.trim() || isStreaming) return;

    // Add user message
    const userMsg: ChatMessage = { role: 'user', content: question.trim(), timestamp: Date.now() };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsStreaming(true);

    // Build context for the LLM
    const systemPrompt = buildSystemPrompt(attributionContext, marketTitle);
    const conversationHistory = [...messages, userMsg].map(m => ({
      role: m.role, content: m.content,
    }));

    try {
      const backendUrl = process.env.NEXT_PUBLIC_PYTHIA_API_URL || 'http://localhost:8000';
      const res = await fetch(`${backendUrl}/api/interrogate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: question.trim(),
          context: attributionContext,
          market_title: marketTitle,
          history: conversationHistory.slice(-6), // Last 3 turns
        }),
      });

      if (!res.ok || !res.body) {
        // Fallback: generate a local response
        const fallbackResponse = generateLocalResponse(question, attributionContext);
        setMessages(prev => [...prev, { role: 'assistant', content: fallbackResponse, timestamp: Date.now() }]);
        setIsStreaming(false);
        return;
      }

      // Stream the response
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let fullResponse = '';

      // Add placeholder assistant message
      setMessages(prev => [...prev, { role: 'assistant', content: '', timestamp: Date.now() }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Process SSE chunks
        while (buffer.includes('\n')) {
          const lineEnd = buffer.indexOf('\n');
          const line = buffer.slice(0, lineEnd);
          buffer = buffer.slice(lineEnd + 1);

          if (line.startsWith('data: ')) {
            const chunk = line.slice(6);
            if (chunk === '[DONE]') continue;
            try {
              const data = JSON.parse(chunk);
              if (data.text) {
                fullResponse += data.text;
                setMessages(prev => {
                  const updated = [...prev];
                  updated[updated.length - 1] = {
                    ...updated[updated.length - 1],
                    content: fullResponse,
                  };
                  return updated;
                });
              }
            } catch {
              // Plain text chunk
              fullResponse += chunk;
              setMessages(prev => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  content: fullResponse,
                };
                return updated;
              });
            }
          }
        }
      }

      // If no streaming worked, use fallback
      if (!fullResponse) {
        const fallbackResponse = generateLocalResponse(question, attributionContext);
        setMessages(prev => {
          const updated = [...prev];
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content: fallbackResponse,
          };
          return updated;
        });
      }
    } catch (err) {
      // Backend not available — generate local response
      const fallbackResponse = generateLocalResponse(question, attributionContext);
      setMessages(prev => [...prev, { role: 'assistant', content: fallbackResponse, timestamp: Date.now() }]);
    }

    setIsStreaming(false);
  }, [isStreaming, messages, attributionContext, marketTitle]);

  if (!isOpen) {
    return (
      <button
        onClick={() => setIsOpen(true)}
        style={{
          width: '100%', padding: '12px 20px',
          background: C.faint, border: `1px solid ${C.border}`,
          borderRadius: 8, cursor: 'pointer',
          fontFamily: mono, fontSize: 12, color: C.info,
          display: 'flex', alignItems: 'center', gap: 8,
          marginTop: 16, transition: 'all 0.2s',
        }}
        onMouseEnter={(e) => { (e.target as HTMLElement).style.borderColor = C.info; }}
        onMouseLeave={(e) => { (e.target as HTMLElement).style.borderColor = C.border; }}
      >
        <span style={{ fontSize: 14 }}>💬</span>
        Ask follow-up questions about this attribution…
      </button>
    );
  }

  return (
    <div style={{
      marginTop: 16,
      border: `1px solid ${C.border}`,
      borderRadius: 8,
      overflow: 'hidden',
      background: C.surface,
    }}>
      {/* Header */}
      <div style={{
        padding: '10px 16px',
        borderBottom: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        background: C.faint,
      }}>
        <span style={{ fontFamily: mono, fontSize: 11, fontWeight: 600, color: C.dark }}>
          💬 Interrogation
        </span>
        <button
          onClick={() => setIsOpen(false)}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            fontFamily: mono, fontSize: 14, color: C.muted, padding: '0 4px',
          }}
        >
          ✕
        </button>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        style={{
          maxHeight: 320,
          minHeight: messages.length > 0 ? 120 : 0,
          overflowY: 'auto' as const,
          padding: messages.length > 0 ? '12px 16px' : '0',
        }}
      >
        {messages.map((msg, i) => (
          <div key={i} style={{
            marginBottom: 12,
            display: 'flex',
            flexDirection: 'column' as const,
            alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start',
          }}>
            <div style={{
              maxWidth: '85%',
              padding: '8px 14px',
              borderRadius: msg.role === 'user' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
              background: msg.role === 'user' ? C.dark : C.faint,
              color: msg.role === 'user' ? '#e8e6dc' : C.dark,
              fontSize: 13,
              lineHeight: 1.6,
              fontFamily: msg.role === 'assistant' ? serif : mono,
              whiteSpace: 'pre-wrap' as const,
            }}>
              {msg.content || (
                <span style={{ color: C.muted, fontFamily: mono, fontSize: 11 }}>
                  Thinking…
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Suggested questions (when no messages yet) */}
      {messages.length === 0 && (
        <div style={{ padding: '12px 16px', display: 'flex', gap: 6, flexWrap: 'wrap' as const }}>
          {getSuggestedQuestions(attributionContext).map((q, i) => (
            <button
              key={i}
              onClick={() => sendQuestion(q)}
              style={{
                background: C.faint, border: `1px solid ${C.border}`,
                borderRadius: 20, padding: '5px 12px',
                fontFamily: mono, fontSize: 10, color: C.info,
                cursor: 'pointer', transition: 'all 0.2s',
              }}
            >
              {q}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div style={{
        padding: '10px 16px',
        borderTop: `1px solid ${C.border}`,
        display: 'flex', gap: 8,
      }}>
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && sendQuestion(input)}
          placeholder="Ask about the attribution…"
          disabled={isStreaming}
          style={{
            flex: 1, padding: '8px 12px',
            border: `1px solid ${C.border}`, borderRadius: 6,
            fontSize: 13, fontFamily: serif,
            background: C.surface, color: C.dark,
            outline: 'none',
            opacity: isStreaming ? 0.5 : 1,
          }}
        />
        <button
          onClick={() => sendQuestion(input)}
          disabled={isStreaming || !input.trim()}
          style={{
            padding: '8px 16px', borderRadius: 6,
            border: 'none', background: C.dark, color: C.bg,
            fontFamily: mono, fontSize: 12, fontWeight: 600,
            cursor: 'pointer', opacity: isStreaming || !input.trim() ? 0.4 : 1,
          }}
        >
          {isStreaming ? '…' : '→'}
        </button>
      </div>
    </div>
  );
}

// ─── Helpers ────────────────────────────────────────────────────────

function buildSystemPrompt(context: any, marketTitle: string): string {
  return `You are Pythia's attribution analyst. You've just completed a BACE (Backward Attribution Causal Engine) analysis of a prediction market spike.

Market: ${marketTitle}

The user is asking follow-up questions about the attribution results. Answer based on the attribution data provided. Be specific, cite agents and evidence from the analysis, and be honest about uncertainty.

Attribution context:
${JSON.stringify(context, null, 2).slice(0, 4000)}`;
}

function getSuggestedQuestions(context: any): string[] {
  const questions: string[] = [];
  const scenarios = context?.scenarios || [];
  const hypotheses = context?.hypotheses || context?.agent_hypotheses || [];

  if (scenarios.length > 1) {
    questions.push(`Why was "${(scenarios[0]?.label || '').slice(0, 30)}" ranked highest?`);
  }

  // Find devil's advocate
  const da = hypotheses.find((h: any) => (h.agent || '').toLowerCase().includes('devil') || (h.agent || '').toLowerCase().includes('advocate'));
  if (da) {
    questions.push("What did the Devil's Advocate think?");
  }

  questions.push('What evidence is weakest?');
  questions.push('Could this be a false signal?');

  if (scenarios.length > 1) {
    questions.push(`What would make Scenario B more likely?`);
  }

  return questions.slice(0, 4);
}

function generateLocalResponse(question: string, context: any): string {
  const q = question.toLowerCase();
  const scenarios = context?.scenarios || [];
  const hypotheses = context?.hypotheses || context?.agent_hypotheses || [];

  // Try to answer based on available data
  if (q.includes('devil') || q.includes('advocate') || q.includes('disagree')) {
    const da = hypotheses.find((h: any) =>
      (h.agent || '').toLowerCase().includes('devil') ||
      (h.agent || '').toLowerCase().includes('advocate')
    );
    if (da) {
      return `The Devil's Advocate (confidence: ${Math.round((da.confidence || 0) * 100)}%) argued:\n\n"${da.cause || da.hypothesis || 'No specific cause recorded'}"\n\nReasoning: ${(da.reasoning || da.causal_chain || 'Not available').slice(0, 300)}`;
    }
    return "The Devil's Advocate agent's specific hypothesis wasn't captured in the result data. This agent typically tests whether simpler explanations (noise, mean reversion, liquidity effects) can explain the spike.";
  }

  if (q.includes('evidence') && (q.includes('weak') || q.includes('change'))) {
    const allEvidence = hypotheses.flatMap((h: any) => h.evidence || []).filter((e: any) => e?.title);
    if (allEvidence.length > 0) {
      return `The evidence chain includes ${allEvidence.length} items. The weakest evidence points are typically those with "concurrent" timing (correlation, not necessarily causation) and those from social media or secondary sources. Key evidence:\n\n${allEvidence.slice(0, 3).map((e: any, i: number) => `${i + 1}. ${e.title} (${e.timing || 'timing unknown'})`).join('\n')}`;
    }
  }

  if (q.includes('scenario') || q.includes('ranked') || q.includes('highest') || q.includes('top')) {
    if (scenarios.length > 0) {
      const top = scenarios[0];
      return `"${top.label}" is ranked highest with ${Math.round((top.confidence || 0) * 100)}% confidence because:\n\n1. Lead agent (${top.lead_agent}) had the strongest evidence chain\n2. ${top.supporting_agents?.length || 0} supporting agents converged on this explanation\n3. Mechanism: ${top.mechanism}\n\n${top.causal_chain ? `Causal narrative: ${top.causal_chain.slice(0, 200)}` : ''}`;
    }
  }

  if (q.includes('false') || q.includes('noise') || q.includes('null')) {
    const nh = hypotheses.find((h: any) =>
      (h.agent || '').toLowerCase().includes('null') ||
      (h.agent || '').toLowerCase().includes('hypothesis')
    );
    if (nh) {
      return `The Null Hypothesis agent tested whether this spike is within normal variance. Its confidence was ${Math.round((nh.confidence || 0) * 100)}%.\n\n${(nh.cause || nh.hypothesis || '')}`;
    }
    return "The Null Hypothesis agent tests whether the spike magnitude falls within the market's normal volatility range. If the p-value is below 0.05, the spike is considered statistically significant and warrants causal explanation.";
  }

  // Generic response
  return `Based on the attribution analysis (${hypotheses.length} hypotheses from ${context?.agentsSpawned || context?.agents_spawned || '?'} agents):\n\nThe analysis covered ${scenarios.length} scenarios across mechanisms including ${scenarios.map((s: any) => s.mechanism).filter(Boolean).join(', ') || 'multiple categories'}.\n\nFor more detailed analysis, ensure the backend is running at ${process.env.NEXT_PUBLIC_PYTHIA_API_URL || 'http://localhost:8000'} — I'll be able to provide richer, LLM-powered answers.`;
}
