# NDJSON → EML Feature Plan

## Goals
- Add NDJSON (imessage-exporter) ingestion without breaking existing XML/HTML paths or the `./adiumToEml.py` entrypoint.
- Prefer refactoring/reuse of existing Conversation + MIME generation; preserve all metadata and keep From/To headers human-friendly.
- Provide a new CLI (`jsonToEml.py`) that splits large NDJSON into conversations via idle/min-messages/max-duration rules and emits RFC822 .eml with readable HTML/XHTML.

## Constraints / Non-goals
- Do not regress current Adium conversions; keep `converted.css` loading expectations.
- Preserve all metadata (participants, handles, timestamps, attachments, aliases, service info); avoid lossy transforms.
- Terse comments only; minimal churn to existing files unless refactoring improves reuse.

## Approach
1) Inventory & refactor shared pieces: identify MIME/Conversation helpers that can be reused; consider moving CSS load and header helpers into a shared module while keeping current behavior intact.
2) NDJSON schema & mapping: document imessage-exporter fields (handles, display names, chat GUIDs, timestamps, attachments, reactions); decide normalization (tz-aware datetimes, html/text bodies, attachment payloads/content-ids).
3) Conversation segmentation: design configurable thresholds (idle gap, min messages, max duration); emit deterministic conversation IDs; ensure participant roles and start/end dates are set for headers.
4) Parser implementation: stream NDJSON to avoid memory blowups; build Conversation objects incrementally; preserve message ordering; capture aliases/realnames for From/To.
5) EML reuse: feed Conversations into conv_to_eml (or extracted helper) to generate MIME; honor `--no-background`, `--attach`, `--clobber`, and add any NDJSON-specific headers if needed.
6) CLI `jsonToEml.py`: argparse for input NDJSON, output dir, thresholds, attach/no-background/debug; write one .eml per conversation; log successes/failures similar to adium_convert.
7) Validation: add NDJSON sample + expected output; run sanity conversions over samples and ensure legacy paths still work; document usage in README/copilot-instructions/memory.

## Deliverables
- Refactored shared conversion helpers (if needed) without breaking current behavior.
- New NDJSON parser + segmentation logic producing Conversation objects.
- `jsonToEml.py` CLI with documented options and sample NDJSON/EML fixtures.
- Updated docs (README, copilot-instructions, copilot-memory) capturing usage and constraints.
