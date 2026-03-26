#!/usr/bin/env python3
"""Relaxed verification: consider attachments present if metadata appears in HTML/text or cid appears even if MIME part missing."""
import os
import sys
import hashlib
import shutil
from email import policy
from email.parser import BytesParser

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from chatlogtoeml.parsers import imessage_json

NDJSON_DIR = 'samples/ndjson'
OUT_BASE = 'samples/ndjson/verify_out'
LOCAL_HANDLE = 'mrogers@pbs.invalid'


def parse_eml(path):
    with open(path, 'rb') as fh:
        msg = BytesParser(policy=policy.default).parse(fh)
    text = ''
    html = ''
    attachments = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        if ctype == 'text/plain':
            try:
                text += part.get_content()
            except Exception:
                payload = part.get_payload(decode=True) or b''
                text += payload.decode('utf-8', errors='replace')
        elif ctype == 'text/html':
            try:
                html += part.get_content()
            except Exception:
                payload = part.get_payload(decode=True) or b''
                html += payload.decode('utf-8', errors='replace')
        else:
            cid = part.get('Content-ID')
            filename = part.get_filename()
            mimetype = part.get_content_type()
            payload = part.get_payload(decode=True)
            attachments.append({'cid': (cid.strip('<>') if cid else None),'filename': filename,'mimetype': mimetype,'payload_len': len(payload) if payload else 0})
    headers = dict(msg.items())
    return headers, text, html, attachments


missing = []
conv_count = 0
msg_count = 0

nd_files = sorted([f for f in os.listdir(NDJSON_DIR) if f.endswith('.ndjson')])
for fname in nd_files:
    ndpath = os.path.join(NDJSON_DIR, fname)
    outdir = os.path.join(OUT_BASE, os.path.splitext(fname)[0])
    if not os.path.isdir(outdir):
        print('No output dir for', fname, 'skipping')
        continue
    eml_files = []
    for root, _, files in os.walk(outdir):
        for fn in files:
            if fn.lower().endswith('.eml'):
                eml_files.append(os.path.join(root, fn))
    eml_index = {'by_ref':{},'by_orig':{},'by_subj':{}}
    for ef in eml_files:
        try:
            headers, text_p, html_p, atts = parse_eml(ef)
        except Exception as e:
            continue
        ref = headers.get('References')
        orig = headers.get('X-Original-File')
        subj = headers.get('Subject') or ''
        if ref:
            eml_index['by_ref'][ref] = ef
        if orig:
            eml_index['by_orig'][orig] = ef
        if subj:
            eml_index['by_subj'][subj] = ef

    convs = list(imessage_json.parse_file(ndpath, local_handle=LOCAL_HANDLE, stream=True, embed_attachments=False))
    for i, conv in enumerate(convs):
        conv_count += 1
        msg_count += len(conv.messages)
        key = ' '.join(sorted(conv.listparticipantuserids())).lower()
        refhash = hashlib.md5(key.encode('utf-8')).hexdigest()
        fakedomain = f"{(conv.service or 'Conversation').lower()}.{(conv.imclient or 'client').lower()}.invalid"
        expected_ref = f"<{refhash}@{fakedomain}>"
        match = None
        if expected_ref in eml_index['by_ref']:
            match = eml_index['by_ref'][expected_ref]
        elif conv.origfilename in eml_index['by_orig']:
            match = eml_index['by_orig'][conv.origfilename]
        else:
            for subj, ef in eml_index['by_subj'].items():
                if conv.filenameuserid and conv.filenameuserid in subj:
                    match = ef; break
        if not match:
            missing.append({'ndjson': ndpath, 'conv_index': i, 'reason': 'no_match'})
            continue
        headers, text_part, html_part, attachments = parse_eml(match)
        for midx, msg in enumerate(conv.messages):
            txt = getattr(msg,'text','') or ''
            html = getattr(msg,'html','') or ''
            sender = getattr(msg,'msgfrom','') or ''
            if txt:
                if txt not in (text_part or '') and txt not in (html_part or ''):
                    missing.append({'ndjson': ndpath, 'conv_index': i, 'msg_index': midx, 'issue': 'text_missing', 'snippet': txt[:80]})
            if sender:
                if sender not in (text_part or '') and sender not in (html_part or '') and sender not in (headers.get('From','') or '') and sender not in (headers.get('To','') or ''):
                    missing.append({'ndjson': ndpath, 'conv_index': i, 'msg_index': midx, 'issue': 'sender_missing', 'sender': sender})
            for att in getattr(msg,'attachments',[]):
                att_basename = os.path.basename(att.name or '')
                found = False
                # check MIME attachments
                for a in attachments:
                    if a.get('cid') and a.get('cid') == att.contentid:
                        found = True; break
                    if a.get('filename') and att.name and a.get('filename') == att.name:
                        found = True; break
                # check html/text for cid or name
                if not found:
                    if att.contentid and (('cid:'+att.contentid) in (html_part or '') or ('cid:'+att.contentid) in (text_part or '')):
                        found = True
                if not found:
                    if att.name and (att.name in (html_part or '') or att_basename in (html_part or '') or att_basename in (text_part or '')):
                        found = True
                if not found:
                    missing.append({'ndjson': ndpath, 'conv_index': i, 'msg_index': midx, 'issue': 'attachment_missing', 'att_name': att.name, 'att_cid': att.contentid})

print('Relaxed verification:')
print('Conversations:', conv_count, 'Messages:', msg_count)
print('Missing items (relaxed):', len(missing))
# tally
from collections import Counter
cnt = Counter([m.get('issue','no_match') for m in missing])
print('Counts:', dict(cnt))
for m in missing[:200]:
    print(m)

sys.exit(0)
