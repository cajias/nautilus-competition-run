"""Trade close counter helper for adaptive paper window self-stop logic."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class TradeCloseCounter:
    """Counts closed positions and signals when to self-stop the paper run."""
    target: int = 20
    count: int = 0

    def bump(self) -> None:
        self.count += 1

    def should_stop(self) -> bool:
        return self.count >= self.target
