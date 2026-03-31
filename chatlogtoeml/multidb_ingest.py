"""Multi-DB ingest and message-level dedupe pipeline.

This module implements a conservative, deterministic dedupe pass over
Conversation objects parsed from multiple source DBs. It follows the
normative rules in DEDUPE_INGEST_PLAN.md but is intentionally focused on a
minimal, well-tested initial implementation.
"""
from __future__ import annotations

import datetime
import hashlib
import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .parsers import apple_db as apple_db_parser
from .parsers.imessage_common import norm_user
from . import conversation


ASCII_US = '\x1f'


def _parse_source_spec(spec: str) -> Dict[str, Optional[str]]:
    # Split on first '::'
    parts = spec.split('::', 1)
    db_path = parts[0] if parts and parts[0] else ''
    attachment_root = parts[1] if len(parts) > 1 and parts[1] else None
    return {'db_path': db_path, 'attachment_root': attachment_root}


def _normalize_text(s: Optional[str]) -> str:
    if not s:
        return ''
    # collapse whitespace
    return ' '.join(str(s).split()).strip()


def _attachment_identity(att: conversation.Attachment) -> Tuple[str, str]:
    """Return (identity_type, idstring) where identity_type is 'hash' or 'meta'."""
    # Prefer payload hash when available
    if getattr(att, 'data', None):
        h = hashlib.sha1()
        try:
            h.update(att.data)
            return ('hash', h.hexdigest())
        except Exception:
            pass
    # fallback fingerprint
    name = (att.name or '')
    mime = (att.mimetype or '')
    size = str(len(att.data) if getattr(att, 'data', None) else 0)
    base = os.path.basename(att.orig_path or '')
    fid = '|'.join([name, mime, size, base])
    return ('meta', fid)


def _escape_component(s: str) -> str:
    return s.replace(ASCII_US, '\\x1f')


def _make_key(rec: Dict[str, Any]) -> Tuple[str, str]:
    # primary
    service = (rec.get('service') or '').lower()
    guid = rec.get('guid')
    if guid:
        pk = ASCII_US.join([service, _escape_component(str(guid))])
        return ('primary', pk)

    # fallback key components
    chat_id = (rec.get('chat_id') or '').lower()
    sender = (rec.get('sender') or '').lower()
    ts = rec.get('timestamp_utc')
    ts_s = ''
    if isinstance(ts, datetime.datetime):
        # round to whole second
        ts_s = ts.replace(microsecond=0).isoformat()
    content = _normalize_text(rec.get('text_norm') or rec.get('html_norm') or '')
    # attachment fingerprint: sorted list of per-attachment ids
    att_ids = []
    for a in rec.get('attachments') or []:
        aid = a.get('payload_hash') or a.get('fingerprint') or ''
        att_ids.append(aid)
    att_ids = sorted([_escape_component(str(x)) for x in att_ids])
    att_fprint = ','.join(att_ids)
    fk = ASCII_US.join([service, _escape_component(chat_id), _escape_component(sender), _escape_component(ts_s), _escape_component(content), _escape_component(att_fprint)])
    return ('fallback', fk)


def _score_candidate(rec: Dict[str, Any]) -> Tuple[int, int, int]:
    # Returns tuple (human_content_score, attachment_score, metadata_score)
    human_score = 0
    text = _normalize_text(rec.get('text_norm') or '')
    html = _normalize_text(rec.get('html_norm') or '')
    if text or html:
        human_score += 1000
        human_score += min(len(text or html), 500)
    # penalize obvious placeholders
    if text and all(ch in '[](){}<>\uFFFC\uFFFD' or not ch.isalnum() for ch in text):
        human_score -= 200

    att_score = 0
    unique_ids = set()
    for a in rec.get('attachments') or []:
        pid = a.get('payload_hash') or a.get('fingerprint')
        if pid and pid not in unique_ids:
            unique_ids.add(pid)
            att_score += 10
            if a.get('has_payload'):
                att_score += 20

    meta_score = 0
    if rec.get('guid'):
        meta_score += 5
    if rec.get('metadata_score_inputs', {}).get('reactions'):
        meta_score += 3
    if rec.get('metadata_score_inputs', {}).get('realname'):
        meta_score += 2
    # service/chat headers present
    meta_score += min(10, int(bool(rec.get('service')) ) + int(bool(rec.get('chat_id'))))
    return (human_score, att_score, meta_score)


def ingest_sources(source_specs: List[str], local_handle: Optional[str] = None,
                   idle_hours: float = 8.0, min_messages: int = 2,
                   max_messages: int = 0, max_days: int = 0,
                   embed_attachments: bool = True) -> Iterable[conversation.Conversation]:
    """Main multi-source ingest: parse sources, dedupe, and yield Conversation objects.

    This implementation parses each DB via the existing Apple DB parser, then
    extracts normalized message records and runs the dedupe grouping/winner
    selection and attachment merge rules.
    """
    # Resolve specs
    sources = []
    for idx, s in enumerate(source_specs):
        spec = _parse_source_spec(s)
        dbp = spec.get('db_path')
        if not dbp:
            raise ValueError('Empty db_path in source spec')
        sources.append({'source_index': idx, 'db_path': dbp, 'attachment_root': spec.get('attachment_root'), 'source_label': os.path.basename(dbp)})

    # Parse each DB into Conversation objects (per-chat segments). We will
    # iterate their messages and build normalized message records.
    records = []
    for src in sources:
        idx = src['source_index']
        try:
            for conv in apple_db_parser.parse_file(
                src['db_path'],
                local_handle=local_handle,
                addressbook_path=None,
                idle_hours=idle_hours,
                min_messages=min_messages,
                max_messages=max_messages,
                max_days=max_days,
                stream=False,
                embed_attachments=embed_attachments,
                attachment_root=src.get('attachment_root'),
            ):
                # Each conv is a conversation segment. Extract messages.
                for msg in conv.messages:
                    if getattr(msg, 'type', 'message') != 'message':
                        continue
                    rec = {}
                    rec['source_index'] = idx
                    rec['service'] = getattr(conv, 'service', 'iMessage') or 'iMessage'
                    rec['chat_id'] = getattr(conv, 'filenameuserid', '') or getattr(conv, 'chat_guid', '') or ''
                    rec['guid'] = getattr(msg, 'guid', None) or None
                    rec['sender'] = getattr(msg, 'msgfrom', '')
                    rec['timestamp_utc'] = getattr(msg, 'date', None)
                    rec['text_norm'] = _normalize_text(getattr(msg, 'text', ''))
                    rec['html_norm'] = _normalize_text(getattr(msg, 'html', ''))
                    rec['has_human_content'] = bool(rec['text_norm'] or rec['html_norm'])
                    # attachments
                    atts = []
                    for a in getattr(msg, 'attachments', []) or []:
                        aid_type, aid = _attachment_identity(a)
                        atts.append({
                            'name': a.name,
                            'mime_type': a.mimetype,
                            'orig_path': getattr(a, 'orig_path', None),
                            'has_payload': bool(getattr(a, 'data', None)),
                            'payload_hash': aid if aid_type == 'hash' else None,
                            'fingerprint': aid if aid_type == 'meta' else None,
                            'data': getattr(a, 'data', None),
                        })
                    rec['attachments'] = atts
                    rec['metadata_score_inputs'] = {}
                    rec['provenance'] = {'source_db': src['db_path'], 'source_label': src['source_label']}
                    records.append(rec)
        except Exception as e:
            logging.error('Failed parsing source %s: %s', src['db_path'], e)

    # Group by dedupe key
    groups: Dict[str, List[Dict[str, Any]]] = {}
    key_types: Dict[str, str] = {}
    for r in records:
        ktype, k = _make_key(r)
        groups.setdefault(k, []).append(r)
        key_types[k] = ktype

    # Choose winners and merge attachments
    deduped: List[Dict[str, Any]] = []
    for k, items in groups.items():
        if len(items) == 1:
            # minimal normalization: ensure attachments list normalized
            deduped.append(items[0])
            continue
        # enforce human-content rule: if any has human content, drop content-empty ones
        any_content = any(it.get('has_human_content') for it in items)
        candidates = [it for it in items if (it.get('has_human_content') or not any_content)]
        # score candidates
        scored = []
        for it in candidates:
            h, a, m = _score_candidate(it)
            scored.append((h, a, m, it))
        # sort by score desc and deterministic tie-break
        scored.sort(key=lambda x: (-(x[0]), -(x[1]), -(x[2]), x[3].get('source_index'), str(x[3].get('guid') or '')))
        winner = scored[0][3]
        # merge attachments: union by identity
        merged = {}
        for it in items:
            for a in it.get('attachments') or []:
                pid = a.get('payload_hash') or a.get('fingerprint') or hashlib.sha1(str(a).encode('utf-8')).hexdigest()
                existing = merged.get(pid)
                if not existing:
                    merged[pid] = dict(a)
                else:
                    # prefer payload if any
                    if not existing.get('has_payload') and a.get('has_payload'):
                        existing['has_payload'] = True
                        existing['payload_hash'] = a.get('payload_hash') or existing.get('payload_hash')
                        existing['data'] = a.get('data') or existing.get('data')
                    # union provenance not tracked per-attachment here, but orig_path list
                    if a.get('orig_path') and a.get('orig_path') not in (existing.get('orig_path') or ''):
                        existing['orig_path'] = (existing.get('orig_path') or '') + ',' + a.get('orig_path')
        winner_copy = dict(winner)
        winner_copy['attachments'] = list(merged.values())
        deduped.append(winner_copy)

    # Group deduped messages into conversations by chat_id
    conv_map: Dict[str, List[Dict[str, Any]]] = {}
    for d in deduped:
        cid = d.get('chat_id') or 'chat'
        conv_map.setdefault(cid, []).append(d)

    # For each chat, sort and segment by idle_hours etc., then yield Conversation objects
    for cid, msgs in conv_map.items():
        # sort
        msgs.sort(key=lambda x: x.get('timestamp_utc') or datetime.datetime.fromtimestamp(0, datetime.timezone.utc))
        # simple segmentation (idle gap)
        segments: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        last_dt = None
        for m in msgs:
            dt = m.get('timestamp_utc') or datetime.datetime.fromtimestamp(0, datetime.timezone.utc)
            if not current:
                current.append(m)
                last_dt = dt
                continue
            gap = (dt - last_dt).total_seconds()
            if idle_hours and gap > idle_hours * 3600:
                if len(current) >= min_messages:
                    segments.append(current)
                current = [m]
                last_dt = dt
                continue
            if max_messages and len(current) >= max_messages:
                if len(current) >= min_messages:
                    segments.append(current)
                current = [m]
                last_dt = dt
                continue
            current.append(m)
            last_dt = dt
        if current and len(current) >= min_messages:
            segments.append(current)

        for seg in segments:
            conv = conversation.Conversation()
            conv.filenameuserid = cid
            conv.origfilename = ','.join(sorted({d.get('provenance', {}).get('source_label', '') for d in seg}))
            conv.service = seg[0].get('service') or 'iMessage'
            # participants
            parts = set()
            for m in seg:
                parts.add(m.get('sender') or '')
            if local_handle:
                parts.add(local_handle)
            for p in parts:
                if p:
                    conv.add_participant(p)
            # messages
            for m in seg:
                msg = conversation.Message('message')
                msg.guid = m.get('guid') or ''
                msg.msgfrom = m.get('sender') or 'UNKNOWN'
                msg.date = m.get('timestamp_utc') or datetime.datetime.fromtimestamp(0, datetime.timezone.utc)
                msg.text = m.get('text_norm') or ''
                msg.html = m.get('html_norm') or ''
                for a in m.get('attachments') or []:
                    att = conversation.Attachment()
                    att.name = a.get('name') or ''
                    att.mimetype = a.get('mime_type') or a.get('mime') or 'application/octet-stream'
                    att.orig_path = a.get('orig_path') or ''
                    if a.get('has_payload') and a.get('data'):
                        try:
                            att.data = a.get('data')
                        except Exception:
                            att.data = b''
                    else:
                        att.data = b''
                    att.gen_contentid()
                    msg.attachments.append(att)
                    conv.hasattachments = True
                conv.add_message(msg)
            if conv.messages:
                conv.startdate = conv.getoldestmessage().date
            yield conv


__all__ = ['ingest_sources']
