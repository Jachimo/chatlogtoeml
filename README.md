# chatlogtoeml

Conversion tool to migrate various instant messaging, SMS, and iMessage log exports into RFC822 `.eml` files for archiving. 


## Usage

There are several utilities you can call from the CLI depending on the source format you're converting.


### `db_to_eml` (Apple iMessage sms.db / chat.db)

```bash
./bin/db_to_eml path/to/chat.db [outdir] [--local-handle <handle>] [--address-book <AddressBook.sqlitedb>] [--attachment-root <dir>] [--no-attach] [--idle-hours N] [--min-messages N] [--max-messages N] [--max-days N] [--no-background] [--clobber] [--debug]
```

Parses Apple Messages SQLite databases (macOS `chat.db` or iOS `sms.db`), resolves attachment metadata and payloads by default, segments conversations by idle gaps/size/duration, and writes per-segment `.eml` files. 

Pass `--address-book /path/to/AddressBook.sqlitedb` to translate handles (phone numbers, in most cases) into real contact names. The parser uses `ABPerson` + `ABMultiValue` for contact lookups and `ABStore.MeIdentifier` to identify the DB owner ("me"), so local messages can render with the owner’s real name in `From:` instead of a generic handle.

Use `--attachment-root` to point to a directory containing attachment files when they are not located alongside the DB. 

Use `--no-attach` to skip embedding binary payloads; in this mode, the original path will be recorded in the message headers(`X-Original-Attachment-Path`).

Existing output files are overwritten by default for idempotency; `--clobber` is allowed without throwing an error, purely for backward compatibility.

**Note: Short-Segment Preservation**

By default, the parser splits messages into segments based on idle gaps, maximum
segment size, and maximum segment duration. To avoid silently dropping short
conversations (for example, single-message segments), the converter "coalesces" 
runs of short segments and merges remaining short segments into an adjacent 
neighbor (preferring the previous segment). If no neighbor exists the
short segment is preserved and emitted. Use `--min-messages` to control the
minimum desired segment size (default `2`) or `--idle-hours` to increase the
idle gap threshold so messages are more likely to be grouped together.


#### `ios_convert.sh` Wrapper Script

For a convenience wrapper script (similar in style to the old the Adium wrapper), which runs conversion with lowered CPU and I/O priority, use `./ios_convert.sh <sms_root_or_db> <outdir> [AddressBook.sqlitedb] [-- <extra db_to_eml args>]`.

The I/O priority in particular is intended to improve performance (read: not crash) low-end NFS servers / NAS heads, after it was observed in testing that Buffalo TeraStation devices in particular seemed to reliably crash when subjected to large amounts of small-file I/O. The wrapper enables conservative attachment-read pacing by default (`ATTACH_READ_PAUSE_MS=15`, `ATTACH_READ_PAUSE_EVERY=1`). Override with environment variables, for example: `ATTACH_READ_PAUSE_MS=0` to disable pacing, `USE_IONICE=0` to skip `ionice`, or `NICE_LEVEL=15` to lower CPU priority further.

Example of wrapper with some cheap-NAS throttling:

```bash
NICE_LEVEL=15 \
USE_IONICE=1 \
IONICE_CLASS=3 \
ATTACH_READ_PAUSE_MS=40 \
ATTACH_READ_PAUSE_EVERY=1 \
./ios_convert.sh \
"/path/to/Library/SMS/sms.db" \
"/path/to/output_eml" \
"/path/to/AddressBook.sqlitedb" \
-- --clobber
```

Recommended network-share profiles (starting points):

- NFS: `NICE_LEVEL=15 IONICE_CLASS=3 ATTACH_READ_PAUSE_MS=40 ATTACH_READ_PAUSE_EVERY=1`
- SMB: `NICE_LEVEL=15 IONICE_CLASS=3 ATTACH_READ_PAUSE_MS=60 ATTACH_READ_PAUSE_EVERY=1`

SMB often benefits from slightly slower pacing due to metadata/open-close overhead.
If unstable, increase `ATTACH_READ_PAUSE_MS` in +20ms steps.


### `chat_convert` (Adium XML/HTML logs)

```bash
./bin/chat_convert path/to/log.chatlog [outputdir] [--clobber] [--attach] [--no-background] [--debug]
```

Accepts `.chatlog`, `.xml`, `.AdiumHTMLLog`, or `.html`, runs the appropriate parser, and writes a `.eml` file with deterministic `Message-ID`/`References` headers. Use `--attach` to embed the original log, `--clobber` to overwrite, and `--no-background` to strip background styling. 


#### `adium_convert.sh` Wrapper Script

The helper script `./adium_convert.sh` calls `bin/chat_convert` when processing directories.


### `json_to_eml` (imessage-exporter NDJSON)

```
./bin/json_to_eml <input.ndjson> <outdir> [--local-handle <handle>] [--idle-hours N] [--min-messages N] [--max-messages N] [--max-days N] [--stream] [--stream-tempdir DIR] [--no-attach] [--no-background] [--clobber] [--debug]
```

Groups records by chat identifier, optionally streams per-chat shards for large files, segments conversations by idle gaps/size/duration, and yields individual `.eml` segments enriched with metadata (chat GUID, service, segment indexes, reactions, attachments, etc.). Streaming is auto-enabled for files larger than 50 MiB. Attachment payloads are embedded by default; use `--no-attach` to disable embedding. Background stripping remains optional.
Existing output files are overwritten by default (idempotent reruns); `--clobber` is accepted for backward compatibility.


## Testing

Run the unit test suite with:

```bash
uv run python -m unittest discover -s tests -v
```

Or, without uv:

```
python3 -m unittest discover -s tests -v
```

## Sample Data

The `samples/` directory contains test fixtures, grouped by ingestion format, so you can
run the converter against the right kind of input:

- `samples/adiumxml/` - XML/.chatlog exports from Adium
- `samples/adiumhtml/` - legacy Adium HTML log snapshot
- `samples/ndjson/` - contains a small `sample.ndjson` and the
  `ndjson/` directory with attachments; used by the streaming NDJSON importer
- `samples/ios/` and `samples/macos/` - contain synthetic SQLite database fixtures,
  plus attachments
- `samples/blob_cases/` contains focused BLOB decode matrix fixtures for
  typedstream and NSKeyedArchiver payload testing
- `samples/eml/` shows what a rendered `.eml` should look like (does not contain all features)

The companion `samples/SAMPLEDATA.md` describes the data and generator scripts in more detail.

## Dependencies

Preferred: use uv for environment isolation and dependency management.

```bash
uv sync
```

Then run CLIs/tests in the managed environment:

```bash
uv run db_to_eml --help
uv run json_to_eml --help
uv run chat_convert --help
uv run python -m unittest discover -s tests -v
```

## Known Bugs / Limitations

### Incomplete Adium Facebook Chat Logs

Adium logs from the Facebook XMPP era are sometimes malformed, contain only one side of the conversation, or omit participants. The XML parser attempts to link Facebook IDs to aliases but cannot always succeed.

### Malformed Adium XML Logs

Some logs contain missing closing tags. Use `extras/adium/fix_xml_close.sh` (which operates on the `failed_YYYY-MM-DD.log` files emitted by the bulk converter) to patch `</chat>` tags before rerunning.

#### Illegal XML Characters

Adium sometimes wrote unescaped ASCII control characters. The XML parser sanitizes input by stripping problematic ranges when `xml.dom.minidom` fails.

### Bad Log File Names

Files with non-ASCII or odd separators in their filenames may break parsing. Rename them to use dashes before converting.

### Trivial (Zero Message) Logs

Logs without any human-generated content are skipped; they could be processed into a different format in future versions.

### Multi-Source Ingest Loads All Attachment Payloads Into Memory

When using `--source` (multi-DB ingest), `multidb_ingest.ingest_sources()` calls `parse_file(..., stream=False)` for each source database. This means all parsed attachment binary payloads from all DBs are held in memory simultaneously while the message-level deduplification pass runs. For a large collection (e.g. several years of photo attachments across 5 devices), this can require several gigabytes of RAM.

**Mitigation:** if embedded attachments are not needed, pass `--no-attach` to skip embedding attachment payloads (path metadata is still preserved in the output EML via `X-Original-Attachment-Path` headers)

A streaming redesign — where attachment data is written to disk and only referenced during MIME assembly — would be required to lift this constraint without `--no-attach`. This is deferred to a later release.

## Strays

- `extras/adium/format-html` contains original Adium transformation helpers.
- `extras/emlToMbox.py` merges a directory of `.eml` files into a single `.mbox` for import into Apple Mail or other MUAs.
- Bulk conversion helper: `./adium_convert.sh`.
- Run all `bin/` scripts from the repository root so `converted.css` is found relative to the package.
