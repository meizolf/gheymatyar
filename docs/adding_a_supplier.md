# Adding a New Supplier Processor

GheymatYar supports one processor per supplier PDF format. Core workflow
services (Excel parse/write, name matching, sessions, API) stay unchanged.

## Checklist

1. Provide a **real PDF sample** and written business rules (especially pricing).
2. Implement a processor class extending `BaseSupplierProcessor`.
3. Override `detection_rules()` with brand names, keywords, and websites so
   `SupplierDetector` can suggest the supplier from PDF **content** (not the
   filename). Detection is only a suggestion; the UI always requires confirmation
   before prices are parsed.
4. Register it in `get_default_registry()`.
5. Add fixtures under `fixtures/suppliers/` and tests under `backend/tests/`.
6. Expose it automatically via `GET /api/suppliers`.

Do **not** invent pricing formulas. If the PDF does not make the final sale
price interpretation clear, stop and ask for clarification.

## Minimal implementation

Create `backend/src/gheymatyar/suppliers/my_supplier.py`:

```python
from pathlib import Path
from decimal import Decimal

from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.suppliers.base import BaseSupplierProcessor, SupplierParseResult


class MySupplierProcessor(BaseSupplierProcessor):
    supplier_key = "my_supplier"          # stable API key
    display_name = "نام تامین‌کننده"      # UI label

    def detection_rules(self):
        from gheymatyar.suppliers.detection import DetectionRules
        return DetectionRules(
            strong_markers=("نام تامین‌کننده", "برند"),
            weak_markers=("کلیدواژه محصول",),
            websites=("example.com",),
        )

    def parse_pdf(self, path: str | Path) -> SupplierParseResult:
        items: list[SupplierPriceItem] = []
        warnings: list[str] = []
        # Extract product name, optional code/size/unit, price…
        # Return standardized SupplierPriceItem rows.
        return SupplierParseResult(
            supplier_key=self.supplier_key,
            supplier_display_name=self.display_name,
            items=items,
            warnings=warnings,
            source_metadata={"source_path": str(path)},
        )

    def calculate_final_sale_price(self, item: SupplierPriceItem) -> Decimal:
        # Override ONLY when explicit supplier rules exist.
        return item.price

    def normalize_supplier_name(self, name: str) -> str:
        # Optional supplier-specific cleanup before shared matching.
        from gheymatyar.services.name_normalization import normalize_product_name
        return normalize_product_name(name)
```

Register in `backend/src/gheymatyar/suppliers/registry.py`:

```python
from gheymatyar.suppliers.my_supplier import MySupplierProcessor

registry.register(MySupplierProcessor())
```

## Contract

Every processor must:

- Understand **its own** PDF layout (do not reuse another supplier’s parser).
- Return `SupplierPriceItem` with a usable `supplier_name` (primary match key).
- Keep monetary values as `Decimal` (never `float`).
- Surface unreadable values as warnings/errors — never guess silently.
- Isolate pricing rules in `calculate_final_sale_price`.

Shared matching then applies:

1. Saved supplier-specific name mapping (SQLite)
2. Unique exact normalized-name match
3. Similar-name suggestions (manual confirmation only)
4. Otherwise `UNMATCHED`

## Tests to add

- PDF extraction against the real sample
- Final price calculation for that supplier’s rules
- At least one matching case against an anonymized Pioneers fixture
- Registry lists the new key; unknown keys still raise `UnsupportedSupplierError`
