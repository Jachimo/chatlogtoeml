# Dedupe Ingest Plan

## Goal

Ingest multiple Apple Messages databases from different devices, deduplicate at the message level, then run existing conversation segmentation and EML emission so output contains one canonical copy of each human message.

## CLI Contract

- Add repeatable paired source argument:
  - `--source <db_path>[::attachment_root]`
- Multi-source mode is active when one or more `--source` values are provided.
- Keep existing segmentation and output flags unchanged.
- Legacy single-db mode remains supported.

### CLI Parsing Rules (Normative)

- Parse `--source` by splitting on the first `::` only:
   - Left side: `db_path`
   - Right side (optional): `attachment_root`
- Reject empty `db_path` values.
- If `attachment_root` is provided but does not exist, log warning and continue with best-effort lookup.
- Preserve source order exactly as passed on the command line.

## Source Resolution

For each source:

1. Parse into:
   - `db_path` (required)
   - `attachment_root_override` (optional)
2. Resolve effective attachment root:
   - Use explicit override when present.
   - Else use sibling `Attachments/` next to `db_path` if present.
   - Else use `None` (continue without hard failure).
3. Validate `db_path` exists before ingest.

### SourceSpec (Implementation Shape)

Use this minimal source record for all downstream steps:

- `source_index: int`
- `db_path: str`
- `attachment_root: str | None`
- `source_label: str` (basename of db path)

## Core Pipeline

1. Parse all source DBs into normalized message records.
2. Normalize handles, timestamps (UTC), and content fields.
3. Compute dedupe key for each record.
4. Group records by key.
5. Pick canonical winner per group using winner policy.
6. Merge attachment set and metadata across grouped duplicates.
7. Group deduped messages into conversations.
8. Apply existing idle-time segmentation unchanged.
9. Emit EML files with existing writer.

### Message Record (Pre-Dedupe)

Every parsed message should be normalized into this shape before dedupe:

- `source_index: int`
- `service: str`
- `chat_id: str`
- `guid: str | None`
- `sender: str`
- `timestamp_utc: datetime`
- `text_norm: str`
- `html_norm: str`
- `has_human_content: bool`
- `attachments: list[AttachmentRecord]`
- `metadata_score_inputs: dict`
- `provenance: dict` (row ids, source db path)

## Dedupe Key Priority

1. Primary key:
   - `service + guid` when `guid` exists and is stable.
2. Fallback key:
   - `service + normalized_chat_id + normalized_sender + utc_timestamp + normalized_human_content + attachment_fingerprint`

Fallback fingerprint should be conservative to avoid false merges.

### Normalization Rules (Normative)

- `service`: lowercase.
- `chat_id`: lowercase/trimmed.
- `sender`: lowercase + handle normalization already used by parser.
- `timestamp_utc`: timezone-aware UTC rounded to whole second.
- `normalized_human_content`:
   - prefer normalized plain text
   - fallback to stripped HTML text if plain text empty
   - collapse whitespace to single spaces
   - trim
- `attachment_fingerprint`:
   - sorted list of per-attachment ids
   - per-attachment id = payload hash when bytes available
   - otherwise `name|mime|size|basename(path)` normalized

### Key Serialization (Normative)

- Join key components with ASCII unit separator `\x1f`.
- Escape embedded separators as `\\x1f` before joining.
- Primary key format:
   - `service\x1fguid`
- Fallback key format:
   - `service\x1fchat_id\x1fsender\x1ftimestamp_utc\x1fnormalized_human_content\x1fattachment_fingerprint`

## Winner Selection Rules

Hard rule:

- Non-empty human communication content always wins over empty-content records.

Scoring order:

1. Human content quality:
   - non-empty text/html/payload
   - non-placeholder quality
   - meaningful length
2. Attachment quality:
   - payload-present attachment count
   - unique attachment count
3. Metadata richness:
   - reactions, contact names, service/chat ids, extra headers
4. Deterministic tie-break:
   - source index, then stable row/guid lexical order

### Winner Algorithm (Normative)

Evaluate candidates in this strict order:

1. `has_human_content` (True beats False)
2. `human_content_score` (higher wins)
3. `attachment_score` (higher wins)
4. `metadata_score` (higher wins)
5. tie-break: `source_index` asc, then `(guid or rowid)` lexical asc

### Score Definitions (Normative)

- `human_content_score`:
   - +1000 if `has_human_content`
   - +min(len(normalized_human_content), 500)
   - -200 if content is only placeholder/object chars
- `attachment_score`:
   - +10 per unique attachment identity
   - +20 per attachment with payload bytes present
- `metadata_score`:
   - +5 if guid present
   - +3 if reactions present
   - +2 if contact realname present
   - +1 each for service/chat headers present (cap at +10)

Notes:

- A content-empty record must never win against a content-present record.
- Metadata richness cannot override rule above.

## Attachment Merge Rules

- Merge union of attachments from all duplicates in the group.
- If attachment payload hashes match, treat as same attachment.
- If payload hash unavailable, use metadata fingerprint fallback.
- Keep one canonical copy per unique attachment identity.
- Preserve original path provenance from all contributing sources.

### Attachment Identity Rules

- Identity key priority:
   1. payload hash (if available)
   2. normalized fallback fingerprint (`name|mime|size|basename(path)`)
- Merge result for each identity should keep:
   - payload bytes if any source has them
   - union of provenance paths

## Determinism and Auditability

- Sort merged messages deterministically (timestamp + stable tie-breakers).
- Emit optional dedupe report with:
  - parsed/kept/dropped counts
  - key type breakdown (guid vs fallback)
  - winner/merge decisions
  - attachment merge stats

### Acceptance Criteria

1. Running same inputs twice yields byte-identical output EML files (aside from expected date headers if any non-deterministic fields remain).
2. Content-bearing message is never dropped in favor of content-empty duplicate.
3. Duplicate attachments across sources are not duplicated in output message.
4. Distinct attachments across sources are preserved in output message.
5. Existing single-source behavior remains backward compatible.

### Implementation Order

1. CLI parsing + `SourceSpec` resolution.
2. Source fan-in parser that emits normalized message records.
3. Dedupe key + winner algorithm.
4. Attachment merge logic.
5. Conversation regroup + existing segmentation + emission.
6. Dedupe report and tests.

## Non-Goals (Initial Iteration)

- Post-hoc dedupe over already-generated EML files.
- Approximate fuzzy matching that risks false-positive merges.
