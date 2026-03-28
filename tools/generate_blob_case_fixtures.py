#!/usr/bin/env python3
"""Generate synthetic sms.db/chat.db fixtures focused on message-body BLOB decoding.

This generator creates edge-case fixtures for:
- text column precedence
- attributedBody streamtyped decoding
- attributedBody NSKeyedArchiver binary plist decoding
- payload_data NSKeyedArchiver binary/xml plist decoding
- malformed blobs and fallback ordering
"""

import json
import plistlib
import sqlite3
import sys
from pathlib import Path

if sys.version_info < (3, 8):
    raise SystemExit("This fixture generator requires Python 3.8+")

BASE_EPOCH = 1735689600
STREAMTYPED_START_PATTERN = b"\x01\x2b"
STREAMTYPED_END_PATTERN = b"\x86\x84"

ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "samples" / "blob_cases"
IOS_DB = OUT_ROOT / "ios" / "sms_blob_cases.db"
IOS_EXPECTED = OUT_ROOT / "ios" / "sms_blob_cases_expected.json"
MAC_DB = OUT_ROOT / "macos" / "chat_blob_cases.db"
MAC_EXPECTED = OUT_ROOT / "macos" / "chat_blob_cases_expected.json"


def _ensure_dirs() -> None:
    IOS_DB.parent.mkdir(parents=True, exist_ok=True)
    MAC_DB.parent.mkdir(parents=True, exist_ok=True)


def _nskeyed_blob(text: str, binary: bool = True) -> bytes:
    uid = plistlib.UID  # type: ignore[attr-defined]
    payload = {
        "$archiver": "NSKeyedArchiver",
        "$version": 100000,
        "$objects": [
            "$null",
            {"NS.string": uid(2), "$class": uid(3)},
            text,
            {"$classname": "NSString", "$classes": ["NSString", "NSObject"]},
        ],
        "$top": {"root": uid(1)},
    }
    if binary:
        return plistlib.dumps(payload, fmt=plistlib.FMT_BINARY)
    # plistlib XML writer can't serialize UID objects. For XML variant, use a plain plist with strings.
    xml_payload = {
        "root": {
            "text": text,
            "format": "xml-plist",
        }
    }
    return plistlib.dumps(xml_payload, fmt=plistlib.FMT_XML)


def _streamtyped_blob(text: str) -> bytes:
    # Includes "streamtyped" marker + START/END delimiters expected by legacy parser.
    return b"streamtyped" + b"\x81\xe8" + STREAMTYPED_START_PATTERN + b"\x06" + text.encode("utf-8") + STREAMTYPED_END_PATTERN


def _streamtyped_lossy_blob(text: str) -> bytes:
    # Invalid UTF-8 prefix triggers loss-tolerant fallback path and drop_chars(3).
    return b"streamtyped" + STREAMTYPED_START_PATTERN + b"\xff\xfe\x00" + text.encode("utf-8") + STREAMTYPED_END_PATTERN


def _blob_cases():
    # (guid, text_col, attributedBody_blob, payload_data_blob, expected_decoded_text)
    return [
        ("case-001-text-only", "plain text from text column", None, None, "plain text from text column"),
        ("case-002-text-wins", "text wins over blobs", _streamtyped_blob("attr should not win"), _nskeyed_blob("payload should not win"), "text wins over blobs"),
        ("case-003-attr-streamtyped", None, _streamtyped_blob("from streamtyped attr"), None, "from streamtyped attr"),
        ("case-004-attr-bplist", None, _nskeyed_blob("from attributedBody bplist"), None, "from attributedBody bplist"),
        ("case-005-payload-bplist", None, None, _nskeyed_blob("from payload_data bplist"), "from payload_data bplist"),
        ("case-006-attr-bad-payload-good", "", b"\x00\xffgarbage\x10\x11", _nskeyed_blob("payload fallback after bad attr"), "payload fallback after bad attr"),
        ("case-007-all-bad", None, b"\x00\xff\x00", b"\x01\x02\x03", ""),
        ("case-008-payload-xml-plist", None, None, _nskeyed_blob("from payload xml plist", binary=False), "from payload xml plist"),
        ("case-009-attr-inline-marker", None, _streamtyped_blob("\uFFFCinline object marker"), None, "\uFFFCinline object marker"),
        ("case-010-streamtyped-lossy", None, _streamtyped_lossy_blob("lossy streamtyped text"), None, "lossy streamtyped text"),
    ]


def _build_ios_fixture(db_path: Path, expected_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.executescript(
        """
        PRAGMA foreign_keys=OFF;
        CREATE TABLE handle (
            ROWID INTEGER PRIMARY KEY,
            id TEXT NOT NULL,
            service TEXT
        );
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY,
            guid TEXT NOT NULL,
            display_name TEXT
        );
        CREATE TABLE chat_handle_join (
            chat_id INTEGER NOT NULL,
            handle_id INTEGER NOT NULL
        );
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY,
            guid TEXT NOT NULL,
            text TEXT,
            attributedBody BLOB,
            payload_data BLOB,
            handle_id INTEGER,
            is_from_me INTEGER NOT NULL,
            service TEXT,
            date INTEGER NOT NULL,
            associated_message_guid TEXT,
            associated_message_type TEXT
        );
        CREATE TABLE chat_message_join (
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL
        );
        """
    )

    cur.execute("INSERT INTO handle(id, service) VALUES(?, ?)", ("+15555550100", "SMS"))
    h_sms = cur.lastrowid
    cur.execute("INSERT INTO chat(guid, display_name) VALUES(?, ?)", ("chat-blob-ios-1", "iOS BLOB decode matrix"))
    chat_id = cur.lastrowid
    cur.execute("INSERT INTO chat_handle_join(chat_id, handle_id) VALUES(?, ?)", (chat_id, h_sms))

    expected = {}
    for idx, (guid, text_col, attr_blob, payload_blob, expected_text) in enumerate(_blob_cases()):
        cur.execute(
            """
            INSERT INTO message(guid, text, attributedBody, payload_data, handle_id, is_from_me, service, date,
                                associated_message_guid, associated_message_type)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guid,
                text_col,
                attr_blob,
                payload_blob,
                h_sms if idx % 2 == 0 else None,
                0 if idx % 2 == 0 else 1,
                "SMS",
                BASE_EPOCH + (idx * 60),
                None,
                None,
            ),
        )
        mid = cur.lastrowid
        cur.execute("INSERT INTO chat_message_join(chat_id, message_id) VALUES(?, ?)", (chat_id, mid))
        expected[guid] = expected_text

    conn.commit()
    conn.close()
    expected_path.write_text(json.dumps(expected, indent=2, sort_keys=True), encoding="utf-8")


def _build_macos_fixture(db_path: Path, expected_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.executescript(
        """
        PRAGMA foreign_keys=OFF;
        CREATE TABLE handle (
            ROWID INTEGER PRIMARY KEY,
            id TEXT NOT NULL,
            service TEXT
        );
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY,
            guid TEXT NOT NULL,
            display_name TEXT,
            chat_identifier TEXT,
            service_name TEXT
        );
        CREATE TABLE chat_handle_join (
            chat_id INTEGER NOT NULL,
            handle_id INTEGER NOT NULL
        );
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY,
            guid TEXT NOT NULL,
            text TEXT,
            attributedBody BLOB,
            payload_data BLOB,
            handle_id INTEGER,
            is_from_me INTEGER NOT NULL,
            service TEXT,
            date INTEGER NOT NULL,
            associated_message_guid TEXT,
            associated_message_type TEXT
        );
        CREATE TABLE chat_message_join (
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            message_date INTEGER
        );
        """
    )

    cur.execute("INSERT INTO handle(id, service) VALUES(?, ?)", ("alice@example.com", "iMessage"))
    h_alice = cur.lastrowid
    cur.execute(
        "INSERT INTO chat(guid, display_name, chat_identifier, service_name) VALUES(?, ?, ?, ?)",
        ("chat-blob-macos-1", "macOS BLOB decode matrix", "blob-matrix", "iMessage"),
    )
    chat_id = cur.lastrowid
    cur.execute("INSERT INTO chat_handle_join(chat_id, handle_id) VALUES(?, ?)", (chat_id, h_alice))

    expected = {}
    for idx, (guid, text_col, attr_blob, payload_blob, expected_text) in enumerate(_blob_cases()):
        cur.execute(
            """
            INSERT INTO message(guid, text, attributedBody, payload_data, handle_id, is_from_me, service, date,
                                associated_message_guid, associated_message_type)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guid,
                text_col,
                attr_blob,
                payload_blob,
                h_alice if idx % 2 == 0 else None,
                0 if idx % 2 == 0 else 1,
                "iMessage",
                BASE_EPOCH + (idx * 60),
                None,
                None,
            ),
        )
        mid = cur.lastrowid
        cur.execute(
            "INSERT INTO chat_message_join(chat_id, message_id, message_date) VALUES(?, ?, ?)",
            (chat_id, mid, BASE_EPOCH + (idx * 60)),
        )
        expected[guid] = expected_text

    conn.commit()
    conn.close()
    expected_path.write_text(json.dumps(expected, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    _ensure_dirs()
    _build_ios_fixture(IOS_DB, IOS_EXPECTED)
    _build_macos_fixture(MAC_DB, MAC_EXPECTED)
    print(f"Wrote {IOS_DB}")
    print(f"Wrote {IOS_EXPECTED}")
    print(f"Wrote {MAC_DB}")
    print(f"Wrote {MAC_EXPECTED}")


if __name__ == "__main__":
    main()
