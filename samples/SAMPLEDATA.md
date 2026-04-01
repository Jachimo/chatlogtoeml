# SAMPLE DATA

This directory contains the fixtures and sample inputs for testing the
`chatlogtoeml` converters. The directory structure is organized by ingestion format:

- `adiumxml/` - Adium XML-based Adium logs (`.chatlog` or `.xml` files).
- `adiumhtml/` - Adium HTML logs (old style)
- `ndjson/` - "Newline Delimited JSON" (`sample.ndjson`) 
- `macos/` - macOS iMessage `chat.db` and its
  attachments directory (created by `tools/generate_macos_chatdb_fixture.py`)
- `ios/` - iOS iMessage `sms.db` fixture and its
  attachments (created by `tools/generate_ios_smsdb_fixture.py`)
- `eml/` - pre-rendered output `.eml` output (for designing downstream converters, etc.)

See `APPLE_DB_NOTES.md` and `.copilot/db-ingest-plan.md` for additional
implementation notes about the database fixtures and parser.

**Data Privacy Note:**

Only synthetic or **thoroughly redacted** files should be committed; scrub all
personal information including human names, screennames, account names /
login names, system hostnames, FQDNs, routable IP addresses, etc.

## Test fixtures

### iOS Messages fixture (`sms.db` + attachments)

Generate the synthetic database and attachments with:

```bash
python3 tools/generate_ios_smsdb_fixture.py
```

The generator writes:

- `samples/ios/sms.db`
- `samples/ios/Attachments/00/hello.txt`
- `samples/ios/Attachments/00/pixel.png`

Notes:
- Uses a fixed base timestamp (2025-01-01 00:00:00 UTC) and 60-second increments.

### BLOB decode matrix fixtures (typedstream / NSKeyedArchiver)

Generate synthetic fixtures that stress message-body decoding paths:

```bash
python3 tools/generate_blob_case_fixtures.py
```

This writes:

- `samples/blob_cases/ios/sms_blob_cases.db`
- `samples/blob_cases/ios/sms_blob_cases_expected.json`
- `samples/blob_cases/macos/chat_blob_cases.db`
- `samples/blob_cases/macos/chat_blob_cases_expected.json`

The matrix includes:

- `text` column present (should win)
- `text` empty + `attributedBody` streamtyped blob
- `text` empty + `attributedBody` NSKeyedArchiver binary plist
- `text`/`attributedBody` empty/bad + `payload_data` NSKeyedArchiver binary plist
- malformed blobs and fallback ordering checks
- binary plist and XML plist variants
- inline replacement marker (`U+FFFC`) preservation

### MacOS Messages fixture (`chat.db` + attachments)

Generate the synthetic database and attachments with:

```bash
python3 tools/generate_macos_chatdb_fixture.py
```

The generator writes:

- `samples/macos/chat.db`
- `samples/macos/Attachments/00/hello.txt`
- `samples/macos/Attachments/00/pixel.png`

Notes:
- Generates `chat.db` files that are the right *shape* for importer tests but
  are not byte-identical to Apple's DBs.
- The fixture does not include a true NSAttributedString "typedstream" blob for
  `attributedBody` (a UTF-8 placeholder is used). The parser treats
  `attributedBody` as a fallback when `text` is NULL.

## Converting fixtures to EML

Use the `db_to_eml` CLI to convert the DB fixtures to `.eml` files. Examples:

```bash
mkdir -p samples/output/db_to_eml_macos
./bin/db_to_eml samples/macos/chat.db samples/output/db_to_eml_macos --clobber --debug

mkdir -p samples/output/db_to_eml_ios
./bin/db_to_eml samples/ios/sms.db samples/output/db_to_eml_ios --clobber --debug

# Optional contact name enrichment (real-world Address Book DB)
./bin/db_to_eml /path/to/real/sms.db /tmp/ios_real_eml \
  --address-book /path/to/AddressBook.sqlitedb \
  --attachment-root /path/to/real/Attachments \
  --clobber
```

Behavior and attachment resolution:

- The parser reads attachment metadata from the database and attempts to
  resolve the referenced files on disk. If attachments are stored somewhere
  other than relative to the DB, supply `--attachment-root <dir>` to tell the
  parser where to look.
- Attachments are embedded by default. Use `--no-attach` to disable embedding
  and preserve only path metadata. When embedding is not possible, the
  converter will add an `X-Original-Attachment-Path` header to the EML to
  record the source path.
- Use `--address-book` to resolve phone/email handles into real names from
  `AddressBook.sqlitedb`. This also populates the local owner name (when
  `ABStore.MeIdentifier` is available), so `From:` shows a human name instead of
  just `me` or a raw account string.

## Troubleshooting

- Attachments not embedded: confirm the path recorded in the DB exists from the
  repository CWD or pass `--attachment-root` to remap attachment locations.
- Missing or garbled message text: ensure required decoder dependencies are
  installed: `pytypedstream` and `NSKeyedUnArchiver`. These are required by the
  Apple DB parser to decode typedstream and binary plist message-body BLOBs.

## Other fixtures

- `ndjson/sample.ndjson` and `ndjson/realworld/` contain NDJSON exports used
  by `bin/json_to_eml`. Use `./bin/json_to_eml <ndjson> <outdir> [--embed-attachments]` to test NDJSON conversions.
