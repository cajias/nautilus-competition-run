---
description: Bring up (or tear down) the Grafana + Prometheus + pushgateway stack for live competition observability.
argument-hint: "[up|down] (default: up)"
allowed-tools: Bash
---

<!--
Usage:
  /nautilus-competition:observability          # bring stack up (default)
  /nautilus-competition:observability up
  /nautilus-competition:observability down     # tear stack down

Requires: `docker` on PATH and `docker-compose.observability.yml` in the
current working directory (this is the nautilus-competition repo root).
-->

The user invoked `/nautilus-competition:observability` with `$ARGUMENTS`.
Manage the docker-compose observability stack (pushgateway:9091 +
prometheus:9090 + grafana:3000) used by `compete run --metrics-endpoint`.

Step 1 — verify docker is installed:

!`command -v docker >/dev/null 2>&1 && echo DOCKER_OK || echo DOCKER_MISSING`

If the check above prints `DOCKER_MISSING`, **stop** and surface this
install hint to the user verbatim, then exit:

```
The `docker` CLI is not on PATH. The observability stack is a
docker-compose deployment (pushgateway + prometheus + grafana). Install
Docker Desktop (https://docs.docker.com/desktop/) or the docker engine
for your platform, then re-run this command.
```

Step 2 — verify the compose file exists in the current directory:

!`test -f docker-compose.observability.yml && echo COMPOSE_OK || echo COMPOSE_MISSING`

If `COMPOSE_MISSING`, surface this hint verbatim and stop:

```
docker-compose.observability.yml is not in the current working directory.
This command must be run from the root of a nautilus-competition checkout
(or any directory that contains docker-compose.observability.yml). cd
there and re-run.
```

Step 3 — dispatch on `$ARGUMENTS`:

- If `$ARGUMENTS` is `down`, tear the stack down:

  !`docker compose -f docker-compose.observability.yml down`

  On success, tell the user the stack is stopped and the Grafana
  dashboard at http://localhost:3000 is no longer reachable. Stop here.

- Otherwise (`up`, `--up`, empty, or anything else), bring the stack up
  in the background:

  !`docker compose -f docker-compose.observability.yml up -d`

Step 4 — for the `up` path only, wait briefly for grafana to become
healthy, then surface the dashboard URL:

!`for i in 1 2 3 4 5 6 7 8 9 10; do curl -fsS http://localhost:3000/api/health >/dev/null 2>&1 && echo GRAFANA_READY && break; sleep 1; done`

If the loop above printed `GRAFANA_READY`, tell the user:

- Stack is up. Open the dashboard at:
  **http://localhost:3000/d/competition**
- Default Grafana login is admin/admin (the dashboard is provisioned via
  observability/grafana/provisioning/, no manual datasource setup needed).
- Export `COMPETE_METRICS_ENDPOINT=http://localhost:9091` in the shell
  that runs `compete run` so the orchestrator pushes counters/gauges to
  prometheus.
- To tear the stack down, run `/nautilus-competition:observability down`.

If the loop did NOT print `GRAFANA_READY`, the containers may still be
starting. Surface the relevant docker logs with `docker compose -f
docker-compose.observability.yml logs --tail=50` and recommend the user
re-run this command in ~30s.
