# SAMPLE DATA

This directory contains sample data for testing the "chatlogtoeml"
tools.

It contains subfolders by ingestion format, e.g. "adium" for Adium
format log files, "ndjson" for Newline Delimited JSON files, etc.

**Data Privacy Note:**

Only synthetic or **thoroughly redacted** files should be committed; scrub all
personal information including human names, screennames, account names
/ login names, system hostnames, FQDNs, routable IP addresses, etc.

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
