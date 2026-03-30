"""Shared iMessage parser helpers.

This module contains chat/message normalization and segmentation logic used by
both NDJSON and Apple DB parser entrypoints.
"""

import datetime
import html as _html
import logging
import os
from typing import Iterable, List, Optional

import dateutil.parser

from .. import conversation
from ..normalize import normalize_user


# Reaction rendering utilities
_REACTION_EMOJI = {
    'like': '👍', 'love': '❤️', 'laugh': '😂', 'haha': '😂',
    'dislike': '👎', 'emphasize': '❗', 'question': '❓',
    'heart': '❤️', 'thumbs_up': '👍', 'thumbs_down': '👎'
}


def parse_date(datestr):
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


def norm_user(user):
    """Normalize a user identifier into a simple string.

    Accepts strings or dicts commonly emitted by iMessage exporters and
    returns a representative string or None.
    """
    return normalize_user(user)


def _group_reactions(reaction_list):
    grouped = {}
    for reaction in reaction_list:
        reaction_type = (reaction.get('reaction_type') or reaction.get('reaction') or 'reacted')
        if reaction_type is None:
            reaction_type = 'reacted'
        key = reaction_type.lower()
        actor = norm_user(reaction.get('actor') or reaction.get('sender') or reaction.get('handle')) or 'UNKNOWN'
        grouped.setdefault(key, []).append(actor)
    return grouped


def _render_reactions_html(reaction_list):
    grouped = _group_reactions(reaction_list)
    parts = []
    for reaction_type, actors in grouped.items():
        emoji = _REACTION_EMOJI.get(reaction_type)
        title = _html.escape(', '.join(actors))
        if emoji:
            if len(actors) > 1:
                parts.append(f'<span class="reaction" title="{title}">{emoji}×{len(actors)}</span>')
            else:
                parts.append(f'<span class="reaction" title="{title}">{emoji}</span>')
        else:
            label = _html.escape(reaction_type)
            if len(actors) > 1:
                parts.append(f'<span class="reaction" title="{title}">{label}×{len(actors)}</span>')
            else:
                parts.append(f'<span class="reaction" title="{title}">{label}</span>')
    if parts:
        return '<div class="reactions">' + ' '.join(parts) + '</div>'
    return ''


def _render_reactions_text(reaction_list):
    grouped = _group_reactions(reaction_list)
    parts = []
    for reaction_type, actors in grouped.items():
        emoji = _REACTION_EMOJI.get(reaction_type)
        if emoji:
            if len(actors) > 1:
                parts.append(f'{emoji}×{len(actors)} ({",".join(actors)})')
            else:
                parts.append(f'{emoji} ({actors[0]})')
        else:
            if len(actors) > 1:
                parts.append(f'{reaction_type}×{len(actors)} ({",".join(actors)})')
            else:
                parts.append(f'{reaction_type} ({actors[0]})')
    return ' | '.join(parts) if parts else ''


def _raw_to_message(obj: dict, local_handle: Optional[str]) -> conversation.Message:
    msg = conversation.Message('message')
    msg.guid = obj.get('guid', '')
    msg.text = obj.get('text') or ''
    msg.html = obj.get('html') or ''
    # Ensure messages have a deterministic fallback date (epoch UTC) when unparseable.
    msg.date = parse_date(obj.get('date')) or datetime.datetime.fromtimestamp(0, datetime.timezone.utc)
    # Determine sender.
    if obj.get('is_from_me'):
        msg.msgfrom = local_handle or 'me'
    else:
        msg.msgfrom = norm_user(obj.get('sender') or obj.get('handle')) or 'UNKNOWN'
    return msg


def segment_messages(raw_msgs: List[dict], idle_hours: float = 8.0, min_messages: int = 2,
                     max_messages: int = 0, max_days: int = 0) -> Iterable[List[dict]]:
    """Split raw message dicts into segments based on idle gap and limits."""
    if not raw_msgs:
        return
    parsed = []
    for raw in raw_msgs:
        raw_dt = parse_date(raw.get('date'))
        if raw_dt is None:
            # If no date, push far in the past to keep ordering stable.
            raw_dt = datetime.datetime.fromtimestamp(0, datetime.timezone.utc)
        parsed.append((raw_dt, raw))
    parsed.sort(key=lambda x: x[0])

    current = []
    last_dt = None
    start_dt = None
    for dt, raw in parsed:
        if not current:
            current.append((dt, raw))
            last_dt = dt
            start_dt = dt
            continue
        gap = (dt - last_dt).total_seconds()
        # Split on idle gap.
        if idle_hours and gap > idle_hours * 3600:
            if len(current) >= min_messages:
                yield [item[1] for item in current]
            else:
                logging.debug('Skipping short segment of %d messages', len(current))
            current = [(dt, raw)]
            last_dt = dt
            start_dt = dt
            continue
        # Split on max_days.
        if max_days and start_dt and (dt - start_dt).total_seconds() > max_days * 86400:
            if len(current) >= min_messages:
                yield [item[1] for item in current]
            else:
                logging.debug('Skipping short segment (max_days) of %d messages', len(current))
            current = [(dt, raw)]
            last_dt = dt
            start_dt = dt
            continue
        # Force split by max_messages.
        if max_messages and len(current) >= max_messages:
            if len(current) >= min_messages:
                yield [item[1] for item in current]
            else:
                logging.debug('Skipping short segment (max_messages) of %d messages', len(current))
            current = [(dt, raw)]
            last_dt = dt
            start_dt = dt
            continue
        current.append((dt, raw))
        last_dt = dt
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

    participants = set()
    for msgobj in segment:
        parts = msgobj.get('participants') or []
        for participant in parts:
            if isinstance(participant, dict):
                participant_id = None
                for key in ('id', 'identifier', 'handle', 'address', 'username', 'phone', 'value'):
                    value = participant.get(key)
                    if value:
                        participant_id = str(value)
                        break
                if not participant_id:
                    for value in participant.values():
                        if value:
                            participant_id = str(value)
                            break
                if participant_id:
                    participants.add(participant_id)
            elif participant:
                participants.add(str(participant))
    if local_handle:
        participants.add(local_handle)
    for participant in participants:
        conv.add_participant(participant)
    if local_handle:
        conv.set_local_account(local_handle)

    messages_by_guid = {}
    reactions = {}

    for msgobj in segment:
        associated_guid = msgobj.get('associated_message_guid')
        reaction_type = msgobj.get('reaction_type') or msgobj.get('reaction')
        if reaction_type or (associated_guid and not msgobj.get('text')):
            if associated_guid:
                reactions.setdefault(associated_guid, []).append(msgobj)
            else:
                reactions.setdefault(None, []).append(msgobj)
            continue

        msg = _raw_to_message(msgobj, local_handle)
        attachments = msgobj.get('attachments') or []
        for attachment_meta in attachments:
            att = conversation.Attachment()
            att.name = attachment_meta.get('filename') or attachment_meta.get('transfer_name') or attachment_meta.get('mime_type') or 'attachment'
            att.mimetype = attachment_meta.get('mime_type') or 'application/octet-stream'
            path = attachment_meta.get('path')
            if embed_attachments and path and os.path.isfile(path):
                try:
                    with open(path, 'rb') as af:
                        att.data = af.read()
                except Exception:
                    att.data = b''
                    logging.warning('Failed to read attachment path: %s', path)
            else:
                att.data = b''
                if path:
                    att.orig_path = path
                    if embed_attachments:
                        logging.warning('Attachment path missing or unreadable; not embedded: %s', path)
            att.gen_contentid()
            msg.attachments.append(att)
            conv.hasattachments = True

        conv.add_participant(msg.msgfrom)
        if local_handle and msg.msgfrom.lower() == (local_handle or '').lower():
            conv.set_local_account(msg.msgfrom)
        else:
            conv.set_remote_account(msg.msgfrom)
        conv.add_message(msg)
        if msg.guid:
            messages_by_guid[msg.guid] = msg

    for target_guid, reaction_list in reactions.items():
        if target_guid is None:
            for reaction in reaction_list:
                actor = norm_user(reaction.get('actor') or reaction.get('sender') or reaction.get('handle')) or 'UNKNOWN'
                reaction_type = reaction.get('reaction_type') or reaction.get('reaction') or 'reacted'
                ev = conversation.Message('event')
                ev.msgfrom = 'System Message'
                ev.date = parse_date(reaction.get('date')) or datetime.datetime.now(datetime.timezone.utc)
                ev.text = f'{actor} {reaction_type} a message (unknown target)'
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
                    escaped = _html.escape(target_msg.text) if target_msg.text else ''
                    target_msg.html = escaped + html_frag
                    if not target_msg.text:
                        target_msg.text = ''
            else:
                if target_msg.text:
                    target_msg.text += '\n' + text_frag
                else:
                    target_msg.text = text_frag
        else:
            for reaction in reaction_list:
                actor = norm_user(reaction.get('actor') or reaction.get('sender') or reaction.get('handle')) or 'UNKNOWN'
                reaction_type = reaction.get('reaction_type') or reaction.get('reaction') or 'reacted'
                ev = conversation.Message('event')
                ev.msgfrom = 'System Message'
                ev.date = parse_date(reaction.get('date')) or datetime.datetime.now(datetime.timezone.utc)
                ev.text = f'{actor} {reaction_type} a message (GUID {target_guid})'
                conv.add_message(ev)

    if conv.messages:
        conv.startdate = conv.getoldestmessage().date
    return conv


__all__ = [
    'parse_date',
    'norm_user',
    'segment_messages',
    'build_conversation_from_segment',
]
