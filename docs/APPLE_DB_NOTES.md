# Apple Messages databases (`sms.db` on iOS, `chat.db` on macOS) — ingestion notes

This document summarizes information for implementing an importer that converts Apple Messages databases into human-readable HTML transcripts (and from there into `.eml` email messages), optionally bundling or linking attachments from a provided Attachments directory.

It is largely AI-written, and designed to be **AI-readable** and implementation-oriented.

> Scope: This does not attempt to reproduce every schema detail for every OS version. Apple’s schema changes over time. The recommended approach is **schema feature-detection** (check which tables/columns exist and adapt).

---

## 1. Terminology

- **SQLite database**: both `sms.db` and `chat.db` are SQLite databases.
- **Handle**: a participant identifier (phone number, email, sometimes a “service” ID).
- **Chat/Conversation/Thread**: a logical conversation, either 1:1 or group.
- **Message**: a row representing a sent/received message; may include edits/reactions modeled as metadata rather than a visible bubble.
- **Attachment**: a file associated with a message (image, video, audio, vCard, etc.).
- **GUID**: Apple uses GUID-like identifiers for messages and chats; these are useful stable keys for threading / replies.

---

## 2. Input formats you might support

### 2.1 iOS `sms.db` (raw)
- User provides:
  - path to an `sms.db` file
  - optional path to an `Attachments/` directory (or “Media” directory) containing attachment payloads

Notes:
- On device, Apple stores it at `/private/var/mobile/Library/SMS/sms.db`, but most tooling reads it from device extractions or backups.
- In iOS backups, the file is stored under a hashed name; supporting that is a separate “backup ingestion” mode.

### 2.2 macOS `chat.db` (raw)
- User provides:
  - path to `chat.db`
  - optional path to a macOS Messages attachments directory (commonly a sibling or known path)

Notes:
- Real macOS `chat.db` often uses SQLite WAL mode and may be accompanied by `chat.db-wal` and `chat.db-shm`.
- For stable reads, copy the DB before opening if the Messages app might be writing to it.

---

## 3. High-level extraction pipeline (works for both iOS and macOS)

### Step A — Open DB and detect schema
1. Open SQLite DB read-only when possible.
2. Query `sqlite_master` to list tables.
3. For key tables (message/chat/handle/attachment), query `PRAGMA table_info(<table>)` to detect which columns exist.

Your importer should branch based on detected columns.

### Step B — Build normalized internal model
Build an internal set of objects:

- `Participant { id, display_name?, service? }`
- `Conversation { id/guid, display_name?, participants[] }`
- `Message { guid, conversation_id, sender_id?, is_from_me, timestamp, body_html/text, reply_to_guid?, reactions?, attachments[] }`
- `Attachment { id, mime, filename_on_disk, display_name?, size?, sha? }`

Populate them via DB joins. Even if the underlying DB differs, normalize early.

### Step C — Group messages into conversations and produce HTML transcript
For each conversation:
- Sort by timestamp (and break ties deterministically by message ROWID).
- Render a transcript with:
  - date separators
  - sender display name
  - message body (escaped)
  - inline or linked attachments
  - reply-to rendering: include a quoted snippet + link/anchor
  - reactions: render as metadata on the target message

Then:
- Emit either:
  - a single `.eml` per conversation with HTML body, or
  - one `.eml` per message (less common for chat archives), or
  - HTML files for preview.

---

## 4. Core concepts in the databases

### 4.1 Participants / handles
Both iOS and macOS typically have a table representing “handles” (participants).

Common columns you may see:
- `handle.ROWID` (primary key)
- `handle.id` (phone number `+1555...` or email)
- `handle.service` (e.g., `SMS`, `iMessage`)

Your importer should:
- map `handle_id` foreign keys from messages to participant IDs
- special-case “from me” messages where sender handle may be null/absent; treat sender as `"me"`.

### 4.2 Chats (threads)
A chat has:
- a GUID or identifier
- a display name for group chats, sometimes null for 1:1
- a service name (`iMessage` vs SMS)

Participant membership is commonly modeled by a join table (chat ↔ handle).

### 4.3 Messages
A message row typically includes:
- stable identifier: `guid`
- sender reference: `handle_id` or equivalent
- direction: `is_from_me` (1 for outgoing, 0 for incoming)
- timestamp: `date` (encoding differs by OS/version; see below)
- body text: may be in `text`, or may require decoding from another field (especially on macOS)

#### Message timestamps
Apple stores timestamps in different epochs/units across contexts. In practice you must determine the encoding by:
- reading a few known messages and comparing with human reality, or
- checking known column documentation per OS/version.

Robust approach:
- implement timestamp decoding as a function selected by heuristics:
  - if values look like seconds since 1970 (≈ 1.6e9–2.0e9), treat as unix seconds
  - if values look like nanoseconds since 2001 (very large), convert from Apple/Cocoa epoch (2001-01-01)
  - if values are negative or extremely large, investigate units (microseconds/nanoseconds)

**Recommendation**: expose a debug mode that prints:
- raw `date`
- decoded date in UTC + local time
so users can confirm correctness.

---

## 5. macOS `chat.db` message bodies: `text` vs `attributedBody`

On macOS, message body can be stored in different places depending on OS version and message type:

- `message.text`: sometimes contains the plain text message.
- `message.attributedBody` (BLOB): may store an `NSAttributedString` serialized using Apple’s typedstream/archival formats.
  - In some modern cases, `text` may be `NULL` and content is only in `attributedBody`.

Importer strategy:
1. If `text` is non-null and non-empty, use it.
2. Else if `attributedBody` exists:
   - Attempt to decode typedstream / archived attributed string.
   - Fall back to a best-effort extraction:
     - If the blob contains readable UTF-8 segments, extract the first reasonable string segment.
3. Else render as empty body (but still render attachments and metadata).

### HTML rendering for macOS bodies
- Convert plain text to HTML by escaping `<>&` and converting newlines to `<br>`.
- If you decode rich text (attributes), keep it simple initially:
  - ignore fonts/colors
  - preserve links if you can detect them
  - preserve newlines

---

## 6. Attachments

### 6.1 How attachments are modeled
Attachments are commonly represented by:
- an `attachment` table describing the file (filename/path, MIME type, etc.)
- a join table linking messages to attachments (message_attachment_join-like)

Your importer should:
- for each message, join to attachments
- map attachment rows to actual files on disk, using:
  - the attachment record’s stored path, OR
  - a user-provided attachments root directory plus relative path mapping

### 6.2 Attachments directory as input
Because the DB alone may not contain the raw payload, support passing:
- `--attachments-dir <path>`

Resolution algorithm (recommended):
1. If `attachment.filename` is an absolute path and exists, use it.
2. Else if `attachment.filename` is relative:
   - try `attachments_dir / attachment.filename` (if filename already includes subdirs)
   - try `attachments_dir / basename(attachment.filename)` (last resort)
3. If not found:
   - still render a placeholder link in HTML (filename + MIME type), mark missing.

### 6.3 Embedding vs linking in HTML/EML
For `.eml`:
- Prefer embedding as MIME parts when feasible:
  - inline images with `Content-ID` references can display in HTML mail clients
  - large videos should likely be linked (or attached non-inline)

For HTML transcript:
- Inline images (`<img src="...">`) if you copy them alongside output
- Otherwise use `<a href="...">Attachment: filename</a>`

### 6.4 Common attachment types
- `image/*` -> inline image preview in HTML
- `video/*` -> link or `<video controls>` if your archive supports it
- `audio/*` -> link or `<audio controls>`
- `text/vcard` / `text/x-vcard` -> render as downloadable file + optionally parse contact card

---

## 7. Threading, replies, and reactions (Tapbacks)

### 7.1 Threading (conversation grouping)
“Threading” normally means “messages that belong to the same chat”.

Implementation:
- Identify chat by `chat.ROWID`/`chat.guid`.
- Join messages through `chat_message_join` (or equivalent).
- Sort by message timestamp.

### 7.2 Replies
Apple has reply-to UI in Messages; the underlying DB representation varies by OS version.

Importer strategy:
- Provide a best-effort `reply_to_guid` concept:
  - If the schema has a reply column, use it.
  - If not, attempt inference (less reliable):
    - look for metadata tables/fields that reference a target message GUID
- Rendering:
  - locate the target message in the same conversation by GUID
  - include a small quoted snippet (e.g., first 80 chars)
  - link to the target via an HTML anchor (`#msg-<guid>`)

### 7.3 Reactions / Tapbacks
Reactions may be modeled as:
- separate “associated message” rows (pseudo-messages)
- metadata fields on message rows
- separate join tables (varies)

Importer strategy:
- Normalize reactions as: `Reaction { from, type, target_guid }`
- When you encounter reaction records:
  - attach them to the target message in your internal model
  - do not render them as separate chat bubbles by default (optional debug toggle)

Rendering suggestion:
- Show as small badges below the target message, e.g.:
  - `Bob liked this`
  - `Alice emphasized this`

---

## 8. Safety and sanitation for sample data

If committing sample DBs into a public repo:
- Use synthetic handles:
  - `alice@example.com`, `+15555550100`, etc.
- Avoid real URLs, GPS coordinates, or unique device identifiers
- Keep attachments minimal and non-sensitive:
  - a 1x1 PNG
  - a short text file

---

## 9. Suggested minimal SQL queries (generic patterns)

These are **patterns**, not guaranteed exact for every schema.

For historical context, older iOS 6-era parsers (e.g., `iphone_message_parser` by jsharkey13) used a much simpler schema:
- Only `handle` and `message` tables were validated.
- Messages were read via `SELECT ROWID, handle_id, is_from_me, date, text FROM message ORDER BY handle_id`.
- Threads were grouped by consecutive `handle_id` (no chat/message join tables).
- Timestamps were stored as “Mac time” seconds; converted to Unix with `date + 978307200`.
- No attachment, reaction, reply, or group chat support.
Use this as a reminder to keep robust schema detection and branching for modern DBs, not to assume this legacy layout.

### 9.1 List chats
```sql
SELECT ROWID, guid, display_name
FROM chat;
```

### 9.2 Chat participants (handles)
```sql
SELECT c.ROWID AS chat_id, h.id AS handle_id, h.service
FROM chat c
JOIN chat_handle_join chj ON chj.chat_id = c.ROWID
JOIN handle h ON h.ROWID = chj.handle_id
ORDER BY c.ROWID;
```

### 9.3 Messages for a chat
```sql
SELECT m.ROWID, m.guid, m.text, m.is_from_me, m.date, m.handle_id
FROM chat_message_join cmj
JOIN message m ON m.ROWID = cmj.message_id
WHERE cmj.chat_id = ?
ORDER BY m.date, m.ROWID;
```

### 9.4 Attachments for a message
```sql
SELECT a.ROWID, a.filename, a.mime_type
FROM message_attachment_join maj
JOIN attachment a ON a.ROWID = maj.attachment_id
WHERE maj.message_id = ?;
```

---

## 10. Implementation tips (pragmatic)

- Always wrap DB access in try/except with helpful error messages (bad path, locked DB, corrupt DB).
- Add a `--debug-db` mode that prints:
  - detected tables
  - detected columns for `message`, `chat`, `attachment`
  - sample row counts
- Use a tolerant HTML renderer:
  - escape everything by default
  - only allow safe tags you generate yourself
- Design the importer as a “driver” with multiple backends:
  - iOS sms.db backend
  - macOS chat.db backend
Each backend should output the same normalized internal model.

---

## 11. What to implement later (beyond minimal fixtures)

macOS:
- Real `attributedBody` typedstream decoding for full fidelity

iOS:
- Backup ingestion:
  - locate sms.db inside backup (hashed filename)
  - resolve attachments from backup structure

Cross-platform:
- Better timestamp decoding per detected schema version
- “Edits” and “unsend” message metadata
- Rich previews / link metadata if you want parity with Messages UI
