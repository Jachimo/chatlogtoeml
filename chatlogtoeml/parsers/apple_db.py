"""Apple sms.db/chat.db parser.

This module parses Apple `sms.db` / `chat.db` SQLite databases and produces
`conversation.Conversation` objects consumable by conv_to_eml.mimefromconv.

Core requirement: decode message body BLOBs (`attributedBody`, `payload_data`)
using typedstream and NSKeyedArchiver decoders.
"""

from __future__ import annotations

import sqlite3
import datetime
import logging
import os
import plistlib
from typing import TYPE_CHECKING, Iterable, Optional, List, Dict, Any

import typedstream  # hard dependency: pytypedstream
import NSKeyedUnArchiver  # hard dependency: NSKeyedUnArchiver

from .imessage_common import build_conversation_from_segment, segment_messages
from . import addressbook

if TYPE_CHECKING:
    from ..conversation import Conversation

# Apple epoch (2001-01-01) -> Unix epoch offset in seconds
# NOTE: Possible this epoch was not consistently used, esp. in early iChat/iOS versions
APPLE_EPOCH_OFFSET = 978307200

# Streamtyped BLOB markers (magic numbers)
STREAMTYPED_START_PATTERN = b"\x01\x2b"
STREAMTYPED_END_PATTERN = b"\x86\x84"

# Common strings found in archived data that are not likely to be message text
_IGNORE_TEXT_TOKENS = {
    "NSString",
    "NSAttributedString",
    "NSMutableString",
    "NSMutableAttributedString",
    "NSObject",
    "NSDictionary",
    "NSMutableDictionary",
    "NSNumber",
    "NSValue",
    "__kIMMessagePartAttributeName",
}


def apple_ts_to_dt(ts: Optional[int]) -> Optional[datetime.datetime]:
    """Convert Apple DB timestamp (seconds/millis/micros/nanos since 2001-01-01)
    into a timezone-aware UTC datetime. Returns None on parse failure.
    """
    if ts is None:
        return None
    try:
        v = int(ts)
    except Exception:
        try:
            v = float(ts)
        except Exception:
            return None
    
    # Order-of-magnitude scaling (nano/micro/milli/seconds)
    try:
        if v > 1e14:
            # nanoseconds
            v = v / 1e9
        elif v > 1e11:
            # microseconds
            v = v / 1e6
        elif v > 1e9:
            # milliseconds
            v = v / 1e3
        # now v is seconds since 2001-01-01

        unix = float(v) + APPLE_EPOCH_OFFSET
        return datetime.datetime.fromtimestamp(unix, tz=datetime.timezone.utc)
    except Exception:
        return None


def _as_bytes(value: Any) -> Optional[bytes]:
    """Convert sqlite BLOB-like values into bytes."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    return None


def _drop_chars(text: str, offset: int) -> Optional[str]:
    """Drop a character offset from the front of a string."""
    if text is None:
        return None
    if offset <= 0:
        return text
    if len(text) <= offset:
        return None
    return text[offset:]


def _normalize_candidate_text(text: str) -> str:
    """Normalize extracted candidate text."""
    if text is None:
        return ''
    return text.replace('\x00', '').strip()


def _is_candidate_text(text: str) -> bool:
    """Filter extracted strings to likely user-visible message text."""
    t = _normalize_candidate_text(text)
    if not t:
        return False
    if t in _IGNORE_TEXT_TOKENS:
        return False
    if t.startswith('$'):
        return False
    # Require at least one likely human-visible char
    if not any(ch.isalnum() for ch in t):
        # allow URLs and attachment/app markers
        if 'http://' not in t and 'https://' not in t and '\uFFFC' not in t and '\uFFFD' not in t:
            return False
    return True


def _extract_text_candidates(obj: Any, out: List[str], seen: Optional[set] = None, depth: int = 0) -> None:
    """Recursively extract string candidates from arbitrary decoded objects."""
    if seen is None:
        seen = set()
    if obj is None or depth > 64:
        return

    if isinstance(obj, str):
        if _is_candidate_text(obj):
            out.append(_normalize_candidate_text(obj))
        return

    if isinstance(obj, bytes):
        try:
            s = obj.decode('utf-8', errors='ignore')
        except Exception:
            s = ''
        if _is_candidate_text(s):
            out.append(_normalize_candidate_text(s))
        return

    uid_type = getattr(plistlib, 'UID', None)
    if uid_type is not None and isinstance(obj, uid_type):
        return

    if isinstance(obj, (int, float, bool)):
        return

    obj_id = id(obj)
    if obj_id in seen:
        return
    seen.add(obj_id)

    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and _is_candidate_text(k):
                out.append(_normalize_candidate_text(k))
            _extract_text_candidates(v, out, seen, depth + 1)
        return

    if isinstance(obj, (list, tuple, set)):
        for item in obj:
            _extract_text_candidates(item, out, seen, depth + 1)
        return

    # typedstream objects and other wrappers often expose .value or __dict__
    try:
        if hasattr(obj, 'value'):
            _extract_text_candidates(getattr(obj, 'value'), out, seen, depth + 1)
    except Exception as e:
        logging.debug('Unable to extract candidate text via .value on %s: %s', type(obj).__name__, e)
    try:
        if hasattr(obj, '__dict__'):
            _extract_text_candidates(vars(obj), out, seen, depth + 1)
    except Exception as e:
        logging.debug('Unable to extract candidate text via __dict__ on %s: %s', type(obj).__name__, e)


def _choose_best_text(candidates: List[str]) -> Optional[str]:
    """Choose the best user-visible body text from extracted candidates."""
    if not candidates:
        return None
    seen = set()
    uniq = []
    for c in candidates:
        n = _normalize_candidate_text(c)
        if not n or n in seen:
            continue
        if not _is_candidate_text(n):
            continue
        seen.add(n)
        uniq.append(n)
    if not uniq:
        return None
    # Prefer candidates preserving replacement characters used by iMessage for inline objects.
    with_markers = [s for s in uniq if ('\uFFFC' in s or '\uFFFD' in s)]
    if with_markers:
        return max(with_markers, key=len)
    return max(uniq, key=len)


def _decode_streamtyped_legacy(blob: bytes) -> Optional[str]:
    """Legacy streamtyped parser, mirroring imessage-exporter fallback behavior."""
    if not blob:
        return None
    start = blob.find(STREAMTYPED_START_PATTERN)
    if start < 0:
        return None
    data = blob[start + len(STREAMTYPED_START_PATTERN):]
    end = data.find(STREAMTYPED_END_PATTERN)
    if end < 0:
        return None
    data = data[:end]
    if not data:
        return None
    try:
        s = data.decode('utf-8')
        s = _drop_chars(s, 1)
    except UnicodeDecodeError:
        s = data.decode('utf-8', errors='replace')
        s = _drop_chars(s, 3)
    if not s:
        return None
    s = _normalize_candidate_text(s)
    return s or None


def _resolve_nskeyed_value(item: Any, objects: List[Any], depth: int = 0) -> Any:
    """Resolve plist UID references in an NSKeyedArchiver object graph."""
    if depth > 128:
        return None
    uid_type = getattr(plistlib, 'UID', None)
    if uid_type is not None and isinstance(item, uid_type):
        try:
            idx = int(getattr(item, 'data'))
        except Exception:
            try:
                idx = int(item)
            except Exception:
                return None
        if 0 <= idx < len(objects):
            return _resolve_nskeyed_value(objects[idx], objects, depth + 1)
        return None
    if isinstance(item, list):
        return [_resolve_nskeyed_value(v, objects, depth + 1) for v in item]
    if isinstance(item, dict):
        out = {}
        for k, v in item.items():
            if k == '$class':
                continue
            out[k] = _resolve_nskeyed_value(v, objects, depth + 1)
        return out
    return item


def _decode_nskeyed_plist(blob: bytes) -> Optional[str]:
    """Decode likely NSKeyedArchiver plist bytes and extract best text."""
    if not blob:
        return None
    try:
        obj = plistlib.loads(blob)
    except Exception:
        return None

    # Generic extraction path first
    generic = []
    _extract_text_candidates(obj, generic)
    generic_best = _choose_best_text(generic)

    # NSKeyedArchiver object table path
    if isinstance(obj, dict) and '$objects' in obj and '$top' in obj:
        objects = obj.get('$objects')
        top = obj.get('$top')
        if isinstance(objects, list) and isinstance(top, dict):
            root_item = top.get('root')
            if root_item is None and len(top) == 1:
                try:
                    root_item = next(iter(top.values()))
                except Exception:
                    root_item = None
            if root_item is None and objects:
                root_item = objects[1] if len(objects) > 1 else objects[0]
            resolved = _resolve_nskeyed_value(root_item, objects) if root_item is not None else None
            candidates = []
            _extract_text_candidates(resolved, candidates)
            best = _choose_best_text(candidates)
            if best:
                return best

    return generic_best


def _decode_with_pytypedstream(blob: bytes) -> Optional[str]:
    """Decode typedstream data using pytypedstream (required dependency)."""
    if not blob:
        return None
    # Typedstream payloads should contain a "streamtyped" header signature.
    # Avoid invoking decoder on unrelated binary blobs.
    if b"streamtyped" not in blob:
        return None
    try:
        obj = typedstream.unarchive_from_data(blob)
    except Exception:
        return None
    candidates: List[str] = []
    _extract_text_candidates(obj, candidates)
    return _choose_best_text(candidates)


def _decode_with_nskeyedunarchiver(blob: bytes) -> Optional[str]:
    """Decode NSKeyedArchiver plist data using NSKeyedUnArchiver."""
    if not blob:
        return None
    # NSKeyedUnArchiver expects plist data. Guard to avoid expensive/unstable decode attempts.
    if not (
        blob.startswith(b"bplist00")
        or blob.lstrip().startswith(b"<?xml")
        or blob.lstrip().startswith(b"<plist")
    ):
        return None
    try:
        obj = NSKeyedUnArchiver.unserializeNSKeyedArchiver(blob)
    except Exception:
        return None
    candidates: List[str] = []
    _extract_text_candidates(obj, candidates)
    return _choose_best_text(candidates)


def _decode_attributed_body_blob(blob: Any) -> Optional[str]:
    """Decode message body from attributedBody BLOB (typedstream and plist formats)."""
    data = _as_bytes(blob)
    if not data:
        return None

    # Preferred: typedstream decoder
    text = _decode_with_pytypedstream(data)
    if text:
        return text

    # Rust-like legacy fallback parser for streamtyped payloads
    text = _decode_streamtyped_legacy(data)
    if text:
        return text

    # NSKeyedUnArchiver path for plist-packed payloads
    text = _decode_with_nskeyedunarchiver(data)
    if text:
        return text

    # Some exports may store plist-style payloads in attributedBody
    text = _decode_nskeyed_plist(data)
    if text:
        return text

    # Last-resort UTF-8 decode only for mostly-printable content to avoid
    # treating random binary garbage as message text.
    try:
        raw = data.decode('utf-8', errors='ignore')
    except Exception:
        return None
    if raw:
        printable = sum(1 for ch in raw if ch.isprintable() or ch in '\r\n\t')
        ratio = printable / max(1, len(raw))
    else:
        ratio = 0.0
    if ratio >= 0.95 and _is_candidate_text(raw):
        return _normalize_candidate_text(raw)
    return None


def _decode_payload_blob(blob: Any) -> Optional[str]:
    """Decode message text-like content from payload_data binary plist BLOB."""
    data = _as_bytes(blob)
    if not data:
        return None
    text = _decode_with_nskeyedunarchiver(data)
    if text:
        return text
    return _decode_nskeyed_plist(data)


def _decode_message_text(text_value: Any, attributed_body_blob: Any, payload_blob: Any) -> str:
    """Choose best available text from text column, attributedBody and payload_data blobs."""
    if isinstance(text_value, str) and text_value.strip():
        return text_value

    attr_text = _decode_attributed_body_blob(attributed_body_blob)
    if attr_text:
        return attr_text

    payload_text = _decode_payload_blob(payload_blob)
    if payload_text:
        return payload_text

    if isinstance(text_value, str):
        return text_value
    return ''


def _load_handles(conn: sqlite3.Connection) -> Dict[int, str]:
    """Load handle table into a mapping of handle_id -> handle string."""
    out: Dict[int, str] = {}
    try:
        cur = conn.cursor()
        cur.execute("SELECT rowid, id FROM handle")
    except sqlite3.OperationalError:
        # table missing or different schema
        logging.debug('handle table not present or accessible')
        return out
    for row in cur:
        try:
            hid = int(row[0])
            ident = row[1]
            out[hid] = ident
        except Exception:
            continue
    return out


def _load_chat_participants(conn: sqlite3.Connection) -> Dict[int, List[int]]:
    """Load chat -> list(handle_id) mapping from chat_handle_join (or equivalent).
    Returns mapping with chat_id ints as keys and lists of handle_ids.
    """
    out: Dict[int, List[int]] = {}
    cur = conn.cursor()
    tried = ["chat_handle_join", "chat_handle", "chat_handle_join_v1"]
    for tbl in tried:
        try:
            cur.execute(f"SELECT chat_id, handle_id FROM {tbl}")
            for row in cur:
                try:
                    cid = int(row[0])
                    hid = int(row[1])
                    out.setdefault(cid, []).append(hid)
                except Exception:
                    continue
            # if we succeeded, return
            if out:
                return out
        except sqlite3.OperationalError:
            continue
    # fallback: empty mapping
    return out


def _get_attachments_for_message(conn: sqlite3.Connection, message_rowid: int) -> List[Dict[str, Any]]:
    """Return list of attachment metadata dicts for a given message ROWID.

    This function is tolerant of varying attachment table schemas. It inspects the
    attachment table columns (PRAGMA table_info) and selects available columns,
    falling back to a minimal select (rowid, filename, mime_type) when necessary.
    Keys returned: rowid, filename, mime_type, transfer_name, total_bytes, uti, path
    """
    out: List[Dict[str, Any]] = []
    cur = conn.cursor()
    # Inspect attachment table columns
    try:
        cur.execute("PRAGMA table_info(attachment)")
        cols = [r[1] for r in cur.fetchall()]
    except Exception:
        cols = []

    minimal_sql = (
        "SELECT a.rowid as rowid, a.filename as filename, a.mime_type as mime_type "
        "FROM message_attachment_join j LEFT JOIN attachment a ON j.attachment_id = a.rowid "
        "WHERE j.message_id = ?"
    )

    # Build richer select only if columns appear present
    rich_cols = ["a.rowid as rowid"]
    if 'filename' in cols:
        rich_cols.append('a.filename as filename')
    if 'mime_type' in cols:
        rich_cols.append('a.mime_type as mime_type')
    if 'transfer_name' in cols:
        rich_cols.append('a.transfer_name as transfer_name')
    if 'total_bytes' in cols:
        rich_cols.append('a.total_bytes as total_bytes')
    if 'uti' in cols:
        rich_cols.append('a.uti as uti')

    try:
        if len(rich_cols) > 1:
            sel = ', '.join(rich_cols)
            sql = f"SELECT {sel} FROM message_attachment_join j LEFT JOIN attachment a ON j.attachment_id = a.rowid WHERE j.message_id = ?"
            cur.execute(sql, (message_rowid,))
        else:
            cur.execute(minimal_sql, (message_rowid,))
    except sqlite3.OperationalError:
        # fallback to minimal
        try:
            cur.execute(minimal_sql, (message_rowid,))
        except sqlite3.OperationalError:
            return out

    # Map rows to dict using cursor.description to be schema-agnostic
    colnames = [d[0] for d in cur.description] if cur.description else []
    for row in cur:
        try:
            rdict = {}
            for idx, cname in enumerate(colnames):
                try:
                    rdict[cname] = row[idx]
                except Exception:
                    rdict[cname] = None
            out.append({
                'rowid': rdict.get('rowid'),
                'filename': rdict.get('filename'),
                'mime_type': rdict.get('mime_type'),
                'transfer_name': rdict.get('transfer_name'),
                'total_bytes': rdict.get('total_bytes'),
                'uti': rdict.get('uti'),
                'path': rdict.get('filename') or rdict.get('transfer_name'),
            })
        except Exception:
            continue
    return out


def _resolve_attachment_path(raw_path: Optional[str], db_path: str, attachment_root: Optional[str]) -> Optional[str]:
    """Resolve attachment paths from Apple DBs into local filesystem paths.

    Supports multiple cases:
    - absolute paths
    - paths rooted at ~/Library/SMS/Attachments/... (remapped to attachment_root)
    - relative paths (resolved against attachment_root first, then DB directory)
    """
    if not raw_path:
        return None
    p = str(raw_path).strip()
    if not p:
        return None

    candidates: List[str] = []
    db_dir = os.path.dirname(os.path.abspath(db_path))
    root_abs = os.path.abspath(attachment_root) if attachment_root else None

    # 1) explicit absolute path
    if os.path.isabs(p):
        candidates.append(p)

    # 2) tilde-style Apple paths from backups (do not expand to current HOME; remap to provided root)
    if p.startswith('~/Library/SMS/Attachments/'):
        rel = p[len('~/Library/SMS/Attachments/'):].lstrip('/\\')
        if root_abs:
            candidates.append(os.path.join(root_abs, rel))
        # fallback under db_dir in case attachments live alongside db copy
        candidates.append(os.path.join(db_dir, 'Attachments', rel))

    # 3) relative paths
    if not os.path.isabs(p) and not p.startswith('~/'):
        if root_abs:
            candidates.append(os.path.join(root_abs, p))
        candidates.append(os.path.join(db_dir, p))

    # 4) as-is fallback
    candidates.append(p)

    seen = set()
    for c in candidates:
        c_norm = os.path.abspath(c)
        if c_norm in seen:
            continue
        seen.add(c_norm)
        if os.path.isfile(c_norm):
            return c_norm

    # Return best-effort mapped path even if missing (for diagnostics/header)
    if candidates:
        return os.path.abspath(candidates[0])
    return None


def _iter_message_rows(conn: sqlite3.Connection):
    """Yield message rows as sqlite3.Row objects using a tolerant SQL query.
    This tries a modern query that includes a LEFT JOIN on chat_message_join so we can
    obtain chat_id per message. Falls back to a minimal query if necessary.
    """
    cur = conn.cursor()

    # Build a "tolerant" query based on available message columns.
    try:
        cur.execute("PRAGMA table_info(message)")
        msg_cols = {r[1] for r in cur.fetchall()}
    except Exception:
        msg_cols = set()

    select_cols = ["m.ROWID as rowid"]
    if "guid" in msg_cols:
        select_cols.append("m.guid as guid")
    if "text" in msg_cols:
        select_cols.append("m.text as text")
    if "date" in msg_cols:
        select_cols.append("m.date as date")
    if "attributedBody" in msg_cols:
        select_cols.append("m.attributedBody as attributedBody")
    if "payload_data" in msg_cols:
        select_cols.append("m.payload_data as payload_data")
    if "date_read" in msg_cols:
        select_cols.append("m.date_read as date_read")
    if "date_delivered" in msg_cols:
        select_cols.append("m.date_delivered as date_delivered")
    if "is_from_me" in msg_cols:
        select_cols.append("m.is_from_me as is_from_me")
    if "handle_id" in msg_cols:
        select_cols.append("m.handle_id as handle_id")
    if "destination_caller_id" in msg_cols:
        select_cols.append("m.destination_caller_id as destination_caller_id")
    if "service" in msg_cols:
        select_cols.append("m.service as service")
    if "account" in msg_cols:
        select_cols.append("m.account as account")
    if "subject" in msg_cols:
        select_cols.append("m.subject as subject")
    if "associated_message_guid" in msg_cols:
        select_cols.append("m.associated_message_guid as associated_message_guid")

    # add chat_id if join table exists
    has_chat_join = False
    try:
        cur.execute("SELECT 1 FROM chat_message_join LIMIT 1")
        has_chat_join = True
    except sqlite3.OperationalError:
        has_chat_join = False

    sql = f"SELECT {', '.join(select_cols)}"
    if has_chat_join:
        sql += ", c.chat_id as chat_id FROM message m LEFT JOIN chat_message_join c ON m.ROWID = c.message_id"
    else:
        sql += " FROM message m"
    if "date" in msg_cols:
        sql += " ORDER BY m.date"

    try:
        cur.execute(sql)
    except sqlite3.OperationalError:
        # Final fallback for very old schemas
        try:
            cur.execute("SELECT ROWID as rowid, guid, text, date, is_from_me, handle_id FROM message ORDER BY date")
        except sqlite3.OperationalError:
            return
    for r in cur:
        yield r


def _row_get(row, key, default=None):
    """Safely get a column from sqlite3.Row or a dict-like row, with a default."""
    try:
        if isinstance(row, dict):
            return row.get(key, default)
        # sqlite3.Row supports keys() and __getitem__
        if key in row.keys():
            return row[key]
        # fallback: attempt to index by ordinal if possible
        try:
            # row.keys() is a sequence; find ordinal index
            keys = list(row.keys())
            idx = keys.index(key)
            return row[idx]
        except Exception:
            return default
    except Exception:
        return default


def _infer_local_handle(conn: sqlite3.Connection) -> Optional[str]:
    """Infer local account handle from common Apple DB columns."""
    cur = conn.cursor()
    # Prefer message.account because it is usually present per-message.
    try:
        cur.execute(
            """
            SELECT account, COUNT(*) AS c
            FROM message
            WHERE account IS NOT NULL AND TRIM(account) != ''
            GROUP BY account
            ORDER BY c DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if row and row[0]:
            return addressbook.normalize_handle(row[0])
    except Exception as e:
        logging.debug('Could not infer local handle from message.account: %s', e)

    # Fallback to chat.account_login used by some DB versions.
    try:
        cur.execute(
            """
            SELECT account_login, COUNT(*) AS c
            FROM chat
            WHERE account_login IS NOT NULL AND TRIM(account_login) != ''
            GROUP BY account_login
            ORDER BY c DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if row and row[0]:
            return addressbook.normalize_handle(row[0])
    except Exception as e:
        logging.debug('Could not infer local handle from chat.account_login: %s', e)
    return None


def parse_file(
        path: str,
        local_handle: Optional[str] = None,
        addressbook_path: Optional[str] = None,
        idle_hours: float = 8.0,
        min_messages: int = 2,
        max_messages: int = 0,
        max_days: int = 0,
        stream: bool = False,
        embed_attachments: bool = True,
        attachment_root: Optional[str] = None,
    ) -> Iterable["Conversation"]:
    """Parse an Apple Messages SQLite DB and yield Conversation objects.

    Creates same raw message dict that 
    `imessage_json.build_conversation_from_segment` expects; reuses that
    function to produce Conversation objects.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    try:
        ab_data = addressbook.AddressBookData(handle_to_name={}, owner_name=None, owner_handle_keys=set())
        if addressbook_path:
            try:
                ab_data = addressbook.load_address_book(addressbook_path)
            except Exception as e:
                logging.warning("Failed to load Address Book DB %s: %s", addressbook_path, e)

        if not local_handle:
            local_handle = _infer_local_handle(conn)

        local_handle_keys = set()
        if local_handle:
            local_handle_keys.update(addressbook.handle_keys(local_handle))

        handle_map = _load_handles(conn)
        chat_participants = _load_chat_participants(conn)

        # Group raw message dicts by chat identifier
        messages_by_chat: Dict[str, List[Dict[str, Any]]] = {}

        for row in _iter_message_rows(conn):
            try:
                rowid = int(row['rowid'])
            except Exception:
                # skip malformed rows
                continue
            # convert date
            date_val = _row_get(row, 'date') if 'date' in row.keys() else (row[3] if len(row) > 3 else None)
            dt = apple_ts_to_dt(date_val)
            date_iso = dt.isoformat() if dt else None

            is_from_me = bool(_row_get(row, 'is_from_me', False))

            # determine sender handle string
            sender = None
            if is_from_me:
                sender = local_handle or 'me'
            else:
                hid = _row_get(row, 'handle_id', None)
                if hid is not None:
                    try:
                        sender = handle_map.get(int(hid)) or str(hid)
                    except Exception:
                        sender = str(hid)
                else:
                    dest = _row_get(row, 'destination_caller_id')
                    sender = dest or 'UNKNOWN'

            # If local_handle was not supplied, infer it from account/account_login when available.
            if not local_handle:
                account_value = _row_get(row, 'account')
                if isinstance(account_value, str) and account_value.strip():
                    local_handle = addressbook.normalize_handle(account_value)
                    local_handle_keys.update(addressbook.handle_keys(local_handle))

            # determine chat identifier
            chat_id = None
            if 'chat_id' in row.keys():
                chat_id = _row_get(row, 'chat_id')
            chat_identifier = str(chat_id) if chat_id is not None else (sender or 'unknown')

            # attachments
            attachments = _get_attachments_for_message(conn, rowid)

            # participants
            participants: List[str] = []
            if chat_id is not None and int(chat_id) in chat_participants:
                for hid in chat_participants[int(chat_id)]:
                    participants.append(handle_map.get(hid) or str(hid))
            else:
                # best-effort: include sender and local_handle
                if sender:
                    participants.append(sender)
                if local_handle and local_handle not in participants:
                    participants.append(local_handle)

            raw = {
                'rowid': rowid,
                'guid': _row_get(row, 'guid') or '',
                'text': _decode_message_text(
                    _row_get(row, 'text'),
                    _row_get(row, 'attributedBody'),
                    _row_get(row, 'payload_data'),
                ),
                'date': date_iso,
                'is_from_me': is_from_me,
                'service': _row_get(row, 'service') if 'service' in row.keys() else None,
                'sender': sender,
                'participants': participants,
                'attachments': [
                    {
                        'filename': a.get('filename'),
                        'mime_type': a.get('mime_type'),
                        'transfer_name': a.get('transfer_name'),
                        'total_bytes': a.get('total_bytes'),
                        'path': _resolve_attachment_path(a.get('path'), path, attachment_root),
                    }
                    for a in attachments
                ],
                'associated_message_guid': _row_get(row, 'associated_message_guid') if 'associated_message_guid' in row.keys() else None,
            }

            messages_by_chat.setdefault(chat_identifier, []).append(raw)

        # Segment into chats and yield Conversations using shared iMessage helpers.
        for chat_id, msgs in messages_by_chat.items():
            for segment in segment_messages(msgs, idle_hours=idle_hours, min_messages=min_messages, max_messages=max_messages, max_days=max_days):
                conv = build_conversation_from_segment(segment, chat_id, path, local_handle, embed_attachments=embed_attachments)

                # Enrich participant real names from Address Book
                if ab_data.handle_to_name:
                    for participant in conv.participants:
                        resolved = addressbook.resolve_name_for_handle(participant.userid, ab_data.handle_to_name)
                        if resolved:
                            participant.realname = resolved

                # Enrich local participant with owner name if available
                if ab_data.owner_name:
                    if conv.localaccount:
                        for participant in conv.participants:
                            if participant.userid and conv.localaccount and participant.userid.lower() == conv.localaccount.lower():
                                participant.realname = ab_data.owner_name
                                break
                    else:
                        for participant in conv.participants:
                            keys = addressbook.handle_keys(participant.userid)
                            if keys and ((keys & ab_data.owner_handle_keys) or (local_handle_keys and (keys & local_handle_keys))):
                                participant.realname = ab_data.owner_name
                                conv.set_local_account(participant.userid)
                                break

                # record source DB basename for fakedomain logic
                conv.source_db_basename = os.path.basename(path)
                yield conv
    finally:
        try:
            conn.close()
        except Exception as e:
            logging.debug('Failed to close sqlite connection for %s: %s', path, e)


__all__ = [
    "parse_file",
    "apple_ts_to_dt",
    "_decode_message_text",
    "_decode_attributed_body_blob",
    "_decode_payload_blob",
    "_decode_streamtyped_legacy",
]
