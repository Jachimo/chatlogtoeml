# Copilot Instructions for chatlogtoeml

## Build / Run / Test
- Requires Python ≥3.9 with dependencies installed: `pip install pytz python-dateutil`.
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
- Run converters from the repo root (or ensure `converted.css` is in the working directory) because `conv_to_eml` reads the stylesheet at import time.
- Keep `Conversation` objects populated with dates and at least two participants; `mimefromconv` raises `ValueError` when conversations are empty or under-populated.
- Account detection relies on Adium directory naming (`Adium Logs/<service>.<local>/<remote>/...`); paths or Facebook IDs are lowercased when parsed, and `.chatlog` bundles must contain an inner XML file sharing the base name.
- The HTML parser assumes logs were created in `America/New_York` and uses filename timestamps for the conversation start; adjust `adium_html.localtz` if converting logs from another timezone.
- Background-color stripping (`--no-background`) removes inline CSS via regex; attachments require `Attachment.data` to be set so `conv_to_eml` can encode and attach them.

## Developing new format support (e.g., NDJSON -> .eml)
- Add a parser that returns a populated `conversation.Conversation`:
  - Set `imclient`, `service`, `origfilename`, and `filenameuserid` (if derivable from the file name).
  - Populate `participants` with `localaccount` and `remoteaccount`, marking positions via `set_local_account`/`set_remote_account`; pad with `UNKNOWN` if fewer than two.
  - Messages must include timezone-aware `date`, `msgfrom`, `text` and/or `html`; keep ordering stable so the deterministic Message-ID/References hashes remain consistent.
  - For attachments, create `Attachment` objects, call `set_payload` (to assign `contentid`), and append to each message’s `attachments`.
  - Set `startdate` (use file metadata or the first message) so `conv_to_eml` can build Date/Subject headers; if absent, it falls back to the oldest message.
- Wire the parser into `adiumToEml.py`: extend the extension allowlist and branch to your parser, mirroring the existing XML/HTML selection; honor `--no-background`, `--attach`, and `--clobber`.
- Keep `converted.css` available or adjust loader logic if you move it; HTML styling relies on it.
- Add a small sample input to `samples/` plus expected output to validate regressions; sanity-check with `./adiumToEml.py sample.ndjson ./out --debug`.
- Use extras for workflows: `extras/reprocess_list.sh` to retry a list, `extras/failed_inspect.sh` to copy and summarize failures, `extras/fix_xml_close.sh` for malformed XML, and `extras/emlToMbox.py` to merge outputs for manual review.
