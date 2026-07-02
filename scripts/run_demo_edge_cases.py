#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "host-python", "src"))
from dreamlayer.simulator import scenarios
cases = [
    ("low_confidence_recall",  scenarios.low_confidence_recall),
    ("no_memory_recall",       scenarios.no_memory_recall),
    ("unknown_query",          scenarios.unknown_query),
    ("resume_after_pause",     scenarios.resume_after_pause),
]
if __name__ == "__main__":
    for name, fn in cases:
        result = fn()
        card = result[1]
        print(f"{name:30s}  \u2192  {card['type'] if card else 'None'}")
