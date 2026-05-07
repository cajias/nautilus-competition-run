# Installation

**Docs:** https://nautilustrader.io/docs/latest/getting_started/installation/

## Requirements

- Python 3.10, 3.11, or 3.12
- Linux, macOS, or Windows

## Install

```bash
pip install nautilus_trader

# With Redis support (for live trading)
pip install nautilus_trader[redis]
```

## Verify

```python
import nautilus_trader
print(nautilus_trader.__version__)

from nautilus_trader.trading import Strategy
from nautilus_trader.backtest.engine import BacktestEngine
```

## Optional: Redis (Live Trading)

```bash
# macOS
brew install redis && redis-server

# Ubuntu
sudo apt-get install redis-server
redis-server

# Verify
redis-cli ping  # PONG
```

## Optional: uvloop (Linux/macOS)

```bash
pip install uvloop
```

```python
import uvloop
uvloop.install()
```

## Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
pip install nautilus_trader
```

## From Source

```bash
git clone https://github.com/nautechsystems/nautilus_trader.git
cd nautilus_trader
pip install -e .
```

## Build Errors

```bash
# Linux
sudo apt-get install build-essential python3-dev

# macOS
xcode-select --install
```
