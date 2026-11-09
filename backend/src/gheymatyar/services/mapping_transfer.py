"""Back up saved product mappings to a JSON file and import them elsewhere.

The file carries every saved mapping of every supplier, keyed by the stable
supplier key (``azin_pipe``, ``texa``, …) and the supplier product's name,
code, and unit. SQLite ids, Excel row numbers, sessions, and paths are never
written, and nothing from the file is trusted as an identity on import: the
supplier name is normalized again with that supplier's own rules, and the
identity key is rebuilt from it.

Import is planned first and written only when the user confirms:

* ``new``: the supplier product has no mapping here and its Pioneers product
  is free → inserted.
* ``identical``: the same supplier product already maps to the same Pioneers
  product → skipped.
* ``conflict``: the supplier product maps to another Pioneers product here
  (``mapped_elsewhere``; replaced only when the user picks it and the
  imported product is still free), or the Pioneers product is held by
  another supplier product of the same supplier (``target_taken``; never
  replaced, since that would take it from the other product).
* ``invalid``: unknown supplier, missing fields, or a file that contradicts
  itself → never written.

All writes happen in one transaction under the mapping write lock, so a
failure leaves SQLite as it was, and importing the same file again finds
everything identical. An imported mapping is checked against the uploaded
Pioneers file whenever it is used: if its product is missing or no longer
unique, matching asks for it to be confirmed again (see ``matching.py``),
so it never exports a price unverified.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from gheymatyar import __version__
from gheymatyar.domain.enums import MappingType
from gheymatyar.repositories._session import commit_or_raise
from gheymatyar.repositories.mapping_repository import MappingRepository
from gheymatyar.repositories.product_decision_repository import ProductDecisionRepository
from gheymatyar.repositories.records import ProductMappingRecord, SupplierRecord
from gheymatyar.repositories.supplier_repository import SupplierRepository
from gheymatyar.services.mapping_uniqueness import (
    MAPPING_WRITE_LOCK,
    PioneersTarget,
    active_mappings,
    mapping_target,
    pioneers_target,
)
from gheymatyar.services.product_identity import supplier_product_identity
from gheymatyar.suppliers.errors import UnsupportedSupplierError
from gheymatyar.suppliers.registry import SupplierProcessorRegistry, get_default_registry

FORMAT = "gheymatyar-mappings"
SCHEMA_VERSION = 1
MAX_IMPORT_BYTES = 20 * 1024 * 1024
MAX_IMPORT_RECORDS = 200_000
_TEXT_LIMIT = 2000


class MappingImportError(ValueError):
    """The file as a whole cannot be imported (format, version, size)."""


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _supplier_key(row: SupplierRecord, registry: SupplierProcessorRegistry) -> str:
    """The registry key a supplier row belongs to (rows store it as parser_type)."""
    if row.parser_type in registry.keys():
        return row.parser_type
    for key in registry.keys():
        if registry.get(key).display_name == row.name:
            return key
    return row.parser_type


def export_document(db: Session) -> dict[str, Any]:
    """Every saved mapping of every supplier, in a stable order. Read-only."""
    registry = get_default_registry()
    repo = MappingRepository(db)
    records = []
    for supplier in SupplierRepository(db).list_all():
        key = _supplier_key(supplier, registry)
        for mapping in repo.list_for_supplier(supplier.id):
            records.append({
                "supplier_key": key,
                "supplier_name_raw": mapping.supplier_name_raw,
                "supplier_name_normalized": mapping.supplier_name_normalized,
                "supplier_code": mapping.supplier_code,
                "unit_normalized": mapping.unit_normalized,
                "legacy_unscoped": mapping.legacy_unscoped,
                "pioneers_name_raw": mapping.pioneers_name_raw,
                "pioneers_name_normalized": mapping.pioneers_name_normalized,
                "pioneers_code": mapping.pioneers_code,
                "mapping_type": mapping.mapping_type,
                "created_at": _iso(mapping.created_at),
                "updated_at": _iso(mapping.updated_at),
            })
    records.sort(key=lambda r: (
        r["supplier_key"], r["supplier_name_normalized"], r["supplier_code"] or "",
        r["unit_normalized"] or "",
    ))
    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "exported_at": _iso(datetime.now(timezone.utc)),
        "app_version": __version__,
        "mapping_count": len(records),
        "mappings": records,
    }


@dataclass
class ImportRecord:
    index: int
    supplier_key: str
    supplier_name: str
    normalized_name: str
    identity: str
    supplier_code: str | None
    unit: str | None
    legacy_unscoped: bool
    pioneers_name: str
    pioneers_code: str | None
    mapping_type: str

    @property
    def target(self) -> PioneersTarget:
        return pioneers_target(self.pioneers_code, self.pioneers_name)


@dataclass
class PlannedRecord:
    index: int
    status: str  # new | identical | conflict | invalid
    supplier_key: str | None = None
    supplier_name: str | None = None
    pioneers_name: str | None = None
    pioneers_code: str | None = None
    reason: str | None = None  # conflict kind or invalid reason
    existing_pioneers_name: str | None = None
    existing_pioneers_code: str | None = None
    holder: str | None = None
    replaceable: bool = False
    record: ImportRecord | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value for key, value in self.__dict__.items() if key != "record"
        }


def read_document(raw: bytes) -> list[Any]:
    """The ``mappings`` list of a valid export file; raises for anything else."""
    if len(raw) > MAX_IMPORT_BYTES:
        raise MappingImportError("mapping file is too large")
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MappingImportError("mapping file is not valid UTF-8 JSON") from exc
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise MappingImportError("file is not a GheymatYar mappings export")
    version = document.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise MappingImportError("mapping file has no schema version")
    if version != SCHEMA_VERSION:
        raise MappingImportError(f"unsupported mapping schema version {version}")
    mappings = document.get("mappings")
    if not isinstance(mappings, list):
        raise MappingImportError("mapping file has no mappings list")
    if len(mappings) > MAX_IMPORT_RECORDS:
        raise MappingImportError("mapping file has too many records")
    return mappings


def _text(value: Any, field_name: str, *, required: bool) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    if len(value) > _TEXT_LIMIT:
        raise ValueError(f"{field_name} is too long")
    return value.strip()


def _parse_record(index: int, raw: Any, registry: SupplierProcessorRegistry) -> ImportRecord:
    if not isinstance(raw, dict):
        raise ValueError("record is not an object")
    key = _text(raw.get("supplier_key"), "supplier_key", required=True)
    try:
        processor = registry.get(key)
    except UnsupportedSupplierError as exc:
        raise ValueError(f"unknown supplier {key}") from exc
    supplier_name = _text(raw.get("supplier_name_raw"), "supplier_name_raw", required=True)
    pioneers_name = _text(raw.get("pioneers_name_raw"), "pioneers_name_raw", required=True)
    code = _text(raw.get("supplier_code"), "supplier_code", required=False)
    unit = _text(raw.get("unit_normalized"), "unit_normalized", required=False)
    pioneers_code = _text(raw.get("pioneers_code"), "pioneers_code", required=False)
    legacy = raw.get("legacy_unscoped", False)
    if not isinstance(legacy, bool):
        raise ValueError("legacy_unscoped must be true or false")
    try:
        mapping_type = MappingType(raw.get("mapping_type") or MappingType.MANUAL.value).value
    except ValueError as exc:
        raise ValueError("mapping_type is not recognized") from exc
    # Rebuilt with this supplier's own rules, exactly as a saved mapping is.
    normalized = (processor.normalize_supplier_name(supplier_name) or "").strip()
    if not normalized:
        raise ValueError("supplier_name_raw has no usable name")
    identity = supplier_product_identity(
        normalized_name=normalized, supplier_code=code, unit=unit
    )
    return ImportRecord(
        index=index, supplier_key=key, supplier_name=supplier_name,
        normalized_name=normalized, identity=identity, supplier_code=code, unit=unit,
        legacy_unscoped=legacy, pioneers_name=pioneers_name, pioneers_code=pioneers_code,
        mapping_type=mapping_type,
    )


class _Holders:
    """Which active supplier product holds each Pioneers product (one supplier).

    Indexed by code and by name so a large file is checked in linear time;
    the rule is :meth:`PioneersTarget.same_as` (codes when both have one,
    names otherwise).
    """

    def __init__(self, mappings: Iterable[ProductMappingRecord], ignored: set[str]) -> None:
        self._targets: dict[str, PioneersTarget] = {}
        self._names: dict[str, str] = {}
        self._by_code: dict[str, set[str]] = {}
        self._by_name: dict[str, set[str]] = {}
        self._ignored = ignored
        for mapping in active_mappings(mappings, ignored):
            self.hold(mapping.identity_key, mapping_target(mapping), mapping.supplier_name_raw)

    def hold(self, identity: str, target: PioneersTarget, supplier_name: str) -> None:
        if identity in self._ignored:
            return  # an ignored product releases its Pioneers product
        self.release(identity)
        self._targets[identity] = target
        self._names[identity] = supplier_name
        if target.code:
            self._by_code.setdefault(target.code, set()).add(identity)
        self._by_name.setdefault(target.name, set()).add(identity)

    def release(self, identity: str) -> None:
        target = self._targets.pop(identity, None)
        if target is None:
            return
        if target.code:
            self._by_code[target.code].discard(identity)
        self._by_name[target.name].discard(identity)

    def holder(self, target: PioneersTarget, *, besides: str) -> str | None:
        same_name = self._by_name.get(target.name, set())
        if target.code:
            hits = self._by_code.get(target.code, set()) | {
                i for i in same_name if not self._targets[i].code
            }
        else:
            hits = same_name
        found = sorted(hits - {besides})
        return self._names[found[0]] if found else None


def _supplier_row(db: Session, key: str, *, create: bool) -> SupplierRecord | None:
    repo = SupplierRepository(db)
    rows = repo.list_all()
    row = next((r for r in rows if r.parser_type == key), None)
    if row is None:
        processor = get_default_registry().get(key)
        row = repo.get_by_name(processor.display_name)
        if row is None and create:
            row = repo.create(name=processor.display_name, parser_type=key)
    return row


def plan_import(db: Session, raw: bytes, *, replace: Iterable[int] = ()) -> list[PlannedRecord]:
    """Classify every record against SQLite. Writes nothing.

    ``replace`` lists record indexes the user chose to replace; it changes
    the plan only for ``mapped_elsewhere`` conflicts whose imported Pioneers
    product is free.
    """
    registry = get_default_registry()
    chosen = set(replace)
    planned: list[PlannedRecord] = []
    parsed: list[ImportRecord] = []
    for index, raw_record in enumerate(read_document(raw)):
        try:
            parsed.append(_parse_record(index, raw_record, registry))
        except ValueError as exc:
            planned.append(PlannedRecord(index=index, status="invalid", reason=str(exc)))

    by_supplier: dict[str, list[ImportRecord]] = {}
    for record in parsed:
        by_supplier.setdefault(record.supplier_key, []).append(record)
    for key, records in by_supplier.items():
        supplier = _supplier_row(db, key, create=False)
        existing = (
            MappingRepository(db).list_for_supplier(supplier.id) if supplier else []
        )
        ignored = (
            ProductDecisionRepository(db).ignored_identity_keys(supplier.id)
            if supplier else set()
        )
        planned.extend(_plan_supplier(records, existing, ignored, chosen))
    return sorted(planned, key=lambda p: p.index)


def _plan_supplier(records, existing, ignored, chosen) -> list[PlannedRecord]:
    by_identity = {m.identity_key: m for m in existing}
    holders = _Holders(existing, ignored)
    seen: dict[str, ImportRecord] = {}
    out: list[PlannedRecord] = []
    for record in records:
        item = PlannedRecord(
            index=record.index, status="new", supplier_key=record.supplier_key,
            supplier_name=record.supplier_name, pioneers_name=record.pioneers_name,
            pioneers_code=record.pioneers_code, record=record,
        )
        out.append(item)
        earlier = seen.get(record.identity)
        if earlier is not None:
            same = earlier.target.same_as(record.target)
            item.status = "identical" if same else "invalid"
            item.reason = None if same else "file maps this supplier product twice"
            continue
        seen[record.identity] = record
        current = by_identity.get(record.identity)
        if current is not None and mapping_target(current).same_as(record.target):
            item.status = "identical"
            continue
        holder = (
            None if record.legacy_unscoped
            else holders.holder(record.target, besides=record.identity)
        )
        if current is not None:
            item.status, item.reason = "conflict", "mapped_elsewhere"
            item.existing_pioneers_name = current.pioneers_name_raw
            item.existing_pioneers_code = current.pioneers_code
            item.holder = holder
            item.replaceable = holder is None
            if item.replaceable and record.index in chosen:
                item.status = "replace"
                holders.hold(record.identity, record.target, record.supplier_name)
            continue
        if holder is not None:
            item.status, item.reason, item.holder = "conflict", "target_taken", holder
            continue
        if not record.legacy_unscoped:
            holders.hold(record.identity, record.target, record.supplier_name)
    return out


def summarize(plan: list[PlannedRecord]) -> dict[str, int]:
    counts = {"new": 0, "identical": 0, "conflict": 0, "invalid": 0, "replace": 0}
    for item in plan:
        counts[item.status] += 1
    return counts


def apply_import(db: Session, raw: bytes, *, replace: Iterable[int] = ()) -> list[PlannedRecord]:
    """Insert new mappings and the chosen replacements in one transaction."""
    with MAPPING_WRITE_LOCK:
        plan = plan_import(db, raw, replace=replace)
        repo = MappingRepository(db)
        suppliers: dict[str, SupplierRecord] = {}
        try:
            for item in plan:
                record = item.record
                if record is None or item.status not in {"new", "replace"}:
                    continue
                supplier = suppliers.get(record.supplier_key)
                if supplier is None:
                    supplier = _supplier_row(db, record.supplier_key, create=True)
                    assert supplier is not None
                    suppliers[record.supplier_key] = supplier
                if item.status == "new":
                    repo.create(
                        supplier_id=supplier.id,
                        supplier_name_raw=record.supplier_name,
                        supplier_name_normalized=record.normalized_name,
                        supplier_code=record.supplier_code,
                        unit=record.unit,
                        legacy_unscoped=record.legacy_unscoped,
                        pioneers_name_raw=record.pioneers_name,
                        pioneers_code=record.pioneers_code,
                        mapping_type=record.mapping_type,
                    )
                else:
                    repo.update(
                        supplier_id=supplier.id,
                        identity_key=record.identity,
                        pioneers_name_raw=record.pioneers_name,
                        pioneers_code=record.pioneers_code,
                        mapping_type=MappingType.MANUAL,
                    )
            commit_or_raise(db)
        except Exception:
            db.rollback()
            raise
    return plan
