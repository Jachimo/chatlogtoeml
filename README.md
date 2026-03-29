# chatlogtoeml

Conversion tool to migrate various instant messaging, SMS, and iMessage log exports into RFC822 `.eml` files for archiving. 

Shared logic lives in the `chatlogtoeml` package, with thin CLI wrappers under `bin/`.

## Usage

### `db_to_eml` (Apple iMessage sms.db / chat.db)

```
./bin/db_to_eml path/to/chat.db [outdir] [--local-handle <handle>] [--address-book <AddressBook.sqlitedb>] [--attachment-root <dir>] [--embed-attachments] [--idle-hours N] [--min-messages N] [--max-messages N] [--max-days N] [--no-background] [--clobber] [--debug]
```

Parses Apple Messages SQLite databases (macOS `chat.db` or iOS `sms.db`), resolves attachment metadata and optional payloads, segments conversations by idle gaps/size/duration, and writes per-segment `.eml` files. Use `--attachment-root` to point to a directory containing attachment files when they are not located relative to the DB. Use `--embed-attachments` to include binary payloads in the resulting EML; when embedding is not possible the original path will be recorded (`X-Original-Attachment-Path`).

Optionally, pass `--address-book /path/to/AddressBook.sqlitedb` to translate handles into real contact names. The parser uses `ABPerson` + `ABMultiValue` for contact lookups and `ABStore.MeIdentifier` to identify the DB owner ("me"), so local messages can render with the owner’s real name in `From:` instead of a generic handle.

### `chat_convert` (Adium XML/HTML logs)

```
./bin/chat_convert path/to/log.chatlog [outputdir] [--clobber] [--attach] [--no-background] [--debug]
```

Detects `.chatlog` bundles, `.xml`, `.AdiumHTMLLog`, or `.html`, runs the appropriate parser, and writes a `.eml` file with deterministic `Message-ID`/`References` headers. Use `--attach` to embed the original log, `--clobber` to overwrite, and `--no-background` to strip background styling. The helper script `./adium_convert.sh` calls `bin/chat_convert` when processing directories.

### `json_to_eml` (imessage-exporter NDJSON)

```
./bin/json_to_eml <input.ndjson> <outdir> [--local-handle <handle>] [--idle-hours N] [--min-messages N] [--max-messages N] [--max-days N] [--stream] [--stream-tempdir DIR] [--embed-attachments] [--no-background] [--clobber] [--debug]
```

Groups records by chat identifier, optionally streams per-chat shards for large files, segments conversations by idle gaps/size/duration, and yields individual `.eml` segments enriched with metadata (chat GUID, service, segment indexes, reactions, attachments, etc.). Streaming is auto-enabled for files larger than 50 MiB. Embedded attachments and background stripping are optional.

### Testing

Run the unit test suite with:

```
python3 -m unittest discover -s tests -v
```

## Sample data layout

The `samples/` directory keeps fixtures grouped by ingestion format so you can
run the converter against the right kind of input without hunting through a
heterogeneous blob.

- `samples/adiumxml/` holds XML/.chatlog exports from Adium
- `samples/adiumhtml/` keeps the legacy Adium HTML log snapshot
- `samples/ndjson/` stores the small `sample.ndjson` fixture and the
  `ndjson/` directory with attachments used by the
  streaming NDJSON importer
- `samples/ios/` and `samples/macos/` contain the synthetic SQLite Messages
  database fixtures plus their attachments
- `samples/blob_cases/` contains focused BLOB decode matrix fixtures for
  typedstream and NSKeyedArchiver payload testing
- `samples/eml/` shows what a rendered `.eml` should look like

The companion `samples/SAMPLEDATA.md` describes the layout, privacy policy,
and generator scripts in more detail.

## Dependencies

Install runtime dependencies with:

```bash
pip install pytz python-dateutil pytypedstream NSKeyedUnArchiver
```

`db_to_eml` requires both blob decoders (`pytypedstream` and `NSKeyedUnArchiver`) for MVP-quality parsing of `attributedBody` and `payload_data`.

## Known Bugs / Limitations

### Incomplete Adium Facebook Chat Logs

Adium logs from the Facebook XMPP era are sometimes malformed, contain only one side of the conversation, or omit participants. The XML parser attempts to link Facebook IDs to aliases but cannot always succeed.

### Malformed Adium XML Logs

Some logs contain missing closing tags. Use `extras/adium/fix_xml_close.sh` (which operates on the `failed_YYYY-MM-DD.log` files emitted by the bulk converter) to patch `</chat>` tags before rerunning.

#### Illegal XML Characters

Adium sometimes wrote unescaped ASCII control characters. The XML parser sanitizes input by stripping problematic ranges when `xml.dom.minidom` fails.

### Bad Log File Names

Files with non-ASCII or odd separators in their filenames may break parsing. Rename them to use dashes before converting.

### Trivial Logs

Logs without any human-generated content are skipped; they could be processed into a different format in future versions.

## References

- `extras/adium/format-html` contains original Adium transformation helpers.
- `extras/adium/emlToMbox.py` merges a directory of `.eml` files into a single `.mbox` for import into Apple Mail or other MUAs.
- Bulk conversion helper: `./adium_convert.sh`.
- Run all `bin/` scripts from the repository root so `converted.css` is found relative to the package.
