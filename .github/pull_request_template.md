## What

<!-- What changes, and why. Link the issue if there is one. -->

## Testing

<!-- `cd host-python && python -m pytest -q -m "not hardware and not benchmark"`
     must be green with zero optional deps installed. Say what you ran. -->

## Checklist

- [ ] Commits are signed off (`git commit -s`, DCO — see CONTRIBUTING.md)
- [ ] New optional capability? It has a lazy import guard, a fallback, an extras-group entry, and a fallback-path test
- [ ] Nothing weakens the privacy contract (capture guards, the Veil, no stranger identification)
