#!/usr/bin/env python3
"""Verify NDJSON -> EML metadata preservation using the synthetic fixtures.

This script:
 - runs bin/json_to_eml on each NDJSON in samples/ndjson
 - parses generated .eml files and Conversations produced by imessage_json.parse_file
 - checks that message text, senders, attachment metadata, reactions, and key headers are present
 - prints a summary and any mismatches

Run from repository root.
"""
import sys
import os
import subprocess
import shutil
import hashlib
from email import policy
from email.parser import BytesParser
# Ensure repo root is on sys.path so imports work regardless of CWD
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from chatlogtoeml import conv_to_eml, conversation
from chatlogtoeml.parsers import imessage_json
import datetime

NDJSON_DIR = 'samples/ndjson/synthetic'
OUT_BASE = 'samples/ndjson/verify_out'
LOCAL_HANDLE = 'mrogers@pbs.invalid'

os.makedirs(OUT_BASE, exist_ok=True)


def run_conversion(ndpath, outdir):
    if os.path.exists(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir, exist_ok=True)
    cmd = [sys.executable, 'bin/json_to_eml', ndpath, outdir, '--stream', '--clobber', '--local-handle', LOCAL_HANDLE, '--embed-attachments']
    print('\nRunning conversion:', ' '.join(cmd))
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print('conversion stdout:')
    print(p.stdout.decode('utf-8', errors='replace'))
    print('conversion stderr:')
    print(p.stderr.decode('utf-8', errors='replace'))
    return p.returncode == 0


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
            attachments.append({
                'cid': (cid.strip('<>') if cid else None),
                'filename': filename,
                'mimetype': mimetype,
                'payload_len': len(payload) if payload else 0
            })
    headers = dict(msg.items())
    return headers, text, html, attachments


all_missing = []
conv_count = 0
msg_count = 0

if not os.path.isdir(NDJSON_DIR):
    print('NDJSON directory not found:', NDJSON_DIR)
    sys.exit(0)

nd_files = sorted([f for f in os.listdir(NDJSON_DIR) if f.endswith('.ndjson')])
if not nd_files:
    print('No NDJSON files found in', NDJSON_DIR)
    sys.exit(0)

for fname in nd_files:
    ndpath = os.path.join(NDJSON_DIR, fname)
    outdir = os.path.join(OUT_BASE, os.path.splitext(fname)[0])
    ok = run_conversion(ndpath, outdir)
    if not ok:
        print('Conversion reported non-zero exit for', ndpath)
    # collect .eml files
    eml_files = []
    for root, _, files in os.walk(outdir):
        for fn in files:
            if fn.lower().endswith('.eml'):
                eml_files.append(os.path.join(root, fn))
    print('Found', len(eml_files), '.eml files for', fname)

    # build simple indexes for matching
    eml_index = {'by_ref':{}, 'by_orig':{}, 'by_subj':{}}
    for ef in eml_files:
        try:
            headers, text_p, html_p, atts = parse_eml(ef)
        except Exception as e:
            print('Failed to parse eml', ef, '->', e)
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

    # parse conversations from NDJSON using same parser options
    convs = list(imessage_json.parse_file(ndpath, local_handle=LOCAL_HANDLE, stream=True, embed_attachments=True))
    print('Parsed', len(convs), 'conversations from', fname)
    for i, conv in enumerate(convs):
        conv_count += 1
        msg_count += len(conv.messages)
        # compute expected References
        key = ' '.join(sorted(conv.listparticipantuserids())).lower()
        refhash = hashlib.md5(key.encode('utf-8')).hexdigest()
        fakedomain = f"{(conv.service or 'Conversation').lower()}.{(conv.imclient or 'client').lower()}.invalid"
        expected_ref = f"<{refhash}@{fakedomain}>"
        match_file = None
        if expected_ref in eml_index['by_ref']:
            match_file = eml_index['by_ref'][expected_ref]
        elif conv.origfilename in eml_index['by_orig']:
            match_file = eml_index['by_orig'][conv.origfilename]
        else:
            for subj, ef in eml_index['by_subj'].items():
                if conv.filenameuserid and conv.filenameuserid in subj:
                    match_file = ef
                    break
        if not match_file:
            print('\nNO MATCH: conversation', i, 'from', fname, 'expected_ref=', expected_ref)
            all_missing.append({'ndjson': ndpath, 'conv_index': i, 'reason': 'no_eml_match', 'expected_ref': expected_ref})
            continue
        print('\nComparing conversation', i, '->', match_file)
        try:
            headers, text_part, html_part, attachments = parse_eml(match_file)
        except Exception as e:
            print('Failed to parse matched eml', match_file, e)
            all_missing.append({'ndjson': ndpath, 'conv_index': i, 'reason': 'parse_eml_failed', 'eml': match_file, 'error': str(e)})
            continue
        # header checks
        if headers.get('X-Original-File') != conv.origfilename:
            all_missing.append({'ndjson': ndpath, 'conv_index': i, 'issue': 'origfile_mismatch', 'expected': conv.origfilename, 'found': headers.get('X-Original-File')})
            print('  header X-Original-File mismatch: expected', conv.origfilename, 'found', headers.get('X-Original-File'))
        if conv.filenameuserid and conv.filenameuserid not in (headers.get('Subject') or ''):
            all_missing.append({'ndjson': ndpath, 'conv_index': i, 'issue': 'subject_missing_filenameuserid', 'expected': conv.filenameuserid, 'found': headers.get('Subject')})
            print('  Subject does not contain filenameuserid', conv.filenameuserid)
        # message-level checks
        for midx, msg in enumerate(conv.messages):
            # text presence
            txt = getattr(msg, 'text', '') or ''
            html = getattr(msg, 'html', '') or ''
            sender = getattr(msg, 'msgfrom', '') or ''
            if txt:
                if txt not in (text_part or '') and txt not in (html_part or ''):
                    all_missing.append({'ndjson': ndpath, 'conv_index': i, 'msg_index': midx, 'issue': 'text_missing', 'snippet': txt[:120]})
                    print(f"  message {midx}: text snippet not found in plain/html")
            if sender:
                if sender not in (text_part or '') and sender not in (html_part or '') and sender not in (headers.get('From') or '') and sender not in (headers.get('To') or ''):
                    all_missing.append({'ndjson': ndpath, 'conv_index': i, 'msg_index': midx, 'issue': 'sender_missing', 'sender': sender})
                    print(f"  message {midx}: sender '{sender}' not found in EML parts or headers")
            # attachments
            for att in getattr(msg, 'attachments', []):
                found = False
                for a in attachments:
                    if (a.get('cid') and a.get('cid') == att.contentid) or (a.get('filename') and att.name and a.get('filename') == att.name):
                        found = True
                        # mimetype check (basic)
                        if att.mimetype and a.get('mimetype') and att.mimetype.split(';')[0] not in a.get('mimetype'):
                            all_missing.append({'ndjson': ndpath, 'conv_index': i, 'msg_index': midx, 'issue': 'att_mimetype_mismatch', 'expected': att.mimetype, 'found': a.get('mimetype')})
                            print(f"  message {midx}: attachment mimetype mismatch for {att.name}")
                        break
                if not found:
                    all_missing.append({'ndjson': ndpath, 'conv_index': i, 'msg_index': midx, 'issue': 'attachment_missing', 'att_name': att.name, 'att_cid': att.contentid})
                    print(f"  message {midx}: attachment '{att.name}' (cid {att.contentid}) not found in EML")
            # reactions
            if html and ('class="reaction"' in html or 'class="reactions"' in html or '×' in html):
                if html not in (html_part or '') and html not in (text_part or ''):
                    all_missing.append({'ndjson': ndpath, 'conv_index': i, 'msg_index': midx, 'issue': 'reaction_missing', 'snippet': (html[:120])})
                    print(f"  message {midx}: reaction html missing from EML")

print('\n=== Verification Summary ===')
print('Conversations examined:', conv_count)
print('Messages examined:', msg_count)
print('Missing items detected:', len(all_missing))
for e in all_missing[:200]:
    print(e)
if not all_missing:
    print('All checked metadata appears in EML outputs according to the heuristic checks.')
else:
    print('\nSome metadata items are missing or mismatched. Review the list above and consider extending the parser or EML builder to preserve these fields.')

# Exit successful (do not fail the shell command so user can review results)
sys.exit(0)
