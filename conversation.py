# Classes for instant messaging "conversations"
#  Inspired by the data model used by https://github.com/kadin2048/ichat_to_eml
#  Uses type hints and requires Python 3.6+

from datetime import datetime  # for hints
import hashlib
import copy


class Conversation:
    """Top-level class for holding instant messaging Conversations"""
    def __init__(self):
        self.origfilename: str = ''  # Originating file name (where conversation was parsed from)
        self.filenameuserid: str = ''  # User ID from the filename, sometimes parsed
        self.imclient: str = ''  # IM client program: Adium, iChat, etc.
        self.service: str = ''  # messaging service: AIM, iChat, MSN, etc.
        self.localaccount: str = ''  # userid of local IM account
        self.remoteaccount: str = ''  # userid of remote IM account
        self.participants: list = []  # List of Participant objects
        self.startdate: datetime = False
        self.enddate: datetime = False
        self.messages: list = []  # List of Message objects
        self.hasattachments: bool = False  # Flag to indicate that 1 or more message contains an attachment

    def add_participant(self, userid):
        # Avoid duplicates (case-insensitive)
        if not any(p.userid.lower() == (userid or '').lower() for p in self.participants):
            p = Participant(userid)
            self.participants.append(copy.deepcopy(p))
        try:
            if self.localaccount and userid and userid.lower() == self.localaccount.lower():
                self.set_local_account(userid)
            if self.remoteaccount and userid and userid.lower() == self.remoteaccount.lower():
                self.set_remote_account(userid)
        except Exception:
            pass

    def get_participant(self, userid):
        for p in self.participants:
            if p.userid and userid and p.userid.lower() == userid.lower():
                return p

    def listparticipantuserids(self) -> list:
        userids = []
        for p in self.participants:
            userids.append(p.userid)
        return userids

    def add_realname_to_userid(self, userid, realname):
        for p in [p for p in self.participants if p.userid and userid and p.userid.lower() == userid.lower()]:
            p.realname = realname

    def add_systemid_to_userid(self, userid, systemid):
        for p in [p for p in self.participants if p.userid and userid and p.userid.lower() == userid.lower()]:
            p.systemid = systemid

    def get_realname_from_userid(self, userid) -> str:
        for p in [p for p in self.participants if p.userid and userid and p.userid.lower() == userid.lower()]:
            return p.realname  # returns '' if not previously set using add_realname_to_userid()
        return ''

    def add_message(self, message):
        self.messages.append(message)

    def getoldestmessage(self):
        return sorted(self.messages)[0]

    def getyoungestmessage(self):
        return sorted(self.messages)[-1]

    def set_local_account(self, userid):
        self.localaccount = userid
        for p in self.participants:
            try:
                if p.userid and userid and p.userid.lower() == userid.lower():
                    p.position = 'local'
            except Exception:
                pass

    def set_remote_account(self, userid):
        self.remoteaccount = userid
        for p in self.participants:
            try:
                if p.userid and userid and p.userid.lower() == userid.lower():
                    p.position = 'remote'
            except Exception:
                pass

    def userid_islocal(self, userid) -> bool:
        for p in self.participants:
            if p.userid and userid and p.userid.lower() == userid.lower():
                return p.position == 'local'
        return False

    def userid_isremote(self, userid) -> bool:
        for p in self.participants:
            if p.userid and userid and p.userid.lower() == userid.lower():
                return p.position == 'remote'
        return False


class Participant:
    """Represents a single participant in a conversation; conversations may have 1 to many participants"""
    def __init__(self, userid):
        self.userid: str = userid
        self.realname: str = ''
        self.systemid: str = ''
        self.position: str = ''  # either 'local' or 'remote'


class Message:
    """Represents a single message sent by one Participant to another in a Conversation"""
    def __init__(self, type):
        self.type: str = type  # types: 'message' or 'event'
        self.guid: str = ''
        self.msgfrom: str = ''
        self.msgto: str = ''
        self.date: datetime = ''
        self.text: str = ''  # text version of the message
        self.textfont: str = ''  # font to display text version
        self.textsize: str = ''  # size to display text version
        self.textcolor: str = ''  # color to display text version
        self.bgcolor: str = ''  # background/highlight color to display text version
        self.html: str = ''  # HTML version of the message
        self.attachments: list = []  # List of Attachment objects (optional)

    def __eq__(self, other):
        """Define equality for purposes of sorting"""
        if self.guid and other.guid:  # if GUIDs are present on both, depend on them for equivalency
            return self.guid == other.guid
        else:
            return self.__dict__ == other.__dict__  # Otherwise, look at dictionaries

    def __lt__(self, other):
        """Define less-than for purposes of sorting Message lists (sorted by date).
        Handle missing (None) dates gracefully.
        """
        try:
            if self.date is None and other.date is None:
                return False
            if self.date is None:
                return True
            if other.date is None:
                return False
            return self.date < other.date
        except Exception:
            # Fallback to dict-wise comparison to avoid raising during sort
            return str(self.__dict__) < str(other.__dict__)


class Attachment:
    """Represents an optional attachment that can be carried by a Message"""
    def __init__(self):
        self.name: str = ''
        self.data = b''
        self.contentid: str = ''
        self.mimetype: str = ''

    def gen_contentid(self):
        """Generate a contentID hash from the attachment data and metadata.
        Use data, name, and mimetype so that metadata-only attachments produce different IDs.
        """
        hasher = hashlib.md5()
        try:
            if isinstance(self.data, bytes):
                hasher.update(self.data)
            else:
                hasher.update(b"" if self.data is None else str(self.data).encode('utf-8'))
        except Exception:
            try:
                hasher.update(b"" if self.data is None else bytes(self.data))
            except Exception:
                pass
        try:
            hasher.update((self.name or '').encode('utf-8'))
        except Exception:
            pass
        try:
            hasher.update((self.mimetype or '').encode('utf-8'))
        except Exception:
            pass
        self.contentid = hasher.hexdigest()

    def set_payload(self, bindata):
        """Set the binary payload of the attachment"""
        self.data = bindata
        self.gen_contentid()
