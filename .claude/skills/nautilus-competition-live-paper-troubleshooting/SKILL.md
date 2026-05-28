---
name: nautilus-competition-live-paper-troubleshooting
description: |
  Diagnose and fix failures in `paper.mode: live` runs against Binance
  Spot Testnet. Use when: (1) a live paper run aborts with
  `HttpClientBuildError("builder error")` from the Rust adapter; (2) a
  live paper run aborts with `MissingBinanceCredentialsError` from the
  fail-fast guard in `paper_phase._run_live`; (3) a live paper run
  reaches Binance and is rejected with `-2014` / `-2015` / `-1022`; (4)
  setting up a fresh Amazon Linux 2023 / RHEL / Fedora host for live
  paper for the first time; (5) the operator's shell exports a stale
  `SSL_CERT_FILE` (e.g., from isengard-cli) that points at a
  non-existent path; (6) a `compete status <run-dir>` post-mortem
  surfaces a live-paper failure root-cause bucket; (7) deciding which
  files in `nautilus-trading/` and the competition repo need to exist
  before running `compete run --paper-mode live`.
author: Claude Code
version: 1.0.0
date: 2026-05-26
---

# Live-paper troubleshooting

`paper.mode: live` swaps the deterministic `BacktestEngine` for a real
`TradingNode` against Binance Spot Testnet. Three preconditions must
hold or the run aborts before placing a single order:

1. **Credentials** — three env vars (`BINANCE_TESTNET_API_KEY`,
   `BINANCE_TESTNET_API_SECRET`, `BINANCE_TESTNET_ED25519_KEY_PATH`)
   plus a PEM file at the path the third variable names.
2. **CA bundle** — `SSL_CERT_FILE` points at a real file the Rust
   `rustls` client can read.
3. **Reachability** — the host can reach `testnet.binance.vision` over
   HTTPS (no MITM proxy stripping certs).

Each precondition fails differently. The matrix below maps observable
symptoms to root causes.

## At a glance

The failure modes cluster into two pre-build aborts and three Binance
rejections. The pre-build aborts (CA bundle, missing creds) account
for nearly every fresh-host failure. The Binance rejections (-2014 /
-2015 / -1022) only fire after the HTTP client builds successfully and
a request reaches the testnet — they're indicative of a bad key, wrong
testnet, or PEM-format mismatch.

## Pre-flight (run before `compete run --paper-mode live`)

Three one-liners cover ~95% of failures. Run all three from the
competition repo root.

### 1. Credential presence (boolean snapshot, no values logged)

```bash
python -c 'from nautilus_competition._env import load_competition_env, describe_credential_sources; load_competition_env(); print(describe_credential_sources())'
```

Output is a dict with `config_paths` (every probed `.envrc` /
`.env.local`), `pem_path` + `pem_exists`, plus
`ssl_cert_file_set` / `ssl_cert_file_path` / `ssl_cert_file_exists`.
The function never returns key material — only paths and presence
flags. Use this on a fresh host before anything else.

### 2. CA bundle resolves to a real file

```bash
python -c 'import os; p=os.environ.get("SSL_CERT_FILE"); print("SSL_CERT_FILE:", p, "exists:", bool(p) and os.path.isfile(p))'
```

If `SSL_CERT_FILE` is unset, `nautilus_competition._env` will
auto-populate it from `_CA_BUNDLE_CANDIDATES` after `load_competition_env()`
runs. If your shell already exports a broken path (the operator's
known case: `/etc/pki/tls/certs/ca-bundle.crt` swapped for a stale
isengard-cli leftover), `setdefault` semantics lose — you must fix the
shell or `nautilus-trading/.envrc` instead.

### 3. PEM parses as PKCS#8 ed25519

```bash
openssl pkey -in "$BINANCE_TESTNET_ED25519_KEY_PATH" -noout -text | head -1
```

Expect `ED25519 Private-Key:`. Anything else (`RSA Private-Key`,
`error reading key`) means the PEM is wrong format and Binance will
reject every signed request with `-1022`.

## Symptom -> root-cause matrix

| Observed error | Where it surfaces | Root cause | Fix |
|---|---|---|---|
| `HttpClientBuildError("builder error")` | `BinanceLiveDataClientFactory.create` deep in `_build_live_node` | rustls native-roots probe couldn't find the system CA bundle | Set `SSL_CERT_FILE` to a real file; on AL2023 use `/etc/pki/tls/certs/ca-bundle.crt`; restart the run |
| `HttpClientBuildError("builder error")` after `SSL_CERT_FILE` was set | same | Shell exports a path that doesn't exist (e.g., stale isengard-cli) | Override in `nautilus-trading/.envrc` so `setdefault` in `_env.py` is bypassed |
| `MissingBinanceCredentialsError: ...` | top of `paper_phase._run_live` (fail-fast guard) | At least one of `BINANCE_TESTNET_API_KEY` / `BINANCE_TESTNET_API_SECRET` / `BINANCE_TESTNET_ED25519_KEY_PATH` is unset after env loading | Run pre-flight #1; populate `nautilus-trading/.envrc` per the workspace setup section below |
| `binance.exceptions.BinanceAPIException: -2014` | first request after node build | API key format invalid (wrong characters, wrong length) | Regenerate the testnet key at testnet.binance.vision and re-export `BINANCE_TESTNET_API_KEY` |
| `binance.exceptions.BinanceAPIException: -2015` | first request after node build | API key valid but rejected — wrong testnet (futures key vs spot), permissions disabled, or IP whitelist blocks the host | Confirm key was issued for SPOT testnet; remove IP restrictions for the host; re-issue if needed |
| `binance.exceptions.BinanceAPIException: -1022` | first signed request | ed25519 signature mismatch — PEM file content does not match the public key bound to the API key on testnet | Re-issue the key pair on testnet, replace `binance_ed25519_private.pem`, re-paste the public key into the testnet UI |
| `FileNotFoundError: ... binance_ed25519_private.pem` | `ensure_ed25519_key_path()` / startup | PEM not at the conventional path | Either symlink to `nautilus-trading/binance_ed25519_private.pem` or set `BINANCE_TESTNET_ED25519_KEY_PATH` explicitly |
| Run hangs at "building TradingNode" with no error | `node.build()` | Network reachability or a corporate proxy stripping TLS | `curl -v https://testnet.binance.vision/api/v3/time` — if that fails, fix networking before re-running |

## Where to look in code

| File | Lines | Purpose |
|---|---|---|
| `nautilus_competition/_env.py` | 33-52 | `_CA_BUNDLE_CANDIDATES` + `_ensure_ca_bundle_env()` (rustls fix) |
| `nautilus_competition/_env.py` | 152-161 | `load_competition_env()` — runs CA fix AFTER all .env loading |
| `nautilus_competition/_env.py` | 164-186 | `ensure_ed25519_key_path()` — bridges KEY_PATH from sibling repo |
| `nautilus_competition/_env.py` | 189-219 | `describe_credential_sources()` — paths-only diagnostic |
| `nautilus_competition/paper_phase.py` | 38-42 | `_REQUIRED_LIVE_ENV_VARS` tuple |
| `nautilus_competition/paper_phase.py` | 45-90 | `MissingBinanceCredentialsError` + formatted message |
| `nautilus_competition/paper_phase.py` | 245-314 | `_build_live_node` — where `HttpClientBuildError` actually originates |
| `nautilus_competition/paper_phase.py` | 317-348 | `_run_live` — fail-fast guard runs before `node.build()` |
| installed `nautilus_trader/adapters/binance/factories.py` | (vendored) | The Rust adapter that surfaces `HttpClientBuildError`. Read-only — do not patch |

## Workspace setup checklist (fresh host)

A first-time operator on a clean Amazon Linux 2023 / RHEL / Fedora /
Debian / Ubuntu host needs:

1. **Sibling `nautilus-trading` repo** at `~/Projects/nautilus/nautilus-trading/`
   (the path `_sibling_nautilus_trading()` walks to). If it lives
   elsewhere, the env loader still falls back to
   `~/Projects/workspace/nautilus-trading/`, but the convention is the
   sibling layout.

2. **PEM file** at `nautilus-trading/binance_ed25519_private.pem`. The
   filename is fixed (`PEM_FILENAME` in `_env.py`). A symlink is fine.

3. **`.envrc` at `nautilus-trading/.envrc`** with these four exports:

   ```bash
   export BINANCE_TESTNET_API_KEY="<hex from testnet.binance.vision>"
   export BINANCE_TESTNET_API_SECRET="$(cat ~/Projects/nautilus/nautilus-trading/binance_ed25519_private.pem)"
   export BINANCE_TESTNET_ED25519_KEY_PATH="$HOME/Projects/nautilus/nautilus-trading/binance_ed25519_private.pem"
   export SSL_CERT_FILE="/etc/pki/tls/certs/ca-bundle.crt"   # AL2023 / RHEL; pick the right path for your distro
   ```

   The fourth line (`SSL_CERT_FILE`) is only needed if your shell
   already exports a broken path; the in-code default in `_env.py`
   handles unset shells. Setting it here makes the precondition
   explicit and survives shell rehashing.

4. **direnv** allowed on the directory (`direnv allow nautilus-trading/`)
   if you use direnv. Otherwise `source nautilus-trading/.envrc`
   manually before invoking `compete run`.

5. **Run the three pre-flight one-liners above** and confirm all three
   return green before the first `compete run --paper-mode live`.

## Operator-known landmines

- **`setdefault` loses to a broken shell export.** `_env.py` only sets
  `SSL_CERT_FILE` when the variable is unset. If your `.bashrc` or a
  sourced helper script (isengard-cli is the known offender) has
  already exported a stale path, the in-code default never runs.
  Either unset it before invoking `compete` or override it in
  `nautilus-trading/.envrc` (the env loader respects the override).
- **PEM contents in a single env var.** `BINANCE_TESTNET_API_SECRET`
  holds the *contents* of the PEM, not a path. The `.envrc` parser in
  `_env.py` understands `$(cat ...)` substitution to inline the PEM —
  this is how it can be a single env var without wrapping newlines.
- **The harness's pre-flight reads `BINANCE_TESTNET_ED25519_KEY_PATH`,
  but the Binance adapter itself only reads KEY/SECRET.** If you skip
  the KEY_PATH variable, the live node will still build — but the
  fail-fast guard in `_run_live` aborts the run. This is intentional:
  setting all three is a workspace-hygiene assertion.

## Cross-references

- Skill `nautilus-competition-operator` — operator runbook;
  pre-flight references this skill for live-paper failures.
- Skill `nautilus-competition-team-author` — team contract; teams
  themselves do not configure live paper, but their `train()` returns
  the strategy that the live node executes. If the strategy crashes
  inside `on_bar`, the failure surfaces here as a Binance rejection
  rather than a build error.
- Skill `nautilus-competition-observability` — `compete status`
  surfaces live-paper failure root-cause buckets including
  `HttpClientBuildError` and `MissingBinanceCredentialsError`.
- `nautilus_competition/_env.py` and `nautilus_competition/paper_phase.py`
  — the only two harness modules involved in live-paper preconditions.
