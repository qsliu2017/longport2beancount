from beancount.core.data import Transaction, Posting, Amount, CostSpec
from longport.openapi import (
    OrderDetail,
    OrderStatus,
    ChargeCategoryCode,
    OrderSide,
    OrderChargeFee,
    OrderChargeItem,
)
from decimal import Decimal

EMPTY_COST_SPEC = CostSpec(
    number_per=None,
    number_total=None,
    currency=None,
    date=None,
    label=None,
    merge=None,
)


def default_transaction_narration(order: OrderDetail) -> str:
    return f"{'Buy ' if order.side == OrderSide.Buy else 'Sell ' if order.side == OrderSide.Sell else ''}{order.quantity} {order.stock_name}"


def default_stock_account(order: OrderDetail) -> str:
    return "Assets:Invest:" + order.symbol


def default_cash_account(order: OrderDetail) -> str:
    return "Assets:Invest:Cash"


def default_fee_account(
    order: OrderDetail, item: OrderChargeItem, fee: OrderChargeFee
) -> str:
    return f"Expenses:Commission:{'Broker:' if item.code == ChargeCategoryCode.Broker else 'Third:' if item.code == ChargeCategoryCode.Third else ''}{fee.code}"


def default_gain_account(order: OrderDetail) -> str:
    return "Income:CapitalGains"


def order_to_transaction(
    order: OrderDetail,
    *,
    transaction_narration=default_transaction_narration,
    stock_account=default_stock_account,
    cash_account=default_cash_account,
    fee_account=default_fee_account,
    gain_account=default_gain_account,
) -> Transaction:
    is_us_option = order.symbol.endswith(".US") and (
        order.stock_name.endswith(" Call") or order.stock_name.endswith(" Put")
    )
    return Transaction(
        meta={},
        date=order.submitted_at,
        flag="*",
        payee=None,
        narration=transaction_narration(order),
        tags=frozenset(),
        links=frozenset(),
        postings=(
            [
                Posting(
                    account=stock_account(order),
                    units=Amount(
                        Decimal(
                            history.quantity
                            * (1 if order.side == OrderSide.Buy else -1)
                        ),
                        order.symbol,
                    ),
                    cost=None if order.side != OrderSide.Sell else EMPTY_COST_SPEC,
                    price=Amount(
                        history.price * Decimal(100 if is_us_option else 1),
                        order.currency,
                    ),
                    flag=None,
                    meta=None,
                )
                for history in order.history
                if history.status == OrderStatus.Filled
            ]
            + [
                Posting(
                    account=fee_account(order, item, fee),
                    units=Amount(fee.amount, fee.currency),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                )
                for item in order.charge_detail.items
                for fee in item.fees
            ]
            + [
                Posting(
                    account=cash_account(order),
                    units=Amount(
                        sum(
                            history.price * Decimal(history.quantity)
                            for history in order.history
                            if history.status == OrderStatus.Filled
                        )
                        * Decimal(-1 if order.side == OrderSide.Buy else 1)
                        * Decimal(100 if is_us_option else 1)
                        - sum(
                            fee.amount
                            for item in order.charge_detail.items
                            for fee in item.fees
                        ),
                        order.currency,
                    ),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                )
            ]
            + (
                [
                    Posting(
                        account=gain_account(order),
                        units=None,
                        cost=None,
                        price=None,
                        flag=None,
                        meta=None,
                    )
                ]
                if order.side == OrderSide.Sell
                else []
            )
        ),
    )


# example: fetch and convert orders of last 3 months
if __name__ == "__main__":
    from longport.openapi import Config, TradeContext
    from beancount.parser.printer import print_entry
    from sys import stderr
    from datetime import datetime
    from time import sleep

    config = Config.from_env()
    ctx = TradeContext(config)
    end = datetime.now()
    start = end.replace(month=end.month - 3)
    orders = [
        order
        for order in ctx.history_orders(start_at=start, end_at=end)
        if order.status == OrderStatus.Filled
    ]
    orders.sort(key=lambda order: order.updated_at)
    for order in orders:
        order_detail = ctx.order_detail(order.order_id)
        print(order_detail, file=stderr)
        print_entry(order_to_transaction(order_detail))
        sleep(1)  # avoid rate limit
