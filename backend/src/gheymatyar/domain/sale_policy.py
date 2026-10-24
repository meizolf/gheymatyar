"""Fixed Pioneers sale-column policy.

``نرخ فروش اصلی`` is always stored and exported in Rial. TOP Industrial and
Kian print Toman and convert with ``TOMAN_TO_RIAL`` exactly once. Other
supported suppliers keep their confirmed printed or per-unit amounts.

Length, metre, branch, roll, and package counts belong in the product name.
Prices are never multiplied by those quantities, and there is no currency or
price-basis setting.
"""

from __future__ import annotations

from decimal import Decimal

#: Currency of the Pioneers final-sale column. Always Rial.
PIONEERS_SALE_CURRENCY = "rial"

#: Toman → Rial factor for suppliers that print Toman (TOP Industrial, Kian).
TOMAN_TO_RIAL = Decimal("10")

#: Use the printed amount as the sale price. Do not multiply by length or pack.
PRICE_BASIS_PRINTED = "printed"

#: Legacy SQLite keys. Startup deletes them. They are not settings anymore.
OBSOLETE_SETTING_KEYS = (
    "pioneers_sale_currency",
    "pioneers_sale_basis",
)
