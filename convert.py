from beancount.core.data import Transaction, Posting, Amount, CostSpec
from longport.openapi import (
    OrderDetail,
    OrderStatus,
    OrderHistoryDetail,
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
    if order.symbol.endswith(".HK"):
        return "Assets:Invest:LongBridge:HK" + order.symbol[:-3]
    if is_us_option(order):
        return "Assets:Invest:LongBridge:Option:" + order.symbol[:-3]
    if order.symbol.endswith(".US"):
        return "Assets:Invest:LongBridge:" + order.symbol[:-3]
    return "Assets:Invest:LongBridge:" + order.symbol


def default_stock_currency(order: OrderDetail) -> str:
    if order.symbol.endswith(".HK"):
        return "HK" + order.symbol[:-3]
    if order.symbol.endswith(".US"):
        return order.symbol[:-3]
    return order.symbol


def default_cash_account(order: OrderDetail) -> str:
    return "Assets:Invest:LongBridge:Cash"


def default_fee_account(
    order: OrderDetail, item: OrderChargeItem, fee: OrderChargeFee
) -> str:
    return f"Expenses:Commission:LongBridge:{'Broker:' if item.code == ChargeCategoryCode.Broker else 'Third:' if item.code == ChargeCategoryCode.Third else ''}{fee.code}"


def default_gain_account(order: OrderDetail) -> str:
    return "Income:CapitalGains"


def is_us_option(order: OrderDetail) -> bool:
    return order.symbol.endswith(".US") and (
        order.stock_name.endswith(" Call") or order.stock_name.endswith(" Put")
    )


def order_history_to_posting(
    order: OrderDetail,
    history: OrderHistoryDetail,
    *,
    stock_account=default_stock_account,
    stock_currency=default_stock_currency,
) -> Posting:
    price_factor = Decimal(100) if is_us_option(order) else Decimal(1)
    if order.side == OrderSide.Sell:
        return Posting(
            account=stock_account(order),
            units=Amount(Decimal(-history.quantity), stock_currency(order)),
            cost=EMPTY_COST_SPEC,
            price=Amount(history.price*price_factor, order.currency),
            flag=None,
            meta=None,
        )
    if order.side == OrderSide.Buy:
        return Posting(
            account=stock_account(order),
            units=Amount(Decimal(history.quantity), stock_currency(order)),
            cost=CostSpec(
                number_per=history.price*price_factor,
                number_total=None,
                currency=order.currency,
                date=None,
                label=None,
                merge=None,
            ),
            price=None,
            flag=None,
            meta=None,
        )
    raise ValueError("Unsupported order side: {order.side}")


def order_to_transaction(
    order: OrderDetail,
    *,
    transaction_narration=default_transaction_narration,
    stock_account=default_stock_account,
    stock_currency=default_stock_currency,
    cash_account=default_cash_account,
    fee_account=default_fee_account,
    gain_account=default_gain_account,
) -> Transaction:
    return Transaction(
        meta={},
        date=order.submitted_at.date(),
        flag="*",
        payee=None,
        narration=transaction_narration(order),
        tags=frozenset(),
        links=frozenset(),
        postings=(
            [
                order_history_to_posting(
                    order, history,
                    stock_account=stock_account,
                    stock_currency=stock_currency,
                ) for history in order.history
                if history.status == OrderStatus.Filled or history.status == OrderStatus.PartialFilled
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
                            history.price * Decimal(history.quantity) for history in order.history
                            if history.status == OrderStatus.Filled or history.status == OrderStatus.PartialFilled
                        )
                        * Decimal(-1 if order.side == OrderSide.Buy else 1)
                        * Decimal(100 if is_us_option(order) else 1)
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


# example: fetch and convert orders of July 2024
if __name__ == "__main__":
    start = datetime(2024, 7, 1)
    end = datetime(2024, 7, 31)

    from beancount.core.data import Open, Close, Booking
    from beancount.parser.printer import print_entries
    from datetime import datetime, date
    from longport.openapi import Config, TradeContext, OrderStatus
    from sys import stderr
    from time import sleep

    ctx = TradeContext(Config.from_env())
    orders = [
        order
        for order in ctx.history_orders(start_at=start, end_at=end)
        if order.status == OrderStatus.Filled
    ]
    orders.sort(key=lambda order: order.updated_at)
    txns = []
    options: dict[str, tuple[date, date]] = {}  # option -> (first, last)
    for order in orders:
        order_detail = ctx.order_detail(order.order_id)
        print(order_detail, file=stderr)
        if is_us_option(order_detail):
            option = order_detail.symbol[:-3]
            options[option] = (
                order_detail.updated_at.date(),
                order_detail.updated_at.date()
            ) if option not in options else (
                min(options[option][0], order_detail.updated_at.date()),
                max(options[option][1], order_detail.updated_at.date()),
            )
        txns.append(order_to_transaction(order_detail))
        sleep(1)  # avoid rate limit

    with open(f"longbridge-2024-07.beancount", "w") as f:
        f.write(f"; {start.date()}-{end.date()}\n\n")
        print_entries([
            Open(
                meta={},
                date=first,
                account="Assets:Invest:LongBridge:Option:" + option,
                currencies=[option],
                booking=Booking.FIFO,
            ) for option, (first, last) in options.items()
        ], file=f)
        print_entries(txns, file=f)
        f.write("\n")
        print_entries([
            Close(
                meta={},
                date=last,
                account="Assets:Invest:LongBridge:Option:" + option,
            ) for option, (first, last) in options.items()
        ], file=f)
