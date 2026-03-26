# SAMPLE DATA

This directory contains the fixtures and sample inputs that power the
`chatlogtoeml` converters. The structure is organized by ingestion format so you
can quickly find the kind of data you need:

- `adiumxml/` keeps XML-based Adium logs (the `.chatlog` bundle exported from
  Adium or its raw XML equivalents).
- `adiumhtml/` stores an example Adium HTML log for regression testing the old
  HTML parser.
- `ndjson/` holds the small `sample.ndjson` fixture plus a larger
  `ndjson/realworld/klmyers_ipad/` directory with attachments used by the
  streaming NDJSON importer.
- `databases/ios/` and `databases/macos/` contain the synthetic Messages
  database files and their attachments that illustrate how the stub fixtures in
  `tools/generate_*` behave.
- `eml/` keeps a pre-rendered `.eml` output so you can inspect the formatting
  expected by the converters.

See `APPLE_DB_NOTES.md` for additional details about the database fixtures.

**Data Privacy Note:**

Only synthetic or **thoroughly redacted** files should be committed; scrub all
personal information including human names, screennames, account names /
login names, system hostnames, FQDNs, routable IP addresses, etc.

## Test fixtures

### iOS Messages fixture (`sms.db` + attachments)

Generate synthetic database file with:

```bash
python3 tools/generate_ios_smsdb_fixture.py
```

Notes:  
- Uses a fixed base timestamp (2025-01-01 00:00:00 UTC) and 60-second increments.
- Writes:
  - `testdata/ios/sms.db`
  - `testdata/ios/Attachments/00/hello.txt`
  - `testdata/ios/Attachments/00/pixel.png`

### MacOS Messages fixture (`chat.db` + attachments)

Generate synthetic database file with: 

```bash
python3 tools/generate_macos_chatdb_fixture.py
```

Notes:  
- Generates `chat.db` files that are the right *shape* for design/test of importer, but not exact.
- Does not contain actual NeXT-style TypedStream BLOB for `attributedBody`, as a real database would. (UTF-8 placeholder only.)
  - The `attributedBody` is only read when `text` is NULL, so it's a fallback / exception case.
  - May be more common in older versions of iChat?
