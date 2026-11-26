"""One way to write a rupee amount: Indian lakh/crore grouping (25,00,000.00), used in every message the server writes."""
from decimal import Decimal


def fmt_inr(amount, places: int = 2) -> str:
    """₹ with Indian grouping. `places` is the number of decimal places (0 for whole rupees)."""
    val = Decimal(str(amount or 0))
    sign = '-' if val < 0 else ''
    text = f'{abs(val):.{places}f}'
    whole, _, dec = text.partition('.')
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.append(head[-2:])
            head = head[:-2]
        if head:
            parts.append(head)
        whole = ','.join(reversed(parts)) + ',' + tail
    return f'{sign}₹{whole}' + (f'.{dec}' if dec else '')
