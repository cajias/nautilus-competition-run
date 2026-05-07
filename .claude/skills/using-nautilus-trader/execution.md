# Execution

**Docs:** https://nautilustrader.io/docs/latest/concepts/execution/

## Execution Flow

```
Strategy.submit_order()
    -> RiskEngine (pre-trade checks)
    -> ExecutionEngine (routing)
    -> OrderEmulator (if needed)
    -> ExecutionClient (venue adapter)
    -> Venue/Exchange
```

## Risk Engine

```python
from nautilus_trader.config import RiskEngineConfig

risk_config = RiskEngineConfig(
    bypass=False,  # NEVER bypass in production
    max_order_submit_rate=100,
    max_order_modify_rate=50,
    max_notionals={"BTCUSDT.BINANCE": 100000.0},
)
```

## OMS Types

- `OmsType.NETTING` - Single position per instrument (crypto)
- `OmsType.HEDGING` - Multiple positions per instrument (futures)

## Order Events

```python
def on_order_submitted(self, event): pass   # Sent to venue
def on_order_accepted(self, event): pass    # Venue acknowledged
def on_order_rejected(self, event): pass    # Venue rejected
def on_order_filled(self, event): pass      # (Partial) fill
def on_order_cancelled(self, event): pass
def on_order_denied(self, event): pass      # Risk engine denied
```

## Position Management

```python
self.close_position(position)
self.close_all_positions()
self.close_all_positions(instrument_id=instrument_id)
```

## Order Emulation

Client-side emulation for unsupported order types:
- Trailing stops (most venues)
- GTD orders (some venues)
- Complex contingent orders

## TWAP Execution Algorithm

```python
from nautilus_trader.execution.algorithm import TWAPExecAlgorithm

order = self.order_factory.market(
    instrument_id=instrument_id,
    order_side=OrderSide.BUY,
    quantity=quantity,
    exec_algorithm_id=ExecAlgorithmId("TWAP-001"),
    exec_algorithm_params={
        "horizon_secs": 3600,    # Total duration
        "interval_secs": 60,     # Child order interval
    },
)
```

## Live Reconciliation

On startup, `LiveExecutionEngine` syncs cached state with venue:
- Generates missing fill events
- Handles cancelled orders
- Adjusts positions

```python
from nautilus_trader.config import LiveExecEngineConfig

exec_config = LiveExecEngineConfig(
    reconciliation=True,
    reconciliation_lookback_mins=60,
)
```
