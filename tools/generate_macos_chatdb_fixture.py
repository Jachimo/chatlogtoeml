#!/usr/bin/env python3
import sys
import sqlite3
import base64
from pathlib import Path

if sys.version_info < (3, 8):
    raise SystemExit("This fixture generator requires Python 3.8+")

# Deterministic fixture base time: 2025-01-01 00:00:00 UTC
BASE_EPOCH = 1735689600

ROOT = Path(__file__).resolve().parents[1]
OUT_DB = ROOT / "samples" / "macos" / "chat.db"
ATTACH_ROOT = ROOT / "samples" / "macos" / "Attachments" / "00"

HELLO_TXT = ATTACH_ROOT / "hello.txt"
PIXEL_PNG = ATTACH_ROOT / "pixel.png"

# 1x1 transparent PNG
PIXEL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB"
    "/aX8vWcAAAAASUVORK5CYII="
)

def ensure_dirs():
    OUT_DB.parent.mkdir(parents=True, exist_ok=True)
    ATTACH_ROOT.mkdir(parents=True, exist_ok=True)

def write_attachments():
    HELLO_TXT.write_text("hello from macOS fixture\n", encoding="utf-8")
    PIXEL_PNG.write_bytes(base64.b64decode(PIXEL_PNG_B64))

def recreate_db():
    # Avoid WAL artifacts being generated and accidentally committed
    if OUT_DB.exists():
        OUT_DB.unlink()

    conn = sqlite3.connect(str(OUT_DB))
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
            handle_id INTEGER,
            is_from_me INTEGER NOT NULL,
            service TEXT,
            date INTEGER NOT NULL,

            -- Synthetic-but-useful fields for developing parser features
            reply_to_guid TEXT,
            associated_message_guid TEXT,
            associated_message_type TEXT
        );

        CREATE TABLE chat_message_join (
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            message_date INTEGER
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
    cur.execute("INSERT INTO handle(id, service) VALUES(?, ?)", ("alice@example.com", "iMessage"))
    h_alice = cur.lastrowid
    cur.execute("INSERT INTO handle(id, service) VALUES(?, ?)", ("bob@example.com", "iMessage"))
    h_bob = cur.lastrowid
    cur.execute("INSERT INTO handle(id, service) VALUES(?, ?)", ("+15555550100", "SMS"))
    h_sms = cur.lastrowid

    # Chats: 1:1 iMessage, group iMessage, 1:1 SMS
    cur.execute(
        "INSERT INTO chat(guid, display_name, chat_identifier, service_name) VALUES(?, ?, ?, ?)",
        ("chat-im-1", "iMessage with Alice", "alice@example.com", "iMessage"),
    )
    chat_im = cur.lastrowid

    cur.execute(
        "INSERT INTO chat(guid, display_name, chat_identifier, service_name) VALUES(?, ?, ?, ?)",
        ("chat-group-1", "Group: Alice & Bob", "group:alice+bob", "iMessage"),
    )
    chat_group = cur.lastrowid

    cur.execute(
        "INSERT INTO chat(guid, display_name, chat_identifier, service_name) VALUES(?, ?, ?, ?)",
        ("chat-sms-1", "SMS with +15555550100", "+15555550100", "SMS"),
    )
    chat_sms = cur.lastrowid

    # Participants
    cur.execute("INSERT INTO chat_handle_join(chat_id, handle_id) VALUES(?, ?)", (chat_im, h_alice))
    for hid in (h_alice, h_bob):
        cur.execute("INSERT INTO chat_handle_join(chat_id, handle_id) VALUES(?, ?)", (chat_group, hid))
    cur.execute("INSERT INTO chat_handle_join(chat_id, handle_id) VALUES(?, ?)", (chat_sms, h_sms))

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

    def add_msg(*, guid, text, attributed_body_bytes, handle_id, is_from_me, service, date_offset, chat_id,
                reply_to_guid=None, associated_message_guid=None, associated_message_type=None, attach_ids=()):
        cur.execute(
            """
            INSERT INTO message(guid, text, attributedBody, handle_id, is_from_me, service, date,
                                reply_to_guid, associated_message_guid, associated_message_type)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guid,
                text,
                attributed_body_bytes,
                handle_id,
                1 if is_from_me else 0,
                service,
                BASE_EPOCH + date_offset,
                reply_to_guid,
                associated_message_guid,
                associated_message_type,
            ),
        )
        mid = cur.lastrowid
        cur.execute(
            "INSERT INTO chat_message_join(chat_id, message_id, message_date) VALUES(?, ?, ?)",
            (chat_id, mid, BASE_EPOCH + date_offset),
        )
        for aid in attach_ids:
            cur.execute(
                "INSERT INTO message_attachment_join(message_id, attachment_id) VALUES(?, ?)",
                (mid, aid),
            )
        return mid

    offset = 0

    # 1:1 iMessage: include one message with text NULL but attributedBody populated (fixture-only simplification)
    m1_guid = "im-0001"
    add_msg(
        guid=m1_guid,
        text=None,
        attributed_body_bytes="Hello from attributedBody".encode("utf-8"),
        handle_id=h_alice,
        is_from_me=False,
        service="iMessage",
        date_offset=offset,
        chat_id=chat_im,
    )
    offset += 60

    add_msg(
        guid="im-0002",
        text="Got it — thanks!",
        attributed_body_bytes=None,
        handle_id=None,
        is_from_me=True,
        service="iMessage",
        date_offset=offset,
        chat_id=chat_im,
        attach_ids=(att_hello,),
    )
    offset += 60

    # Group iMessage with reply + reaction-like metadata + image attachment
    group_root_guid = "grp-0001"
    add_msg(
        guid=group_root_guid,
        text="Happy New Year!",
        attributed_body_bytes=None,
        handle_id=None,
        is_from_me=True,
        service="iMessage",
        date_offset=offset,
        chat_id=chat_group,
    )
    offset += 60

    bob_msg_guid = "grp-0002"
    add_msg(
        guid=bob_msg_guid,
        text="Happy New Year to you too",
        attributed_body_bytes=None,
        handle_id=h_bob,
        is_from_me=False,
        service="iMessage",
        date_offset=offset,
        chat_id=chat_group,
        attach_ids=(att_png,),
    )
    offset += 60

    add_msg(
        guid="grp-0003",
        text="Replying to Bob",
        attributed_body_bytes=None,
        handle_id=h_alice,
        is_from_me=False,
        service="iMessage",
        date_offset=offset,
        chat_id=chat_group,
        reply_to_guid=bob_msg_guid,
    )
    offset += 60

    add_msg(
        guid="tap-0001",
        text=None,
        attributed_body_bytes=None,
        handle_id=h_bob,
        is_from_me=False,
        service="iMessage",
        date_offset=offset,
        chat_id=chat_group,
        associated_message_guid=group_root_guid,
        associated_message_type="like",
    )
    offset += 60

    # 1:1 SMS
    add_msg(
        guid="sms-0001",
        text="SMS fixture message",
        attributed_body_bytes=None,
        handle_id=h_sms,
        is_from_me=False,
        service="SMS",
        date_offset=offset,
        chat_id=chat_sms,
    )

    conn.commit()
    conn.close()

def main():
    ensure_dirs()
    write_attachments()
    recreate_db()
    print(f"Wrote {OUT_DB}")

if __name__ == "__main__":
    main()
