#!/usr/bin/env python3
import sys

if sys.version_info < (3, 8):
    raise SystemExit("This fixture generator requires Python 3.8+")

import sqlite3
from pathlib import Path
import base64

# Deterministic fixture base time: 2025-01-01 00:00:00 UTC
BASE_EPOCH = 1735689600

ROOT = Path(__file__).resolve().parents[1]
OUT_DB = ROOT / "testdata" / "ios" / "sms.db"
ATTACH_ROOT = ROOT / "testdata" / "ios" / "Attachments" / "00"

HELLO_TXT = ATTACH_ROOT / "hello.txt"
PIXEL_PNG = ATTACH_ROOT / "pixel.png"

# 1x1 transparent PNG
PIXEL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB"
    "/aX8vWcAAAAASUVORK5CYII="
)

def _ensure_dirs():
    (OUT_DB.parent).mkdir(parents=True, exist_ok=True)
    ATTACH_ROOT.mkdir(parents=True, exist_ok=True)

def _write_attachments():
    HELLO_TXT.write_text("hello world\n", encoding="utf-8")
    PIXEL_PNG.write_bytes(base64.b64decode(PIXEL_PNG_B64))

def _recreate_db():
    if OUT_DB.exists():
        OUT_DB.unlink()

    conn = sqlite3.connect(str(OUT_DB))
    cur = conn.cursor()

    # Minimal, parser-oriented subset. Column names intentionally resemble Apple DBs but
    # are not guaranteed to match every iOS version exactly.
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
            handle_id INTEGER,
            is_from_me INTEGER NOT NULL,
            service TEXT,
            date INTEGER NOT NULL,
            cache_roomnames TEXT,
            reply_to_guid TEXT,
            associated_message_guid TEXT,
            associated_message_type TEXT
        );

        CREATE TABLE chat_message_join (
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL
        );

        CREATE TABLE attachment (
            ROWID INTEGER PRIMARY KEY,
            filename TEXT NOT NULL,
            mime_type TEXT
        );

        CREATE TABLE message_attachment_join (
            message_id INTEGER NOT NULL,
            attachment_id INTEGER NOT NULL
        );
        """
    )

    # Handles
    cur.execute("INSERT INTO handle(id, service) VALUES(?, ?)", ("+15555550100", "SMS"))
    h_sms = cur.lastrowid
    cur.execute("INSERT INTO handle(id, service) VALUES(?, ?)", ("alice@example.com", "iMessage"))
    h_alice = cur.lastrowid
    cur.execute("INSERT INTO handle(id, service) VALUES(?, ?)", ("bob@example.com", "iMessage"))
    h_bob = cur.lastrowid
    cur.execute("INSERT INTO handle(id, service) VALUES(?, ?)", ("carol@example.com", "iMessage"))
    h_carol = cur.lastrowid

    # Chats
    cur.execute("INSERT INTO chat(guid, display_name) VALUES(?, ?)", ("chat-sms-1", "SMS with +15555550100"))
    chat_sms = cur.lastrowid
    cur.execute("INSERT INTO chat(guid, display_name) VALUES(?, ?)", ("chat-imessage-1", "iMessage with Alice"))
    chat_im = cur.lastrowid
    cur.execute("INSERT INTO chat(guid, display_name) VALUES(?, ?)", ("chat-group-1", "Group: Alice, Bob, Carol"))
    chat_group = cur.lastrowid

    # Chat participants (for group chats, include everyone; for 1:1, include the remote)
    cur.execute("INSERT INTO chat_handle_join(chat_id, handle_id) VALUES(?, ?)", (chat_sms, h_sms))
    cur.execute("INSERT INTO chat_handle_join(chat_id, handle_id) VALUES(?, ?)", (chat_im, h_alice))

    for hid in (h_alice, h_bob, h_carol):
        cur.execute("INSERT INTO chat_handle_join(chat_id, handle_id) VALUES(?, ?)", (chat_group, hid))

    # Attachments
    cur.execute(
        "INSERT INTO attachment(filename, mime_type) VALUES(?, ?)",
        (str(HELLO_TXT.relative_to(ROOT)), "text/plain"),
    )
    att_hello = cur.lastrowid

    cur.execute(
        "INSERT INTO attachment(filename, mime_type) VALUES(?, ?)",
        (str(PIXEL_PNG.relative_to(ROOT)), "image/png"),
    )
    att_png = cur.lastrowid

    def add_msg(*, guid, text, handle_id, is_from_me, service, date_offset, chat_id, reply_to_guid=None,
                associated_message_guid=None, associated_message_type=None, attach_ids=()):
        cur.execute(
            """
            INSERT INTO message(guid, text, handle_id, is_from_me, service, date, cache_roomnames,
                                reply_to_guid, associated_message_guid, associated_message_type)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guid,
                text,
                handle_id,
                1 if is_from_me else 0,
                service,
                BASE_EPOCH + date_offset,
                None,
                reply_to_guid,
                associated_message_guid,
                associated_message_type,
            ),
        )
        mid = cur.lastrowid
        cur.execute("INSERT INTO chat_message_join(chat_id, message_id) VALUES(?, ?)", (chat_id, mid))
        for aid in attach_ids:
            cur.execute("INSERT INTO message_attachment_join(message_id, attachment_id) VALUES(?, ?)", (mid, aid))
        return mid

    offset = 0

    # 1:1 SMS
    m1_guid = "sms-0001"
    add_msg(guid=m1_guid, text="Hey, are we still on for lunch?", handle_id=h_sms, is_from_me=False,
            service="SMS", date_offset=offset, chat_id=chat_sms)
    offset += 60

    add_msg(guid="sms-0002", text="Yep—see you at 12:30.", handle_id=None, is_from_me=True,
            service="SMS", date_offset=offset, chat_id=chat_sms)
    offset += 60

    # 1:1 iMessage + attachment
    im1_guid = "im-0001"
    add_msg(guid=im1_guid, text="Can you review this file?", handle_id=h_alice, is_from_me=False,
            service="iMessage", date_offset=offset, chat_id=chat_im, attach_ids=(att_hello,))
    offset += 60

    add_msg(guid="im-0002", text="Sure—taking a look now.", handle_id=None, is_from_me=True,
            service="iMessage", date_offset=offset, chat_id=chat_im)
    offset += 60

    # Group iMessage + image attachment
    group1_guid = "grp-0001"
    add_msg(guid=group1_guid, text="Happy New Year everyone!", handle_id=None, is_from_me=True,
            service="iMessage", date_offset=offset, chat_id=chat_group)
    offset += 60

    add_msg(guid="grp-0002", text="Happy New Year!", handle_id=h_bob, is_from_me=False,
            service="iMessage", date_offset=offset, chat_id=chat_group)
    offset += 60

    add_msg(guid="grp-0003", text="Here’s a tiny image", handle_id=h_carol, is_from_me=False,
            service="iMessage", date_offset=offset, chat_id=chat_group, attach_ids=(att_png,))
    offset += 60

    # Reply (reply to Bob)
    add_msg(guid="grp-0004", text="Replying to you, Bob.", handle_id=h_alice, is_from_me=False,
            service="iMessage", date_offset=offset, chat_id=chat_group, reply_to_guid="grp-0002")
    offset += 60

    # Reaction / tapback as pseudo-message metadata
    # (Many real schemas model this differently; parser should treat associated_message_* as a reaction.)
    add_msg(guid="tap-0001", text=None, handle_id=h_bob, is_from_me=False,
            service="iMessage", date_offset=offset, chat_id=chat_group,
            associated_message_guid=group1_guid, associated_message_type="like")

    conn.commit()
    conn.close()

def main():
    _ensure_dirs()
    _write_attachments()
    _recreate_db()
    print(f"Wrote {OUT_DB}")


if __name__ == "__main__":
    main()