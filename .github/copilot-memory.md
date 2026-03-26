# Copilot Memory

- Requires Python 3.9+ and runtime dependencies `pytz` and `python-dateutil`.
- `chatlogtoeml.conv_to_eml` now loads `converted.css` relative to its module path, so you can run CLI wrappers from any directory.
- Use `./bin/chat_convert` for Adium/XML/HTML logs and `./bin/json_to_eml` for NDJSON exports.
- Bulk conversion helper: `./adium_convert.sh "<log_root>" "<output_dir>"`.
- Run tests with `python3 -m unittest discover -v`.
