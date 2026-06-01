"""Tests for the shared self-stop trade-counter helper."""
from __future__ import annotations
from competition_3.shared.trade_close_counter import TradeCloseCounter


def test_counter_starts_at_zero() -> None:
    assert TradeCloseCounter(target=20).count == 0
    assert not TradeCloseCounter(target=20).should_stop()


def test_counter_reaches_target() -> None:
    c = TradeCloseCounter(target=20)
    for _ in range(19):
        c.bump()
        assert not c.should_stop()
    c.bump()
    assert c.should_stop()


def test_counter_keeps_counting_past_target() -> None:
    c = TradeCloseCounter(target=3)
    for _ in range(5):
        c.bump()
    assert c.count == 5
    assert c.should_stop()
