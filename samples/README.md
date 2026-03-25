# Test fixtures

## iOS Messages fixture (`sms.db` + attachments)

Generate deterministic fixtures with:

```bash
python3 tools/generate_ios_smsdb_fixture.py
```

Notes:
- Uses a fixed base timestamp (2025-01-01 00:00:00 UTC) and 60-second increments.
- Writes:
  - `testdata/ios/sms.db`
  - `testdata/ios/Attachments/00/hello.txt`
  - `testdata/ios/Attachments/00/pixel.png`
