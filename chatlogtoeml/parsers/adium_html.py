# Utility functions for processing old Adium HTML-based log files

import logging
import datetime
import os
import pytz  # type: ignore[import-untyped]
from typing import TextIO
import re

from .. import conversation

doctype: str = '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">\n'
localtz: str = 'America/New_York'  # timezone that chat logs were created in (since no tz in HTML logs)
tags: re.Pattern = re.compile('<.*?>')  # For better regex performance


def toconv(fi: TextIO) -> conversation.Conversation:
    """Convert old-style .AdiumHTMLLog file to a Conversation object"""
    conv: conversation.Conversation = conversation.Conversation()
    conv.imclient = 'Adium'  # since we are only parsing Adium logs with this module
    conv.origfilename = os.path.basename(fi.name)  # Set it on the Conversation object for future reference

    # Parse the first line of the input file for start date
    conv.startdate = get_filename_date(fi.readline(), conv.origfilename)  # Only start date is set
    logging.debug(f'Start date set to {conv.startdate}')

    # If possible, determine the IM service based on the grandparent folder name if hierarchy is either:
    #  /path/to/Adium Logs/AIM.myaccountname/theiraccountname/theiraccountname (date).AdiumHTMLLog
    #  /path/to/Adium/Logs*/AIM.myaccountname/theiraccountname/theiraccountname (date).AdiumHTMLLog
    filepathlist = os.path.realpath(fi.name).split(os.path.sep)
    if (filepathlist[-4] == 'Adium Logs') or (filepathlist[-4].find('Logs') == 0 and filepathlist[-5] == 'Adium'):
        # We can *probably* assume we're in the Adium Logs tree...
        conv.service = filepathlist[-3].split('.', 1)[0]
        conv.localaccount  = filepathlist[-3].split('.', 1)[1]
        conv.remoteaccount = filepathlist[-2]

    fi.seek(0)
    divs = fi.read().split('</div>\n')  # Split by <div>
    for div in divs:
        logging.debug(f'DIV: {div}')
        if 'class="receive"' in div:  # probably a received message
            msg = conversation.Message('message')  # Create Message object
            logtime = getlinecontent(div, '<span class="timestamp">', '</span>')  # note this is time ONLY
            msg.date = make_msg_time(logtime, conv.startdate)  # create datetime object for message
            msg.msgfrom = getlinecontent(div, '<span class="sender">', ': </span>').split(' ')[0]
            conv.add_participant(msg.msgfrom)
            conv.set_remote_account(msg.msgfrom)
            msg.html = getlinecontent(div, '<pre class="message">', '</pre>')
            msg.text = striphtml(msg.html)
            conv.add_message(msg)
        elif 'class="send"' in div:  # probably a transmitted message
            msg = conversation.Message('message')
            logtime = getlinecontent(div, '<span class="timestamp">', '</span>')
            msg.date = make_msg_time(logtime, conv.startdate)  # create datetime object for message
            msg.msgfrom = getlinecontent(div, '<span class="sender">', ': </span>')
            conv.add_participant(msg.msgfrom)
            conv.set_local_account(msg.msgfrom)
            msg.html = getlinecontent(div, '<pre class="message">', '</pre>')
            msg.text = striphtml(msg.html)
            conv.add_message(msg)
        elif 'class="status"' in div:  # status message (can be multiline)
            msg = conversation.Message('event')
            try:
                logtime = div.rsplit('(')[-1].strip(')')  # this is fairly fragile
                msg.date = make_msg_time(logtime, conv.startdate)  # create datetime object for message
            except ValueError:
                logging.debug(f'Error while parsing log time value: {logtime}')
                pass
            msg.msgfrom = 'System Message'
            msg.text = getlinecontent(div, '<div class="status">', ' (')
            msg.html = msg.text.replace('\n', '<br>\n')
            conv.add_message(msg)
    # If there are less than two Participants in the Conversation, pad it with 'UNKNOWN' to prevent errors later
    if len(conv.participants) < 2:
        conv.add_participant('UNKNOWN')
        conv.add_realname_to_userid('UNKNOWN', 'Unknown User')
    return conv


def striphtml(text: str) -> str:
    """Remove html tags from a string"""
    # See https://medium.com/@jorlugaqui/how-to-strip-html-tags-from-a-string-in-python-7cb81a2bbf44
    return re.sub(tags, '', text)


def make_msg_time(logtime: str, convdateobj: datetime.datetime) -> datetime.datetime:
    """Take a time-only string (like '12:01:48 AM') and combine with date from conv.startdate to produce datetime"""
    # TODO may not handle logs that cross midnight very well...
    try:
        time = datetime.datetime.strptime(logtime, '%I:%M:%S %p')  # format is usually '12:01:48 AM'
    except ValueError:
        time = datetime.datetime.strptime(logtime, '%H:%M:%S')  # if that doesn't work, try %H:%M:%S
    dt = datetime.datetime.combine(convdateobj.date(), time.time())
    mytz = pytz.timezone(localtz)  # set the log's timezone at the top of this file
    return mytz.localize(dt)


def get_filename_date(line: str, filename: str) -> datetime.datetime:
    """Determine the date and time of an old-style Adium log, using a single
    line (typically the first), and the filename.
    """
    # Date we can determine from the log file's filename
    logdate = getlinecontent(filename, "(", ")")
    logging.debug(f'Filename date is {logdate}')

    # We must determine time from inside the log
    if '<span class="timestamp">' in line:
        logtime = getlinecontent(line, '<span class="timestamp">', '</span>')
    if '<div class="status">' in line:
        logtime = getlinecontent(line, ' (', ')</div>')
    logging.debug(f'Log time is {logtime}')

    # Turn it into a datetime object
    try:
        d = datetime.datetime.strptime(logdate + ' ' + logtime, '%Y-%m-%d %I:%M:%S %p')
    except ValueError:
        # if that date format (most common) doesn't work, try differently:
        try:
            d = datetime.datetime.strptime(logdate + ' ' + logtime, '%Y|%m|%d %H:%M:%S')
        except ValueError:
            # if that doesnt work either, try a 3rd time, this time without AM/PM flag
            d = datetime.datetime.strptime(logdate + ' ' + logtime, '%Y-%m-%d %H:%M:%S')

    # Last but not least, set the timezone as we return the datetime object
    mytz = pytz.timezone(localtz)  # set the log's timezone at the top of this file
    return mytz.localize(d)


def getparticipants(fi: TextIO) -> list:
    """Determine the participants in an old-style Adium HTML log, using the log
    as a file object, and return a list of strings.
    """
    participants = []
    fi.seek(0)  # make sure we are at the beginning of the file

    for line in fi:
        if '<div class="receive">' in line:
            participants.append(getlinecontent(line, '<span class="sender">', ': </span>'))
        if '<div class="send">' in line:
            participants.append(getlinecontent(line, '<span class="sender">', ': </span>'))
    return participants


def getlinecontent(line: str, startstring: str, endstring: str) -> str:
    if (startstring in line) and (endstring in line):
        return line[line.find(startstring) + len(startstring): line.find(endstring)]
    else:
        return ''
