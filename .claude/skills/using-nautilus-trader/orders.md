# Orders

**Location:** `nautilus_trader.model.orders`

**Docs:** https://nautilustrader.io/docs/latest/concepts/orders/

## Order Types

```python
# Market
order = self.order_factory.market(
    instrument_id=instrument_id,
    order_side=OrderSide.BUY,
    quantity=Quantity.from_str("1.0"),
)

# Limit
order = self.order_factory.limit(
    instrument_id=instrument_id,
    order_side=OrderSide.BUY,
    quantity=Quantity.from_str("1.0"),
    price=Price.from_str("50000.00"),
    time_in_force=TimeInForce.GTC,
)

# Stop Market
order = self.order_factory.stop_market(
    instrument_id=instrument_id,
    order_side=OrderSide.SELL,
    quantity=Quantity.from_str("1.0"),
    trigger_price=Price.from_str("49000.00"),
    trigger_type=TriggerType.LAST_PRICE,
)

# Stop Limit
order = self.order_factory.stop_limit(
    instrument_id=instrument_id,
    order_side=OrderSide.SELL,
    quantity=Quantity.from_str("1.0"),
    trigger_price=Price.from_str("49000.00"),
    price=Price.from_str("48900.00"),
)

# Trailing Stop
order = self.order_factory.trailing_stop_market(
    instrument_id=instrument_id,
    order_side=OrderSide.SELL,
    quantity=Quantity.from_str("1.0"),
    trigger_price=Price.from_str("49000.00"),
    trailing_offset=Price.from_str("500.00"),
    trailing_offset_type=TrailingOffsetType.PRICE,
)
```

## Time In Force

```python
TimeInForce.GTC   # Good Till Cancelled
TimeInForce.IOC   # Immediate Or Cancel
TimeInForce.FOK   # Fill Or Kill
TimeInForce.DAY   # Day order
TimeInForce.GTD   # Good Till Date (requires expire_time)
```

## Order Management

```python
self.submit_order(order)
self.cancel_order(order)
self.modify_order(order, quantity=new_qty, price=new_price)
self.cancel_all_orders()
self.cancel_all_orders(instrument_id=instrument_id)
```

## Contingent Orders

```python
# OCO (One-Cancels-Other)
tp = self.order_factory.limit(..., contingency_type=ContingencyType.OCO)
sl = self.order_factory.stop_market(
    ...,
    contingency_type=ContingencyType.OCO,
    linked_order_ids=[tp.client_order_id],
)
tp.linked_order_ids = [sl.client_order_id]

# OTO (One-Triggers-Other)
entry = self.order_factory.limit(...)
stop = self.order_factory.stop_market(
    ...,
    contingency_type=ContingencyType.OTO,
    linked_order_ids=[entry.client_order_id],
)
```

## Order State

```python
order = self.cache.order(client_order_id)

order.is_open        # Working at venue
order.is_closed      # Terminal state
order.is_pending     # Pending modify/cancel
order.quantity       # Total quantity
order.filled_qty     # Filled quantity
order.leaves_qty     # Remaining
order.avg_px         # Average fill price
```

## Order Events

```python
def on_order_submitted(self, event: OrderSubmitted): pass
def on_order_accepted(self, event: OrderAccepted): pass
def on_order_rejected(self, event: OrderRejected): pass
def on_order_filled(self, event: OrderFilled): pass
def on_order_cancelled(self, event: OrderCancelled): pass
def on_order_expired(self, event: OrderExpired): pass
```

## Additional Options

```python
order = self.order_factory.limit(
    ...,
    post_only=True,          # Maker only
    reduce_only=True,        # Only reduce position
    display_qty=Quantity.from_str("0.1"),  # Iceberg
    tags=["entry"],          # Custom tags
)
```
