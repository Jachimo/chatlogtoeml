# Copilot Memory

- Requires Python 3.9+ and runtime dependencies `pytz` and `python-dateutil`.
- `chatlogtoeml.conv_to_eml` now loads `converted.css` relative to its module path, so you can run CLI wrappers from any directory.
- Use `./bin/chat_convert` for Adium/XML/HTML logs and `./bin/json_to_eml` for NDJSON exports.
 - `chatlogtoeml.conv_to_eml` now loads `converted.css` relative to its module path, so you can run CLI wrappers from any directory.
 - Use `./bin/chat_convert` for Adium/XML/HTML logs, `./bin/json_to_eml` for NDJSON exports, and `./bin/db_to_eml` for Apple Messages SQLite DB imports (`sms.db` / `chat.db`). `db_to_eml` supports multi-source mode via repeated `--source` arguments.
- Bulk conversion helper: `./adium_convert.sh "<log_root>" "<output_dir>"`.
- Run tests with `python3 -m unittest discover -v`.
 - Run tests with `python3 -m unittest discover -v`.
 - Wrappers: use `./ios_convert.sh` for single-source runs and the new `./ios_multi_convert.sh` for multi-source runs; both accept env knobs for `NICE_LEVEL`, `USE_IONICE`, `IONICE_CLASS`, `IONICE_LEVEL`, `ATTACH_READ_PAUSE_MS`, and `ATTACH_READ_PAUSE_EVERY` to throttle CPU and I/O.
