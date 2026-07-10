# DreamLayer — full feature catalog

Every glasses feature, in demo order. Each row is a beat in the master film (`master`) and a standalone clip (`<id>`). The card is the real HUD renderer output.

| # | Section | Feature | VO line | Card |
|--:|---------|---------|---------|------|
| 1 | The morning | **Wake → your day** | Put the Halo on; the morning brief is already waiting. | `MorningBriefCard` |
| 2 | The morning | **Hey Juno** | A word wakes it — then just keep talking. | `ListeningCard` |
| 3 | The morning | **Ask it anything** | It runs the device or answers from your brain, in its own voice. | `JunoReplyCard` |
| 4 | In conversation | **Live captions** | Every word, transcribed at the rim. | `SpokenCaptionCard` |
| 5 | In conversation | **Look → who is this** | A glance names them and surfaces your history together. | `PersonDossierCard` |
| 6 | In conversation | **Faces at the rim** | Who they are, without staring. | `PersonContextCard` |
| 7 | In conversation | **The answer before you speak** | It overhears a question and hands you the answer in time. | `AnswerAheadCard` |
| 8 | In conversation | **Truth, checked live** | Flags a claim that doesn't hold up — or contradicts what they told you before. | `FactCheckCard` |
| 9 | In conversation | **Read the room** | Delivery signals fused into one credibility read. | `TruthLensCard` |
| 10 | In conversation | **A tap on the shoulder** | Listen! — the one thing worth hearing, right now. | `HarkCard` |
| 11 | Memory | **What you owe** | A promise you made, captured and returned when it matters. | `CommitmentRecallCard` |
| 12 | Memory | **Before it slips** | A commitment about to lapse, surfaced early. | `CommitmentDriftCard` |
| 13 | Memory | **Where you left it** | Your keys — last seen on the kitchen table, 7:42. | `ObjectRecallCard` |
| 14 | Memory | **It remembers for you** | The context you need, unasked. | `ProactiveMemoryCard` |
| 15 | Memory | **Keep a moment** | Save what matters in a blink. | `SavedMemoryCard` |
| 16 | Memory | **Notes on the world** | Leave a memory pinned to a place. | `WorldAnchorCard` |
| 17 | Memory | **Rewind your day** | Scrub the day in place, node by node. | `TimeScrubNodeCard` |
| 18 | Looking out for you | **Off your usual path** | A gentle nudge when something's unusual. | `DeviationAlertCard` |
| 19 | Looking out for you | **Your inner weather** | Your own climate, made visible. | `SynesthesiaCard` |
| 20 | Yours alone | **Privacy Veil** | One gesture and capture stops. Nothing kept. | `PrivacyVeilCard` |
| 21 | Yours alone | **Private zones** | Places that never record. | `PrivateZoneCard` |
| 22 | Yours alone | **Ask first** | Consent before anyone is captured. | `ConsentRequiredCard` |
| 23 | Yours alone | **Forget that** | Undo the last capture instantly. | `ForgetLastCard` |
| 24 | Yours alone | **Always ready** | Calm until you need it. | `ReadyCard` |

_Render:_ `python -m dreamlayer.demo catalog out/catalog` — writes every per-feature clip, the master film, and this file.
