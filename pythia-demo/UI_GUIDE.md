# Pythia Demo - UI Guide

## What Design Partners Will See

### Home Screen (Signal Feed)

```
┌─────────────────────────────────┐
│ 🎯 Pythia Live            ● LIVE│
│ Prediction Market Intelligence  │
├─────────────────────────────────┤
│ [🎯 All] [🏦 Fed] [📦 Tariffs]  │
│ [₿ Crypto] [🌍 Geo] [🛡️ Defense]│
├─────────────────────────────────┤
│ ┌───────────────────────────┐   │
│ │ 🏦  Fed Rate Cut - March  │HIGH│
│ │     15m ago               │   │
│ │                           │   │
│ │  Layers    Hit Rate  Edge │   │
│ │   3/8        73%    18hrs │   │
│ │                           │   │
│ │  Asset Impact:            │   │
│ │  TLT          +2.1%       │   │
│ │  SPY          +0.8%       │   │
│ │                           │   │
│ │  [Polymarket] [Congress]  │   │
│ │  [Twitter]                │   │
│ │                           │   │
│ │  Tap for full analysis  → │   │
│ └───────────────────────────┘   │
│                                 │
│ ┌───────────────────────────┐   │
│ │ ₿  Bitcoin ETF Flows      │MED │
│ │     45m ago               │   │
│ │  ...                      │   │
│ └───────────────────────────┘   │
│                                 │
│ ┌───────────────────────────┐   │
│ │ 📦  China Tariff          │CRIT│
│ │     2h ago                │   │
│ │  ...                      │   │
│ └───────────────────────────┘   │
└─────────────────────────────────┘
```

**Key features:**
- Live indicator (pulsing green dot)
- Category filter pills (horizontal scroll)
- Signal cards (color-coded by severity)
- Time ago ("15m ago" auto-updates)
- Key metrics visible at a glance
- Tap any card → detail view

---

### Signal Detail View

```
┌─────────────────────────────────┐
│ ← Back              [Share] 📤  │
├─────────────────────────────────┤
│ [HIGH ALERT]                    │
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
│ 🔗 Layers Fired                 │
│                                 │
│ ● Polymarket (5.2% spike)      │
│ ● Congressional Trading (3 buys)│
│ ● Twitter Velocity (2.1x)      │
├─────────────────────────────────┤
│ 📊 Asset Impact                 │
│                                 │
│ TLT          +2.1%   (0.89)    │
│ SPY          +0.8%   (0.73)    │
│ DXY          -0.5%   (-0.68)   │
│ XLF          -0.3%   (-0.54)   │
├─────────────────────────────────┤
│ 📜 Historical Precedent         │
│                                 │
│ 2025-12-18                      │
│ Fed cut 25bps as predicted      │
│ TLT +2.3% within 24h           │
│                                 │
│ 2025-11-07                      │
│ Fed held but dovish pivot       │
│ TLT +1.8% within 24h           │
├─────────────────────────────────┤
│ ⏱️ Edge Window Active           │
│                                 │
│ Historical data shows this      │
│ signal type decays within 18hrs │
│ (median). Act fast for maximum  │
│ alpha.                          │
└─────────────────────────────────┘
```

**Key features:**
- Back button + native share
- Severity badge at top
- 4 key metrics (grid layout)
- Layers fired (with specifics)
- Asset impact table (with correlation)
- Historical precedent (3 most recent)
- Edge window warning (calls to action)

---

## Color Coding

### Severity Levels

**Critical** (Red)
- Border: Red
- Badge: Red background
- Used for: High-impact, time-sensitive signals

**High** (Orange)
- Border: Orange
- Badge: Orange background
- Used for: Important signals with strong confluence

**Medium** (Yellow)
- Border: Yellow
- Badge: Yellow background
- Used for: Notable signals, moderate confidence

**Low** (Green)
- Border: Green
- Badge: Green background
- Used for: Informational signals

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
- **Pull to refresh** (future enhancement)

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
- Max width: 672px centered
- Mouse hover states
- Keyboard navigation support

---

## Dark Mode Only

**Why:** Traders prefer dark interfaces (Bloomberg/trading terminals standard).

**Colors:**
- Background: Slate 950 (very dark blue-black)
- Cards: Slate 900/800 (dark gray-blue)
- Text: Slate 100 (off-white)
- Accents: Blue 600 (primary actions)

---

## Performance Features

### Optimizations

1. **Static generation** for home page
2. **Dynamic API routes** for signals
3. **Auto-refresh** every 30s (configurable)
4. **Image optimization** (Next.js built-in)
5. **Font optimization** (Inter, preloaded)

### Loading States

- **Initial load:** Spinner + "Loading signals..."
- **Empty state:** "No signals yet" + check back message
- **Error state:** Generic error + retry button

---

## Accessibility

### Screen Reader Support

- Semantic HTML (header, main, nav)
- ARIA labels on interactive elements
- Alt text on icons (decorative marked as such)

### Keyboard Navigation

- Tab order follows visual flow
- Enter/Space activate buttons
- Escape closes modals (future)

### Touch Targets

- Minimum 44×44px (Apple HIG)
- Adequate spacing between tappable elements
- No accidental taps

---

## Future Enhancements (Post-Demo)

### Phase 1
- [ ] Pull-to-refresh
- [ ] Push notifications (opt-in)
- [ ] Dark/light mode toggle

### Phase 2
- [ ] Position tracking
- [ ] Personalized filters
- [ ] Historical signal browser

### Phase 3
- [ ] User accounts
- [ ] Subscription tiers
- [ ] Payment integration

---

## Testing Scenarios

### Happy Path

1. Load feed → see 3 signals
2. Tap Fed filter → see 1 Fed signal
3. Tap signal → see full detail
4. Tap share → native share sheet opens
5. Tap back → return to feed
6. Wait 30s → signals auto-refresh

### Edge Cases

- No signals available → empty state
- API error → error message
- Slow connection → loading state
- Invalid signal ID → 404 page

---

## Analytics to Track (Post-Deploy)

### User Behavior

- Page views (feed vs detail)
- Most-tapped signals
- Most-used filters
- Time spent on site
- Bounce rate

### Performance

- First Load time
- Time to Interactive
- Largest Contentful Paint
- Cumulative Layout Shift

---

*Built 24 Feb 2026 | Mobile-first, zero friction*
