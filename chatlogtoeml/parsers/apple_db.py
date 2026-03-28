"""Apple sms.db/chat.db parser

This module provides a parser for Apple `sms.db` / `chat.db` SQLite databases.

Currently: it loads messages, handles and chat mappings,
converts Apple timestamps to timezone-aware datetimes, and produces
conversation.Conversation objects consumable by conv_to_eml.mimefromconv.

Typedstream (NSAttributedString) parsing is TBD.
"""

from __future__ import annotations

import sqlite3
import datetime
import logging
import os
from typing import Iterable, Optional, List, Dict, Any

# FIXME: this is an ugly hack to avoid circular import, should be refactored
try:
    from . import imessage_json
except Exception:
    # When imported as a top-level module fallback
    import imessage_json

# Conversation model
try:
    from chatlogtoeml import conversation
except Exception:
    import conversation

# Apple epoch (2001-01-01) -> Unix epoch offset in seconds
# NOTE: Possible this epoch was not consistently used, esp. in early iChat/iOS versions
APPLE_EPOCH_OFFSET = 978307200


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


def _iter_message_rows(conn: sqlite3.Connection):
    """Yield message rows as sqlite3.Row objects using a tolerant SQL query.
    This tries a modern query that includes a LEFT JOIN on chat_message_join so we can
    obtain chat_id per message. Falls back to a minimal query if necessary.
    """
    cur = conn.cursor()

    # Try a richer query first (modern schema)
    try:
        cur.execute(
            """
            SELECT m.ROWID as rowid, m.guid as guid, m.text as text, m.date as date,
                   m.date_read as date_read, m.date_delivered as date_delivered,
                   m.is_from_me as is_from_me, m.handle_id as handle_id,
                   m.destination_caller_id as destination_caller_id,
                   m.service as service, m.subject as subject,
                   m.associated_message_guid as associated_message_guid,
                   c.chat_id as chat_id
            FROM message m
            LEFT JOIN chat_message_join c ON m.ROWID = c.message_id
            ORDER BY m.date;
            """,
        )
    
    # Fallback to minimal query (older schemas?)
    except sqlite3.OperationalError:
        
        try:
            cur.execute("SELECT ROWID as rowid, guid, text, date, is_from_me, handle_id FROM message ORDER BY date")
        except sqlite3.OperationalError:
            # TODO: log this
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


def parse_file(
        path: str,
        local_handle: Optional[str] = None,
        idle_hours: float = 4.0,
        min_messages: int = 2,
        max_messages: int = 0,
        max_days: int = 0,
        stream: bool = False,
        embed_attachments: bool = False,
        attachment_root: Optional[str] = None,
    ) -> Iterable[conversation.Conversation]:
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
                'text': _row_get(row, 'text') or '',
                'date': date_iso,  # ISO string for imessage_json._parse_date
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
                        'path': a.get('path'),
                    }
                    for a in attachments
                ],
                'associated_message_guid': _row_get(row, 'associated_message_guid') if 'associated_message_guid' in row.keys() else None,
            }

            messages_by_chat.setdefault(chat_identifier, []).append(raw)

        # Segment into chats and yield Conversations via imessage_json.build_conversation_from_segment
        for chat_id, msgs in messages_by_chat.items():
            for segment in imessage_json.segment_messages(msgs, idle_hours=idle_hours, min_messages=min_messages, max_messages=max_messages, max_days=max_days):
                conv = imessage_json.build_conversation_from_segment(segment, chat_id, path, local_handle, embed_attachments=embed_attachments)
                # record source DB basename for fakedomain logic
                try:
                    conv.source_db_basename = os.path.basename(path)
                except Exception:
                    pass
                yield conv
    finally:
        try:
            conn.close()
        except Exception:
            pass


# TODO: Typedstream parsing
# The message body in newer macOS/iOS databases is stored as a "typedstream" (NSAttributedString)
# or as PLISTs. We should parse these to extract text and attachments. 

__all__ = ["parse_file", "apple_ts_to_dt"]
