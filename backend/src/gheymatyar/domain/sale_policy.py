"""Confirmed Pioneers sale-column policy.

User-confirmed business rule: ``نرخ فروش اصلی`` is stored and exported in
**Rial**. Supplier processors may print other currencies; conversion into
this column must use ``Decimal`` and keep the original amount/currency in
item metadata.
"""

from __future__ import annotations

from decimal import Decimal

#: Confirmed currency of the Pioneers final-sale column.
PIONEERS_SALE_CURRENCY = "rial"

#: Setting key for the confirmed Pioneers sale currency.
SETTING_SALE_CURRENCY_KEY = "pioneers_sale_currency"

#: Setting key for the confirmed sale basis when the workbook has no unit.
SETTING_SALE_BASIS_KEY = "pioneers_sale_basis"

#: Toman → Rial factor for suppliers that print Toman (e.g. TOP Industrial).
TOMAN_TO_RIAL = Decimal("10")

#: Price basis meaning: use the printed amount as the sale price as-is.
#: Package length / carton quantity must not be multiplied in.
PRICE_BASIS_PRINTED = "printed"
