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
from typing import TYPE_CHECKING, Iterable, Optional
import os
import tempfile
import hashlib

from .imessage_common import (
    build_conversation_from_segment,
    norm_user,
    parse_date,
    segment_messages,
)

if TYPE_CHECKING:
    from ..conversation import Conversation


def parse_file(path: str, local_handle: Optional[str] = None,
               idle_hours: float = 4.0, min_messages: int = 2,
               max_messages: int = 0, max_days: int = 0,
               stream: bool = False, stream_dir: Optional[str] = None,
               embed_attachments: bool = False) -> Iterable["Conversation"]:
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
                    except Exception as e:
                        logging.debug('Failed closing shard file handle %s: %s', k, e)

        # close remaining
        for v in open_files.values():
            try:
                v.close()
            except Exception as e:
                logging.debug('Failed closing shard file handle: %s', e)
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
                    except Exception as e:
                        logging.debug('Failed removing shard file %s: %s', os.path.join(base, fn), e)
                os.rmdir(base)
            except Exception as e:
                logging.debug('Failed cleaning shard tempdir %s: %s', base, e)


__all__ = [
    'parse_file',
    'segment_messages',
    'build_conversation_from_segment',
    'parse_date',
    'norm_user',
]
