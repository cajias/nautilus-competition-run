# merger/regime_detector.md

**Version: 1**

The merger uses this rule to classify the current regime as `bull | bear | chop`. Update + version-bump when the weekly-reflector flags miscalibration.

## Initial rule (numerical-only — only inputs the merger may consult)

- Compute trailing 60-bar return: `r60 = log(close[-1] / close[-60])`.
- Compute trailing 20-bar realized vol: `vol20 = std(log_returns[-20:])`.

Classification:
- `bull` if `r60 > +1.5 * vol20`
- `bear` if `r60 < -1.5 * vol20`
- `chop` otherwise

The merger MAY refine this rule based on weekly reflector recommendations. Every change requires a same-iteration entry in `notes/weight_changes.md` AND a version bump here.
