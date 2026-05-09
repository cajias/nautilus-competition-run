# alpha158_operators

Quick reference for `synthesis-agent` when emitting `factor-mining` hypotheses. Full canonical list at `microsoft/qlib` repo (`qlib/contrib/data/handler.py:Alpha158`).

## Time-series operators (key ones)

- `ts_rank(x, n)` — rolling rank of x in last n bars
- `ts_max(x, n)`, `ts_min(x, n)` — rolling max / min
- `ts_argmax(x, n)`, `ts_argmin(x, n)` — index of rolling max / min
- `delta(x, n)` — `x - x.shift(n)`
- `decay_linear(x, n)` — linearly weighted moving average
- `correlation(x, y, n)` — rolling correlation
- `ts_cov(x, y, n)` — rolling covariance
- `ts_std(x, n)` — rolling std
- `ts_sum(x, n)` — rolling sum

## Cross-sectional operators (single-instrument competition: mostly no-op)

- `rank(x)` — rank within universe; trivial when universe has size 1
- `scale(x, k)` — `x / sum(abs(x)) * k`

## Arithmetic / unary

- `+`, `-`, `*`, `/`
- `abs(x)`, `log(x)`, `sign(x)`, `exp(x)`, `power(x, p)`

## Conditional

- `where(cond, x, y)` / `if_else(cond, x, y)`

## Available inputs (single-instrument competition)

- `open`, `high`, `low`, `close`, `volume`
- `vwap` — derive as `(high+low+close)/3` if not directly provided

## Common factor patterns to mutate

- `ts_rank(close - delta(close, 5), 20)` — momentum
- `correlation(close, volume, 10)` — price-volume relationship
- `(high - low) / close` — intra-bar volatility ratio
- `ts_std(close, 20) / close` — realized vol
- `decay_linear(volume * (close - delta(close, 1)), 10)` — weighted return-volume

Most Alpha158 factors are single-line expressions of these. Generate diversity by varying lookback windows (5/10/20/60), composing operators differently, and inverting signs.
