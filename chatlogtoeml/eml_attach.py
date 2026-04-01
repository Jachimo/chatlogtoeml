"""Attach a specified file to an email object"""

import os
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from typing import BinaryIO


def attach(fileobject: BinaryIO, eml: MIMEMultipart) -> MIMEMultipart:
    attachmentpart = MIMEApplication(fileobject.read(), 'octet-stream')
    attachmentpart.add_header('Content-Disposition', 'attachment', filename=os.path.basename(fileobject.name))
    eml.attach(attachmentpart)
    return eml
