# SAMPLE DATA

This directory contains the fixtures and sample inputs that power the
`chatlogtoeml` converters. The structure is organized by ingestion format so you
can quickly find the kind of data you need:

- `adiumxml/` keeps XML-based Adium logs (the `.chatlog` bundle exported from
  Adium or its raw XML equivalents).
- `adiumhtml/` stores an example Adium HTML log for regression testing the old
  HTML parser.
- `ndjson/` holds the small `sample.ndjson` fixture plus the
  `ndjson/realworld/klmyers_ipad/` directory with attachments used by the
  streaming NDJSON importer.
- `samples/macos/` contains the synthetic macOS `chat.db` fixture and its
  attachments (created by `tools/generate_macos_chatdb_fixture.py`).
- `testdata/ios/` contains the synthetic iOS `sms.db` fixture and its
  attachments (created by `tools/generate_ios_smsdb_fixture.py`).
- `eml/` keeps a pre-rendered `.eml` output so you can inspect the formatting
  expected by the converters.

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

- `testdata/ios/sms.db`
- `testdata/ios/Attachments/00/hello.txt`
- `testdata/ios/Attachments/00/pixel.png`

Notes:
- Uses a fixed base timestamp (2025-01-01 00:00:00 UTC) and 60-second increments.

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
./bin/db_to_eml samples/macos/chat.db samples/output/db_to_eml_macos --embed-attachments --clobber --debug

mkdir -p samples/output/db_to_eml_ios
./bin/db_to_eml testdata/ios/sms.db samples/output/db_to_eml_ios --embed-attachments --clobber --debug
```

Behavior and attachment resolution:

- The parser reads attachment metadata from the database and attempts to
  resolve the referenced files on disk. If attachments are stored somewhere
  other than relative to the DB, supply `--attachment-root <dir>` to tell the
  parser where to look.
- Use `--embed-attachments` to include binary payloads in the resulting EMLs.
  When embedding is not possible, the converter will add an `X-Original-Attachment-Path`
  header to the EML to record the source path.

## Troubleshooting

- Attachments not embedded: confirm the path recorded in the DB exists from the
  repository CWD or pass `--attachment-root` to remap attachment locations.
- Missing or garbled message text: many real DBs store rich `attributedBody`
  typedstream blobs. Typedstream parsing is not implemented yet — expected
  fallbacks are provided but may lose formatting or embedded inline objects.

## Other fixtures

- `ndjson/sample.ndjson` and `ndjson/realworld/` contain NDJSON exports used
  by `bin/json_to_eml`. Use `./bin/json_to_eml <ndjson> <outdir> [--embed-attachments]` to test NDJSON conversions.

---

If you need additional sanitized fixtures or want to expand test coverage for
edge cases (reactions, replies, various timestamp encodings), add generator
scripts under `tools/` and document them here.
