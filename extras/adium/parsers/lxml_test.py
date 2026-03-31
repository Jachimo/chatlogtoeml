#!/usr/bin/env python3 -i
# Sample XML parser using Python XML ElementTree

#import xml.etree.ElementTree as ET
import lxml.etree as ET

fname = 'xmlbug (2021-11-30T22.11.00-0500).chatlog'

def get_xmlns(e):
    """Determine XML namespace of supplied Element."""
    if e.tag[0] == "{":
        uri, ignore, tag = e.tag[1:].partition("}")
    else:
        uri = None
    return '{' + uri + '}'

# Parse similarly to adium_xml.py
etree = ET.parse(fname)
root = etree.getroot()
xmlns = get_xmlns(root)
print('XML Namespace:', xmlns)

# for e in root:  # iterate over all child elements of the root
#     if e.tag == xmlns + 'message':  # Handle <message>
#         for c in e:
#             c.tag = c.tag.replace(xmlns, '')  # strip namespace from HTML elements -- doesn't seem to work
#             c.tag = ET.QName(c).localname
#             html = ET.tostring(c, encoding='unicode')
#             print(f'Tag: {c.tag}\nText: {c.text}\nHTML: {html}\n')

for e in root.findall(xmlns + 'message'):
    e.tag = ET.QName(e).localname
    html = ET.tostring(e, encoding='unicode')
    print(f'Tag: {e.tag}\nText: {e.text}\nHTML: {html}\n')
