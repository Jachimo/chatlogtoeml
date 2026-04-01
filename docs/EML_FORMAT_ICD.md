# Interface Control Document: Chat Log EML Archive Format

**Document ID:** chatlogtoeml-ICD-001  
**Revision:** 1.1  
**Date:** 2026-03-31  
**Status:** DRAFT  

---

## Table of Contents

1. [Purpose and Scope](#1-purpose-and-scope)  
2. [Normative References](#2-normative-references)  
3. [Overview](#3-overview)  
4. [MIME Structure](#4-mime-structure)  
   - 4.1 [`multipart/alternative` Internal Ordering](#41-multipartalternative-internal-ordering)  
   - 4.2 [HTML Body Styling](#42-html-body-styling)  
5. [Standard RFC 5322 Headers](#5-standard-rfc-5322-headers)  
6. [Pseudo-Address Construction](#6-pseudo-address-construction)  
7. [Subject Line Format](#7-subject-line-format)  
8. [Message-ID and References](#8-message-id-and-references)  
9. [Extension Headers (X-*)](#9-extension-headers-x-)  
10. [Attachment Parts](#10-attachment-parts)  
11. [Message Index Microformat](#11-message-index-microformat)  
12. [Output File Naming](#12-output-file-naming)  
13. [Segment Boundary Policy](#13-segment-boundary-policy)  
14. [Deduplication Reference Architecture](#14-deduplication-reference-architecture)  
15. [Versioning and Compatibility](#15-versioning-and-compatibility)  

---

## 1. Purpose and Scope

This document defines the structure and semantics of the `.eml` files produced by **chatlogtoeml** when converting Apple iMessage databases (iOS `sms.db`, macOS `chat.db`) or equivalent NDJSON exports into MIME messages suitable for archives.

The format is designed to be:

- **Self-contained.** Each output file is a valid RFC 5322 Internet Message with RFC 2045–2049 MIME structure that can be opened by any standards-compliant mail client.
- **Metadata-rich.** All metadata available in the source database is preserved in headers or structured attachments.
- **Dedupe/sync-ready.** Every file carries enough machine-readable identity information to detect and eliminate duplicate message coverage at message level, without requiring access to the original database.

This document covers the `db_to_eml` (Apple DB) and `json_to_eml` (NDJSON) conversion paths. The legacy Adium path (`chat_convert`) produces a subset of these headers.

---

## 2. Normative References

| Standard | Title |
|----------|-------|
| RFC 5322 | Internet Message Format |
| RFC 2045 | MIME Part One: Format of Internet Message Bodies |
| RFC 2046 | MIME Part Two: Media Types |
| RFC 2047 | MIME Part Three: Message Header Extensions |
| RFC 2049 | MIME Part Five: Conformance Criteria and Examples |
| RFC 2183 | Communicating Presentation Information in Internet Messages (Content-Disposition) |
| RFC 2392 | Content-ID and Message-ID Uniform Resource Locators |
| RFC 2822 | Internet Message Format (predecessor to RFC 5322, referenced for compatibility) |
| RFC 5321 | Simple Mail Transfer Protocol (address syntax) |

---

## 3. Overview

A chatlogtoeml `.eml` file represents one **conversation segment** — a time-bounded slice of a single chat thread. When a long chat thread is exported, it is split into multiple segments; each segment becomes a separate `.eml` file. The segmentation policy is described in [Section 13](#13-segment-boundary-policy).

Each `.eml` encodes:

- The participants, as RFC 5322 `From:` / `To:` addresses constructed from messaging handles.
- A human-readable `Subject:` line identifying the chat and date.
- The complete message transcript as both `text/plain` and `text/html` MIME alternatives.
- Any embedded file attachments.
- A machine-readable `chatlogtoeml-index.json` attachment listing every message GUID in the segment, enabling future deduplication.
- A rich set of `X-*` extension headers carrying source-database metadata.

---

## 4. MIME Structure

The top-level content type is `multipart/related`. Its parts are ordered as follows:

```
Content-Type: multipart/related
│
├── [1] Content-Type: multipart/alternative
│       ├── [1a] Content-Type: text/plain; charset="us-ascii"
│       │         Plain-text transcript of all messages
│       └── [1b] Content-Type: text/html; charset="us-ascii"
│                 HTML transcript with CSS styling
│
├── [2..N] Per-message file attachments  (optional, 0 or more)
│           Content-Type: <mime-main>/<mime-sub>
│           Content-Disposition: attachment | inline
│           Content-ID: <md5hash>
│           Content-Transfer-Encoding: base64
│
└── [N+1]  Content-Type: application/x-chatlogtoeml-index  (when GUIDs available)
            Content-Disposition: attachment; filename="chatlogtoeml-index.json"
            Content-ID: <chatlogtoeml-index>
            Content-Transfer-Encoding: base64
```

**Rationale for `multipart/related`:** The HTML body references embedded image attachments by `Content-ID` URI (`cid:` scheme, RFC 2392). Using `multipart/related` as the outer type lets compliant mail clients render those images inline within the HTML body.

**Part ordering within `multipart/related`:** The `multipart/alternative` body block is always the **first** part so that mail clients which display the earliest part have immediate access to the readable transcript. Image attachments follow, inserted between the body block and the index attachment so they can be referenced by the HTML part. The index attachment is always last.

### 4.1 `multipart/alternative` Internal Ordering

Within the `multipart/alternative` block, the parts are ordered as follows:

1. `text/plain` — **first** (lowest fidelity)
2. `text/html` — **last** (highest fidelity)

**This ordering is normative and must not be reversed.**

**Rationale:** RFC 2046 § 5.1.4 specifies that in a `multipart/alternative` body, alternatives should appear in increasing order of preference, with the *most preferred* (highest fidelity) format listed *last*. Mail clients are expected to render the last part they are capable of displaying.

Thunderbird follows this rule strictly: it selects the **last** MIME alternative it can render. If `text/html` were placed before `text/plain`, Thunderbird would display only the plain-text version, ignoring the HTML transcript entirely. The `text/plain` part is therefore always emitted first, and `text/html` always last, to ensure compliant mail clients (including Thunderbird) display the richly formatted HTML transcript.

### 4.2 HTML Body Styling

The HTML part references a CSS stylesheet that is embedded directly in the `<head>` of the HTML document (not as a separate MIME part). The stylesheet defines the following classes:

| Class | Purpose |
|-------|---------|
| `.localname` | Sender name for the local account (rendered in blue) |
| `.remotename` | Sender name for a remote participant (rendered in red) |
| `.name` | Sender name for indeterminate participants (rendered in black) |
| `.timestamp` | Message timestamp (rendered in small grey text) |
| `.message` | Wrapper paragraph for a user message |
| `.system_message` | Wrapper paragraph for a system/event message |
| `.message_text` | The message body text span |
| `.reactions` | Container for reaction annotations |
| `.reaction` | Individual reaction pill |
| `.attachment` | Attachment reference link |
| `.attachment_image` | Wrapper for inline image |

When the `--no-background` flag is used, any `background-color` and `background` CSS properties are stripped from all inline styles in message HTML.

---

## 5. Standard RFC 5322 Headers

### 5.1 `From:`

The `From:` header is set to the **local participant** — the account owner whose database is being exported.

**Selection precedence:**

1. The participant whose `.position` field is `"local"`.
2. If none is marked local, the participant matching `conv.localaccount`.
3. If still unresolved, the first participant in the list.

**Format:** `Display Name <localpart@pseudo-domain>`  
See [Section 6](#6-pseudo-address-construction) for address construction rules.

### 5.2 `To:`

The `To:` header contains all participants *other than* the local participant, comma-separated.

If the conversation has only one participant (e.g., a self-note thread), `To:` is set equal to `From:`.

### 5.3 `Date:`

The `Date:` header is the RFC 2822–formatted datetime of the first message in the segment (`conv.startdate`), falling back to the oldest message's timestamp if `startdate` is not set. If no date can be determined, the current UTC time at conversion is used.

**Format:** `strftime`-formatted via Python `email.utils.format_datetime`.

### 5.4 `Subject:`

See [Section 7](#7-subject-line-format).

### 5.5 `Message-ID:`

See [Section 8.1](#81-message-id).

### 5.6 `References:`

See [Section 8.2](#82-references).

---

## 6. Pseudo-Address Construction

Messaging handles (phone numbers, iMessage email addresses, Apple IDs, short numeric chat IDs) are not valid RFC 5321 email addresses. chatlogtoeml constructs synthetic RFC-safe email addresses as follows.

### 6.1 Pseudo-Domain

The domain portion of all addresses in a given file is a fixed **pseudo-domain** derived from the source database:

| Source | Pseudo-domain |
|--------|--------------|
| iOS `sms.db` (basename starts with `sms`) | `sms.imessage.invalid` |
| macOS `chat.db` (basename starts with `chat`) | `chat.imessage.invalid` |
| Any other / fallback | `{service}.{imclient}.invalid` |

The `.invalid` TLD is reserved by RFC 2606 and will never route to any real destination.

The pseudo-domain is **consistent within a file** — every address in the same `.eml` uses the same domain. This makes the `References:` threading header stable.

### 6.2 Local-Part Derivation

If the handle already contains an `@` character, it is used as-is (assumed to be a valid email address, e.g., an Apple ID like `user@icloud.com`).

Otherwise, the handle is processed as follows:

1. **URI scheme stripping.** If the handle begins with `tel:`, `sms:`, `mailto:`, or `im:`, the scheme prefix is removed.
2. **ASCII normalization.** Unicode characters are NFKD-normalized; non-ASCII bytes are dropped; CR/LF are replaced with spaces.
3. **Character filtering.** Only `[A-Za-z0-9._-]` is kept; all other characters (including `+`, spaces, parentheses) are dropped.
4. **Fallback.** If the result is empty, the local-part becomes `unknown`.

**Examples:**

| Source handle | Derived address |
|--------------|-----------------|
| `+15555551234` | `15555551234@sms.imessage.invalid` |
| `tel:+15555551234` | `15555551234@sms.imessage.invalid` |
| `alice@icloud.com` | `alice@icloud.com` (verbatim) |
| `+44 20 7946 0958` | `442079460958@sms.imessage.invalid` |
| `42` (numeric chat ID) | `42@chat.imessage.invalid` |

### 6.3 Display Name

The display name portion of the address (`"Name" <addr>`) is chosen in precedence order:

1. The participant's resolved real name from the address book (`realname` field).
2. A sanitized token derived from the handle (for phone numbers, the digits only, e.g., `15555551234`).
3. The address itself (used as both display name and address if nothing else is available).

All display names are ASCII-only (non-ASCII characters are dropped after NFKD normalization) to avoid RFC 2047 encoded-word syntax, which reduces compatibility with older mail clients and indexers.

---

## 7. Subject Line Format

### 7.1 iMessage Conversations

When the source is an iMessage conversation (`service == "iMessage"`, `source_db_basename` starts with `sms` or `chat`):

```
{service} with {participant_name}[ ({chat_id})] on {day}, {month} {dd} {year}
```

**Examples:**
```
iMessage with Alice on Tue, Jan 15 2019
iMessage with Alice (family-group@example.com) on Tue, Jan 15 2019
```

Where:
- `{service}` is the value of `conv.service` (e.g., `iMessage`), ASCII-normalized.
- `{participant_name}` is the first non-local participant's real name, or a sanitized handle token if no real name is available. Phone-number handles are stripped to digits only.
- `({chat_id})` is an optional suffix appended when `conv.filenameuserid` has clear human meaning — specifically when it contains alphabetic or email-like characters (e.g., `family-group@example.com`). It is **omitted** for:
  - Purely numeric or phone-like identifiers (e.g., `42`, `+15555551234`).
  - Apple chat-GUID forms (e.g., `SMS;-;+15555551234`).
  - UUID- or hex-digest-like opaque strings.
  - Identifiers containing no alphabetic or `@` characters.
- The date uses Python's `%a, %b %e %Y` strftime format.

### 7.2 Non-iMessage / Legacy Conversations

```
{service} with {participant_name} on {day}, {month} {dd} {year}
```

---

## 8. Message-ID and References

### 8.1 `Message-ID`

The `Message-ID` header is a **content-based hash** of the segment's transcript:

```
Message-ID: <{md5hex}@{pseudo-domain}>
```

Where `md5hex` is the MD5 hexdigest of the concatenation of:

```
Date_header_value (UTF-8)
+ Subject_header_value (UTF-8)
+ newline-joined plain text transcript (UTF-8)
```

**Properties:**

- Two segments with the same participants, date, subject, and transcript will produce the same `Message-ID`. This is intentional: it allows mail clients and mbox importers to deduplicate at the segment level using standard MIME deduplication logic.
- The `Message-ID` is **not** a globally unique identifier in the IETF sense; it is a deterministic fingerprint. It will differ if the plain text transcript differs even slightly.
- Note: MIME headers (including `X-*` headers) are explicitly excluded from the hash so that metadata changes do not invalidate the ID.

### 8.2 `References`

The `References` header enables mail-client threading of all segments of the same conversation:

```
References: <{md5hex}@{pseudo-domain}>
```

Where `md5hex` is the MD5 hexdigest of the space-joined, lexicographically sorted, lowercased participant user IDs.

**Properties:**

- All segments of the same conversation (same participant set) produce the same `References` value.
- This allows a mail client to thread together all `.eml` files belonging to a single chat thread.
- The value is stable across re-exports as long as the participant list is stable.

---

## 9. Extension Headers (X-*)

All `X-*` headers are optional — any consumer must tolerate their absence. Headers are set only when the corresponding value is available from the source.

All string header values are ASCII-normalized (NFKD → ASCII drop) before being set, to prevent RFC 2047 encoded-word sequences.

### 9.1 Headers set by `conv_to_eml.mimefromconv()` (all conversion paths)

| Header | Value | Notes |
|--------|-------|-------|
| `X-Converted-On` | Conversion timestamp | `strftime('%a, %d %b %Y %T %z')` of the local system clock at conversion time |
| `X-Original-File` | Source file path | The value of `conv.origfilename`; may be a DB path, XML path, or NDJSON path |
| `X-Message-Index-SHA256` | 64-char hex SHA-256 digest | Only present when GUIDs are available; see [Section 11](#11-message-index-microformat) |

### 9.2 Headers set by `db_to_eml` (Apple DB path)

| Header | Value | Notes |
|--------|-------|-------|
| `X-Chat-Identifier` | `conv.filenameuserid` | The sanitized numeric or string chat identifier from the Apple DB `chat` table |
| `X-Chat-GUID` | `conv.chat_guid` | The Apple-assigned globally unique chat identifier (e.g., `SMS;-;+15555551234`); omitted if not available |
| `X-Segment-Start` | ISO 8601 datetime | `conv.startdate.isoformat()`; the timestamp of the first message in the segment |
| `X-Segment-Messages` | Integer (string) | Count of messages in this segment |
| `X-iMessage-Service` | `conv.service` | Service string from the database (`iMessage`, `SMS`, etc.); omitted if not available |
| `X-Converted-By` | `db_to_eml` | Binary name; falls back to literal string `db_to_eml` if invoked via Python directly |

### 9.3 Headers set by `json_to_eml` (NDJSON path)

Identical to [Section 9.2](#92-headers-set-by-db_to_eml-apple-db-path), except:

| Header | Value | Notes |
|--------|-------|-------|
| `X-Converted-By` | `os.path.basename(sys.argv[0])` | Exact binary name as invoked; typically `json_to_eml` |

### 9.4 Headers set by `chat_convert` (legacy Adium path)

| Header | Value | Notes |
|--------|-------|-------|
| `X-Converted-By` | `os.path.basename(sys.argv[0])` | Typically `chat_convert` |

Note: the legacy Adium path does not set `X-Chat-Identifier`, `X-Chat-GUID`, `X-Segment-Start`, `X-Segment-Messages`, `X-iMessage-Service`, or `X-Message-Index-SHA256` — these are iMessage-specific.

### 9.5 Per-attachment header

When a message attachment exists in the source but its binary payload could not be retrieved at conversion time:

| Header | Value | Notes |
|--------|-------|-------|
| `X-Original-Attachment-Path` | Original filesystem path from source | Allows a future re-run to locate and embed the payload; may appear multiple times |

---

## 10. Attachment Parts

### 10.1 Message Attachments

Each file attached to a message in the source database is embedded as a separate MIME part with:

- **Content-Type:** Derived from the attachment's MIME type in the source database (e.g., `image/jpeg`, `video/mp4`, `application/pdf`). Falls back to `application/octet-stream` if the MIME type is unknown or unparseable.
- **Content-Transfer-Encoding:** `base64`
- **Content-ID:** `<{contentid}>` where `contentid` is a hex MD5 digest of `data_bytes + filename_utf8 + mimetype_utf8`. This is used by the HTML body to reference inline images via `<img src="cid:{contentid}">`.
- **Content-Disposition:**
  - `inline; filename=...` for image types (`Content-Type` starts with `image/`)
  - `attachment; filename=...` for all other types

If an attachment has no binary payload (e.g., the attachment file was not available at the path recorded in the database), no MIME part is created for it. Instead, if the original path is known, an `X-Original-Attachment-Path` header is added to the outer message (see [Section 9.5](#95-per-attachment-header)).

### 10.2 Source File Attachment (legacy path only)

When the `--attach` flag is passed to `chat_convert`, the original source log file is appended as a final MIME part:

- **Content-Type:** `application/octet-stream`
- **Content-Disposition:** `attachment; filename={basename of source file}`
- **Content-Transfer-Encoding:** Handled by Python's `MIMEApplication` (defaults to base64)

---

## 11. Message Index Microformat

### 11.1 Motivation

When a user runs `db_to_eml` multiple times against the same database — for example, once in 2022 against an iPhone backup and again in 2024 against a newer backup — the resulting `.eml` archive may contain duplicate coverage of the same messages. A deduplication tool needs a way to determine which messages a given `.eml` file covers without re-parsing the transcript text.

The message index microformat embeds a machine-readable manifest of every message GUID in a segment, enabling exact and partial overlap detection at message granularity.

### 11.2 MIME Envelope

The index is a MIME attachment with the following headers:

```
Content-Type: application/x-chatlogtoeml-index
Content-Disposition: attachment; filename="chatlogtoeml-index.json"
Content-ID: <chatlogtoeml-index>
Content-Transfer-Encoding: base64
```

The payload is a UTF-8–encoded JSON document, base64-encoded. It is always the **last** MIME part in the file.

The index part is **omitted** (silently) when no non-empty GUIDs are present in the segment — for example, in legacy Adium XML/HTML logs, which do not carry message GUIDs.

### 11.3 JSON Payload Schema

```json
{
  "schema_version": 1,
  "chat_identifier": "<string>",
  "segment_start": "<ISO 8601 datetime string or null>",
  "segment_end":   "<ISO 8601 datetime string or null>",
  "message_count": <integer>,
  "guid_count":    <integer>,
  "guid_sha256":   "<64-char hex string>",
  "message_guids": ["<guid-1>", "<guid-2>", ...]
}
```

### 11.4 Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | integer | Always `1` in this revision. Consumers must check this field and reject or warn on unknown values. |
| `chat_identifier` | string | The sanitized chat identifier (`conv.filenameuserid`), e.g., `"42"` or `"alice_example_com"`. Empty string if not available. |
| `segment_start` | string or null | ISO 8601 datetime (with timezone) of the first message in the segment. `null` if not available. |
| `segment_end` | string or null | ISO 8601 datetime (with timezone) of the last message in the segment. `null` if not available. |
| `message_count` | integer | Total number of `Message` objects in the segment, including system events. |
| `guid_count` | integer | Number of entries in `message_guids`. May be less than `message_count` if some messages lack GUIDs (e.g., system events). |
| `guid_sha256` | string | SHA-256 hex digest of the **sorted** GUID list joined by newline characters (see [Section 11.5](#115-guid_sha256-computation)). |
| `message_guids` | array of strings | The GUIDs of all messages in this segment, in **chronological insertion order**. This is the order in which messages appear in the transcript. |

### 11.5 `guid_sha256` Computation

The digest is computed as:

```python
sorted_guids = sorted(guids)              # lexicographic sort
digest = hashlib.sha256(
    '\n'.join(sorted_guids).encode('utf-8')
).hexdigest()
```

The sort makes the digest **order-independent**: two segments covering exactly the same set of messages will always produce the same `guid_sha256`, regardless of the chronological order in which those messages were inserted. This is the canonical identity fingerprint for a segment's message coverage.

### 11.6 `X-Message-Index-SHA256` Header

The same `guid_sha256` digest is also emitted as the `X-Message-Index-SHA256` RFC 5322 extension header on the outer envelope. This allows a scanner to determine segment identity with a single header read — without decoding or parsing the base64-encoded JSON part — making large-archive sweeps substantially faster.

---

## 12. Output File Naming

Output `.eml` files are named by the `make_out_filename()` function:

```
{datepart}_{sanitized_chat_id}_{index:04d}.eml
```

| Component | Description |
|-----------|-------------|
| `datepart` | ISO 8601-like timestamp: `YYYY-MM-DDTHHMMSS` if a full datetime is available; `YYYY-MM-DD` if only a date; `nodate` if unavailable. |
| `sanitized_chat_id` | `conv.filenameuserid` with all non-alphanumeric characters replaced by underscores, leading underscores stripped, truncated to 64 characters. Falls back to `chat` if empty. |
| `index` | Zero-based zero-padded 4-digit segment counter for this chat identifier within a single conversion run. Resets to `0000` for each distinct `chat_identifier`. |

**Examples:**
```
2019-01-15T143022_42_0000.eml
2019-01-28T092311_42_0001.eml
2024-03-10T000000_alice_example_com_0000.eml
```

---

## 13. Segment Boundary Policy

A long conversation is split into segments by the `segment_messages()` function in `chatlogtoeml/parsers/imessage_common.py`. The following parameters control segmentation (all exposed as CLI arguments):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `idle_hours` | `8.0` | Split the conversation when consecutive messages are separated by more than this many hours. |
| `max_days` | `0` | Force a split when a segment spans more calendar days than this. `0` = unlimited. |
| `max_messages` | `0` | Force a split when a segment reaches this many messages. `0` = unlimited. |
| `min_messages` | `2` | Segments with fewer messages than this are not emitted as standalone files. Instead, they are coalesced with an adjacent segment (preferring the previous neighbor). |

**Short segment handling:** If a segment would contain fewer than `min_messages` messages, it is merged into the immediately preceding segment (or the following segment if it is the first segment). This prevents the creation of large numbers of one- or two-message files from sparse conversation periods. Setting `--min-messages 1` disables all merging.

---

## 14. Deduplication Reference Architecture

This section describes how the structures defined above can be used to implement message-level deduplication of an `.eml` archive. This functionality is **not yet implemented** in chatlogtoeml itself; this section documents the intended usage of the index microformat.

### 14.1 Problem Statement

A user runs `db_to_eml` against a backup from 2020, producing `archive_v1/`. In 2024, they run again against a newer backup that includes all the old messages plus new ones, producing `archive_v2/`. A naïve merge of both archives into a single mbox would duplicate every message from 2020.

### 14.2 Exact-Duplicate Segment Detection

**Algorithm:**

1. For each `.eml` file in the archive, read the `X-Message-Index-SHA256` header.
2. Build a map: `guid_sha256 → list of .eml paths`.
3. Any `guid_sha256` that appears more than once identifies a set of files covering the **exactly same** messages. All but the highest-quality copy should be removed or marked as superseded.

**Complexity:** O(N) header reads, no attachment parsing required.

### 14.3 Partial-Overlap Detection

When two segments share some but not all messages (e.g., one is a strict subset of the other, or they overlap at the boundary):

1. For each `.eml`, decode and parse the `chatlogtoeml-index.json` attachment.
2. Build a reverse map: `message_guid → list of .eml paths`.
3. Any GUID appearing in more than one file represents a duplicated message.
4. The overlap can be quantified as a set intersection of the `message_guids` arrays.

**Subset detection:** If segment A's `message_guids` is a subset of segment B's `message_guids`, segment A is entirely covered by segment B and can be discarded.

**Priority / winner selection:** When choosing which copy of a message to keep, the following heuristics are recommended (in order of preference):

1. The segment with the larger `guid_count` (more complete coverage).
2. The segment whose `X-Converted-By` value indicates a more authoritative source (e.g., `db_to_eml` over `json_to_eml`).
3. The more recently converted segment (higher `X-Converted-On` timestamp).

### 14.4 Synchronization with a Live Database

If the goal is to bring an `.eml` archive up to date with a current `sms.db` without duplicating existing messages:

1. Build the GUID set from all existing `.eml` index attachments.
2. Query the database for messages whose GUIDs are **not** in that set.
3. Export only the new messages, producing new segment files for each gap period.

This approach uses `message_guids` as a cursor into the database, avoiding the need to re-export already-archived messages.

### 14.5 `schema_version` Contract

Consumers of `chatlogtoeml-index.json` **must** check the `schema_version` field before processing. The current version is `1`. If a consumer encounters a `schema_version` it does not recognise, it must either skip the file or emit a warning. No backwards-incompatible changes will be made without incrementing this field.

---

## 15. Versioning and Compatibility

### 15.1 Forward Compatibility

- Any unrecognised `X-*` header must be tolerated and ignored.
- Any unrecognised field in `chatlogtoeml-index.json` must be tolerated and ignored.
- The `schema_version` field in the index JSON is the version discriminator.
- The MIME structure (outer `multipart/related` containing `multipart/alternative`) is stable.

### 15.2 Backwards Compatibility

- Files written without `X-Message-Index-SHA256` (absence of the index) must be treated as having unknown message coverage. A dedup tool may still use `Message-ID` for segment-level dedup.
- Files written without `X-Chat-Identifier` (e.g., legacy Adium path) lack database provenance metadata. Segment threading via `References` still works.

### 15.3 Known Limitations

- **`Message-ID` collisions.** The MD5-based `Message-ID` is a transcript fingerprint, not a globally unique identifier. Two conversions of the same source data will produce the same `Message-ID`; this is desirable for segment-level dedup. However, if the transcript is reformatted (e.g., different timezone display), the `Message-ID` will differ.
- **Non-GUID messages.** System events (delivery receipts, "liked a message", group name changes) may not carry their own Apple GUID. Such events are counted in `message_count` but omitted from `message_guids` and `guid_count`. A segment with only system events will have no index attachment.
- **Address determinism.** The pseudo-address for a phone number that appears both with and without the `tel:` prefix (e.g., from different source databases) will normalise to the same local-part, so threading and dedup are not affected.

---

*End of document.*
