"""Helpers for loading Apple AddressBook.sqlitedb contact names."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Dict, Optional, Set, Any


PHONE_PROPERTIES = {3}
EMAIL_PROPERTIES = {4}
IM_PROPERTIES = {46}
SUPPORTED_PROPERTIES = PHONE_PROPERTIES | EMAIL_PROPERTIES | IM_PROPERTIES


@dataclass
class AddressBookData:
    handle_to_name: Dict[str, str]
    owner_name: Optional[str]
    owner_handle_keys: Set[str]


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _display_name_from_row(row: sqlite3.Row) -> Optional[str]:
    for key in ("DisplayName", "CompositeNameFallback"):
        value = _safe_text(row[key]) if key in row.keys() else ""
        if value:
            return value
    first = _safe_text(row["First"]) if "First" in row.keys() else ""
    middle = _safe_text(row["Middle"]) if "Middle" in row.keys() else ""
    last = _safe_text(row["Last"]) if "Last" in row.keys() else ""
    full = " ".join(x for x in (first, middle, last) if x)
    if full:
        return full
    for key in ("Organization", "Nickname"):
        value = _safe_text(row[key]) if key in row.keys() else ""
        if value:
            return value
    return None


def _strip_known_prefixes(raw: str) -> str:
    s = raw.strip()
    lower = s.lower()
    for prefix in ("e:", "p:", "i:", "s:", "tel:", "mailto:", "sms:"):
        if lower.startswith(prefix):
            s = s[len(prefix):]
            lower = s.lower()
    return s.strip()


def normalize_handle(raw: Any) -> str:
    return _strip_known_prefixes(_safe_text(raw))


def _phone_keys(raw: str) -> Set[str]:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return set()
    out = {digits}
    if len(digits) == 11 and digits.startswith("1"):
        out.add(digits[1:])
    if len(digits) == 10:
        out.add("1" + digits)
    return out


def handle_keys(raw: Any) -> Set[str]:
    s = normalize_handle(raw)
    if not s:
        return set()
    if "@" in s:
        return {s.lower()}
    phone = _phone_keys(s)
    if phone:
        return phone
    return {s.lower()}


def resolve_name_for_handle(handle: Any, mapping: Dict[str, str]) -> Optional[str]:
    if not mapping:
        return None
    for key in handle_keys(handle):
        name = mapping.get(key)
        if name:
            return name
    return None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,))
    return cur.fetchone() is not None


def load_address_book(path: str) -> AddressBookData:
    if not path:
        return AddressBookData(handle_to_name={}, owner_name=None, owner_handle_keys=set())

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "ABPerson") or not _table_exists(conn, "ABMultiValue"):
            logging.warning("Address Book DB missing expected ABPerson/ABMultiValue tables: %s", path)
            return AddressBookData(handle_to_name={}, owner_name=None, owner_handle_keys=set())

        person_names: Dict[int, str] = {}
        cur = conn.cursor()
        cur.execute("SELECT * FROM ABPerson")
        for row in cur:
            try:
                pid = int(row["ROWID"])
            except Exception:
                continue
            display = _display_name_from_row(row)
            if display:
                person_names[pid] = display

        handle_to_name: Dict[str, str] = {}
        handles_by_person: Dict[int, Set[str]] = {}
        cur.execute("SELECT record_id, property, value FROM ABMultiValue WHERE value IS NOT NULL")
        for row in cur:
            try:
                pid = int(row["record_id"])
                prop = int(row["property"]) if row["property"] is not None else None
            except Exception:
                continue
            if prop not in SUPPORTED_PROPERTIES:
                continue
            name = person_names.get(pid)
            if not name:
                continue
            keys = handle_keys(row["value"])
            if not keys:
                continue
            handles_by_person.setdefault(pid, set()).update(keys)
            for key in keys:
                handle_to_name.setdefault(key, name)

        owner_name = None
        owner_keys: Set[str] = set()
        if _table_exists(conn, "ABStore"):
            try:
                cur.execute(
                    """
                    SELECT MeIdentifier
                    FROM ABStore
                    WHERE MeIdentifier IS NOT NULL AND MeIdentifier > 0
                    ORDER BY Enabled DESC, ROWID ASC
                    """
                )
                for row in cur:
                    me_id = int(row["MeIdentifier"])
                    if me_id in person_names:
                        owner_name = person_names[me_id]
                        owner_keys = handles_by_person.get(me_id, set()).copy()
                        break
            except Exception:
                logging.debug("Unable to read ABStore MeIdentifier from %s", path)

        if owner_name:
            for key in owner_keys:
                handle_to_name[key] = owner_name

        return AddressBookData(
            handle_to_name=handle_to_name,
            owner_name=owner_name,
            owner_handle_keys=owner_keys,
        )
    finally:
        try:
            conn.close()
        except Exception as e:
            logging.debug("Failed to close Address Book DB %s: %s", path, e)
