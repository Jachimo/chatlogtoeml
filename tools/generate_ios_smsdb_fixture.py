import sqlite3
from pathlib import Path
import base64
import datetime

# Define paths
sms_db_path = Path('testdata/ios/sms.db')
attachments_dir = Path('testdata/ios/Attachments/00/')
attachments_dir.mkdir(parents=True, exist_ok=True)

# Create SQLite database
conn = sqlite3.connect(sms_db_path)
cursor = conn.cursor()

# Create tables
cursor.executescript("""
CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
CREATE TABLE message (ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, handle_id INTEGER, is_from_me INTEGER, date INTEGER, cache_roomnames TEXT, reply_to_guid TEXT, associated_message_guid TEXT, associated_message_type TEXT);
CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, guid TEXT);
CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
CREATE TABLE attachment (ROWID INTEGER PRIMARY KEY, file_name TEXT, mime_type TEXT);
CREATE TABLE message_attachment_join (message_id INTEGER, attachment_id INTEGER);
""")

# Insert sample data
conversations = [
    ('1:1 SMS', 'Hello!', '1', 1, datetime.datetime.now().timestamp()),
    ('1:1 iMessage', 'Hi there!', '2', 1, datetime.datetime.now().timestamp()),
    ('Group iMessage', 'Group chat message', '3', 1, datetime.datetime.now().timestamp()),
    ('Reply message', 'Reply to this message', '2', 0, datetime.datetime.now().timestamp()),
]
for text, guid, handle_id, is_from_me, date in conversations:
    cursor.execute("INSERT INTO message (guid, text, handle_id, is_from_me, date) VALUES (?, ?, ?, ?, ?)", (guid, text, handle_id, is_from_me, int(date)))

# Insert attachments
files = [{'name': 'hello.txt', 'mime': 'text/plain'}, {'name': 'pixel.png', 'mime': 'image/png'}]
for file in files:
    cursor.execute("INSERT INTO attachment (file_name, mime_type) VALUES (?, ?)", (file['name'], file['mime']))
    # Join messages and attachments as needed

conn.commit()
conn.close()
