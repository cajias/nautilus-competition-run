"""Entry for team_finrl_policy_learner — FinRL/PPO research lab.

Train-time pipeline (≤600s wall clock):
  1. researcher (run_claude subprocess, ~180s budget, cached)
  2. hypothesis-generator → (lambda_turnover, mu_drawdown, ppo_hparams)
  3. env-designer + reward-shaper → gymnasium TradingEnv
  4. policy-trainer → PPO under wall-clock budget (falls back on any failure)
  5. policy-critic → overfit check on holdout; may force fallback
  6. risk-officer → runtime_rules.json
  7. memory-keeper + critic → notes/memory.md, attempts/<iter>/critic.md
  8. return (FinRLPolicyStrategy, FinRLPolicyConfig)

Trade-time (no LLM): Strategy loads policy.zip (PPO) or the handwritten
sign(momentum)·vol_scale fallback. Risk-officer runtime rules override
unsafe actions to FLAT.

See CLAUDE.md for persona + role roster + SOTA citations.
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import time
import traceback
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nautilus_trader.config import StrategyConfig  # type: ignore[import-untyped]
from nautilus_trader.model.data import Bar, BarType  # type: ignore[import-untyped]
from nautilus_trader.model.enums import OrderSide, TimeInForce  # type: ignore[import-untyped]
from nautilus_trader.model.identifiers import InstrumentId  # type: ignore[import-untyped]
from nautilus_trader.trading.strategy import Strategy  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from nautilus_trader.model.instruments import Instrument  # type: ignore[import-untyped]

log = logging.getLogger(__name__)

TEAM_DIR = Path(__file__).parent
NOTES_DIR = TEAM_DIR / "notes"
ATTEMPTS_DIR = TEAM_DIR / "attempts"
POLICY_PATH = TEAM_DIR / "policy.zip"
RULES_PATH = TEAM_DIR / "runtime_rules.json"
RESEARCH_CACHE = NOTES_DIR / "research_log.md"
MEMORY_LOG = NOTES_DIR / "memory.md"

# ---------------------------------------------------------------------------
# Budget constants
# ---------------------------------------------------------------------------
RESEARCHER_TIMEOUT_S = 420
PPO_WALL_BUDGET_S = 300  # leaves ~120s headroom inside 600s harness budget
PPO_TOTAL_TIMESTEPS = 50_000
PPO_N_STEPS = 1024
PPO_BATCH_SIZE = 256
PPO_N_EPOCHS = 4
POLICY_LAYERS = [64, 64]

# ---------------------------------------------------------------------------
# Role 1: researcher — run_claude subprocess
# ---------------------------------------------------------------------------
RESEARCHER_PROMPT = """\
You are the RESEARCHER for team_finrl_policy_learner, a reinforcement-learning
research lab in the FinRL lineage (Liu et al. 2020, arXiv 2011.09607) using PPO
(Schulman et al. 2017, arXiv 1707.06347) via stable-baselines3.

Read CLAUDE.md, docs/state-of-the-art/*.md (the FinRL / RL / PPO sections), and
any competition_1/teams/*/notes/ you can find. Propose:

1. The state-feature vector (default: log-returns w=32, vol w=64, momentum diff
   5/60, normalized-position). Justify any tweak.
2. Reward shape coefficients (λ turnover penalty, μ drawdown penalty). Suggest
   starting values and a perturbation ladder for loss-driven retries.
3. PPO hyperparams within our wall-clock budget (n_steps=1024, n_epochs=4,
   batch=256, MlpPolicy [64,64], total_timesteps=50000).
4. Fallback policy if PPO times out or overfits. Default: sign(momentum) ·
   vol_scale with the same caps. Confirm or propose an alternative.

Write your answer to notes/research_log.md AND to attempts/<iter>/research.md.
Keep it ≤400 lines. The deterministic Python pipeline will consume it and
decide per-iteration λ, μ, and whether to re-invoke you next round.

Exit when both files exist.
"""


def _invoke_researcher(ctx: Any, iter_idx: int) -> None:
    """Invoke the researcher subprocess if cache is stale.

    Cache is considered stale when:
    - notes/research_log.md is missing, OR
    - iter_idx == 0 AND round_index == 0 (fresh competition), OR
    - ctx.prev_gain is very negative (<-0.3) → thesis reconsideration.
    """
    stale = not RESEARCH_CACHE.exists()
    if not stale and ctx.iteration == 0 and ctx.round_index == 0:
        stale = True
    if not stale and ctx.prev_gain is not None and ctx.prev_gain < -0.3:
        stale = True

    if not stale:
        log.info("researcher cache hit; skipping subprocess")
        return

    try:
        from nautilus_competition.agent_runner import run_researcher  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - only hit outside harness
        log.warning("agent_runner import failed: %s; skipping researcher", exc)
        return

    attempt_dir = ATTEMPTS_DIR / f"{iter_idx:03d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (TEAM_DIR / "_inbox").mkdir(exist_ok=True)
    (TEAM_DIR / "_inbox" / "context.md").write_text(
        f"# Round Context\n"
        f"- round_index: {ctx.round_index}\n"
        f"- iteration: {ctx.iteration}\n"
        f"- prev_gain: {ctx.prev_gain}\n"
        f"- instrument: {ctx.config.instrument.symbol}\n"
        f"- bar_type: {ctx.config.instrument.bar_type}\n"
    )

    timeout_s = min(RESEARCHER_TIMEOUT_S, ctx.config.agent.per_train_timeout_seconds)
    result = run_researcher(
        workspace_dir=TEAM_DIR,
        prompt=RESEARCHER_PROMPT,
        timeout_seconds=timeout_s,
        fail_loud=False,
    )
    if not result.payload and result.raw_stderr:
        log.warning(
            "researcher returned no payload; raw_stderr=%r",
            result.raw_stderr[:300],
        )

    # If the researcher didn't write the cache, seed a deterministic default so
    # downstream roles have something to read.
    if not RESEARCH_CACHE.exists():
        RESEARCH_CACHE.write_text(_default_research_fallback())


def _default_research_fallback() -> str:
    return (
        "# research_log.md (default seed)\n\n"
        "Researcher subprocess unavailable; using deterministic defaults.\n\n"
        "- features: log-returns w=32, vol w=64, momentum diff 5/60, position.\n"
        "- reward: ΔPnL − 0.001·|Δpos| − 0.5·max(0, drawdown).\n"
        "- PPO: n_steps=1024, n_epochs=4, batch=256, MlpPolicy [64,64], total=50000.\n"
        "- fallback: sign(momentum)·vol_scale, cap=60% equity.\n"
    )


# ---------------------------------------------------------------------------
# Role 2: hypothesis-generator
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Hypothesis:
    lambda_turnover: float
    mu_drawdown: float
    entropy_coef: float
    feature_window_returns: int
    feature_window_vol: int
    momentum_short: int
    momentum_long: int
    switch_to_fallback: bool  # if True, skip PPO entirely


def _hypothesis(ctx: Any) -> Hypothesis:
    """Pick reward-shape + PPO knobs from ctx.prev_gain.

    - iter 0 (prev_gain None): default.
    - prev_gain >= 0: keep knobs; just resample seed.
    - prev_gain in [-0.3, 0): perturb toward more turnover / drawdown penalty.
    - prev_gain < -0.3: consecutive loss-like signal; switch to fallback.
    """
    base = Hypothesis(
        lambda_turnover=0.001,
        mu_drawdown=0.5,
        entropy_coef=0.01,
        feature_window_returns=32,
        feature_window_vol=64,
        momentum_short=5,
        momentum_long=60,
        switch_to_fallback=False,
    )
    prev = ctx.prev_gain
    if prev is None or prev >= 0.0:
        return base
    if prev < -0.3:
        return Hypothesis(
            lambda_turnover=base.lambda_turnover,
            mu_drawdown=base.mu_drawdown,
            entropy_coef=base.entropy_coef,
            feature_window_returns=base.feature_window_returns,
            feature_window_vol=base.feature_window_vol,
            momentum_short=base.momentum_short,
            momentum_long=base.momentum_long,
            switch_to_fallback=True,
        )
    # Mild loss: scale up both penalties, raise entropy for exploration.
    return Hypothesis(
        lambda_turnover=base.lambda_turnover * 3.0,
        mu_drawdown=base.mu_drawdown * 1.5,
        entropy_coef=0.02,
        feature_window_returns=base.feature_window_returns,
        feature_window_vol=base.feature_window_vol,
        momentum_short=base.momentum_short,
        momentum_long=base.momentum_long,
        switch_to_fallback=False,
    )


# ---------------------------------------------------------------------------
# Roles 6/7/8/9: env-designer, reward-shaper, policy-trainer, policy-critic
# ---------------------------------------------------------------------------
def _load_train_closes(ctx: Any) -> list[float]:
    """Load train-window close prices from the catalog. Train window only."""
    from nautilus_trader.persistence.catalog import ParquetDataCatalog  # type: ignore[import-untyped]

    handle = ctx.get_train_data()
    catalog = ParquetDataCatalog(str(handle.catalog_path))
    bars = catalog.bars(
        bar_types=[handle.instrument.bar_type],
        start=handle.start,
        end=handle.end,
    )
    return [float(b.close) for b in bars]


def _train_ppo(
    closes: list[float],
    hypo: Hypothesis,
    attempt_dir: Path,
    start_wall: float,
    wall_budget_s: int,
) -> tuple[bool, float]:
    """Train PPO on a gymnasium env wrapping `closes`.

    Returns (succeeded, holdout_score). On ANY failure (import, timeout,
    overfit-critic flag) returns (False, 0.0) and the caller falls back.
    """
    try:
        import gymnasium as gym  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
        from stable_baselines3 import PPO  # type: ignore[import-not-found]
    except Exception as exc:
        (attempt_dir / "policy_trainer.log").write_text(
            f"stable_baselines3/gymnasium import failed: {exc}\n"
        )
        return False, 0.0

    # Split 80/20 for overfit check (policy-critic).
    split = int(len(closes) * 0.8)
    train_closes = closes[:split]
    holdout_closes = closes[split:]
    if len(train_closes) < 200 or len(holdout_closes) < 50:
        (attempt_dir / "policy_trainer.log").write_text(
            f"insufficient bars: train={len(train_closes)} holdout={len(holdout_closes)}\n"
        )
        return False, 0.0

    class TradingEnv(gym.Env):  # type: ignore[misc]
        """Discrete 3-way (short/flat/long) env over pre-loaded closes."""

        metadata: dict = {}

        def __init__(self, env_closes: list[float]) -> None:
            super().__init__()
            self._closes = np.asarray(env_closes, dtype=np.float64)
            self._rets = np.diff(np.log(self._closes + 1e-12))
            self._win_r = hypo.feature_window_returns
            self._win_v = hypo.feature_window_vol
            self._mom_s = hypo.momentum_short
            self._mom_l = hypo.momentum_long
            self._warmup = max(self._win_r, self._win_v, self._mom_l) + 1
            self.action_space = gym.spaces.Discrete(3)  # 0=short, 1=flat, 2=long
            obs_dim = self._win_r + 3  # returns window + vol + mom_s + mom_l
            self.observation_space = gym.spaces.Box(
                low=-5.0, high=5.0, shape=(obs_dim,), dtype=np.float32
            )
            self._t = self._warmup
            self._pos = 0  # -1, 0, +1
            self._equity = 1.0
            self._peak = 1.0

        def _obs(self) -> Any:
            rets = self._rets[self._t - self._win_r : self._t]
            vol = float(np.std(self._rets[self._t - self._win_v : self._t]) + 1e-9)
            mom_s = float(np.mean(self._rets[self._t - self._mom_s : self._t]))
            mom_l = float(np.mean(self._rets[self._t - self._mom_l : self._t]))
            obs = np.concatenate(
                [rets.astype(np.float32), np.asarray([vol, mom_s, mom_l], dtype=np.float32)]
            )
            return np.clip(obs, -5.0, 5.0)

        def reset(self, seed: int | None = None, options: Any = None) -> Any:
            super().reset(seed=seed)
            self._t = self._warmup
            self._pos = 0
            self._equity = 1.0
            self._peak = 1.0
            return self._obs(), {}

        def step(self, action: int) -> Any:
            new_pos = int(action) - 1  # {-1, 0, +1}
            bar_ret = float(self._rets[self._t])
            pnl = self._pos * bar_ret
            turnover = abs(new_pos - self._pos)
            self._equity *= 1.0 + pnl
            self._peak = max(self._peak, self._equity)
            drawdown = (self._peak - self._equity) / self._peak
            reward = pnl - hypo.lambda_turnover * turnover - hypo.mu_drawdown * max(
                0.0, drawdown - 0.05
            )
            self._pos = new_pos
            self._t += 1
            terminated = self._t >= len(self._rets)
            return self._obs(), float(reward), terminated, False, {}

    try:
        env = TradingEnv(train_closes)
        model = PPO(
            "MlpPolicy",
            env,
            n_steps=PPO_N_STEPS,
            n_epochs=PPO_N_EPOCHS,
            batch_size=PPO_BATCH_SIZE,
            ent_coef=hypo.entropy_coef,
            policy_kwargs={"net_arch": list(POLICY_LAYERS)},
            verbose=0,
        )
    except Exception as exc:
        (attempt_dir / "policy_trainer.log").write_text(
            f"PPO construction failed: {exc}\n{traceback.format_exc()}\n"
        )
        return False, 0.0

    # Wall-clock watchdog: run total_timesteps in chunks; break if budget exceeded.
    chunk = PPO_N_STEPS * 4
    trained = 0
    try:
        while trained < PPO_TOTAL_TIMESTEPS:
            elapsed = time.time() - start_wall
            if elapsed > wall_budget_s:
                (attempt_dir / "policy_trainer.log").write_text(
                    f"PPO wall-budget exceeded at elapsed={elapsed:.1f}s trained={trained}\n"
                )
                break
            step = min(chunk, PPO_TOTAL_TIMESTEPS - trained)
            model.learn(total_timesteps=step, reset_num_timesteps=False)
            trained += step
    except Exception as exc:
        (attempt_dir / "policy_trainer.log").write_text(
            f"PPO.learn raised: {exc}\n{traceback.format_exc()}\n"
        )
        return False, 0.0

    # Policy-critic: score on holdout.
    try:
        holdout_env = TradingEnv(holdout_closes)
        obs, _ = holdout_env.reset()
        cum = 0.0
        done = False
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, _ = holdout_env.step(int(action))
            cum += reward
            done = terminated or truncated
    except Exception as exc:
        (attempt_dir / "policy_critic.log").write_text(
            f"holdout eval raised: {exc}\n{traceback.format_exc()}\n"
        )
        return False, 0.0

    if cum <= 0.0:
        (attempt_dir / "policy_critic.log").write_text(
            f"holdout cum_reward={cum:.4f} ≤ 0 → declare overfit, force fallback\n"
        )
        return False, cum

    # Success: persist.
    try:
        model.save(str(POLICY_PATH))
    except Exception as exc:
        (attempt_dir / "policy_trainer.log").write_text(
            f"model.save failed: {exc}\n"
        )
        return False, cum
    (attempt_dir / "policy_critic.log").write_text(
        f"holdout cum_reward={cum:.4f} OK; trained_timesteps={trained}\n"
    )
    return True, cum


# ---------------------------------------------------------------------------
# Role 4: risk-officer
# ---------------------------------------------------------------------------
def _write_runtime_rules(fallback_mode: bool, hypo: Hypothesis) -> None:
    RULES_PATH.write_text(
        json.dumps(
            {
                "fallback_mode": fallback_mode,
                "max_position_notional_pct": 0.6,
                "drawdown_kill_pct": 0.15,
                "min_warmup_bars": max(
                    hypo.feature_window_returns,
                    hypo.feature_window_vol,
                    hypo.momentum_long,
                )
                + 1,
                "feature_window_returns": hypo.feature_window_returns,
                "feature_window_vol": hypo.feature_window_vol,
                "momentum_short": hypo.momentum_short,
                "momentum_long": hypo.momentum_long,
            },
            indent=2,
        )
    )


# ---------------------------------------------------------------------------
# Roles 3 & 5: critic + memory-keeper
# ---------------------------------------------------------------------------
def _record_memory(
    ctx: Any, hypo: Hypothesis, fallback_mode: bool, holdout_score: float
) -> None:
    NOTES_DIR.mkdir(exist_ok=True)
    with MEMORY_LOG.open("a", encoding="utf-8") as f:
        f.write(
            f"round={ctx.round_index} iter={ctx.iteration} "
            f"prev_gain={ctx.prev_gain} "
            f"lambda={hypo.lambda_turnover:.4f} mu={hypo.mu_drawdown:.3f} "
            f"fallback={fallback_mode} holdout={holdout_score:.4f}\n"
        )


def _write_critic(
    attempt_dir: Path,
    hypo: Hypothesis,
    fallback_mode: bool,
    holdout_score: float,
) -> None:
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "critic.md").write_text(
        f"# Critic verdict\n\n"
        f"- fallback_mode: {fallback_mode}\n"
        f"- holdout_score: {holdout_score:.4f}\n"
        f"- lambda_turnover: {hypo.lambda_turnover}\n"
        f"- mu_drawdown: {hypo.mu_drawdown}\n"
        f"- entropy_coef: {hypo.entropy_coef}\n"
        f"- reward-hack risk: "
        f"{'HIGH (mu high, policy may hug flat)' if hypo.mu_drawdown > 1.0 else 'low'}\n"
    )


# ---------------------------------------------------------------------------
# Strategy (trade-time): loads PPO policy OR the handwritten fallback.
# ---------------------------------------------------------------------------
class FinRLPolicyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    policy_path: str
    rules_path: str
    trade_size: Decimal = Decimal("0.001")


class FinRLPolicyStrategy(Strategy):
    """RL-policy strategy with handwritten fallback.

    on_start: load runtime_rules.json; attempt to load policy.zip via
    stable_baselines3; on any failure flip to fallback.

    on_bar: once warm, compute features, infer action, apply risk-officer
    runtime rules, submit at most one market order per bar.
    """

    def __init__(self, config: FinRLPolicyConfig) -> None:
        super().__init__(config)
        self.instrument: Instrument | None = None
        self._closes: list[float] = []
        self._position: int = 0  # -1, 0, +1
        self._rules: dict = {}
        self._policy: Any | None = None
        self._fallback: bool = True
        self._equity_peak: float = 1.0
        self._equity_sim: float = 1.0
        self._killed: bool = False

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument not found: {self.config.instrument_id}")
            self.stop()
            return

        # Load runtime rules (risk-officer contract).
        try:
            self._rules = json.loads(Path(self.config.rules_path).read_text())
        except Exception as exc:
            self.log.warning(f"runtime_rules load failed ({exc}); defaulting")
            self._rules = {
                "fallback_mode": True,
                "max_position_notional_pct": 0.6,
                "drawdown_kill_pct": 0.15,
                "min_warmup_bars": 64,
                "feature_window_returns": 32,
                "feature_window_vol": 64,
                "momentum_short": 5,
                "momentum_long": 60,
            }

        self._fallback = bool(self._rules.get("fallback_mode", True))
        if not self._fallback:
            try:
                from stable_baselines3 import PPO  # type: ignore[import-not-found]

                policy_path = Path(self.config.policy_path)
                if policy_path.exists():
                    self._policy = PPO.load(str(policy_path))
                    self.log.info("loaded PPO policy from %s" % policy_path)
                else:
                    self.log.warning("policy.zip missing; fallback engaged")
                    self._fallback = True
            except Exception as exc:
                self.log.warning(f"PPO load failed ({exc}); fallback engaged")
                self._fallback = True

        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        if self.instrument is None or self._killed:
            return

        self._closes.append(float(bar.close))
        # Trim buffer to 4x longest window to bound memory.
        max_keep = 4 * int(self._rules.get("momentum_long", 60)) + 16
        if len(self._closes) > max_keep:
            self._closes = self._closes[-max_keep:]

        warmup = int(self._rules.get("min_warmup_bars", 64))
        if len(self._closes) < warmup:
            return

        desired = self._infer_action()

        # Risk-officer runtime rules: drawdown kill-switch.
        dd_kill = float(self._rules.get("drawdown_kill_pct", 0.15))
        drawdown = (self._equity_peak - self._equity_sim) / max(self._equity_peak, 1e-9)
        if drawdown > dd_kill:
            self.log.warning(
                f"drawdown {drawdown:.3f} > kill {dd_kill:.3f}; forcing FLAT"
            )
            desired = 0
            self._killed = True  # latch: never re-arm inside one eval run

        self._reconcile_position(desired)
        # Update simulated equity tracker for risk monitor.
        if len(self._closes) >= 2:
            ret = self._closes[-1] / self._closes[-2] - 1.0
            self._equity_sim *= 1.0 + self._position * ret
            self._equity_peak = max(self._equity_peak, self._equity_sim)

    def _infer_action(self) -> int:
        """Return desired position ∈ {-1, 0, +1}."""
        if self._fallback or self._policy is None:
            return self._fallback_action()
        try:
            import numpy as np  # type: ignore[import-not-found]

            win_r = int(self._rules["feature_window_returns"])
            win_v = int(self._rules["feature_window_vol"])
            mom_s = int(self._rules["momentum_short"])
            mom_l = int(self._rules["momentum_long"])
            arr = np.asarray(self._closes, dtype=np.float64)
            rets = np.diff(np.log(arr + 1e-12))
            if len(rets) < max(win_r, win_v, mom_l):
                return 0
            ret_win = rets[-win_r:]
            vol = float(np.std(rets[-win_v:]) + 1e-9)
            ms = float(np.mean(rets[-mom_s:]))
            ml = float(np.mean(rets[-mom_l:]))
            obs = np.concatenate(
                [ret_win.astype(np.float32), np.asarray([vol, ms, ml], dtype=np.float32)]
            )
            obs = np.clip(obs, -5.0, 5.0)
            action, _ = self._policy.predict(obs, deterministic=True)
            return int(action) - 1
        except Exception as exc:
            self.log.warning(f"policy inference failed ({exc}); fallback")
            self._fallback = True
            return self._fallback_action()

    def _fallback_action(self) -> int:
        """Handwritten policy: sign(short_momentum) · vol-scale gate.

        Same MDP philosophy as the PPO target — if the RL layer collapsed, the
        lab's hand-coded ghost still trades the same thesis.
        """
        try:
            import numpy as np  # type: ignore[import-not-found]

            mom_s = int(self._rules.get("momentum_short", 5))
            mom_l = int(self._rules.get("momentum_long", 60))
            win_v = int(self._rules.get("feature_window_vol", 64))
            arr = np.asarray(self._closes, dtype=np.float64)
            rets = np.diff(np.log(arr + 1e-12))
            if len(rets) < max(mom_l, win_v):
                return 0
            ms = float(np.mean(rets[-mom_s:]))
            ml = float(np.mean(rets[-mom_l:]))
            vol = float(np.std(rets[-win_v:]) + 1e-9)
            signal_strength = (ms - ml) / vol
            # Gate: only take a position if the signal clears a vol-scaled band.
            if signal_strength > 0.5:
                return 1
            if signal_strength < -0.5:
                return -1
            return 0
        except Exception as exc:
            self.log.warning(f"fallback action raised ({exc}); FLAT")
            return 0

    def _reconcile_position(self, desired: int) -> None:
        """Emit at most one market order to move current → desired."""
        if desired == self._position:
            return
        if self.instrument is None:
            return
        delta = desired - self._position
        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        qty = self.instrument.make_qty(self.config.trade_size * Decimal(abs(delta)))
        try:
            order = self.order_factory.market(
                instrument_id=self.config.instrument_id,
                order_side=side,
                quantity=qty,
                time_in_force=TimeInForce.GTC,
            )
            self.submit_order(order)
            self._position = desired
        except Exception as exc:
            self.log.warning(f"order submit failed ({exc}); position unchanged")

    def on_stop(self) -> None:
        try:
            self.cancel_all_orders(self.config.instrument_id)
            self.unsubscribe_bars(self.config.bar_type)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Harness entry point
# ---------------------------------------------------------------------------
def train(ctx: Any) -> tuple[type[FinRLPolicyStrategy], FinRLPolicyConfig]:
    start_wall = time.time()
    NOTES_DIR.mkdir(exist_ok=True)
    ATTEMPTS_DIR.mkdir(exist_ok=True)
    iter_idx = int(ctx.iteration)
    attempt_dir = ATTEMPTS_DIR / f"{iter_idx:03d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)

    # 1. researcher (cached)
    _invoke_researcher(ctx, iter_idx)

    # 2. hypothesis-generator
    hypo = _hypothesis(ctx)

    # 3. env-designer + reward-shaper + 8. policy-trainer + 9. policy-critic
    fallback_mode = hypo.switch_to_fallback
    holdout_score = 0.0
    if not fallback_mode:
        try:
            closes = _load_train_closes(ctx)
        except Exception as exc:
            (attempt_dir / "env_designer.log").write_text(
                f"catalog load failed: {exc}\n{traceback.format_exc()}\n"
            )
            closes = []
        if len(closes) < 400:
            fallback_mode = True
        else:
            wall_remaining = max(
                30,
                int(PPO_WALL_BUDGET_S - (time.time() - start_wall)),
            )

            # signal.alarm watchdog (POSIX only); fallback to per-chunk check.
            alarm_fired = {"flag": False}

            def _alarm_handler(signum: int, frame: Any) -> None:  # noqa: ARG001
                alarm_fired["flag"] = True
                raise TimeoutError("PPO wall budget")

            alarm_armed = False
            old_handler = None
            if hasattr(signal, "SIGALRM"):
                try:
                    old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
                    signal.alarm(wall_remaining)
                    alarm_armed = True
                except Exception:
                    alarm_armed = False

            try:
                ok, score = _train_ppo(
                    closes, hypo, attempt_dir, start_wall, wall_remaining
                )
                fallback_mode = not ok
                holdout_score = score
            except TimeoutError:
                (attempt_dir / "policy_trainer.log").write_text(
                    "SIGALRM fired; PPO aborted, falling back.\n"
                )
                fallback_mode = True
            except Exception as exc:
                (attempt_dir / "policy_trainer.log").write_text(
                    f"PPO pipeline crashed: {exc}\n{traceback.format_exc()}\n"
                )
                fallback_mode = True
            finally:
                if alarm_armed:
                    try:
                        signal.alarm(0)
                        if old_handler is not None:
                            signal.signal(signal.SIGALRM, old_handler)
                    except Exception:
                        pass

    # 4. risk-officer
    _write_runtime_rules(fallback_mode, hypo)

    # 5. memory-keeper
    _record_memory(ctx, hypo, fallback_mode, holdout_score)

    # 3. critic (aggregate)
    _write_critic(attempt_dir, hypo, fallback_mode, holdout_score)

    # Build config pointing at persisted artifacts.
    instrument = ctx.config.instrument
    cfg = FinRLPolicyConfig(
        instrument_id=InstrumentId.from_str(instrument.symbol),
        bar_type=BarType.from_str(instrument.bar_type),
        policy_path=str(POLICY_PATH),
        rules_path=str(RULES_PATH),
    )
    log.info(
        "train done in %.1fs fallback=%s holdout=%.4f",
        time.time() - start_wall,
        fallback_mode,
        holdout_score,
    )
    return FinRLPolicyStrategy, cfg
