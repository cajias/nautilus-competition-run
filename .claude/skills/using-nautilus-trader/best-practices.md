# Best Practices

## Configuration

- Use `StrategyConfig` subclasses for all parameters
- Environment variables for credentials: `os.getenv("BINANCE_API_KEY")`
- Never hardcode secrets

## Testing Path

1. **Backtest** with realistic fill model: `FillModel(prob_fill_on_limit=0.2, prob_slippage=0.5)`
2. **Paper trade** on testnet: `testnet=True`
3. **Live** with small positions, gradually increase

## Risk Management

```python
# Never bypass risk engine in production
RiskEngineConfig(bypass=False, max_notionals={"BTCUSDT.BINANCE": 10000.0})

# Always use stops
stop = self.order_factory.stop_market(trigger_price=entry * 0.98)

# Check position limits
if abs(self.portfolio.net_position(instrument_id)) >= MAX_POSITION:
    return
```

## Performance

- Register indicators: `self.register_indicator_for_bars()` (auto-updates)
- Only subscribe to needed data (bars vs ticks)
- Use ParquetDataCatalog for backtests

## Error Handling

```python
def on_order_rejected(self, event):
    self.log.error(f"Rejected: {event.reason}")
    if "insufficient balance" in event.reason.lower():
        self.stop()
```

## State Persistence

```python
def on_save(self) -> dict:
    return {"trade_count": self.trade_count}

def on_load(self, state: dict):
    self.trade_count = state.get("trade_count", 0)
```

## Shutdown

```python
def on_stop(self):
    self.cancel_all_orders()
    if self.close_on_stop:
        self.close_all_positions()
```

## Pitfalls

- **Look-ahead bias**: Don't use bar.high/low for entry signals (known only after close)
- **Overfitting**: Test out-of-sample, keep strategies simple
- **Ignoring costs**: Account for commission + slippage
- **No risk management**: Always use stops and position limits
