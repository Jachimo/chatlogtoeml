#!/usr/bin/env python3
"""Simple NDJSON (imessage-exporter) -> Conversation parser

Notes:
- This implementation is intentionally conservative and easy to read. It builds
  Conversation objects from NDJSON records and performs simple segmentation by
  idle gap. It preserves visible metadata but does not (yet) attach binary
  payloads from attachment paths.
- Improve streaming / memory behavior later (see DEV_PLAN.md).
"""

import json
import logging
from typing import Iterable, List, Optional
import dateutil.parser
import datetime

import conversation


def _parse_date(datestr):
    if not datestr:
        return None
    try:
        return dateutil.parser.parse(datestr)
    except Exception:
        logging.debug(f'unable to parse date: {datestr}')
        return None


def _raw_to_message(obj: dict, local_handle: Optional[str]) -> conversation.Message:
    m = conversation.Message('message')
    m.guid = obj.get('guid', '')
    m.text = obj.get('text') or ''
    m.html = obj.get('html') or ''
    m.date = _parse_date(obj.get('date'))
    # Determine sender
    if obj.get('is_from_me'):
        m.msgfrom = local_handle or 'me'
    else:
        m.msgfrom = obj.get('sender') or obj.get('handle') or 'UNKNOWN'
    return m


def segment_messages(raw_msgs: List[dict], idle_hours: float = 4.0, min_messages: int = 2,
                     max_messages: int = 0, max_days: int = 0) -> Iterable[List[dict]]:
    """Split a list of raw message dicts into segments based on idle gap and limits.

    Yields lists of raw message dicts (sorted by date).
    """
    if not raw_msgs:
        return
    # Parse dates and sort
    parsed = []
    for r in raw_msgs:
        r_dt = _parse_date(r.get('date'))
        if r_dt is None:
            # if no date, push far in the past to keep ordering stable
            r_dt = datetime.datetime.fromtimestamp(0, datetime.timezone.utc)
        parsed.append((r_dt, r))
    parsed.sort(key=lambda x: x[0])

    current = []
    last_dt = None
    for dt, r in parsed:
        if not current:
            current.append((dt, r))
            last_dt = dt
            continue
        gap = (dt - last_dt).total_seconds()
        if idle_hours and gap > idle_hours * 3600:
            # emit current
            if len(current) >= min_messages:
                yield [item[1] for item in current]
            else:
                logging.debug('Skipping short segment of %d messages', len(current))
            current = [(dt, r)]
            last_dt = dt
            continue
        # force split by max_messages
        if max_messages and len(current) >= max_messages:
            if len(current) >= min_messages:
                yield [item[1] for item in current]
            else:
                logging.debug('Skipping short segment (max_messages) of %d messages', len(current))
            current = [(dt, r)]
            last_dt = dt
            continue
        current.append((dt, r))
        last_dt = dt
    # final
    if current and len(current) >= min_messages:
        yield [item[1] for item in current]


def build_conversation_from_segment(segment: List[dict], chat_identifier: str,
                                    origfilename: str, local_handle: Optional[str]) -> conversation.Conversation:
    conv = conversation.Conversation()
    conv.origfilename = origfilename
    conv.imclient = 'iMessage'
    conv.service = 'iMessage'
    conv.filenameuserid = chat_identifier

    # Build participants set
    participants = set()
    for msgobj in segment:
        parts = msgobj.get('participants') or []
        for p in parts:
            participants.add(p)
    # ensure local_handle present if supplied
    if local_handle:
        participants.add(local_handle)
    for p in participants:
        conv.add_participant(p)
    # set local/remote positions based on is_from_me on messages
    if local_handle:
        conv.set_local_account(local_handle)

    # Add messages
    for msgobj in segment:
        m = _raw_to_message(msgobj, local_handle)
        # Add participant for this message
        conv.add_participant(m.msgfrom)
        # Set remote/local flags
        if local_handle and m.msgfrom.lower() == local_handle.lower():
            conv.set_local_account(m.msgfrom)
        else:
            conv.set_remote_account(m.msgfrom)
        # Preserve attachments metadata if present (no binary payload)
        atts = msgobj.get('attachments') or []
        for a in atts:
            att = conversation.Attachment()
            att.name = a.get('filename') or a.get('transfer_name') or a.get('mime_type') or 'attachment'
            att.mimetype = a.get('mime_type') or 'application/octet-stream'
            # payload not read; keep path if available in metadata
            att.data = b''
            att.gen_contentid()
            m.attachments.append(att)
            conv.hasattachments = True
        conv.add_message(m)
    # determine startdate
    if conv.messages:
        conv.startdate = conv.getoldestmessage().date
    return conv


def parse_file(path: str, local_handle: Optional[str] = None,
               idle_hours: float = 4.0, min_messages: int = 2,
               max_messages: int = 0, max_days: int = 0) -> Iterable[conversation.Conversation]:
    """Main entry: parse NDJSON and yield Conversation objects (segmented).

    This implementation groups by chat_identifier in memory; large exports may require a
    streaming / flushing strategy (see DEV_PLAN.md).
    """
    with open(path, 'r') as f:
        chats = {}
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                obj = json.loads(ln)
            except Exception as e:
                logging.warning('Failed to parse NDJSON line: %s', e)
                continue
            chat_id = obj.get('chat_identifier') or obj.get('chat_guid') or 'unknown'
            chats.setdefault(chat_id, []).append(obj)

    for chat_id, msgs in chats.items():
        for segment in segment_messages(msgs, idle_hours=idle_hours, min_messages=min_messages,
                                        max_messages=max_messages, max_days=max_days):
            conv = build_conversation_from_segment(segment, chat_id, path, local_handle)
            yield conv
