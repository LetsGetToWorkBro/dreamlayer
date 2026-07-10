# Juno earcons — cue families

Juno's attention sounds are grouped into **families**; a random variant plays
each time (never the same one twice in a row) so it never feels repetitive.
`src/services/sound.ts` maps card `earcon` ids → families and rotates.

| family      | plays when…                          | variants (add more anytime) |
|-------------|--------------------------------------|-----------------------------|
| `hey`       | Juno wakes ("Hey Juno")          | **`hey1.mp3`** ✓, **`hey2.mp3`** ✓ |
| `listen`    | the "Listen!" shoulder tap (hark)    | **`listen1.mp3`** ✓, **`listen2.mp3`** ✓ |
| `look`      | "look at this" / a face you know     | **`look1.mp3`** ✓, **`look2.mp3`** ✓ |
| `watchout`  | an **urgent** heads-up               | **`watchout1.mp3`** ✓, **`watchout2.mp3`** ✓ |
| `sfx`       | neutral confirmations                | **`sfx10.mp3`** ✓, **`sfx13.mp3`** ✓ |

✓ = shipped. To add a variant: drop the file here with the listed name, then add
its `require()` to the matching family array in `src/services/sound.ts`.
Short (< 2s), quiet, `.mp3`/`.wav`/`.m4a`.
