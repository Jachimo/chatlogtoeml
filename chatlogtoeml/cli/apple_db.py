"""CLI for parsing Apple Messages sqlite DBs (sms.db / chat.db) and emitting EMLs."""

import argparse
import logging
import os
import sys

from .. import conv_to_eml
from .common import make_out_filename
from ..parsers import apple_db


def _converted_by_name(argv0: str = None) -> str:
    raw = argv0 if argv0 is not None else (sys.argv[0] if sys.argv else '')
    name = os.path.basename(raw or '').strip()
    if not name or name in ('-', '-c') or name.lower().startswith('python'):
        return 'db_to_eml'
    return name


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    parser = argparse.ArgumentParser(description='Convert Apple sms.db/chat.db to .eml files')
    parser.add_argument('infile', help='Input sqlite DB file (chat.db or sms.db)')
    parser.add_argument('outdir', nargs='?', default=os.getcwd(), help='Output directory (defaults to cwd)')
    parser.add_argument('--local-handle', help='Local account handle (phone/email) to use for From:', default=None)
    parser.add_argument('--address-book', help='Optional path to AddressBook.sqlitedb for participant real-name resolution', default=None)
    parser.add_argument('--attachment-root', help='Override root for attachment paths (for backups)', default=None)
    parser.add_argument('--idle-hours', type=float, default=8.0, help='Idle gap hours to segment conversations')
    parser.add_argument('--min-messages', type=int, default=2, help='Minimum messages to keep a segment')
    parser.add_argument('--max-messages', type=int, default=0, help='Force split at this many messages (0=unlimited)')
    parser.add_argument('--max-days', type=int, default=0, help='Force split if segment spans more than N days (0=unlimited)')
    parser.set_defaults(embed_attachments=True)
    parser.add_argument('--embed-attachments', dest='embed_attachments', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--no-attach', dest='embed_attachments', action='store_false', help='Do not embed attachment payloads in EML; keep path metadata only')
    parser.add_argument('--no-background', action='store_true', help='Strip background style from HTML')
    parser.set_defaults(clobber=True)
    parser.add_argument('--clobber', action='store_true', help='Overwrite existing .eml files')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    infile = args.infile
    outdir = args.outdir
    if not os.path.isfile(infile):
        logging.critical('Input DB not found: %s', infile)
        return 1
    if not os.path.isdir(outdir):
        logging.critical('Output dir (%s) specified but not a directory.', outdir)
        return 1

    idx_counters = {}
    for conv in apple_db.parse_file(
        infile,
        local_handle=args.local_handle,
        addressbook_path=args.address_book,
        idle_hours=args.idle_hours,
        min_messages=args.min_messages,
        max_messages=args.max_messages,
        max_days=args.max_days,
        stream=False,
        embed_attachments=args.embed_attachments,
        attachment_root=args.attachment_root,
    ):
        chat_id = conv.filenameuserid or conv.origfilename or 'chat'
        startdate = conv.startdate
        if not startdate:
            try:
                startdate = conv.getoldestmessage().date
            except Exception:
                startdate = None
        idx = idx_counters.get(chat_id, 0)
        outname = make_out_filename(chat_id, startdate or '', idx)
        outpath = os.path.join(outdir, outname)
        if os.path.exists(outpath) and not args.clobber:
            logging.warning('Skipping existing file %s (use --clobber to overwrite)', outpath)
            idx_counters[chat_id] = idx + 1
            continue
        try:
            eml = conv_to_eml.mimefromconv(conv, args.no_background)
        except Exception as e:
            logging.error('Failed to create MIME for chat %s: %s', chat_id, e)
            idx_counters[chat_id] = idx + 1
            continue

        if conv.filenameuserid:
            eml['X-Chat-Identifier'] = conv.filenameuserid
        if getattr(conv, 'chat_guid', None):
            eml['X-Chat-GUID'] = conv.chat_guid
        if hasattr(conv, 'startdate') and conv.startdate:
            eml['X-Segment-Start'] = conv.startdate.isoformat()
        if conv.messages:
            eml['X-Segment-Messages'] = str(len(conv.messages))
        imsvc = getattr(conv, 'service', None)
        if imsvc:
            eml['X-iMessage-Service'] = imsvc
        eml['X-Converted-By'] = _converted_by_name()

        try:
            with open(outpath, 'w') as fo:
                fo.write(eml.as_string())
            logging.info('Wrote %s', outpath)
        except Exception as e:
            logging.error('Failed to write %s: %s', outpath, e)
        idx_counters[chat_id] = idx + 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
