# Plan: Direct ingestion of Apple sms.db / chat.db

## Goal
Add a direct ingestion path for Apple Messages sqlite databases (iOS `sms.db` and macOS `chat.db`) so the converter can parse these DBs and produce RFC822 .eml files without an external NDJSON step.

This document lists research tasks, design decisions, implementation steps, tests, and deliverables so a future AI or human can implement the feature with minimal hand-holding.

---

## Summary / High-level approach
- Preferred approach: implement a native Python parser module under chatlogtoeml.parsers (e.g. `chatlogtoeml/parsers/apple_db.py`) that uses `sqlite3` to read DBs, normalizes rows into existing `conversation.Conversation` objects, and then reuses `conv_to_eml.mimefromconv` to emit `.eml` files.
- Two pragmatic alternatives: port the user's Rust parser to Python (recommended if Rust code already expresses the logic clearly), or wrap a Rust binary (subprocess) / FFI (PyO3) for faster POC or performance-critical needs.

---

## Research tasks (discover & validate)
1. Collect authoritative references on `sms.db` and `chat.db` schema across iOS/macOS versions. Target sources:
   - imessage-exporter, open-source parsers, forensic writeups, and Apple developer notes.
   - The user's Rust parser (request the repo or code sample) — this is high-value for porting heuristics.
2. Inspect sample DBs (user-provided) with `sqlite3` to enumerate tables & columns; capture PRAGMA table_info() output for all relevant tables.
3. Specifically validate where and how these fields are stored: message text, guid, date/dates (sent/delivered/read/edited), is_from_me, handle id/handle table mapping, chat/chat_message_join, attachments table and physical attachment storage path, reactions/associated_message_guid, and flags.
4. Confirm date/time storage units (seconds vs micro/nano) and epoch (Apple 2001-01-01 vs Unix 1970-01-01). Build robust converters (heuristics and detection).

---

## Known schema concepts to expect (mapping plan)
- Tables typically of interest: `message`, `handle`, `chat`, `chat_message_join` (or `chat_handle_join`), `attachment`, `message_attachment_join`, `message_attachment`, `message_related`.
- Key fields to extract per message: GUID (or ROWID), text/plain body, html (if any), date (sent), date_read/date_delivered/date_edited, is_from_me (boolean), handle_id (sender), participants (via chat join tables), attachments (filename, mime, transfer path), and any associated GUIDs (for reactions/replies).
- Normalization: convert DB rows to the existing Conversation/Message/Attachment model used by the repo (populate `conv.source_db_basename`, `conv.origfilename`, participant realnames where available).

---

## Date/time conversion (implementation note)
- Apple epoch offset: 978307200 seconds between 1970-01-01 and 2001-01-01.
- DB values may be:
  - seconds since 2001 (integer/float)
  - nanoseconds/microseconds since 2001 (large integers)
  - CoreData timestamps encoded as absolute seconds (or milliseconds)
- Implement robust converter: detect magnitude and apply appropriate scaling and add epoch offset to produce tz-aware UTC datetimes.

Example heuristic:
```py
def apple_ts_to_dt(v):
    if v is None:
        return None
    # float/int input
    v = float(v)
    # detect nanoseconds/microseconds vs seconds
    if v > 1e14:  # nanoseconds
        v = v / 1e9
    elif v > 1e11:  # microseconds
        v = v / 1e6
    elif v > 1e9:  # milliseconds
        v = v / 1e3
    # Now assume v is seconds since 2001-01-01
    unix = v + 978307200
    return datetime.datetime.fromtimestamp(unix, tz=datetime.timezone.utc)
```

---

## Attachments
- The DB typically references attachment records and physical files stored in a separate Attachments directory (paths vary by export method / device / iCloud). Parser must:
  - read attachment metadata from DB (filename, mimetype, stored path or GUID)
  - attempt to resolve the physical path relative to the DB (or accept a base attachments directory passed via CLI)
  - when `--embed-attachments` is set, read local file bytes and set `Attachment.data`; otherwise preserve metadata and set `Attachment.orig_path`.
- If attachments are missing, record an X- header or log warning (already handled by conv_to_eml changes).

---

## Reactions / Tapbacks / Replies
- Recent iMessage versions store reactions as separate message rows with an association to the target message GUID. Verify how that field is named (e.g., `associated_message_guid` or a `message.linked_message` field).
- Implement a post-pass that collects reaction rows and attaches their rendered HTML/text to the target `Message` in the Conversation or emits a system `event` if target is out-of-segment.

---

## Implementation tasks
1. Research & schema capture (PRAGMA exports) for multiple sample DBs (task: 1-2 days of research + sample analysis).
2. Design parser API: `parse_file(path, local_handle=None, embed_attachments=False, min_messages=2, idle_hours=4.0) -> Iterable[Conversation]` (match imessage_json API). Ensure `conv.source_db_basename` is set.
3. Implement `chatlogtoeml/parsers/apple_db.py` with helper functions:
   - _open_db(path)
   - _list_tables_and_columns(conn)
   - _fetch_chats(conn) -> list(chat_ids)
   - _fetch_messages_for_chat(conn, chat_id) -> generator of dict rows
   - _normalize_participant(row)
   - _apple_ts_to_dt
   - segment_messages() (reuse NDJSON segment logic)
4. Wire parser into a new CLI `bin/db_to_eml` (or extend `bin/json_to_eml` to accept `--db`/`--format chatdb`) while keeping the existing `bin/chat_convert` (Adium) and `bin/json_to_eml` (NDJSON) entrypoints intact.
5. Tests: produce sanitized sample DBs as fixtures under `samples/fixtures/chatdb/` and unit tests in `tests/test_chatdb.py`. Add integration test that runs CLI against sanitized DB and verifies EMLs.
6. Documentation: update README + DEV_PLAN with DB ingestion usage and security notes.

---

## Tests & verification
- Unit tests for date conversion, participant normalization, attachment resolution.
- Integration test with sanitized DB: ensure parity with NDJSON conversion where possible.
- Use verifier script (adapted earlier) to compare outputs.

---

## Security & privacy
- Do not commit real user DBs or attachments. Create small, sanitized fixtures capturing key edge cases.
- Log warnings for absolute home paths and do not implicitly attempt to read outside an explicit attachments base dir unless user confirms.

---

## Alternatives & trade-offs
- Port Rust parser: faster to implement if Rust code already implemented complex heuristics; results easier to maintain in Python long-term.
- Subprocess wrapper: fastest POC; low integration cost; harder to package and maintain cross-platform.
- PyO3 FFI: best performance; significant build complexity and developer toolchain burden.

---

## Deliverables
- `chatlogtoeml/parsers/apple_db.py` (primary parser)
- `bin/db_to_eml` (executable CLI or extension of json_to_eml)
- `tests/test_chatdb.py` and sanitized fixtures
- README and DEV_PLAN updates

---

## Unknowns / Risks (to validate during research)
- Schema differences across OS versions (iOS/macOS) may require conditional logic
- Date storage units/fields vary by export method
- Attachment paths may be absolute to a user home dir — need mapping strategy
- Reactions representation format across OS/versions

---

## Next actions (concrete)
1. Gather sample DBs and the Rust parser code (if available).
2. Run PRAGMA on each sample to capture table/column shapes.
3. Implement minimal parser reading `message`, `handle`, `chat`, `attachment` and produce a working EML for a small conversation.
4. Iterate on edge cases revealed by real-world samples and add tests.

---

## Acceptance criteria
- Parser produces EMLs with From/To, Date, Subject, Message-ID, Attachments (embedded or metadata), and reactions preserved and rendered inline where possible.
- Unit and integration tests pass and verifier checks show parity with NDJSON-generated EMLs for the same content.


## Implementation status

Status: Prototype implemented in this branch/repository.

- Implemented `chatlogtoeml/parsers/apple_db.py` (SQLite parser). Key features:
  - Robust `apple_ts_to_dt()` with magnitude heuristics for seconds/millis/micros/nanos.
  - Tolerant `_get_attachments_for_message()` that inspects `PRAGMA table_info(attachment)` and builds a best-effort SELECT; falls back to a minimal query when schema differs.
  - Produces message dicts compatible with `imessage_json.build_conversation_from_segment()` and sets `conv.source_db_basename` for pseudo-domain derivation.
- Added CLI wrapper `bin/db_to_eml` that calls the parser and `conv_to_eml.mimefromconv()`; supports `--embed-attachments`, `--attachment-root`, `--local-handle`, `--no-background`, and `--clobber`.
- Sample fixture generators added: `tools/generate_macos_chatdb_fixture.py` and `tools/generate_ios_smsdb_fixture.py` (produce DBs and attachments under `samples/` and `testdata/`).
- Verification: ran end-to-end conversions; attachment embedding now works (embedded payloads verified by SHA256 match).

Notes / next steps:
- Typedstream (NSAttributedString) parsing for `attributedBody` remains TODO.
- Consider improving `--attachment-root` heuristics to remap absolute user home paths to sanitized fixture locations.
- Add unit tests for `_get_attachments_for_message()` and larger integration tests for DB ingestion.

*Plan saved to `.copilot/db-ingest-plan.md` in the repository.*
