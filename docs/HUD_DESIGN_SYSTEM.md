# DreamLayer — HUD Design System

## Philosophy
Calm, glanceable, premium. One thought at a time. The HUD should feel composed,
never like terminal output. Outlines over heavy fills. Generous breathing room.

## Display target
- 256×256 **circular** color display
- Direct rendering (no Frame-style double buffering)
- Safe content sits inside a circular inset (~16px margin) to avoid edge clipping

## Color system (semantic tokens)
| Token            | Hex      | Role |
|------------------|----------|------|
| background       | #000000  | full black canvas |
| surface          | #0E1416  | card shell fill (subtle) |
| text_primary     | #FFFFFF  | the one thing that matters |
| text_secondary   | #8A9BA3  | cool slate, supporting lines |
| accent_memory    | #2FD4C4  | teal — trusted memory / info |
| accent_attention | #FF6B5E  | coral — active / proactive |
| accent_success   | #56D364  | confirmations (memory saved) |
| accent_error     | #FF5C5C  | errors |
| border_subtle    | #1F2A2E  | hairline outlines |
| status_paused    | #6B7A82  | muted blue-gray paused state |

Never scatter raw hex in logic — use `palette.lua` / `themes.py` tokens.

## Card anatomy
```
        ( accent eyebrow / label )      <- text_secondary or accent
        ===========================
              PRIMARY LINE             <- text_primary, largest
            secondary line             <- text_secondary
            detail line                <- text_secondary, smaller
        - - - - - - - - - - - - - -
        timestamp / confidence dot     <- footer
```
- Max ~5 short lines
- Title block centered; vertical optical centering on the circular display

## Spacing
- Outer safe inset: 16px
- Line spacing: 1.35× cap height
- Min legible body size abstraction: `typography.SIZE_SM`

## Motion rules
- fade in/out: ~180ms
- slide up: ~220ms, small travel (8–12px)
- idle breathing: 2.4s ease-in-out loop, opacity 0.55→1.0
- No flashy sci-fi. Motion supports confidence, never distracts.
- All motion can be disabled (`settings.reduce_motion`).

## All HUD states (cards)
ReadyCard, SavedMemoryCard, QueryListeningCard, LoadingCard, ObjectRecallCard,
CommitmentRecallCard, ProactiveMemoryCard, PersonContextCard, PrivacyVeilCard,
ErrorCard, LowConfidenceCard.

## Do / Don't
- DO: "Keys / Kitchen table / Beside blue notebook / 7:42 PM"
- DON'T: paragraphs, dense menus, debug text, more than one accent color per card
- DO: show a single confidence dot; DON'T print raw scores in-eye
