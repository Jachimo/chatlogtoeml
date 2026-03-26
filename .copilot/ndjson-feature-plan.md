NDJSON (imessage-exporter) → EML Feature Plan

Purpose
-------
Add a robust, well-tested NDJSON ingestion path that produces RFC822 .eml files like the existing Adium converter. Preserve all metadata, avoid regressions in Adium paths, and provide a separate CLI entrypoint (`bin/json_to_eml`).

Goals
-----
- Reuse conv_to_eml MIME generation for deterministic, human-readable EML output.
- Implement a conservative NDJSON parser (imessage_json.py) that:
  - Groups messages into conversations by chat_identifier/chat_guid
  - Segments by configurable idle gap / min_messages / max_days / max_messages
  - Preserves attachments metadata and optionally embeds binary payloads
  - Renders reactions inline (HTML badges) and provides text fallbacks
  - Normalizes participant representations and preserves display names
  - Produces Conversation objects usable by conv_to_eml.mimefromconv
- Provide `bin/json_to_eml` CLI with streaming/shard support for very large NDJSON files.

Design decisions and conventions
--------------------------------
- Conversation model: keep using conversation.Conversation, Participant, Message, Attachment. Parsers MUST populate at least userid and text/html/date fields for messages; attachments should call Attachment.set_payload when binary data is embedded.
- Date handling: parser must return timezone-aware datetimes. If a message date is missing/unparseable, assign a deterministic fallback (UTC epoch 1970-01-01T00:00:00Z). This preserves ordering and deterministic Message-IDs while avoiding crashes in arithmetic.
- Participant normalization: accept strings or dicts. Extract canonical id from keys in order: id, identifier, handle, address, username, phone, value. Fallback to the first non-empty dict value, or stringified representation. Always add participants to Conversation as strings.
- Reactions: group reactions by type and actors; render as inline HTML badges (emoji×count) where emoji mapping exists and fallback to textual label. If the reaction references a message GUID in the same segment, append HTML/text to the target message; otherwise emit a system event message.
- Streaming: shard large NDJSON into per-chat temp files (safe filenames using hash). Process shards sequentially to control memory usage. Default auto-stream threshold: 50 MiB (tunable).
- CLI flags (`bin/json_to_eml`): --stream, --stream-tempdir, --embed-attachments, --local-handle, --no-background, --clobber, --debug.
- EML generation: conv_to_eml.mimefromconv(conv, no_background=False) is the stable API. It loads converted.css from module directory so converters can be run from other CWDs.

Implementation notes / code pointers
-----------------------------------
- imessage_json.py:
  - _parse_date(datestr): use dateutil.parser.parse and coerce naive datetimes to UTC. Return None on parse failure; callers should fallback to epoch.
  - _norm_user(u): normalize dicts and strings to a canonical string id.
  - segment_messages(...): convert missing dates to epoch for stable sorting and segmentation.
  - build_conversation_from_segment(...): build Conversation, add participants (strings), add messages (with deterministic dates), collect reactions and apply to target messages or emit system events.
  - parse_file(..., stream=True): shard NDJSON by chat_identifier using safe filenames and process each shard.
- conv_to_eml.py:
  - Reuse mimefromconv API; ensure it handles conversations with missing dates/participants gracefully. Use current modifications to fallback header Date to UTC now if messages have no dates.
  - Keep CSS load using module path to ensure behavior when running from different CWDs.
- conversation.py:
  - Participant/Message/Attachment models. Ensure Message.__lt__ is robust to missing dates. gen_contentid should include data + name + mimetype.

Testing
-------
- Unit tests live under tests/
  - tests/test_imessage_json.py: streaming, reactions, embed-attachments
  - tests/test_conv_to_eml.py: CSS stripping, content-id uniqueness, reaction HTML preservation, case-insensitive participant matching
- Run tests with: python3 -m unittest discover -s tests -v
- For local validation with exports you don’t commit:
  1. Copy NDJSON files into a temporary local folder (e.g., samples/ndjson/realworld/<export>/ or a path outside the repo). Do NOT add to git.
  2. Run: python3 bin/json_to_eml <ndjson-file> <outdir> --stream --local-handle <your-handle> --embed-attachments (optional)
  3. Inspect resulting .eml files in the outdir. Use an MUA or 'less' to check headers, HTML rendering, attachments, and reactions.

Edge cases and policy decisions
------------------------------
- Missing dates: deterministic fallback to epoch keeps Message-ID deterministic and preserves content. Alternative (file-level start date) is feasible but complicates determinism when reprocessing subsets.
- Single-participant conversations: allow EML generation (From and To will be identical) with a warning. Previously converters required >=2 participants which caused failures for some real exports.
- Participant dicts with unexpected schema: normalize best-effort and log warnings when structure is unrecognized.

Deliverables (current)
----------------------
- imessage_json.py: NDJSON parser with streaming, normalization, reaction rendering, embed_attachments.
- `bin/json_to_eml`: CLI for NDJSON -> EML with streaming and flags.
- conv_to_eml.py, conversation.py: hardened to tolerate missing dates and participant edge cases; CSS loading unchanged.
- Unit tests covering reactions, streaming, attachment embedding, and conv_to_eml edge cases.
- Documentation: README update and this plan (file stored here).

Next steps / TODOs
-----------------
- Expand unit tests to cover additional imessage-exporter schema variants (nested participant dicts, SMS-only exports, group chats with many participants, message records missing attachments keys).
- Improve reaction-linking across adjacent segments when reactions target messages in previous shards.
- Add better logging when encountering unparseable or unexpected structures; consider writing a small summary report of skipped/mutated records.
- Performance testing on large NDJSON exports and tune shard flush thresholds and max_open descriptors.

Contact / context for future AI
------------------------------
- Key files: imessage_json.py, `bin/json_to_eml`, conv_to_eml.py, conversation.py, converted.css
- Tests: tests/test_imessage_json.py, tests/test_conv_to_eml.py
- To extend: follow build_conversation_from_segment to create Conversation objects; then call conv_to_eml.mimefromconv() to obtain MIME object and write as .eml using .as_bytes().

This plan was created to be machine- and human-readable; follow the conventions above to avoid regressions and preserve deterministic behavior for message ordering and headers.
