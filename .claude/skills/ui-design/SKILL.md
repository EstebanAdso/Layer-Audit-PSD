---
name: ui-design
description: Use when modifying the visual layout, typography, colors, spacing, or components of the Layer Audit PSD GUI (gui.py — Tkinter app). Encodes the design system, ttk gotchas, and refactoring patterns specific to this codebase. Triggers on requests like "improve the design", "make the UI cleaner", "the X looks cramped", "rediseña Y", "tipografía", "espaciado", "colores".
---

# UI Design — Layer Audit PSD

This is a Tkinter desktop app for designers / automation engineers. The visual language is **clean, neutral, indigo-accented**, leaning closer to Linear / Vercel than to native OS chrome. Every change should reinforce that direction.

## Design tokens

These constants live at the top of `gui.py`. Treat them as the source of truth — when you add new UI, pick from this palette rather than introducing new values.

### Color palette (already defined)
```
BG          #f1f3f9   page background (outside cards)
SURFACE     #ffffff   card / panel background
SURFACE_ALT #f8fafc   secondary surface (toolbar filters, badges)
BORDER      #e2e8f0   1-px separators and inactive indicators
TEXT        #0f172a   primary text
TEXT_MUTED  #64748b   secondary text, captions, placeholders
PRIMARY     #4f46e5   indigo — primary actions, accents, focus
PRIMARY_HOV #4338ca   indigo hover
PRIMARY_DIM #a5b4fc   indigo at low emphasis (queued state)
OK          #16a34a   green — success/OK status text
OK_BG       #dcfce7   green pill background
ERR         #dc2626   red — error/problem status text
ERR_BG      #fee2e2   red pill background
WARN        #d97706   amber — in-progress destructive ops (REPARANDO)
WARN_BG     #fef3c7   amber pill background
SELECTED_BG #eef2ff   row background when selected
HOVER_BG    #f8fafc   row background on hover
```

### Typography scale
Use these named tuples instead of repeating raw `('Segoe UI', 9)` everywhere. When introducing new text, pick the closest role.

| Token | Spec | Role |
|---|---|---|
| `FONT_TITLE` | `('Segoe UI', 13, 'bold')` | Panel headings ("Detalles") |
| `FONT_SUBTITLE` | `('Segoe UI', 10)` | Subtitles / file path under heading |
| `FONT_BODY_BOLD` | `('Segoe UI', 10, 'bold')` | File name in a row, important labels |
| `FONT_BODY` | `('Segoe UI', 10)` | Default text, button labels, list items |
| `FONT_CAPTION` | `('Segoe UI', 9)` | Status text, secondary metadata, badges |
| `FONT_MICRO` | `('Segoe UI', 8)` | Path lines, version tag, footnotes |
| `FONT_MONO` | `('Consolas', 9)` | Coordinates, transform values, layer IDs |

### Spacing scale (4-px grid)
```
SPACE_XS  = 4    # internal padding of pills, tight clusters
SPACE_SM  = 8    # gap between siblings in a row
SPACE_MD  = 12   # gap between control groups
SPACE_LG  = 16   # card inner padding
SPACE_XL  = 24   # section separation
```

Stick to this scale. Mixing 6, 10, 14 px ad-hoc creates visual noise.

## Component recipes

### Status pill (the right way to show state)
Don't just color text. A pill = `tk.Label` with `bg`, `fg`, padding `padx=8 pady=2`, `font=FONT_CAPTION`, and a 1-pixel border via `highlightthickness=1, highlightbackground=...`.

```python
def make_pill(parent, text, fg, bg):
    return tk.Label(parent, text=text, fg=fg, bg=bg,
                    font=FONT_CAPTION, padx=SPACE_SM, pady=2,
                    highlightthickness=0)
```

Pill color combos (always pair `fg` with the matching `_BG`):
- OK → `fg=OK, bg=OK_BG`
- Problemas → `fg=ERR, bg=ERR_BG`
- Reparando → `fg=WARN, bg=WARN_BG`
- En cola / Analizando → `fg=PRIMARY, bg=SELECTED_BG`
- Pendiente / Sin analizar → `fg=TEXT_MUTED, bg=SURFACE_ALT`

### Card (panels in the layout)
A card = `tk.Frame` with `bg=SURFACE`, surrounded by `highlightthickness=1, highlightbackground=BORDER`. Inner padding `SPACE_LG`. No rounded corners (Tk can't easily). The border-only outline reads as "card" without needing a shadow.

### Section heading inside a card
`tk.Label(parent, text=..., font=FONT_TITLE, fg=TEXT, bg=SURFACE, anchor='w')` followed by an optional subtitle in `FONT_SUBTITLE, fg=TEXT_MUTED`.

### Toolbar / filter band
Place primary actions (buttons) on one row with `SURFACE` bg. Secondary controls (checkboxes, filters) on a separate row below with `SURFACE_ALT` bg, prefixed by a muted "Filtros:" label. **Never mix actions and filters on the same row** — primary actions get cropped first on narrow windows.

## ttk gotchas (the painful ones)

These are tripwires I keep stepping on:

1. **`ttk.Checkbutton` does not inherit `bg` from a `tk.Frame` parent**. When you place a checkbutton on a `SURFACE_ALT` background, you'll get a default-gray box around the text. Fix: declare a per-context style:
   ```python
   ttk.Style().configure('Filter.TCheckbutton', background=SURFACE_ALT)
   ttk.Style().map('Filter.TCheckbutton', background=[('active', SURFACE_ALT)])
   ```
   Same issue for `ttk.Button` if you have non-default surroundings — but our default `'clam'` theme handles buttons OK with the existing `Primary.TButton` style.

2. **`ttk.Progressbar` color must be set via Style, not `config(bg=...)`**. To get a status-colored bar:
   ```python
   ttk.Style().configure('Done.Horizontal.TProgressbar',
                         background=OK, troughcolor=BORDER, borderwidth=0)
   ```
   Then `bar.config(style='Done.Horizontal.TProgressbar')`.

3. **`'clam'` theme is the only ttk theme that respects custom colors cross-platform**. Don't switch themes mid-session; everything is calibrated for clam.

4. **Recursive `bg` propagation**. When a row is selected and you change its background, you must walk every descendant — children don't inherit. There's already a `_recursive_bg` helper in `gui.py` — use it. Don't duplicate that traversal.

5. **`tk.Frame` cannot have rounded corners**. If you need a "pill" look, simulate with a `Label` + `bg` + small `padx/pady`. For shadows, use a 1-px `BORDER` outline (`highlightthickness=1`). Resist the urge to ship custom Canvas drawings — they don't scale on HiDPI.

6. **`'hand2'` cursor on clickable text is the only universal click affordance** in Tkinter. Always set `cursor='hand2'` on any `tk.Label` or `tk.Frame` that responds to `<Button-1>`. Without it the user gets no visual hint.

7. **Hover states require explicit `<Enter>` / `<Leave>` bindings**. There's no CSS `:hover`. Bind both, swap `bg` or `fg`, and remember to skip hover changes when the row is in a "busy" state (`ST_RUNNING`, `ST_QUEUED`, `ST_FIXING`).

## Refactor patterns

When asked to "improve the design" of an area:

1. **Identify what state is being communicated.** Each FileRow encodes: idle, queued, running, fixing, fixed, done-OK, done-error, done-problems. Each state should have a *single* unambiguous visual treatment — pill text, pill color, indicator stripe, progress bar mode/color. If the same state is encoded redundantly (e.g. green left bar + green text + green bar), pick one canonical channel and tone down the others.

2. **Walk the type scale.** Grep for `('Segoe UI'` and check whether each occurrence maps to a `FONT_*` token. New ad-hoc font specs are a smell.

3. **Walk the spacing scale.** Grep for `padx=` / `pady=` / `padding=` and check for off-grid values (6, 10, 14, 18). Snap to the 4-px scale.

4. **Empty / loading states deserve as much polish as the happy path.** A blank "select something to start" state shouldn't be a paragraph of muted text alone. Use a centered glyph + heading + 2-line subtitle for emphasis.

5. **Selected state needs more than a `bg` change.** Add a stronger indicator (e.g. left stripe goes from neutral → `PRIMARY`) so the active row stands out from a hover state.

6. **Don't add emojis or icons.** The project rule is no emojis in code/files unless asked. Use ASCII symbols (`▶`, `↻`, `✕`, `•`, `›`) sparingly — they render consistently across OSes without bringing in icon fonts.

## When in doubt

- Prefer **subtlety over flash**: 1-px borders, muted captions, generous whitespace.
- **Hierarchy by typography first, color second**. Color is the accent, not the structure.
- **Status colors must always pair with their `_BG`**. Never `fg=ERR` on `bg=SURFACE` — too harsh; use `fg=ERR, bg=ERR_BG` as a pill.
- **One primary action per view**. The "Analizar Todo" button is THE primary. "Corregir capas" inside the details is also primary in its context. Avoid more than one indigo `Primary.TButton` visible at the same time.

If a request can't be satisfied within these constraints, raise it explicitly — adding a new color token, font size, or component recipe should be a deliberate decision, not a drift.
