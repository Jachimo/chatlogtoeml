#!/usr/bin/env python3 -i
# Example of parsing an Adium XML chatlog with Python minidom

import xml.dom.minidom

fname = 'xmlbug (2021-11-30T22.11.00-0500).chatlog'

dom = xml.dom.minidom.parse(fname)
chat = dom.firstChild  # root should always be <chat>

account = chat.getAttribute('account')
service = chat.getAttribute('service')
print(f'Chat account: {account}\nChat service: {service}')


# Utility function for getting inner text of nested elements
#  Inspired by suggestion from Manlio Perillo on python-list@python.org
#  Message-ID: <s3lbp093s95onf1tclrvkese1gfoa07m3v@4ax.com>
def get_inner_text(node):
    """Get all text associated with node and its children"""
    textlist = ['']
    for n in node.childNodes:
        if n.nodeName == '#text':
            textlist.append(n.data)
        else:
            textlist.append(get_inner_text(n))
    return ''.join(textlist)


# Accessing all 1st-level elements
for e in chat.childNodes:
    if e.nodeName == 'event':
        type = e.getAttribute('type')
        sender = e.getAttribute('sender')
        time = e.getAttribute('time')
        print(f'Found {type} event sent by {sender} at {time}')
    if e.nodeName == 'status':
        type = e.getAttribute('type')
        sender = e.getAttribute('sender')
        time = e.getAttribute('time')
        print(f'Found {type} status sent by {sender} at {time}')
    if e.nodeName == 'message':
        sender = e.getAttribute('sender')
        time = e.getAttribute('time')
        htmlcontent = e.firstChild.toxml()
        print(f'Found message sent by {sender} at {time}\n    HTML: {htmlcontent}')
        text = get_inner_text(e)
        print(f'    TEXT: {text}')

# Accessing <message> elements exclusively:
# messages = dom.getElementsByTagName('message')
# print('Document contains', len(messages), 'messages')
# for message in messages:
#     sender = message.getAttribute('sender')
#     time = message.getAttribute('time')
#     value = message.nodeValue
#     htmlcontent = message.firstChild.toxml()
#     print(f'Sender: {sender}\nTime: {time}\nHTML: {htmlcontent}')
