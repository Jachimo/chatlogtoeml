# Copilot Instructions for chatlogtoeml

## Build / Run / Test
- Requires Python >=3.9 with dependencies installed: `pip install pytz python-dateutil`.
- Convert a single log: `./adiumToEml.py path/to/log.chatlog [output_dir] [--clobber] [--attach] [--no-background] [--debug]` (works with .chatlog bundles, .xml, .AdiumHTMLLog, .html).
- Bulk convert a tree: `./adium_convert.sh "<log_root>" "<output_dir>"` (writes converted_YYYY-MM-DD.log and failed_YYYY-MM-DD.log).
- Merge .eml outputs into an mbox: `python extras/emlToMbox.py <eml_dir> <output.mbox>`.
- No automated tests or linters are defined; sanity-check by running the converter against the sample logs in `samples/`.

## Architecture overview
- `adiumToEml.py` is the CLI entrypoint: validates inputs/outputs, unwraps `.chatlog` bundles to their inner XML, picks the XML or HTML parser, optionally attaches the source log, and writes the resulting `.eml` with `X-Converted` headers.
- Parsers return a `Conversation` object (`conversation.py`): `adium_xml.toconv` handles XML/.chatlog (infers service/local/remote from Adium path layout, strips Facebook `@chat.facebook.com` IDs, records aliases); `adium_html.toconv` handles old HTML logs (derives date from filename + first timestamp, assumes timezone `America/New_York`, infers accounts from parent folders).
- `conversation.py` defines the data model (`Conversation`/`Participant`/`Message`/`Attachment`); messages are sortable by date, participants can be marked local/remote, and missing participants are padded with `UNKNOWN` to avoid converter errors.
- `conv_to_eml.mimefromconv` converts a Conversation to multipart/related email: loads `converted.css` at import time, builds text and HTML parts, strips background-color when `--no-background` is set, attaches message attachments, and creates deterministic `References`/`Message-ID` headers; `eml_attach.attach` adds the source log when requested.
- Supporting tools: `adium_convert.sh` wraps bulk conversion with `find` and writes success/failure logs; `extras/fix_xml_close.sh` repairs malformed chatlogs; `extras/failed_inspect.sh` and `extras/reprocess_list.sh` help review failures; `extras/emlToMbox.py` joins `.eml` outputs; `extras/parsers` and `extras/format-html` contain reference parsers/stylesheets.

## Conventions and gotchas
- Run converters from the repo root (or ensure `converted.css` is in the working directory) because `conv_to_eml` reads the stylesheet at import time with a bare `open()`. This is a known issue; the fix (use `os.path.dirname(__file__)`) is documented in `DEV_PLAN.md` and must be applied before implementing the NDJSON feature.
- Keep `Conversation` objects populated with dates and at least two participants; `mimefromconv` raises `ValueError` when conversations are empty or under-populated.
- Account detection relies on Adium directory naming (`Adium Logs/<service>.<local>/<remote>/...`); paths or Facebook IDs are lowercased when parsed, and `.chatlog` bundles must contain an inner XML file sharing the base name.
- The HTML parser assumes logs were created in `America/New_York` and uses filename timestamps for the conversation start; adjust `adium_html.localtz` if converting logs from another timezone.
- Background-color stripping (`--no-background`) removes inline CSS via regex; attachments require `Attachment.data` to be set so `conv_to_eml` can encode and attach them.
- `conv_to_eml.mimefromconv(conv, args)` currently takes a raw argparse Namespace. This is being refactored to `mimefromconv(conv, no_background=False)` as part of the NDJSON work; see `DEV_PLAN.md`.

## Developing new format support (NDJSON / imessage-exporter)

The detailed plan is in `DEV_PLAN.md`. Summary of key points:

- New format gets its own entrypoint `jsonToEml.py` and parser `imessage_json.py`; do **not** modify `adiumToEml.py` except to update the `mimefromconv` call site.
- **Before writing new code**, apply two required refactors to `conv_to_eml.py`:
  1. Fix CSS loading to use `os.path.dirname(__file__)` instead of bare `open('converted.css')`.
  2. Change `mimefromconv(conv, args)` to `mimefromconv(conv, no_background=False)` and update the one call site in `adiumToEml.py`.
- Group iMessage NDJSON by `chat_identifier` first, then segment by idle gap / message count / duration thresholds.
- Supply `--local-handle` to identify the local account (maps to `From:`). Default to `"me"` if omitted.
- Group chats: `From:` = local account, `To:` = all remote participants comma-separated.
- Reactions/tapbacks: correlate by `associated_message_guid` and render as footnotes under the target message; never as top-level thread entries.
- Output naming: `{sanitized_chat_id}_{date}_{index:04d}.eml`.
- `--attach` is explicitly not supported for NDJSON (files are too large).
- Add a synthetic NDJSON fixture to `samples/` and confirm legacy `adiumToEml.py` conversions still work after refactoring.
- Use `with` context managers for all file I/O in new code.
