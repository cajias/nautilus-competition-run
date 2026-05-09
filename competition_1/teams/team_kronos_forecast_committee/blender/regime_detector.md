# blender/regime_detector.md

**Version: 1**

The blender uses this rule to classify the current regime as `bull | bear | chop`. Update + version-bump when the blender's `log.md` shows the rule miscalibrating.

## Initial rule (numerical-only)

- Compute trailing 60-bar return: `r60 = log(close[-1] / close[-60])`.
- Compute trailing 20-bar realized vol: `vol20 = std(log_returns[-20:])`.

Classification:
- `bull` if `r60 > +1.5 * vol20`
- `bear` if `r60 < -1.5 * vol20`
- `chop` otherwise

## Disagreement threshold

`low_confidence: true` if `std-dev across mini/base/extended point[0] > 1.0 * vol20`. Tune in `blender/log.md` if confidence-flagging rate is mis-calibrated.
