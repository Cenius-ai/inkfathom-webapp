# Design direction — InkFathom

Committed for this product; every rendered surface consumes it. InkFathom is a
terminal tool, so the "surface" is the terminal cell grid: the same tokens below are
expressed as ANSI codes and layout rules in `inkfathom.py` (see the `design tokens`
block at the top of the file) instead of CSS.

## Archetype and style family

| Token | Value |
| --- | --- |
| Archetype | `cli` — help-first, plain line-oriented output, no TUI |
| Style family | calm-precise |
| Density | compact |
| Type personality | mono / mono — the terminal's own monospace; no font is fetched or embedded |
| Surface / mode | terminal dark (the honest CLI surface) |
| Layout | aligned terminal columns, box-drawing separators, help-first output |
| Shape language | monospace, no chrome; one `─` rule style on every table, no second border style |
| Signature | aligned columns; one accent for the primary signal; no colour-only signal |

## Colour

| Role | Value | Where |
| --- | --- | --- |
| Accent (CSS/OKLCH) | `oklch(0.58 0.12 161)` | documented token `ACCENT_OKLCH` |
| Accent (hex) | `#1e9063` | documented token `ACCENT_HEX`; the truthful value for any non-CSS consumer (charts, canvas, native theming) |
| Accent (terminal) | `\x1b[38;2;30;144;99m` | `ACCENT_ANSI` — used for the `WARNING` word only |
| Structural | bold / dim | column headers and ids (`BOLD`), rules and secondary meta (`DIM`) |
| Neutral ramp | the terminal's own foreground on its own background | no second palette, no background fills; contrast is the terminal's, and nothing is signalled by colour alone |

Rules:

* Colour is applied only when stdout is a TTY, `NO_COLOR` / `INKFATHOM_NO_COLOR` is
  unset, and `TERM` is not `dumb`. Piped, redirected and recorded output is plain text.
* The accent never carries the only copy of a meaning: the warning reads
  `WARNING: … FAILED` in words, ids are printed as text, empty states are sentences.

## Type ramp (cells)

| Level | Use |
| --- | --- |
| UPPERCASE + bold | table headers (`ID  CLIENT  DATE  INK`), product banner |
| Sentence case | result lines (`Added session S-… — client, date, 2.50 ml`) |
| Lowercase dim | meta lines (`4 sessions · newest first`) and rules |
| Sentence case, one line | every error, on stderr |

## Spacing scale

Two cells between columns, one blank line between client blocks, one rule
(`─` × content width) above and below each table. No other spacing exists.

## Motion

None. A CLI does not animate; there is nothing to honour `prefers-reduced-motion` for.
