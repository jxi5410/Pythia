# Pythia Hero Panel — Design Template v1.0

## Layout Structure

```
┌──────────────────────────────────────────────────────────────┐
│ [Category · Subcategory]                        [↗] [☆]     │  ← 10px top
│ Event Title (Newsreader 23px bold, 2-line clamp)            │  ← 4px gap
│                                                              │
│ ┌─LEFT (280px fixed)──────┐ ┌─RIGHT (flex 1)──────────────┐│
│ │ [P] Source    ● Live    │ │                              ││  ← 20px top
│ │                         │ │  ┌─────────────────────────┐ ││
│ │  Market  Pays out  Odds │ │  │  SVG Chart (860×330)    │ ││  ← 16px gap
│ │  ─────────────────────  │ │  │  - #d97757 price line   │ ││
│ │  Yes  1.39x     72%    │ │  │  - Volume bars (8% α)   │ ││
│ │  ────── (#788c5d)       │ │  │  - Spike shades + P/–   │ ││
│ │  No   3.57x     28%    │ │  │  - Y-axis right (5% inc)│ ││
│ │  ────── (#d97757)       │ │  │  - X-axis dates bottom  │ ││
│ │                         │ │  │  - Crosshair + tooltip   │ ││
│ │  $18M Vol              │ │  └─────────────────────────┘ ││  ← 16px gap
│ │  Ends Mar 19, 2026    │ │                              ││
│ │  9d left               │ │                              ││
│ └─────────────────────────┘ └──────────────────────────────┘│
│ ─────────────────────────────────────────────────────────────│  ← border-top
│ ●━● ● ●            ‹ Prev event  │  Next event ›           │  ← nav row
└──────────────────────────────────────────────────────────────┘
```

## Fixed Dimensions
- Panel height: **480px** (min/max locked)
- Panel max-width: **1180px**
- Left column: **280px** fixed
- Border radius: **22px**
- Chart SVG viewBox: **860×330**

## Colors (Claude/Anthropic Palette)
- Background: `#faf9f5` (warm off-white)
- Panel: `rgba(255,255,255,0.84)` + `backdrop-filter: blur(10px)`
- Primary/Yes: `#788c5d` (sage green)
- Secondary/No: `#d97757` (terra cotta)
- Chart line: `#d97757` (always)
- Text dark: `#141413`
- Text muted: `#b0aea5`
- Borders: `#e8e6dc`
- Info accent: `#6a9bcc`

## Typography
- Display: `Newsreader` (editorial serif)
- Body: `Source Serif 4`
- Mono: `JetBrains Mono`
- Title: 23px/700
- Category: 13px/500
- Odds: 14-15px/600-700
- Supplemental: 12px
- Nav: 12px/500, arrows 18px

## Interactive Behaviors
- **Crosshair**: vertical line + dot on hover, shows date/time + probability + volume + cumulative volume
- **Spike shading**: transparent colored regions with edge lines
- **P/– markers**: circle at top-center of spike. P = attributors detected (#d97757), – = none (#b0aea5)
- **Click spike → pin popup**: shows duration, move, range, start/end dates, attributors with source links. Close via ✕ or click chart.
- **Bookmark ☆/★**: toggles state, no box border
- **Share ↗**: Web Share API or clipboard
- **Source logo**: clickable link to source event
- **Live indicator**: green pulsing dot, right of source logo
- **Nav row**: grey arrows/text (#b0aea5), vertical divider, 270px fixed width per button, smart text shortening

## Data Contract (API → Component)
```typescript
interface MarketData {
  id: string;
  question: string;
  category: string;
  probability: number;
  previousProbability: number;
  volume24h: number;
  totalVolume: number;
  liquidity: number;
  endDate: string;           // ISO
  source: string;            // 'polymarket' | 'kalshi'
  sourceUrl: string;         // links to source event
  trending: boolean;
  tags: string[];
  probabilityHistory: number[];   // 200 points, 30 days
  volumeHistory: number[];        // same length, normalized to totalVolume
  spikeAttributors: Record<number, SpikeAttributor[]>;  // per spike index
}
```

## Live Update
- `useLiveMarkets(30000)` — polls `/api/markets` every 30s
- Chart, odds, volume all re-render on new data
- `lastUpdated` timestamp anchors date calculations
- Selected market auto-syncs with fresh data via useEffect
