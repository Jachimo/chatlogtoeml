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
import os
import tempfile
import hashlib
import html as _html

import conversation


# Reaction rendering utilities
_REACTION_EMOJI = {
    'like': '👍', 'love': '❤️', 'laugh': '😂', 'haha': '😂',
    'dislike': '👎', 'emphasize': '❗', 'question': '❓',
    'heart': '❤️', 'thumbs_up': '👍', 'thumbs_down': '👎'
}


def _group_reactions(reaction_list):
    grouped = {}
    for r in reaction_list:
        rtype = (r.get('reaction_type') or r.get('reaction') or 'reacted')
        if rtype is None:
            rtype = 'reacted'
        rkey = rtype.lower()
        actor = _norm_user(r.get('actor') or r.get('sender') or r.get('handle')) or 'UNKNOWN'
        grouped.setdefault(rkey, []).append(actor)
    return grouped


def _render_reactions_html(reaction_list):
    grouped = _group_reactions(reaction_list)
    parts = []
    for rtype, actors in grouped.items():
        emoji = _REACTION_EMOJI.get(rtype)
        title = _html.escape(', '.join(actors))
        if emoji:
            if len(actors) > 1:
                parts.append(f'<span class="reaction" title="{title}">{emoji}×{len(actors)}</span>')
            else:
                parts.append(f'<span class="reaction" title="{title}">{emoji}</span>')
        else:
            lbl = _html.escape(rtype)
            if len(actors) > 1:
                parts.append(f'<span class="reaction" title="{title}">{lbl}×{len(actors)}</span>')
            else:
                parts.append(f'<span class="reaction" title="{title}">{lbl}</span>')
    if parts:
        return '<div class="reactions">' + ' '.join(parts) + '</div>'
    return ''


def _render_reactions_text(reaction_list):
    grouped = _group_reactions(reaction_list)
    parts = []
    for rtype, actors in grouped.items():
        emoji = _REACTION_EMOJI.get(rtype)
        if emoji:
            if len(actors) > 1:
                parts.append(f'{emoji}×{len(actors)} ({",".join(actors)})')
            else:
                parts.append(f'{emoji} ({actors[0]})')
        else:
            if len(actors) > 1:
                parts.append(f'{rtype}×{len(actors)} ({",".join(actors)})')
            else:
                parts.append(f'{rtype} ({actors[0]})')
    return ' | '.join(parts) if parts else ''


def _parse_date(datestr):
    if not datestr:
        return None
    try:
        dt = dateutil.parser.parse(datestr)
        # Ensure timezone-aware datetimes for consistent arithmetic
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except Exception:
        logging.debug(f'unable to parse date: {datestr}')
        return None


def _norm_user(u):
    """Normalize a user identifier into a simple string.

    Accepts strings or dicts commonly emitted by imessage-exporter and
    returns a representative string or None.
    """
    if not u:
        return None
    if isinstance(u, dict):
        # common keys to try
        for k in ('id', 'identifier', 'handle', 'address', 'username', 'phone', 'value'):
            v = u.get(k)
            if v:
                return str(v)
        # fallback to first non-empty value
        for v in u.values():
            if v:
                return str(v)
        return None
    return str(u)


def _raw_to_message(obj: dict, local_handle: Optional[str]) -> conversation.Message:
    m = conversation.Message('message')
    m.guid = obj.get('guid', '')
    m.text = obj.get('text') or ''
    m.html = obj.get('html') or ''
    # ensure messages have a deterministic fallback date (epoch UTC) when unparseable
    m.date = _parse_date(obj.get('date')) or datetime.datetime.fromtimestamp(0, datetime.timezone.utc)
    # Determine sender
    if obj.get('is_from_me'):
        m.msgfrom = local_handle or 'me'
    else:
        m.msgfrom = _norm_user(obj.get('sender') or obj.get('handle')) or 'UNKNOWN'
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
    start_dt = None
    for dt, r in parsed:
        if not current:
            current.append((dt, r))
            last_dt = dt
            start_dt = dt
            continue
        gap = (dt - last_dt).total_seconds()
        # split on idle gap
        if idle_hours and gap > idle_hours * 3600:
            if len(current) >= min_messages:
                yield [item[1] for item in current]
            else:
                logging.debug('Skipping short segment of %d messages', len(current))
            current = [(dt, r)]
            last_dt = dt
            start_dt = dt
            continue
        # split on max_days
        if max_days and start_dt and (dt - start_dt).total_seconds() > max_days * 86400:
            if len(current) >= min_messages:
                yield [item[1] for item in current]
            else:
                logging.debug('Skipping short segment (max_days) of %d messages', len(current))
            current = [(dt, r)]
            last_dt = dt
            start_dt = dt
            continue
        # force split by max_messages
        if max_messages and len(current) >= max_messages:
            if len(current) >= min_messages:
                yield [item[1] for item in current]
            else:
                logging.debug('Skipping short segment (max_messages) of %d messages', len(current))
            current = [(dt, r)]
            last_dt = dt
            start_dt = dt
            continue
        current.append((dt, r))
        last_dt = dt
    # final
    if current and len(current) >= min_messages:
        yield [item[1] for item in current]


def build_conversation_from_segment(segment: List[dict], chat_identifier: str,
                                    origfilename: str, local_handle: Optional[str],
                                    embed_attachments: bool = False) -> conversation.Conversation:
    conv = conversation.Conversation()
    conv.origfilename = origfilename
    conv.imclient = 'iMessage'
    conv.service = 'iMessage'
    conv.filenameuserid = chat_identifier

    # Build participants set (normalize dict entries into string userids)
    participants = set()
    for msgobj in segment:
        parts = msgobj.get('participants') or []
        for p in parts:
            # normalize participant entries to string ids
            if isinstance(p, dict):
                pid = None
                for k in ('id', 'identifier', 'handle', 'address', 'username', 'phone', 'value'):
                    v = p.get(k)
                    if v:
                        pid = str(v)
                        break
                if not pid:
                    # fallback to first non-empty value
                    for v in p.values():
                        if v:
                            pid = str(v)
                            break
                if pid:
                    participants.add(pid)
            elif p:
                participants.add(str(p))
    # ensure local_handle present if supplied
    if local_handle:
        participants.add(local_handle)
    for p in participants:
        conv.add_participant(p)
    # set local/remote positions based on is_from_me on messages
    if local_handle:
        conv.set_local_account(local_handle)

    # Two-pass: build messages and collect reactions
    messages_by_guid = {}
    reactions = {}  # target_guid -> list of reaction dicts

    for msgobj in segment:
        assoc = msgobj.get('associated_message_guid')
        rtype = msgobj.get('reaction_type') or msgobj.get('reaction')
        # If this looks like a reaction (no text or explicit reaction_type), collect it
        if rtype or (assoc and not msgobj.get('text')):
            if assoc:
                reactions.setdefault(assoc, []).append(msgobj)
            else:
                reactions.setdefault(None, []).append(msgobj)
            continue
        # Normal message
        m = _raw_to_message(msgobj, local_handle)
        # Preserve attachments metadata; include payload if local path available
        atts = msgobj.get('attachments') or []
        for a in atts:
            att = conversation.Attachment()
            att.name = a.get('filename') or a.get('transfer_name') or a.get('mime_type') or 'attachment'
            att.mimetype = a.get('mime_type') or 'application/octet-stream'
            path = a.get('path')
            if embed_attachments and path and os.path.isfile(path):
                try:
                    with open(path, 'rb') as af:
                        att.data = af.read()
                except Exception:
                    att.data = b''
            else:
                att.data = b''
            att.gen_contentid()
            m.attachments.append(att)
            conv.hasattachments = True
        # Add participant for this message and set roles
        conv.add_participant(m.msgfrom)
        if local_handle and m.msgfrom.lower() == (local_handle or '').lower():
            conv.set_local_account(m.msgfrom)
        else:
            conv.set_remote_account(m.msgfrom)
        conv.add_message(m)
        if m.guid:
            messages_by_guid[m.guid] = m

    # Process reactions: attach as richer inline HTML to target messages when possible
    for target_guid, reaction_list in reactions.items():
        if target_guid is None:
            # Unknown-target reactions -> render as events
            for r in reaction_list:
                actor = _norm_user(r.get('actor') or r.get('sender') or r.get('handle')) or 'UNKNOWN'
                rtype = r.get('reaction_type') or r.get('reaction') or 'reacted'
                ev = conversation.Message('event')
                ev.msgfrom = 'System Message'
                ev.date = _parse_date(r.get('date')) or datetime.datetime.now(datetime.timezone.utc)
                ev.text = f'{actor} {rtype} a message (unknown target)'
                conv.add_message(ev)
            continue
        target_msg = messages_by_guid.get(target_guid)
        if target_msg:
            html_frag = _render_reactions_html(reaction_list)
            text_frag = _render_reactions_text(reaction_list)
            if html_frag:
                if target_msg.html:
                    target_msg.html += html_frag
                else:
                    # ensure there is an html field so conv_to_eml can render reactions inline
                    escaped = _html.escape(target_msg.text) if target_msg.text else ''
                    target_msg.html = escaped + html_frag
                    if not target_msg.text:
                        target_msg.text = ''
            else:
                # append textual representation
                if target_msg.text:
                    target_msg.text += '\n' + text_frag
                else:
                    target_msg.text = text_frag
        else:
            # Target outside this segment -> emit as event
            for r in reaction_list:
                actor = _norm_user(r.get('actor') or r.get('sender') or r.get('handle')) or 'UNKNOWN'
                rtype = r.get('reaction_type') or r.get('reaction') or 'reacted'
                ev = conversation.Message('event')
                ev.msgfrom = 'System Message'
                ev.date = _parse_date(r.get('date')) or datetime.datetime.now(datetime.timezone.utc)
                ev.text = f'{actor} {rtype} a message (GUID {target_guid})'
                conv.add_message(ev)

    # determine startdate
    if conv.messages:
        conv.startdate = conv.getoldestmessage().date
    return conv


def parse_file(path: str, local_handle: Optional[str] = None,
               idle_hours: float = 4.0, min_messages: int = 2,
               max_messages: int = 0, max_days: int = 0,
               stream: bool = False, stream_dir: Optional[str] = None,
               embed_attachments: bool = False) -> Iterable[conversation.Conversation]:
    """Main entry: parse NDJSON and yield Conversation objects (segmented).

    If stream=True, messages are sharded to per-chat temporary files to avoid
    holding all chats in memory. After sharding, each chat file is processed
    sequentially to build Conversation objects.
    """
    if not stream:
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
                conv = build_conversation_from_segment(segment, chat_id, path, local_handle, embed_attachments=embed_attachments)
                yield conv
        return

    # streaming / sharding path
    if stream_dir:
        base = os.path.abspath(stream_dir)
        os.makedirs(base, exist_ok=True)
        cleanup_base = False
    else:
        base = tempfile.mkdtemp(prefix='imessage_shards_')
        cleanup_base = True

    open_files = {}
    chatfile_map = {}  # fpath -> chat_id
    max_open = 512

    try:
        with open(path, 'r') as f:
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
                key_hash = hashlib.sha1(chat_id.encode('utf-8', errors='ignore')).hexdigest()[:8]
                safe = ''.join([c if c.isalnum() else '_' for c in chat_id])[:40]
                fname = f"{safe}_{key_hash}.ndjson"
                fpath = os.path.join(base, fname)
                if fpath not in chatfile_map:
                    chatfile_map[fpath] = chat_id
                fh = open_files.get(fpath)
                if fh is None:
                    try:
                        fh = open(fpath, 'a')
                        open_files[fpath] = fh
                    except Exception:
                        # fallback: write in one-shot
                        with open(fpath, 'a') as fh2:
                            fh2.write(ln + "\n")
                        continue
                fh.write(ln + "\n")
                # limit open descriptors
                if len(open_files) > max_open:
                    k, v = open_files.popitem()
                    try:
                        v.close()
                    except Exception:
                        pass

        # close remaining
        for v in open_files.values():
            try:
                v.close()
            except Exception:
                pass
        open_files.clear()

        # process each chat file sequentially
        for fpath in sorted(chatfile_map.keys()):
            chat_id = chatfile_map.get(fpath) or os.path.basename(fpath)
            msgs = []
            try:
                with open(fpath, 'r') as fh:
                    for ln in fh:
                        ln = ln.strip()
                        if not ln:
                            continue
                        try:
                            obj = json.loads(ln)
                        except Exception:
                            continue
                        msgs.append(obj)
            except Exception as e:
                logging.warning('Failed to read shard %s: %s', fpath, e)
                continue

            for segment in segment_messages(msgs, idle_hours=idle_hours, min_messages=min_messages,
                                            max_messages=max_messages, max_days=max_days):
                conv = build_conversation_from_segment(segment, chat_id, path, local_handle, embed_attachments=embed_attachments)
                yield conv

    finally:
        if cleanup_base:
            try:
                for fn in os.listdir(base):
                    try:
                        os.remove(os.path.join(base, fn))
                    except Exception:
                        pass
                os.rmdir(base)
            except Exception:
                pass
