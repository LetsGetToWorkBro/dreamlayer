# Oracle earcons

Drop short audio clips here, named after the earcon id, then wire them in
`src/services/sound.ts` (uncomment the matching `require()` line):

| file            | when it plays                                   |
|-----------------|-------------------------------------------------|
| `hark.mp3`      | Oracle's "Listen!" — a proactive shoulder tap   |
| `wake.mp3`      | Oracle woke ("Hey Oracle")                      |
| `success.mp3`   | a light confirmation                            |

`.mp3`, `.wav`, or `.m4a` all work. Keep them short (< 2s) and quiet.
Until a file is added and its `require()` uncommented, playback is a silent
no-op — nothing breaks.
