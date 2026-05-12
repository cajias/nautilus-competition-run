# research_log.md (default seed)

Researcher subprocess unavailable; using deterministic defaults.

- features: log-returns w=32, vol w=64, momentum diff 5/60, position.
- reward: ΔPnL − 0.001·|Δpos| − 0.5·max(0, drawdown).
- PPO: n_steps=1024, n_epochs=4, batch=256, MlpPolicy [64,64], total=50000.
- fallback: sign(momentum)·vol_scale, cap=60% equity.
