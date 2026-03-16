# NDJSON → EML Feature Plan

## Goals

- Add NDJSON output from [imessage-exporter](https://github.com/ReagentX/imessage-exporter) as an
  input format without touching or breaking the existing `./adiumToEml.py` entrypoint or any of its
  supported formats (`.chatlog`, `.xml`, `.AdiumHTMLLog`, `.html`).
- Prefer refactoring/reuse of the existing `Conversation` data model and `conv_to_eml` MIME
  generation; only write new code where genuinely necessary.
- Provide a new standalone executable `jsonToEml.py` that:
  - Reads one large NDJSON file (one JSON object per line).
  - Groups messages by chat (`chat_identifier`), then segments each chat into discrete
    conversations using configurable idle-gap / min-message / max-duration thresholds.
  - Emits one RFC 822 `.eml` per conversation, with human-readable HTML body and all
    available metadata in headers.
  - Preserves `From:`/`To:` with real names and handles; group chats become `From:` + `To:`
    (local account) with all remote participants listed.

## Constraints / Non-goals

- **No regressions.** `adiumToEml.py` and its three supported paths must work identically after
  any refactoring.
- **Preserve all metadata.** handles, display names, chat GUIDs, timestamps (timezone-aware),
  service (iMessage vs SMS), delivery/read status, reactions/tapbacks, attachment names/types.
  Avoid lossy transforms anywhere in the pipeline.
- Terse comments only; do not over-comment obvious code.
- Minimal churn to `conversation.py` — fix known bugs there only if they would affect the new
  feature or are trivially safe.
- `--attach` (attaching the original source file) is **not implemented** for NDJSON; a single
  NDJSON export file can be hundreds of MB. Document this explicitly as out of scope.

---

## Known Issues in Existing Code to Address During Refactor

These are bugs or design problems that would directly interfere with the new feature and must be
resolved before or during implementation:

### 1. `conv_to_eml.py` — CSS loaded at module import time with a bare `open()`

```python
# CURRENT (line 17-18) — breaks if CWD != project root:
with open('converted.css', 'r') as cssfile:
    css = cssfile.read()
```

Fix: use the module's own directory so it works regardless of CWD:

```python
import os as _os
_cssfile = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'converted.css')
with open(_cssfile, 'r') as f:
    css = f.read()
```

This is a one-line mechanical change; `adiumToEml.py` currently works only because it is always
run from the project root. The new entrypoint must not carry this constraint.

### 2. `conv_to_eml.mimefromconv(conv, args)` — takes raw `argparse.Namespace`

The only field accessed from `args` is `args.no_background` (lines 165, 181). Passing an entire
argparse Namespace into a library function is bad practice; it prevents reuse without either
constructing a fake Namespace or coupling the caller to argparse.

Refactor signature to:

```python
def mimefromconv(conv: conversation.Conversation, no_background: bool = False) -> MIMEMultipart:
```

Update the single call site in `adiumToEml.py`:

```python
eml = conv_to_eml.mimefromconv(conv, no_background=args.no_background)
```

No other callers exist; this is a safe, mechanical change.

### 3. Group chat support (>2 participants)

`conv_to_eml` assumes exactly two participants at indices `[0]` and `[1]` for `From:` and `To:`.
iMessage group chats have N participants. Strategy:

- `participants[0]` = the local account (the owner of the exported data); maps to `From:`.
- All other participants map to `To:` as a comma-separated list.
  `conv_to_eml` must be updated to iterate `conv.participants[1:]` when building the `To:` header.
- The `References` hash (already uses sorted participant list) naturally handles groups.

---

## imessage-exporter NDJSON Schema

> **Important:** The exact schema must be verified against the actual export. Run
> `imessage-exporter --format ndjson` on a test account and inspect the output before writing the
> parser. What follows is the expected structure based on current documentation and known output.

Each line is a self-contained JSON object. Key fields:

| Field | Type | Notes |
|---|---|---|
| `rowid` | int | Database row ID; use as tie-breaker when timestamps collide |
| `guid` | str | Unique message GUID; use as `Message.guid` |
| `text` | str \| null | Plain-text body; null for attachment-only or reaction messages |
| `service` | str | `"iMessage"` or `"SMS"` |
| `handle_id` | int | Numeric sender ID (join to handle table via `handle` field) |
| `is_from_me` | bool | True if sent by the local account |
| `date` | str (ISO 8601) | Timestamp with timezone; parse with `dateutil.parser.parse()` |
| `chat_identifier` | str | Primary grouping key: phone/email for 1:1, group UUID for group chats |
| `chat_guid` | str | Full GUID of the chat thread |
| `sender` | str \| null | Handle string (e.g., `+15551234567`, `user@example.com`); null if `is_from_me` |
| `participants` | list[str] | All participant handles in the chat (including local account) |
| `attachments` | list[obj] | See attachment sub-schema below |
| `reactions` | list[obj] | Tapbacks; see reactions sub-schema below |
| `associated_message_guid` | str \| null | For reactions: GUID of the target message |
| `is_read` | bool | Read receipt status (informational; preserve in metadata) |
| `is_delivered` | bool | Delivery status (informational; preserve in metadata) |
| `edited_at` | str \| null | ISO 8601 timestamp if message was edited |

**Attachment sub-schema:**

| Field | Type | Notes |
|---|---|---|
| `filename` | str | Original filename |
| `mime_type` | str | MIME type string, e.g. `"image/jpeg"` |
| `transfer_name` | str | Display name |
| `total_bytes` | int | File size |
| `path` | str \| null | Absolute path on the source machine; may not exist on target |

**Reactions sub-schema:**

| Field | Type | Notes |
|---|---|---|
| `reaction_type` | str | e.g., `"Loved"`, `"Liked"`, `"Disliked"`, `"Laughed at"`, `"Emphasized"`, `"Questioned"` |
| `actor` | str | Handle of the person who reacted |
| `associated_message_guid` | str | GUID of the target message |

---

## Architecture

### New files

| File | Purpose |
|---|---|
| `imessage_json.py` | Parser: reads NDJSON, groups by `chat_identifier`, segments by idle/duration/count thresholds, yields `Conversation` objects |
| `jsonToEml.py` | CLI entrypoint; mirrors structure of `adiumToEml.py` |

### Modified files (refactor only, no behavior change for Adium paths)

| File | Change |
|---|---|
| `conv_to_eml.py` | Fix CSS `open()` to use `__file__`; change `mimefromconv(conv, args)` → `mimefromconv(conv, no_background=False)`; support `participants[1:]` for group `To:` |
| `adiumToEml.py` | Update single call site: `mimefromconv(conv, no_background=args.no_background)` |
| `conversation.py` | No changes required unless a bug is found that affects the new feature |

### Data flow

```
NDJSON file
    │
    ▼
imessage_json.py
    ├── stream lines (no full-file load)
    ├── group by chat_identifier (dict of lists, flushed per-chat)
    ├── segment each chat → list[Conversation]
    │     (rules: idle gap ≥ threshold, OR msg count ≥ max, OR duration ≥ max)
    └── yield Conversation objects
          │
          ▼
    conv_to_eml.mimefromconv(conv, no_background=...)
          │
          ▼
    MIMEMultipart → write to .eml file
```

---

## Conversation Segmentation Rules

Implemented as a generator function `segment_chat(messages, ...)` in `imessage_json.py`.

Default thresholds (all configurable via CLI flags):

| Parameter | CLI flag | Default | Notes |
|---|---|---|---|
| Idle gap | `--idle-hours` | `4` | Split if gap between consecutive messages > N hours |
| Min messages | `--min-messages` | `2` | Discard (skip) conversation segments with fewer than N messages |
| Max messages | `--max-messages` | `0` (unlimited) | Force-split if segment reaches N messages |
| Max duration | `--max-days` | `0` (unlimited) | Force-split if segment spans > N days |

Segments with fewer than `--min-messages` messages are logged as skipped (not as failures).

---

## Participant / From: / To: Handling

iMessage does not store a "local account" handle inside the NDJSON message objects directly.
Strategy:

1. The `is_from_me` field identifies outgoing messages.  The local account handle must be supplied
   by the user via `--local-handle` CLI argument (e.g., `+15551234567` or `user@icloud.com`).
   If not supplied, it defaults to `"me"` (still functional; just less human-readable in headers).
2. For 1:1 chats: `From:` = local account, `To:` = `chat_identifier` (or resolved display name).
3. For group chats: `From:` = local account, `To:` = comma-separated list of all remote participants.
4. Display names: imessage-exporter may or may not include `display_name` for participants. If
   present, store via `conv.add_realname_to_userid()`.  The `From:`/`To:` header logic in
   `conv_to_eml` already prefers `realname` over `userid` when available.

---

## Output File Naming

Since one NDJSON may produce thousands of `.eml` files, use a deterministic scheme:

```
{sanitized_chat_identifier}_{startdate_iso}_{segment_index:04d}.eml
```

Where:
- `sanitized_chat_identifier`: `chat_identifier` with non-alphanumeric chars replaced by `_`,
  truncated to 64 chars.
- `startdate_iso`: ISO 8601 date of the first message in the segment, e.g. `2023-04-15`.
- `segment_index`: zero-padded sequential index within the same chat on the same date (handles
  multiple segments in a single day).

The `--clobber` flag behaves identically to `adiumToEml.py`.

---

## Reactions / Tapbacks

Reactions in iMessage are stored as separate messages with an `associated_message_guid`. Options:

- **Recommended**: Render reactions as a footnote below the target message in the HTML body
  (e.g., `👍 Liked by Alice`). This requires a post-processing pass over messages within each
  segment to correlate reactions to their targets by GUID.
- Reactions should **not** be rendered as top-level messages in the conversation thread.
- If the associated target message is outside the current segment (e.g., reacting to an old
  message), render the reaction as a system event: `Alice liked a message`.

---

## iMessage-specific MIME Headers

Add these `X-` headers to each output `.eml` (in addition to existing `X-Converted-By`,
`X-Converted-On`, `X-Original-File`):

| Header | Value |
|---|---|
| `X-Chat-Identifier` | `chat_identifier` from NDJSON |
| `X-Chat-GUID` | `chat_guid` from NDJSON |
| `X-iMessage-Service` | `iMessage` or `SMS` (from first message in segment) |
| `X-Segment-Messages` | Count of messages in this segment |

---

## CLI: `jsonToEml.py`

```
Usage: ./jsonToEml.py <input.ndjson> [output_dir] [options]

Arguments:
  input.ndjson          Input NDJSON file from imessage-exporter
  output_dir            Output directory (default: cwd)

Options:
  --local-handle HANDLE Phone/email of the local account (for From: header)
  --idle-hours N        Idle gap threshold in hours (default: 4)
  --min-messages N      Skip segments with fewer than N messages (default: 2)
  --max-messages N      Force-split segments at N messages (default: unlimited)
  --max-days N          Force-split segments spanning N+ days (default: unlimited)
  --no-background       Strip background-color from HTML output
  --clobber             Overwrite existing output files
  --debug               Very verbose logging
```

Success output (one line per `.eml`, suitable for piping to `tee`):
```
{chat_identifier}\t{outfilename}\t{Message-ID}\x1e
```

Failures logged to stderr and to `failed_{date}.log` in the output directory.

---

## Implementation Steps (in order)

1. **Refactor `conv_to_eml.py`** (CSS path fix + signature change). Run existing conversions
   against `samples/` to confirm no regression before proceeding.
2. **Update `adiumToEml.py`** call site (one line). Re-run `samples/` sanity check.
3. **Write `imessage_json.py`**: schema validation → grouping → segmentation → Conversation
   construction. Start with 1:1 chats; add group chat support after.
4. **Write `jsonToEml.py`** entrypoint: argparse → drive `imessage_json` → `conv_to_eml` →
   write `.eml`. Follow `adiumToEml.py` structure; include `#!/usr/bin/env python3` shebang
   and make executable (`chmod +x`). Use `with` context managers for all file I/O.
5. **Handle reactions**: add post-processing pass in `imessage_json.py` before yielding each
   Conversation.
6. **Add sample NDJSON fixture** to `samples/` (synthetic, no real data) and a corresponding
   expected `.eml`; document verification steps.
7. **Update docs**: README, `.github/copilot-instructions.md`, `.github/copilot-memory.md`.

---

## Deliverables

### Recent updates (2026-03-16)
- Pseudo-domain logic changed: `conv_to_eml` now derives the pseudo-domain from `Conversation.source_db_basename` or the basename of `conv.origfilename`. `sms.db` → `sms.imessage.invalid`; `chat.db` → `chat.imessage.invalid`. Added unit tests: `tests/test_fakedomain.py`.
- Unit tests run locally: new fakedomain tests pass. NDJSON verification run and summary saved to `.copilot/ndjson-test-summary-2026-03-15.md`.
- README updated to document NDJSON usage and the pseudo-domain behavior (NDJSON docs placed above the Adium section).

Next steps:
- Ensure parsers set `conv.source_db_basename` when DB-origin metadata is available in NDJSON exports.
- Add tests for text-encoding edge cases discovered during verification (object-replacement characters, emoji-only messages).
- Improve logging when `--embed-attachments` is requested but payloads are unavailable (consider adding `X-Original-Attachment-Path` header for missing payloads).

- Modified `conv_to_eml.py` (CSS path + signature; no behavior change for existing callers).
- Modified `adiumToEml.py` (updated call site only).
- New `imessage_json.py` (parser + segmentation).
- New `jsonToEml.py` (CLI entrypoint, executable).
- Sample NDJSON fixture in `samples/` with synthetic data.
- Updated README, `.github/copilot-instructions.md`, `.github/copilot-memory.md`.
