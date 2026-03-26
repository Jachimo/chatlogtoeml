# Convert a Conversation object (see conversation.py) to an email.mime.multipart object

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
import hashlib
import datetime
import email.encoders
from email.utils import format_datetime
import re
import logging

from . import conversation


# CSS for styling the HTML part of the message
import os as _os
_cssfile = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'converted.css')
try:
    with open(_cssfile, 'r') as cssfile:
        css = cssfile.read()
except Exception:
    css = ''

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
        logging.warning('Conversation has only one participant; constructing EML with that participant as both From and To.')

    # Create a base message object for the entire conversation's components
    msg_base = MIMEMultipart('related')

    # Then a sub-part for the two alternative text and HTML components
    msg_texts = MIMEMultipart('alternative')

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

    if '@' in local_participant.userid:
        header_from_userid = local_participant.userid
    else:
        header_from_userid = local_participant.userid + '@' + fakedomain
    if local_participant.realname:
        header_from = f'"{local_participant.realname}" <{header_from_userid}>'
    else:
        header_from = f'"{header_from_userid}" <{header_from_userid}>'
    msg_base['From'] = header_from

    # Construct 'To' header - include all other participants
    to_parts = []
    for p in conv.participants:
        if p.userid == local_participant.userid:
            continue
        if '@' in p.userid:
            header_to_userid = p.userid
        else:
            header_to_userid = p.userid + '@' + fakedomain
        if p.realname:
            to_parts.append(f'"{p.realname}" <{header_to_userid}>')
        else:
            to_parts.append(f'"{header_to_userid}" <{header_to_userid}>')
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
    if conv.get_realname_from_userid(filenameuserid):
        header_withname = conv.get_realname_from_userid(filenameuserid)
    else:
        header_withname = filenameuserid

    msg_base['Date'] = format_datetime(header_date)
    msg_base['Subject'] = f'{header_service} with {header_withname} on {header_date.strftime("%a, %b %e %Y")}'

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
    mimetext = MIMEText('\n'.join(text_lines), 'text')
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
                    line.append('<span class="localname">')
                elif conv.userid_isremote(message.msgfrom):  # for remote participant CSS
                    line.append('<span class="remotename">')
                else:
                    line.append('<span class="name">')  # catchall for indeterminate participants
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
                        attachment_part.add_header('Content-Disposition', 'attachment', filename=att.name)
                        attachment_part.add_header('Content-ID', '<' + att.contentid + '>')
                        if att.mimetype:
                            try:
                                attachment_part.add_header('Content-Type', att.mimetype, name=att.name)
                            except Exception:
                                pass
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

    # Attach the (multipart/related) component to the root
    msg_base.attach(msg_texts)
    return msg_base
