# Premonition — the future side of the ring stops being empty

RecurrenceModel (dream_mode/premonition.py) mines the day's stored events for
rhythms — (weekday, hour, kind, summary-head, place) slots seen on ≥2 distinct
days (≥4 weekdays ⇒ predicts daily). Inside the dial's 5 h future window the
Horizon renders them as future ghosts: kind-6 marks, always luma 1, shimmering
at ~70% duty on a desynced phase (reduce_motion: static dim). Echo reborn as
weather — no dialogs, no text, probability made faintly luminous.

Precision is the law: the two-Tuesdays test pins that a fortnight of noise
plus a one-off decoy produces exactly the rhythm and nothing else. A real
event within ±45 min hardens the ghost (the prediction retires; the genuine
mark takes its place, and the slot earns trust); an hour that passes empty is
a defiance — two misses with a low hit factor and the slot goes quiet. Ghosts
never displace real marks: they only fill spare dial capacity, dropped first.
Private events are never observed.

Tests: `src/dreamlayer/tests/test_premonition.py` (13, incl. the Lua plotter
admitting kind 6 and rejecting kind 7).
