# Live Monitor Panel - Final Design

## Layout Structure
```
┌─────────────────────────────────┐
│ ⚡ LIVE MONITOR      [STATUS]   │  ← Fixed header
├─────────────────────────────────┤
│ ████████████░░░░░░░░░░░░░░░░░░ │  ← Progress bar (processing only)
├─────────────────────────────────┤
│                                 │
│   SCROLLABLE STEP HISTORY       │  ← Oldest completed at top
│   (dynamic height)              │    Most recent completed at bottom
│                                 │    Current step at very bottom
├─────────────────────────────────┤
│ ▶ Warnings & Errors (0)        │  ← Collapsible section
└─────────────────────────────────┘
```

---

## STATE 1: IDLE
```
┌─────────────────────────────────┐
│ ⚡ LIVE MONITOR          ONLINE │
├─────────────────────────────────┤
│         ╭───────────╮           │
│         │     ✓     │           │
│         ╰───────────╯           │
│       Systems Online            │
├─────────────────────────────────┤
│ ▶ Warnings & Errors (0)        │  ← Collapsed by default
└─────────────────────────────────┘
```

---

## STATE 2: PROCESSING
```
┌─────────────────────────────────┐
│ ⚡ LIVE MONITOR      PROCESSING │
├─────────────────────────────────┤
│ ████████████░░░░░░░░░░░░░░░░░░ │  
├─────────────────────────────────┤  ↑ SCROLLABLE AREA
│ ✓ Query Expansion       (2.1s) │  ← Oldest completed (top)
│   • Semantic analysis           │
│   • Context building            │
│                                 │
│ ✓ Deep Research        (18.3s) │  ← More recent (closer to current)
│   • Searching 50 papers         │
│   • Filtering results           │
├─────────────────────────────────┤
│ ┌─────────────────────────────┐ │
│ │ 🔄 Neural Reranking         │ │  ← CURRENT (always at bottom)
│ │    ○ Optimizing relevance   │ │
│ │    Elapsed: 5.2s            │ │  ← Live timer (updates every 1s)
│ └─────────────────────────────┘ │
├─────────────────────────────────┤
│ ▼ Warnings & Errors (2)        │  ← Expanded (has items)
│ ⚠️ Low source count detected   │
│ ⚠️ API latency high            │
└─────────────────────────────────┘
```

**Step Order (top to bottom):**
1. Oldest completed step
2. Second oldest completed
3. ... 
4. Most recently completed
5. **CURRENT STEP** (highlighted, always at bottom of step list)

---

## STATE 3: COMPLETE
```
┌─────────────────────────────────┐
│ ⚡ LIVE MONITOR        COMPLETE │
├─────────────────────────────────┤
│         ╭───────────╮           │
│         │     ✓     │           │
│         ╰───────────╯           │
│       Analysis Complete         │
│       45.2s • 15 sources        │
├─────────────────────────────────┤
│ PROCESS HISTORY (scrollable)   │
│ ✓ Query Expansion       (2.1s) │  ← Oldest at top
│ ✓ Deep Research        (18.3s) │
│ ✓ Neural Reranking      (5.2s) │
│ ✓ Response Synthesis   (15.8s) │
│ ✓ Verification          (3.8s) │  ← Most recent at bottom
├─────────────────────────────────┤
│ ▶ Warnings & Errors (2)        │  ← Stays collapsed but shows count
└─────────────────────────────────┘
```

---

## Collapsible Warnings Section

```
Collapsed (default):
├─────────────────────────────────┤
│ ▶ Warnings & Errors (0)        │  ← Click to expand
└─────────────────────────────────┘

Expanded (when has items):
├─────────────────────────────────┤
│ ▼ Warnings & Errors (3)        │  ← Click to collapse
│ ⚠️ Low source count detected   │
│ ⚠️ API latency high            │
│ ❌ Reranker timeout, retried   │
└─────────────────────────────────┘
```

**Behavior:**
- Collapsed by default
- Shows count in header: `(0)`, `(2)`, etc.
- Expands vertically as more warnings appear
- Never deletes previous warnings
- All warnings persist until next query

---

## Dynamic Sizing

| Panel State | Height |
|-------------|--------|
| IDLE | Compact (~180px) |
| PROCESSING (few steps) | Medium (~300px) |
| PROCESSING (many steps) | `max-height: calc(100vh - 120px)`, scrollable |
| COMPLETE | Medium-large, scrollable history |
| Warnings expanded | Grows downward as needed |

**CSS approach:**
```css
.step-history {
    max-height: 400px;      /* Limit height */
    overflow-y: auto;       /* Scroll when exceeded */
    min-height: 100px;      /* Minimum readable area */
}
.warnings-section {
    max-height: 150px;      /* Cap warnings area */
    overflow-y: auto;       /* Scroll if too many */
}
```

---

## Section Mode Display

```
│ ✓ Query Expansion       (2.1s) │
│ ✓ Deep Research        (18.3s) │
│ ✓ Section (1/7)         (6.1s) │  ← Completed sections
│   • Searching                   │
│   • Reranking                   │
│   • Writing                     │
│ ✓ Section (2/7)         (7.3s) │
├─────────────────────────────────┤
│ ┌─────────────────────────────┐ │
│ │ 🔄 Section (3/7)            │ │  ← Current section
│ │    ✓ Searching               │ │
│ │    ○ Reranking              │ │  ← Active sub-step
│ │    ○ Writing                 │ │
│ │    Elapsed: 4.8s            │ │
│ └─────────────────────────────┘ │
```

---

## Implementation Notes

1. **Panel container**: Fixed position, right side
2. **Step history**: Scrollable div, auto-scroll to bottom as new steps complete
3. **Current step**: Always visible at bottom of step area
4. **Live timer**: JavaScript interval updating every 1000ms
5. **Warnings**: Separate collapsible section, persists all warnings
6. **Dynamic height**: CSS min/max-height with overflow scroll
