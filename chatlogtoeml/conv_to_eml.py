# Convert a Conversation object (see conversation.py) to an email.mime.multipart object

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
import hashlib
import json as _json
import datetime
import email.encoders
from email.utils import format_datetime, formataddr
import html as _html
import re
import logging
import unicodedata

from . import conversation


# CSS for styling the HTML part of the message
import os as _os
_DEFAULT_CSS = """<style type = text/css>
.name {
  font-weight: bold;
  color: black;
}
.localname {
  font-weight: bold;
  color: blue;
}
.remotename {
  font-weight: bold;
  color: red;
}
.timestamp {
  font-size: 10pt;
  color: grey;
}
.reactions {
  margin-top: 4px;
  font-size: 0.9em;
  color: #333;
}
.reaction {
  display: inline-block;
  margin-right: 6px;
  padding: 2px 6px;
  border-radius: 12px;
  background: #f0f0f0;
  color: #111;
  font-size: 0.9em;
  border: 1px solid #ddd;
}
</style>"""


def _load_css() -> str:
    """Load converted.css from common locations with a safe built-in fallback."""
    here = _os.path.dirname(_os.path.abspath(__file__))
    candidates = [
        _os.path.join(here, 'converted.css'),
        _os.path.join(_os.path.dirname(here), 'converted.css'),
        _os.path.join(_os.getcwd(), 'converted.css'),
    ]
    for path in candidates:
        try:
            with open(path, 'r') as cssfile:
                data = cssfile.read()
            if data.strip():
                return data
        except Exception:
            continue
    logging.warning('Unable to load converted.css from expected paths; using built-in default CSS.')
    return _DEFAULT_CSS


css = _load_css()

# Regex for matching CSS to strip when --strip-background argument is used
bgcssregex = re.compile(r'(?:background(?:-color)?\s*:\s*[^;]+;)', re.I)


def _determine_fakedomain(conv: conversation.Conversation) -> str:
    """Derive a pseudo-domain from the originating DB basename when available.

    - If conv.source_db_basename contains 'sms' or 'sms.db' -> 'sms.imessage.invalid'
    - If it contains 'chat' or 'chat.db' -> 'chat.imessage.invalid'
    - Otherwise fall back to '<service>.<imclient>.invalid'
    """
    import os
    try:
        basename = ''
        if getattr(conv, 'source_db_basename', None):
            basename = str(conv.source_db_basename).lower()
        elif getattr(conv, 'origfilename', None):
            basename = os.path.basename(conv.origfilename).lower()
    except Exception:
        basename = ''
    if basename:
        if 'sms.db' in basename or basename.startswith('sms'):
            return 'sms.imessage.invalid'
        if 'chat.db' in basename or basename.startswith('chat'):
            return 'chat.imessage.invalid'
    svc = (conv.service or 'conversation').lower()
    cl = (conv.imclient or 'client').lower()
    return f'{svc}.{cl}.invalid'


def _is_imessage_conversation(conv: conversation.Conversation) -> bool:
    service = (conv.service or '').lower()
    if service == 'imessage':
        return True
    try:
        basename = (getattr(conv, 'source_db_basename', '') or '').lower()
    except Exception:
        basename = ''
    if basename.startswith('sms') or basename.startswith('chat'):
        return True
    return False


def _subject_participant_name(conv: conversation.Conversation, local_participant: conversation.Participant) -> str:
    """Pick a human-friendly participant name for Subject."""
    others = [p for p in conv.participants if p.userid != local_participant.userid]
    chosen = others[0] if others else local_participant
    if chosen.realname:
        return chosen.realname
    if chosen.userid:
        return chosen.userid
    return ''


def _ascii_header_text(value: str) -> str:
    """Normalize header text to ASCII to avoid RFC2047 encoded-word output."""
    if value is None:
        return ''
    normalized = unicodedata.normalize('NFKD', str(value))
    ascii_text = normalized.encode('ascii', 'ignore').decode('ascii')
    ascii_text = ascii_text.replace('\r', ' ').replace('\n', ' ')
    ascii_text = ' '.join(ascii_text.split())
    return ascii_text.strip()


def _ascii_display_name(value: str) -> str:
    """ASCII-only display name for address headers."""
    name = _ascii_header_text(value)
    if not name:
        return ''
    # Remove quote/backslash noise before formataddr applies safe quoting.
    return name.replace('"', '').replace('\\', '').strip()


def _subject_name_from_handle(value: str) -> str:
    """Derive a readable subject token from a handle/email-like value."""
    text = _ascii_header_text(value)
    if not text:
        return ''
    if '@' in text:
        text = text.split('@', 1)[0]
    # Strip non-alnum characters (e.g. '+' from phone numbers).
    text = re.sub(r'[^A-Za-z0-9 ]+', '', text)
    text = ' '.join(text.split())
    return text.strip()


def _pseudo_localpart_from_handle(value: str) -> str:
    """Build an RFC-safe local-part from a non-email handle."""
    text = _ascii_header_text(value)
    if not text:
        return 'unknown'
    lower = text.lower()
    for prefix in ('tel:', 'sms:', 'mailto:', 'im:'):
        if lower.startswith(prefix):
            text = text[len(prefix):]
            lower = text.lower()
            break
    # keep ASCII alnum plus a minimal safe subset for local-part readability
    text = re.sub(r'[^A-Za-z0-9._-]+', '', text)
    if not text:
        return 'unknown'
    return text


def _format_header_address(userid: str, realname: str, fakedomain: str) -> str:
    uid = _ascii_header_text(userid)
    if '@' in uid:
        addr = uid
    else:
        addr = _pseudo_localpart_from_handle(uid) + '@' + fakedomain
    disp = _ascii_display_name(realname)
    if disp:
        return formataddr((disp, addr))
    # No contact name available: fall back to a readable handle token (e.g., phone digits).
    fallback_disp = _subject_name_from_handle(uid)
    if fallback_disp:
        return formataddr((fallback_disp, addr))
    return formataddr((addr, addr))


def _make_message_index_part(conv: conversation.Conversation):
    """Build a MIME attachment containing a JSON index of message GUIDs for this segment.

    Returns a ``(MIMEBase part, sha256_hex)`` tuple, or ``(None, None)`` when no
    non-empty GUIDs are available (e.g. legacy Adium logs that predate GUID tracking).

    The JSON payload schema::

        {
          "schema_version": 1,
          "chat_identifier": "<filenameuserid>",
          "segment_start": "<ISO-8601 or null>",
          "segment_end":   "<ISO-8601 or null>",
          "message_count": <int>,
          "guid_count":    <int>,
          "guid_sha256":   "<SHA-256 hex of sorted GUIDs joined by newline>",
          "message_guids": ["<guid1>", ...]   // chronological insertion order
        }

    ``guid_sha256`` is computed over the *sorted* GUID list so that two segments
    covering exactly the same messages always produce the same fingerprint regardless
    of the order in which messages were written.  This value is also emitted as the
    ``X-Message-Index-SHA256`` header on the outer MIME envelope for fast scanning
    without parsing the attachment body.
    """
    guids = [msg.guid for msg in conv.messages if getattr(msg, 'guid', None)]
    if not guids:
        return None, None

    sorted_guids = sorted(guids)
    digest = hashlib.sha256('\n'.join(sorted_guids).encode('utf-8')).hexdigest()

    payload = {
        'schema_version': 1,
        'chat_identifier': getattr(conv, 'filenameuserid', '') or '',
        'segment_start': conv.startdate.isoformat() if getattr(conv, 'startdate', None) else None,
        'segment_end': conv.enddate.isoformat() if getattr(conv, 'enddate', None) else None,
        'message_count': len(conv.messages),
        'guid_count': len(guids),
        'guid_sha256': digest,
        'message_guids': guids,  # chronological; use guid_sha256 for order-insensitive comparison
    }

    data = _json.dumps(payload, indent=2).encode('utf-8')
    part = MIMEBase('application', 'x-chatlogtoeml-index')
    part.set_payload(data)
    email.encoders.encode_base64(part)
    part.add_header('Content-Disposition', 'attachment', filename='chatlogtoeml-index.json')
    part.add_header('Content-ID', '<chatlogtoeml-index>')
    return part, digest


def mimefromconv(conv: conversation.Conversation, no_background: bool = False) -> MIMEMultipart:
    """Now we take the Conversation object and make a MIME email message out of it..."""
    # Do some sanity-checking on the input Conversation and skip trivial (no message contents) logs
    if not isinstance(conv, conversation.Conversation):
        error_msg = 'conv_to_eml was passed an unknown or malformed object; exiting.'
        logging.warning(error_msg)
        raise ValueError(error_msg)
    if len(conv.messages) == 0:
        error_msg = 'Conversation does not appear to contain any Messages; exiting.'
        logging.warning(error_msg)
        raise ValueError(error_msg)
    if len(conv.listparticipantuserids()) == 0:
        error_msg = 'Conversation does not have any Participants; exiting.'
        logging.warning(error_msg)
        raise ValueError(error_msg)
    if len(conv.listparticipantuserids()) == 1:
        # Allow single-participant conversations (e.g., exported threads with only local entries)
        logging.debug('Conversation has only one participant; constructing EML with that participant as both From and To.')

    # Create a base message object for the entire conversation's components
    msg_base = MIMEMultipart('related')

    # Then a sub-part for the two alternative text and HTML components
    msg_texts = MIMEMultipart('alternative')
    # Keep the body first in multipart/related for MUAs that prioritize early parts.
    msg_base.attach(msg_texts)

    fakedomain = _determine_fakedomain(conv)  # derived pseudo-domain (sms/chat or fallback svc.imclient.invalid)

    # Construct 'From' header
    # Prefer participant marked 'local', fall back to conv.localaccount or first participant
    local_participant = None
    for p in conv.participants:
        if p.position == 'local':
            local_participant = p
            break
    if not local_participant and conv.localaccount:
        local_participant = conv.get_participant(conv.localaccount)
    if not local_participant:
        local_participant = conv.participants[0]

    header_from = _format_header_address(local_participant.userid, local_participant.realname, fakedomain)
    msg_base['From'] = header_from

    # Construct 'To' header - include all other participants
    to_parts = []
    for p in conv.participants:
        if p.userid == local_participant.userid:
            continue
        to_parts.append(_format_header_address(p.userid, p.realname, fakedomain))
    if to_parts:
        msg_base['To'] = ', '.join(to_parts)
    else:
        msg_base['To'] = header_from

    # Construct 'Date' and 'Subject' headers
    if conv.filenameuserid:
        filenameuserid = conv.filenameuserid  # used parsed version if it is set (useful for Facebook logs)
    else:
        filenameuserid = conv.origfilename.split(' (')[0]
    # Determine header_date robustly; fallback to now (UTC) if necessary
    header_date = None
    try:
        if conv.startdate:
            header_date = conv.startdate
        else:
            header_date = conv.getoldestmessage().date
    except Exception:
        header_date = None
    if not header_date or not hasattr(header_date, 'timetuple'):
        header_date = datetime.datetime.now(datetime.timezone.utc)
    if conv.service:
        header_service = conv.service
    else:
        header_service = 'Conversation'
    header_withname = _subject_participant_name(conv, local_participant) or filenameuserid

    msg_base['Date'] = format_datetime(header_date)
    safe_header_service = _ascii_header_text(header_service) or 'Conversation'
    safe_header_name = _ascii_header_text(header_withname)
    if safe_header_name and (
        '@' in safe_header_name
        or safe_header_name.startswith('+')
        or re.fullmatch(r'[0-9+\-(). ]+', safe_header_name)
    ):
        safe_header_name = _subject_name_from_handle(safe_header_name)
    if not safe_header_name:
        safe_header_name = _subject_name_from_handle(header_withname)
    if safe_header_name and safe_header_name == _ascii_header_text(filenameuserid) and to_parts:
        first_to = next((p for p in conv.participants if p.userid != local_participant.userid), local_participant)
        to_name = _subject_name_from_handle(first_to.userid or '')
        if to_name:
            safe_header_name = to_name
    if not safe_header_name and to_parts:
        # fall back to the first destination participant when no better name is available
        first_to = next((p for p in conv.participants if p.userid != local_participant.userid), local_participant)
        safe_header_name = _subject_name_from_handle(first_to.userid or '')
    if not safe_header_name:
        safe_header_name = _subject_name_from_handle(local_participant.userid or '')
    if not safe_header_name:
        safe_header_name = _ascii_header_text(filenameuserid)
    safe_header_id = _ascii_header_text(filenameuserid)
    if _is_imessage_conversation(conv) and safe_header_id:
        msg_base['Subject'] = f'{safe_header_service} with {safe_header_name} #{safe_header_id} on {header_date.strftime("%a, %b %e %Y")}'
    else:
        msg_base['Subject'] = f'{safe_header_service} with {safe_header_name} on {header_date.strftime("%a, %b %e %Y")}'

    # Determine date format to use in logs - be robust to missing dates
    try:
        youngest = conv.getyoungestmessage().date
        oldest = conv.getoldestmessage().date
        if youngest and oldest and (youngest - oldest) > datetime.timedelta(days=1):
            datefmt = '%D %r'
        else:
            datefmt = '%r'
    except Exception:
        datefmt = '%r'

    # produce a text version of the messages
    text_lines = []
    for msg in conv.messages:
        line_parts = []
        if msg.type == 'message':  # formatting for most lines
            if msg.date:
                line_parts.append('(' + msg.date.strftime(datefmt) + ')')
            if msg.msgfrom:
                if conv.get_realname_from_userid(msg.msgfrom):
                    line_parts.append(f'{conv.get_realname_from_userid(msg.msgfrom)} [{msg.msgfrom}]:')
                else:
                    line_parts.append(f'{msg.msgfrom}:')
            line_parts.append(msg.text)
            text_lines.append(' '.join(line_parts))
        if msg.type == 'event':  # Don't put the msgfrom section on system messages, it looks dumb
            if msg.date:
                line_parts.append('(' + msg.date.strftime(datefmt) + ')')
            line_parts.append(msg.text)
            text_lines.append(' '.join(line_parts))
    mimetext = MIMEText('\n'.join(text_lines), 'plain')
    msg_texts.attach(mimetext)  # Attach the plaintext component as one part of (multipart/alternative)

    # Construct html_lines the same way to produce HTML version
    html_lines = []
    html_lines.append('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">')
    html_lines.append('<html>')
    css_use = css
    if no_background:
        try:
            css_use = re.sub(bgcssregex, '', css)
        except Exception:
            css_use = css
    html_lines.append('<head>\n' + css_use + '\n</head>')  # see css at top of this file
    html_lines.append('<body>')
    for message in conv.messages:
        if message.type == 'event':  # this is for system messages, etc.
            line = []
            line.append('<p class="system_message">')
            if message.date:
                line.append('<span class="timestamp">')
                line.append('(' + message.date.strftime(datefmt) + ')&nbsp;')
                line.append('</span>')
            if message.html:
                # If message exists as HTML, pass it through
                line.append('<span class="message_text">')
                line.append(message.html)
                line.append('</span>')
            elif message.text:
                line.append('<span class="message_text">')
                line.append(message.text.replace('\n', '<br>'))  # convert any LFs in message text to <br>s
                line.append('</span>')
            line.append('</p>')
            html_lines.append(''.join(line))
        else:  # for regular messages
            line = []
            line.append('<p class="message">')
            if message.date:
                line.append('<span class="timestamp">')
                line.append('(' + message.date.strftime(datefmt) + ')&nbsp;')
                line.append('</span>')
            if message.msgfrom:
                if conv.userid_islocal(message.msgfrom):   # for local participant CSS
                    line.append('<span class="localname" style="font-weight: bold; color: blue;">')
                elif conv.userid_isremote(message.msgfrom):  # for remote participant CSS
                    line.append('<span class="remotename" style="font-weight: bold; color: red;">')
                else:
                    line.append('<span class="name" style="font-weight: bold; color: black;">')  # catchall for indeterminate participants
                if conv.get_realname_from_userid(message.msgfrom):
                    line.append(conv.get_realname_from_userid(message.msgfrom) + ':&ensp;')
                else:
                    line.append(message.msgfrom + ':&ensp;')
                line.append('</span>')
            if message.html:  # If message exists as HTML, pass it through
                line.append('<span class="message_text">')
                if no_background:  # strip background-color, e.g. "background-color: #acb5bf;"
                    line.append(re.sub(bgcssregex, '', message.html))  # see regex at top of file
                else:
                    line.append(message.html)
                line.append('</span>')
            elif message.text:  # If there's no HTML provided, create it from text and styling information
                line.append('<span')
                if message.textfont or message.textsize or message.textcolor or message.bgcolor:
                    # only if needed, we add a style attribute to the message text...
                    line.append(' style="')
                    if message.textfont:
                        line.append('font-family: ' + message.textfont + '; ')
                    if message.textsize:
                        line.append('font-size: ' + str(int(message.textsize)) + 'pt; ')
                    if message.textcolor:
                        line.append('color: ' + message.textcolor + '; ')
                    if message.bgcolor and (not no_background):
                        line.append('background-color: ' + message.bgcolor + '; ')
                    line.append('"')
                line.append(' class="message_text">')
                line.append(message.text.replace('\n', '<br>'))  # convert any LFs in message text to <br>s
                line.append('</span>')
            if message.attachments:  # if the message has an Attachment, then we need to process it...
                for att in message.attachments:  # in theory there could be >1 attachment per msg, but in practice rare
                    is_inline_image = isinstance(att.mimetype, str) and att.mimetype.lower().startswith('image/')
                    if is_inline_image:
                        safe_name = _html.escape(att.name or 'image', quote=True)
                        line.append(
                            '\n<br><span class="attachment_image"><img src="cid:'
                            + att.contentid
                            + '" alt="'
                            + safe_name
                            + '" style="max-width: min(100%, 640px); height: auto; display: block; margin-top: 6px;"></span>'
                        )
                    line.append('\n<br><span class="attachment">Attachment:&nbsp;<a href="cid:'
                                + att.contentid + '">' + att.name + '</a></span>')
                    if att.data:
                        # determine mime main/sub
                        mime_main = 'application'
                        mime_sub = 'octet-stream'
                        if isinstance(att.mimetype, str) and '/' in att.mimetype:
                            try:
                                mime_main, mime_sub = att.mimetype.split('/', 1)
                            except Exception:
                                mime_main, mime_sub = 'application', 'octet-stream'
                        attachment_part = MIMEBase(mime_main, mime_sub)
                        attachment_part.set_payload(att.data)
                        email.encoders.encode_base64(attachment_part)  # BASE64 for attachments
                        if is_inline_image:
                            attachment_part.add_header('Content-Disposition', 'inline', filename=att.name)
                        else:
                            attachment_part.add_header('Content-Disposition', 'attachment', filename=att.name)
                        attachment_part.add_header('Content-ID', '<' + att.contentid + '>')
                        if att.mimetype:
                            try:
                                attachment_part.add_header('Content-Type', att.mimetype, name=att.name)
                            except Exception as e:
                                logging.debug('Failed to set attachment Content-Type header (%s, %s): %s', att.name, att.mimetype, e)
                        msg_base.attach(attachment_part)  # attach to the top-level object, multipart/related
                    else:
                        # No binary payload to attach. If original path is known, add a header to indicate missing payload
                        if getattr(att, 'orig_path', None):
                            try:
                                msg_base.add_header('X-Original-Attachment-Path', att.orig_path)
                            except Exception:
                                logging.debug('Failed to add X-Original-Attachment-Path header for %s', att.orig_path)
            line.append('</p>')
            html_lines.append(''.join(line))  # join line components without spaces
    html_lines.append('</body>')
    html_lines.append('</html>')
    mimehtml = MIMEText('\n'.join(html_lines), 'html')  # join lines with \n chars
    msg_texts.attach(mimehtml)  # Attach the html component as second half of (multipart/alternative)

    # The References header is a hash of the sorted participants list, allowing MUA to thread Conversations together
    msg_base['References'] = ('<' + hashlib.md5(
        ' '.join(sorted(conv.listparticipantuserids())).lower().encode('utf-8')).hexdigest() + '@' + fakedomain + '>')

    # Create Message-ID by hashing the text content (allows for duplicate detection); note headers are NOT hashed
    msg_base['Message-ID'] = ('<' + hashlib.md5(
        msg_base['Date'].encode('utf-8') + msg_base['Subject'].encode('utf-8')
        + '\n'.join(text_lines).encode('utf-8')).hexdigest() + '@' + fakedomain + '>')

    # Set additional headers (comment out if not desired)
    msg_base['X-Converted-On'] = datetime.datetime.now().strftime('%a, %d %b %Y %T %z')
    msg_base['X-Original-File'] = conv.origfilename

    # Attach a GUID index for future message-level deduplication.
    # The companion X-Message-Index-SHA256 header lets scanners skip attachment parsing
    # when doing a quick fingerprint comparison across an archive.
    _index_part, _index_sha256 = _make_message_index_part(conv)
    if _index_part is not None:
        msg_base['X-Message-Index-SHA256'] = _index_sha256
        msg_base.attach(_index_part)

    return msg_base
