---
name: nautilus-competition-observability
description: |
  Live observability stack for nautilus-competition runs. Use when:
  (1) bringing up the docker-compose Prometheus + pushgateway + Grafana
  stack with `docker compose -f docker-compose.observability.yml up -d`;
  (2) wiring `compete run` to push metrics via `--metrics-endpoint` /
  `COMPETE_METRICS_ENDPOINT`; (3) the dashboard at
  http://localhost:3000/d/competition shows "No data"; (4) inspecting
  raw metric values via `curl http://localhost:9091/metrics`; (5)
  understanding the eight panels (Active Round, Eval gain_factor, Paper
  equity, Current price, Eval backtests, Latest metrics, Team failures,
  Avg eval duration); (6) wiping pushgateway state between runs.
author: Claude Code
version: 1.0.0
date: 2026-05-07
---

# Live observability for `compete run`

The competition harness can stream per-team backtest counts, gain
factors, paper equity, and current ticker into a local Grafana dashboard
via Prometheus + a pushgateway. The pushgateway model fits the
short-lived `compete run` CLI: each phase pushes a snapshot, the
pushgateway persists the latest values, and Prometheus scrapes the
pushgateway every 5 seconds.

The harness is correct without any of this — observability is opt-in.

## Quickstart

```bash
# 1. Bring up the stack (pushgateway:9091, prometheus:9090, grafana:3000).
docker compose -f docker-compose.observability.yml up -d

# 2. Install the optional extra so `compete run` knows how to push.
uv pip install --extra observability --editable .

# 3. Run the demo competition with metrics enabled — either via flag…
compete run examples/demo_competition \
    --paper-duration-minutes 1 \
    --metrics-endpoint http://localhost:9091 \
    --run-id obs-demo

# …or via env var (useful for direnv / dev shells):
export COMPETE_METRICS_ENDPOINT=http://localhost:9091
compete run examples/demo_competition --paper-duration-minutes 1 --run-id obs-demo

# 4. Watch the dashboard (anonymous read-only, or admin/admin to edit).
open http://localhost:3000/d/competition
```

**Configuration precedence** (first match wins):

1. `--metrics-endpoint URL` CLI flag.
2. `COMPETE_METRICS_ENDPOINT` environment variable.
3. Both unset → metrics emission is disabled (the harness no-ops
   gracefully).

## Metric naming convention

All harness-emitted metrics share the `compete_` prefix. They're labeled
by `team`, `round`, and `phase` (one of `eval`, `paper`):

| Metric | Type | Labels | Meaning |
|--------|------|--------|---------|
| `compete_round` | Gauge | (none) | Current round index. Used to derive the active-round stat. |
| `compete_team_gain_factor` | Gauge | `team`, `round`, `phase` | Final equity / starting equity after the phase. |
| `compete_team_equity_usdt` | Gauge | `team`, `round`, `phase` | Final paper equity in USDT. |
| `compete_current_price` | Gauge | `team`, `round`, `phase` | Last close price seen at end of phase. |
| `compete_backtests_total` | Counter | `team`, `round`, `phase` | Cumulative train iterations per team-round. |
| `compete_team_failures_total` | Counter | (none) | Teams that hit `FAILED` (max iterations without a positive-gain eval). |
| `compete_eval_duration_seconds` | Histogram | `team`, `round` | Wall-clock per `train()` iteration. |

Each `compete run` invocation is grouped under `grouping_key={run_id}`
on the pushgateway, so concurrent or sequential runs don't clobber each
other.

## The eight dashboard panels

| Panel | Source metric |
|-------|---------------|
| Active Round (stat) | `max(compete_round)` |
| Eval gain_factor (timeseries) | `compete_team_gain_factor{phase="eval"}` |
| Paper equity (timeseries) | `compete_team_equity_usdt{phase="paper"}` |
| Current price (timeseries) | `compete_current_price` |
| Eval backtests (bar chart) | `compete_backtests_total{phase="eval"}` |
| Latest metrics (table) | `compete_team_gain_factor`, `compete_team_equity_usdt` |
| Team failures (stat) | `compete_team_failures_total` |
| Avg eval duration (stat) | `compete_eval_duration_seconds_*` |

## Inspect metrics directly

To verify the pushgateway saw any pushes from a recent run:

```bash
curl -s http://localhost:9091/metrics | grep compete_
```

Empty output means `compete run` never reached the pushgateway. Common
causes:

- `--metrics-endpoint` and `COMPETE_METRICS_ENDPOINT` both unset.
- Container down (`docker ps | grep pushgateway`).
- The `observability` extra isn't installed (`compete` will silently
  drop the push). `uv pip install --extra observability --editable .`.

You can also hit Prometheus directly:

```bash
curl -s 'http://localhost:9090/api/v1/query?query=compete_round'
```

## Operations

### Wipe pushgateway state

Useful between runs that share a `run_id`:

```bash
curl -X DELETE http://localhost:9091/metrics/job/compete
```

### Tear down (preserves Grafana state)

```bash
docker compose -f docker-compose.observability.yml down
```

The Grafana SQLite + dashboards persist across `down`/`up` cycles via
the `grafana_data` named volume. To wipe everything (including saved
dashboard edits):

```bash
docker compose -f docker-compose.observability.yml down -v
```

## Configuration files

- `docker-compose.observability.yml` — service definitions.
- `observability/prometheus.yml` — scrape config (5s interval).
- `observability/grafana/provisioning/` — datasource + dashboard
  provider declarations.
- `observability/grafana/dashboards/competition.json` — the dashboard
  itself. Edit-then-export from the Grafana UI to revise; check the
  JSON back in.

## Known limits

- **Per-bar emission is not wired.** The "Current price" panel updates
  once per team-round (a snapshot at end of phase), not per-bar. To
  stream per-bar prices we'd need a NautilusTrader `Actor` that
  subscribes to bar-data events on the `MessageBus` and calls
  `_metrics_emit.record_bar(...)`. Out of scope for now; the panel
  remains in the dashboard so wiring it up is a single commit later.
- **Loki log aggregation** is not included. `docker compose logs
  compete-grafana` is sufficient for local debugging.

## Troubleshooting

- Dashboard says "No data": confirm the pushgateway saw any pushes via
  `curl http://localhost:9091/metrics | grep compete_`. If empty,
  `compete run` isn't reaching the pushgateway — check
  `--metrics-endpoint`, network, and that you installed the
  `observability` extra.
- Containers crash-loop: `docker compose -f
  docker-compose.observability.yml logs <service>` for the offender.
- Port collisions: change the host-side port in
  `docker-compose.observability.yml` (e.g. `"9099:9091"`).

## References

- `docs/observability.md` — the canonical observability runbook.
- `nautilus-competition-operator` skill — how `--metrics-endpoint` /
  `COMPETE_METRICS_ENDPOINT` slot into the operator workflow.
