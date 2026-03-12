# Copilot Memory

- conv_to_eml loads converted.css at import time; run from the repo root or ensure converted.css is in the working directory so imports succeed.
- Python 3.9+ deps: install with `pip install pytz python-dateutil`.
- No automated tests; sanity-check with the sample logs in `samples/` using `./adiumToEml.py`.
- Bulk conversion helper: `./adium_convert.sh "<log_root>" "<output_dir>"` writes converted_YYYY-MM-DD.log and failed_YYYY-MM-DD.log.
- HTML parser assumes `America/New_York` for filename/timestamps (`adium_html.localtz`); adjust if logs come from other timezones.
