# Pythia Demo - UI Guide

## Design Philosophy

Modern elite finance — clean, sophisticated, and minimal. Inspired by the best of Stripe, Mercury, and Ramp with institutional-grade precision. Dark mode only with a refined indigo accent system.

## What Design Partners Will See

### Home Screen (Signal Feed)

```
┌─────────────────────────────────┐
│ Pythia  [Beta]           ● LIVE │
│ Real-time prediction market     │
│ intelligence                    │
│        [Track Record]           │
├─────────────────────────────────┤
│ (All) (Fed) (Tariffs) (Crypto)  │
│ (Geo) (Defense)                 │
├─────────────────────────────────┤
│ ┌───────────────────────────┐   │
│ │ Fed Rate Cut - March  HIGH│   │
│ │     15m ago               │   │
│ │                           │   │
│ │  Layers    Hit Rate  Edge │   │
│ │   3/8        73%    18hrs │   │
│ │                           │   │
│ │  Asset Impact:            │   │
│ │  TLT          +2.1%       │   │
│ │  SPY          +0.8%       │   │
│ │                           │   │
│ │  Polymarket · Congress    │   │
│ │  Twitter                  │   │
│ │                           │   │
│ │  [View Full Analysis →]   │   │
│ └───────────────────────────┘   │
│                                 │
│ ┌───────────────────────────┐   │
│ │ Bitcoin ETF Flows     MED │   │
│ │     45m ago               │   │
│ │  ...                      │   │
│ └───────────────────────────┘   │
└─────────────────────────────────┘
```

**Key features:**
- Live indicator (pulsing green dot with soft animation)
- Pill-shaped category filters (horizontal scroll)
- Signal cards with refined severity indicators
- Time ago ("15m ago" auto-updates)
- Key metrics visible at a glance
- Tap any card → detail view

---

### Signal Detail View

```
┌─────────────────────────────────┐
│ ← Back                 [Share]  │
├─────────────────────────────────┤
│ [HIGH SIGNAL]                   │
│                                 │
│ Fed Rate Cut - March FOMC       │
│ Feb 24, 2026 10:16 AM           │
├─────────────────────────────────┤
│ ┌─────────────┬─────────────┐  │
│ │ Confluence  │ Hit Rate    │  │
│ │    3/8      │   73%       │  │
│ │ layers fired│ n=47        │  │
│ └─────────────┴─────────────┘  │
│ ┌─────────────┬─────────────┐  │
│ │ Edge Window │ Confidence  │  │
│ │   18hrs     │   87%       │  │
│ │ median lead │ model score │  │
│ └─────────────┴─────────────┘  │
├─────────────────────────────────┤
│ Active Layers                   │
│                                 │
│ ● Polymarket (5.2% spike)      │
│ ● Congressional Trading (3 buys)│
│ ● Twitter Velocity (2.1x)      │
├─────────────────────────────────┤
│ Expected Asset Moves            │
│                                 │
│ TLT          +2.1%   (0.89)    │
│ SPY          +0.8%   (0.73)    │
│ DXY          -0.5%   (-0.68)   │
│ XLF          -0.3%   (-0.54)   │
├─────────────────────────────────┤
│ Historical Precedent            │
│                                 │
│ 2025-12-18                      │
│ Fed cut 25bps as predicted      │
│ TLT +2.3% within 24h           │
├─────────────────────────────────┤
│ ⏱ Edge Window Active           │
│                                 │
│ Historical data shows this      │
│ signal type decays within 18hrs │
└─────────────────────────────────┘
```

---

## Design System

### Colors — Modern Elite Finance

**Surfaces (cool near-black):**
- Primary: `#09090b`
- Secondary: `#111114`
- Card: `#131316`
- Elevated: `#1a1a1f`
- Hover: `#1c1c22`

**Text:**
- Primary: `#f4f4f5` (crisp white)
- Secondary: `#a1a1aa` (readable gray)
- Muted: `#63637a` (subtle)

**Accent (refined indigo):**
- Primary: `#635bff`
- Hover: `#7c75ff`
- Text: `#818cf8`
- Muted: `rgba(99, 91, 255, 0.10)`

**Semantic:**
- Positive: `#10b981` (emerald)
- Negative: `#f43f5e` (rose)
- Warning: `#f59e0b` (amber)
- Info: `#3b82f6` (blue)

### Severity Levels

| Level | Color | Border | Meaning |
|-------|-------|--------|---------|
| Critical | Rose `#f43f5e` | Left accent + inner glow | 4+ layers, immediate attention |
| High | Orange `#f97316` | Left accent + inner glow | 3 layers, act within hours |
| Medium | Yellow `#eab308` | Left accent + subtle glow | 2 layers, monitor closely |
| Low | Emerald `#10b981` | Left accent + subtle glow | 1 layer, watch for confirmation |

### Typography

- **Sans-serif:** Inter (primary UI font)
- **Monospace:** JetBrains Mono (data values)
- **Headings:** -0.02em to -0.03em letter-spacing
- **Labels:** Uppercase, 0.06em letter-spacing

### Spacing

Generous breathing room:
- xs: 4px, sm: 8px, md: 14px, lg: 20px, xl: 28px, 2xl: 40px

### Border Radius

Modern rounded:
- sm: 8px, md: 10px, lg: 14px, xl: 20px
- Badges/pills: 100px (fully rounded)

### Shadows

Subtle depth system:
- sm: `0 1px 2px rgba(0, 0, 0, 0.3)`
- md: `0 4px 12px rgba(0, 0, 0, 0.25)`
- lg: `0 8px 24px rgba(0, 0, 0, 0.3)`
- glow: `0 0 20px rgba(99, 91, 255, 0.08)`

---

## Mobile Interactions

### Tap Gestures
1. **Tap signal card** → Navigate to detail view
2. **Tap category filter** → Filter signals by category
3. **Tap back arrow** → Return to feed
4. **Tap share button** → Open native share sheet

### Swipe Gestures
- **Horizontal scroll** on category filters
- **Vertical scroll** on signal feed

### Native Behaviors
- **Share button** → iOS/Android native share sheet
- **Links** → Open in external browser
- **Add to Home Screen** → Install as PWA

---

## Responsive Design

### Mobile (Primary)
- Single column layout
- Full-width cards
- Touch-optimized tap targets (min 44×44px)
- Category filters scroll horizontally

### Tablet
- Same as mobile (optimized for portrait)
- Max width: 768px centered

### Desktop
- Max width: 680px centered
- Mouse hover states with subtle elevation
- Keyboard navigation support

---

## Dark Mode Only

**Why:** Traders and finance professionals prefer dark interfaces. It reduces eye strain during extended sessions and conveys a premium, professional aesthetic.

---

## Accessibility

- Semantic HTML (header, main, nav)
- ARIA labels on interactive elements
- Tab order follows visual flow
- Touch targets minimum 44×44px
- Color contrast compliant

---

*Built Feb 2026 | Mobile-first, modern elite finance*
