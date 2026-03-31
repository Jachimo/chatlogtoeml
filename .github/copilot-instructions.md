# Copilot Instructions for chatlogtoeml

## Build / Run / Test
- Requires Python >=3.9 with dependencies installed: `pip install pytz python-dateutil`.
- Convert a single Adium/XML/HTML log: `./bin/chat_convert path/to/log.chatlog [output_dir] [--clobber] [--attach] [--no-background] [--debug]`.
- Convert an imessage-exporter NDJSON export: `./bin/json_to_eml <input.ndjson> <outdir> [--local-handle <handle>] [--idle-hours <float>] [--min-messages <int>] [--max-messages <int>] [--max-days <int>] [--stream] [--stream-tempdir <dir>] [--embed-attachments] [--no-background] [--clobber] [--debug]`.
- Bulk convert a directory: `./adium_convert.sh "<log_root>" "<output_dir>"` (writes `converted_YYYY-MM-DD.log` and `failed_YYYY-MM-DD.log`).
- Merge `.eml` outputs into an mbox: `python extras/emlToMbox.py <eml_dir> <output.mbox>`.
- No extra linters are defined; run `python3 -m unittest discover -v` to sanity check.
 - Convert an imessage-exporter NDJSON export: `./bin/json_to_eml <input.ndjson> <outdir> [--local-handle <handle>] [--idle-hours <float>] [--min-messages <int>] [--max-messages <int>] [--max-days <int>] [--stream] [--stream-tempdir <dir>] [--embed-attachments] [--no-background] [--clobber] [--debug]`.
 - Convert Apple Messages SQLite DBs (sms.db / chat.db): `./bin/db_to_eml <infile> <outdir> [--local-handle <handle>] [--address-book <AddressBook.sqlitedb>] [--attachment-root <dir>] [--idle-hours <float>] [--min-messages <int>] [--max-messages <int>] [--max-days <int>] [--no-attach] [--no-background] [--clobber] [--debug]`.
   - Multi-source mode: pass `--source <db_path>[::attachment_root]` multiple times and use `-` as the positional `infile` placeholder, followed by the `outdir` position. Example:
     `./bin/db_to_eml --source /path/a/sms.db::/path/a/Attachments --source /path/b/chat.db::/path/b/Attachments - /path/to/out --clobber`
 - Bulk convert a directory: `./adium_convert.sh "<log_root>" "<output_dir>"` (writes `converted_YYYY-MM-DD.log` and `failed_YYYY-MM-DD.log`).
 - Merge `.eml` outputs into an mbox: `python extras/emlToMbox.py <eml_dir> <output.mbox>`.
 - No extra linters are defined; run `python3 -m unittest discover -v` to sanity check.

## Architecture overview
- `chatlogtoeml` is now a package. `chatlogtoeml.conversation` holds the data model, `chatlogtoeml.conv_to_eml` handles MIME generation, and `chatlogtoeml.parsers.*` contain format-specific parsers (`adium_xml`, `adium_html`, `imessage_json`).
- CLI wrappers live under `bin/`: `bin/chat_convert` invokes `chatlogtoeml.cli.legacy` for Adium/XML/HTML logs, while `bin/json_to_eml` invokes `chatlogtoeml.cli.ndjson` for NDJSON streams.
 - CLI wrappers live under `bin/`: `bin/chat_convert` invokes `chatlogtoeml.cli.legacy` for Adium/XML/HTML logs, `bin/json_to_eml` invokes `chatlogtoeml.cli.ndjson` for NDJSON streams, and `bin/db_to_eml` invokes `chatlogtoeml.cli.apple_db` for Apple DB imports. The Apple DB CLI supports single-db mode (positional infile) and a multi-source mode via repeated `--source` values.
- `conv_to_eml.mimefromconv` loads `converted.css` relative to the module so the CLI can run from any working directory. It prefers local participants for `From:` and aggregates the rest into `To:` (supports group chats).
- `eml_attach.attach` adds the original source file when requested.
- Supporting tools: `adium_convert.sh`, `extras/fix_xml_close.sh`, `extras/failed_inspect.sh`, `extras/reprocess_list.sh`, `extras/emlToMbox.py`, and the `extras/parsers`/`extras/format-html` helpers remain in place.
 - `eml_attach.attach` adds the original source file when requested.
 - New convenience wrapper: `ios_multi_convert.sh` supports multi-source runs with sane `nice`/`ionice`/attachment-pacing defaults and accepts `--address-book` prior to the `--` passthrough. `ios_convert.sh` remains available for single-source directory or DB runs.
 - Supporting tools: `adium_convert.sh`, `extras/fix_xml_close.sh`, `extras/failed_inspect.sh`, `extras/reprocess_list.sh`, `extras/emlToMbox.py`, and the `extras/parsers`/`extras/format-html` helpers remain in place.

## Conventions and gotchas
- Run CLI scripts from the repo root so `bin/chat_convert`/`bin/json_to_eml` can locate `converted.css` via the package import path.
- Conversations must have at least two participants; the parsers add `UNKNOWN` placeholders if needed.
- Account detection relies on Adium directory naming (`Adium Logs/<service>.<local>/<remote>/...`). Facebook IDs are sanitized, and `.chatlog` bundles must contain an inner XML file sharing the base name.
- HTML logs assume `America/New_York`; adjust `chatlogtoeml.parsers.adium_html.localtz` if logs come from other timezones.
- `treeconv.conv_to_eml` strips inline `background-color` styles when `--no-background` is requested.
- `chatlogtoeml.cli.ndjson` adds `X-Chat-Identifier`, `X-Chat-GUID`, `X-iMessage-Service`, `X-Segment-Messages`, and other metadata headers to each generated `.eml`.
- `chatlogtoeml.cli.ndjson` automatically streams large NDJSON files and exposes segmentation options via `--idle-hours`, `--max-days`, and `--max-messages`.
 - `chatlogtoeml.cli.ndjson` automatically streams large NDJSON files and exposes segmentation options via `--idle-hours`, `--max-days`, and `--max-messages`.
 - The Apple DB and NDJSON parsers now coalesce and merge short (below `--min-messages`) segments instead of dropping them; use `--min-messages 1` to keep single-message segments as separate outputs.

## NDJSON / imessage-exporter support
- Parser: `chatlogtoeml.parsers.imessage_json`. It groups records by `chat_identifier`/`chat_guid`, segments by idle gaps/duration/count, normalizes participants, applies reactions as inline HTML or system events, and preserves attachment metadata.
- CLI: `bin/json_to_eml` (`chatlogtoeml.cli.ndjson`):
  - `--local-handle`: supply the local account handle (phone/email) for `From:`; defaults to `"me"`.
  - `--idle-hours`: break segments when the idle gap exceeds the threshold (default 4 hours).
  - `--min-messages`: skip segments with fewer than this many messages (default 2).
  - `--max-messages` / `--max-days`: force splits after reaching a size or duration limit.
  - `--stream`: shard NDJSON to per-chat temporary files to bound memory usage (auto-enabled for files >50MiB). `--stream-tempdir` overrides the temp directory.
  - `--embed-attachments`: attempts to read local attachment payloads and embed them (warns if not accessible).
  - `--no-background`: strips inline background styling from generated HTML.
  - `--clobber`: overwrite existing `.eml` outputs.
  - `--debug`: verbose logging.
- Output files follow `{sanitized_chat_identifier}_{startdate}_{segment_index:04d}.eml`. `X-Converted-By` reports the CLI binary name (`json_to_eml`).
