# Troubleshooting

## Installation

```bash
pip show nautilus_trader
python -c "import nautilus_trader; print(nautilus_trader.__version__)"
```

**Build errors:**
```bash
# Linux
sudo apt-get install build-essential python3-dev
# macOS
xcode-select --install
```

## Data Issues

**"Data must be sorted chronologically"**
```python
bars = sorted(bars, key=lambda x: x.ts_event)
```

**"Instrument not found in cache"**
```python
engine.add_instrument(instrument)  # Before add_data
engine.add_data(bars)
```

**No data received**: Check InstrumentId/BarType match exactly
```python
# Must match
InstrumentId.from_str("BTCUSDT.BINANCE")
BarType.from_str("BTCUSDT.BINANCE-1-MINUTE-LAST-EXTERNAL")
```

## Backtest Issues

**Orders not filling:**
```python
FillModel(prob_fill_on_limit=1.0)  # Always fill for testing
```

**Indicator not initializing:**
```python
self.register_indicator_for_bars(bar_type, indicator)  # Must register
self.subscribe_bars(bar_type)

def on_bar(self, bar):
    if not self.indicator.initialized:
        return  # Wait for warmup
```

## Live Trading

**Connection failed:**
- Check API credentials: `os.getenv("BINANCE_API_KEY")`
- Verify network: `ping api.binance.com`
- Check testnet config

**Redis errors:**
```bash
redis-cli ping  # Should return PONG
redis-server    # Start if not running
```

**Order rejected:**
- Insufficient balance
- Invalid price/quantity (check min/max)
- Rate limit exceeded

## Debug

```python
LoggingConfig(log_level="DEBUG")

# In strategy
self.log.info(f"Indicator: {self.ema.value}")
self.log.info(f"Position: {self.portfolio.net_position(instrument_id)}")
```

## Resources

- GitHub Issues: https://github.com/nautechsystems/nautilus_trader/issues
- Docs: https://nautilustrader.io/docs/
