"""Shared base + helpers for all competition_3 team strategies.

The interesting piece is `TradeCloseCounter` — a small testable helper
that lets `TeamStrategyBase.on_position_closed()` decide when to call
`self.stop()`. Kept as a separate class so we can unit-test the
self-stop logic without a BacktestEngine.
"""
from __future__ import annotations

from nautilus_trader.trading.strategy import Strategy

from competition_3.shared.trade_close_counter import TradeCloseCounter


class TeamStrategyBase(Strategy):
    """Common bits: 20-trade self-stop, multi-instrument-aware on_start hook.

    Concrete strategies override `on_start_subscribe()` to subscribe to
    whichever symbols their /autoresearch found promising, and
    `on_bar(bar)` to do whatever they do.
    """

    SELF_STOP_AFTER_TRADES = 20

    def on_start(self) -> None:
        self._closed_counter = TradeCloseCounter(self.SELF_STOP_AFTER_TRADES)
        self.on_start_subscribe()

    def on_start_subscribe(self) -> None:
        """Override to subscribe to the team's chosen instruments + bar types."""
        raise NotImplementedError

    def on_position_closed(self, event) -> None:
        self._closed_counter.bump()
        if self._closed_counter.should_stop():
            self.log.info(
                f"competition_3: reached {self._closed_counter.target} closed trades; "
                f"self-stopping paper window"
            )
            self.stop()
