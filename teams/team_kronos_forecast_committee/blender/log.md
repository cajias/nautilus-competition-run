# blender/log.md

Append-only log. One entry per `regime_weights.json` mutation. Schema:

```
## <round>_<iter> — <ISO timestamp>
- Regime detected: <bull|bear|chop>
- Realized outcome: <gain factor>
- Per-checkpoint outcome:
  - mini    predicted=<x>  realized=<y>  contribution=<+/->
  - base    predicted=<x>  realized=<y>  contribution=<+/->
  - extended predicted=<x>  realized=<y>  contribution=<+/->
- Weight changes: { mini: 0.20 -> 0.18, base: 0.50 -> 0.55, extended: 0.30 -> 0.27 } (renormalized for `<bull>` regime)
- Justification: <free text>
```

If you cannot justify a change, do not make it.
