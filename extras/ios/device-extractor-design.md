# iOS Device Extractor — Design Document

**Purpose:** Describe the design for a new `extras/ios/` toolchain that allows a Linux
user to plug an iPhone into their computer, create an iTunes-compatible backup, extract
`sms.db` and its `Attachments/` tree, and feed them directly into the existing
`bin/db_to_eml` converter — all without macOS or a jailbreak.

This document is intended as an implementation specification that can be handed directly
to a developer or a small LLM for coding.

---

## 1. Background and Constraints

### 1.1 Why Linux cannot directly read the iPhone filesystem

iOS enforces the **AFC (Apple File Conduit)** protocol over USB. The general-purpose AFC
service only exposes the media partition (photos, media). The SMS database lives on the
protected data partition and is inaccessible via AFC without jailbreaking.

The only sanctioned exit path for `sms.db` on a non-jailbroken device is through the
**MobileBackup2** protocol — the same protocol used by iTunes/Finder. This protocol is
fully implemented on Linux via [`libimobiledevice`](https://github.com/libimobiledevice/libimobiledevice)
and its `idevicebackup2` utility.

### 1.2 What an iTunes backup looks like on disk

A backup directory (named by the device UDID) contains:

```
<UDID>/
  Info.plist          # device metadata
  Manifest.plist      # backup-level settings, encryption flag
  Manifest.db         # SQLite index: filename → hash → domain
  Status.plist        # backup completion status
  <xx>/               # 256 subdirs named by first 2 hex chars of SHA1
    <sha1hash>        # actual backup file payload (no extension)
```

`sms.db` is stored under a hash that is **stable across backups** for a given iOS
version. The canonical SHA1 for `Library/SMS/sms.db` in `HomeDomain` is:

```
3d0d7e5fb2ce288813306e4d4636395e047a3d28
```

→ stored at `<UDID>/3d/3d0d7e5fb2ce288813306e4d4636395e047a3d28`

However, **do not hard-code this hash**. Always query `Manifest.db` (see §4.2).

For **encrypted** backups the file payloads are AES-256-CBC encrypted and cannot be read
directly. The `iphone-backup-decrypt` Python library handles decryption (see §3.2).

### 1.3 Scope of this design

This design covers:

- A shell wrapper script `extras/ios/ios_extract.sh` — the primary user-facing entry point
- A Python helper `extras/ios/ios_extract.py` — handles all backup-format logic
- Integration with the existing `bin/db_to_eml` pipeline (no changes to `db_to_eml`)
- Both **encrypted** and **unencrypted** backup paths
- Attachment extraction mirroring the directory structure `db_to_eml --attachment-root` expects

Out of scope for this document:

- Jailbroken device extraction (different path entirely)
- Windows or macOS (both have native tooling; this is Linux-only)
- Wi-Fi backup (same libimobiledevice protocol; straightforward extension)
- Full backup restore

---

## 2. System Dependencies

These must be installed on the Linux host before the toolchain can run.

### 2.1 C libraries and system packages (apt/dnf/pacman)

| Package | Purpose |
|---|---|
| `libimobiledevice-utils` | Provides `idevicebackup2`, `idevicepair`, `idevice_id` |
| `usbmuxd` | USB multiplexer daemon that routes device connections |
| `libimobiledevice6` or `libimobiledevice` | Runtime library |
| `python3` (≥3.9) | Same requirement as the main project |

**Important note on versions:** The apt packages in Ubuntu 22.04 / Debian 12 are often
too old to support iOS 16+. If the user is on a recent iPhone, they may need to build
`libimobiledevice` from source. The design document should check and warn at runtime (see
§6.1). Minimum required: libimobiledevice ≥ 1.3.0.

Source build dependencies (for documentation only, not automated):

```
libplist-dev libusbmuxd-dev libimobiledevice-glue-dev libtatsu-dev
libssl-dev usbmuxd autoconf automake libtool-bin build-essential
```

See: https://github.com/libimobiledevice/libimobiledevice#building

### 2.2 Python packages

| Package | Purpose | Install |
|---|---|---|
| `iphone-backup-decrypt` | Decrypt encrypted iTunes backups | `pip install iphone-backup-decrypt` |
| `fastpbkdf2` | Optional: faster key derivation (PBKDF2) | `pip install fastpbkdf2` |

The main project already requires `pytz` and `python-dateutil`; no change there.

`iphone-backup-decrypt` has no hard dependency on `fastpbkdf2` but falls back to
`pycryptodome` (~50% slower) if it is absent. For periodic archiving this is acceptable.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  ios_extract.sh                      │
│  (user-facing entry point, argument parsing,         │
│   dependency checks, final db_to_eml invocation)     │
└────────────────────┬────────────────────────────────┘
                     │ calls
                     ▼
┌─────────────────────────────────────────────────────┐
│                  ios_extract.py                      │
│  Phase 1: idevicebackup2 (via subprocess)            │
│  Phase 2: extract sms.db + Attachments               │
│    - unencrypted: direct hash-path copy              │
│    - encrypted:   iphone-backup-decrypt library      │
└────────────────────┬────────────────────────────────┘
                     │ produces
                     ▼
┌──────────────────────────────┐
│  work_dir/                   │
│    sms.db                    │
│    Attachments/              │
│      ...mirrored tree...     │
└──────────────────────────────┘
                     │
                     │ passed to
                     ▼
┌──────────────────────────────┐
│  bin/db_to_eml               │
│  (existing, no changes)      │
└──────────────────────────────┘
```

---

## 4. Detailed Design

### 4.1 Phase 1 — Create the Backup

**Entry point:** `idevicebackup2 backup --full <backup_root>`

The backup root is a user-configurable directory (default: `~/.ios-backups/`). Each
backup creates or updates a subdirectory named by the device UDID.

#### 4.1.1 Device pairing

The very first time a device is connected, the user must:

1. Unlock the iPhone.
2. Tap **"Trust"** on the iPhone screen.

`idevicepair pair` performs the pairing handshake and writes pairing credentials to
`/var/lib/lockdown/<UDID>.plist` (root) or `~/.config/lockdown/<UDID>.plist` (user).

The script should detect whether pairing credentials already exist for the connected
device and prompt the user if not. Pseudocode:

```python
result = subprocess.run(["idevicepair", "validate"], capture_output=True)
if result.returncode != 0:
    print("Device not paired. Ensure iPhone is unlocked, then press Enter...")
    input()
    subprocess.run(["idevicepair", "pair"], check=True)
```

#### 4.1.2 Detecting connected devices

```python
result = subprocess.run(["idevice_id", "-l"], capture_output=True, text=True, check=True)
udids = result.stdout.strip().splitlines()
```

If `udids` is empty → no device connected. If multiple → prompt user to select one (or
accept `--udid` CLI flag to skip the prompt).

#### 4.1.3 Running the backup

```python
subprocess.run(
    ["idevicebackup2", "--udid", udid, "backup", "--full", backup_root],
    check=True
)
```

**`--full` flag rationale:** Without `--full`, `idevicebackup2` does an incremental
backup and may skip files that haven't changed. For periodic archiving this is fine, but
`sms.db` grows continuously so it will always be included in an incremental backup.
Implementers may drop `--full` as an optimization after verifying that `sms.db` is
always treated as changed.

**Estimated time:** 30 seconds to several minutes depending on device size and USB speed.
The script should not time out.

#### 4.1.4 Encrypted vs unencrypted backups

After the backup completes, read `Manifest.plist` to determine if encryption is enabled:

```python
import plistlib
with open(os.path.join(backup_root, udid, "Manifest.plist"), "rb") as f:
    manifest = plistlib.load(f)
is_encrypted = manifest.get("IsEncrypted", False)
```

If `is_encrypted` is `True`, the passphrase is required (see §4.2.2).

**Recommendation in user-facing docs:** Users should enable encrypted backups in
iTunes/Finder at least once before using this tool. Encrypted backups include more data
(Health, Messages, Keychain), are more secure, and remain interoperable with Apple's own
restore. The script should print a notice if the backup is unencrypted.

---

### 4.2 Phase 2 — Extract `sms.db` and Attachments

#### 4.2.1 Locating files via `Manifest.db`

`Manifest.db` is a SQLite database containing a `Files` table:

```sql
CREATE TABLE Files (
    fileID TEXT PRIMARY KEY,   -- SHA1 hash (= filename on disk)
    domain TEXT,               -- e.g. "HomeDomain"
    relativePath TEXT,         -- e.g. "Library/SMS/sms.db"
    flags INTEGER,             -- 1=file, 2=dir, 4=symlink
    file BLOB                  -- serialized plist with file metadata
);
```

**Query for `sms.db`:**

```sql
SELECT fileID FROM Files
WHERE domain = 'HomeDomain'
  AND relativePath = 'Library/SMS/sms.db';
```

**Query for all SMS attachments:**

```sql
SELECT fileID, relativePath FROM Files
WHERE domain = 'MediaDomain'
  AND relativePath LIKE 'Library/SMS/Attachments/%';
```

Note: On iOS, SMS attachments live in `MediaDomain` under
`Library/SMS/Attachments/<bucket>/<uuid>/<filename>`. The `<bucket>` is a 2-char hex
prefix, mirroring the `Attachments/` directory structure the real device uses. The
existing `db_to_eml --attachment-root` flag expects exactly this layout.

For **unencrypted** backups, the raw file on disk is:
```
<backup_root>/<udid>/<fileID[0:2]>/<fileID>
```

#### 4.2.2 Encrypted backup extraction

Use the `iphone-backup-decrypt` library:

```python
from iphone_backup_decrypt import EncryptedBackup, RelativePath

backup = EncryptedBackup(
    backup_directory=os.path.join(backup_root, udid),
    passphrase=passphrase  # from CLI arg, env var, or interactive prompt
)

# Extract sms.db
backup.extract_file(
    relative_path=RelativePath.SMS,
    output_filename=os.path.join(work_dir, "sms.db")
)

# Extract all SMS attachments
backup.extract_files(
    relative_path="Library/SMS/Attachments/",
    domain="MediaDomain",
    output_folder=os.path.join(work_dir, "Attachments"),
    preserve_folders=True
)
```

`RelativePath.SMS` resolves to `"Library/SMS/sms.db"`. `preserve_folders=True` keeps
the `<bucket>/<uuid>/` directory structure intact under `work_dir/Attachments/`, which
is exactly what `db_to_eml --attachment-root` expects.

#### 4.2.3 Unencrypted backup extraction

For unencrypted backups, perform the extraction manually using `Manifest.db`:

```python
import shutil, sqlite3

conn = sqlite3.connect(os.path.join(backup_root, udid, "Manifest.db"))
conn.row_factory = sqlite3.Row

# Extract sms.db
row = conn.execute(
    "SELECT fileID FROM Files WHERE domain='HomeDomain' AND relativePath='Library/SMS/sms.db'"
).fetchone()
if not row:
    raise FileNotFoundError("sms.db not found in backup Manifest.db")
file_id = row["fileID"]
src = os.path.join(backup_root, udid, file_id[:2], file_id)
shutil.copy2(src, os.path.join(work_dir, "sms.db"))

# Extract attachments
rows = conn.execute(
    "SELECT fileID, relativePath FROM Files "
    "WHERE domain='MediaDomain' AND relativePath LIKE 'Library/SMS/Attachments/%'"
).fetchall()
for row in rows:
    file_id = row["fileID"]
    relative = row["relativePath"]  # Library/SMS/Attachments/<bucket>/<uuid>/<file>
    # Strip "Library/SMS/" prefix to get Attachments/<bucket>/...
    suffix = relative[len("Library/SMS/"):]
    dest = os.path.join(work_dir, suffix)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    src = os.path.join(backup_root, udid, file_id[:2], file_id)
    if os.path.exists(src):
        shutil.copy2(src, dest)
conn.close()
```

---

### 4.3 Phase 3 — Invoke `db_to_eml`

After extraction, the work directory contains:

```
work_dir/
  sms.db
  Attachments/
    <bucket>/
      <uuid>/
        <filename>
```

Invoke `db_to_eml`:

```python
subprocess.run([
    sys.executable, "-m", "chatlogtoeml.cli.apple_db",
    # OR: use the bin/db_to_eml entrypoint if on PATH
    os.path.join(work_dir, "sms.db"),
    output_dir,
    "--attachment-root", os.path.join(work_dir, "Attachments"),
    "--local-handle", local_handle,   # from CLI, optional
    "--embed-attachments",            # optional, configurable
    "--clobber",                      # for periodic re-runs
], check=True)
```

The caller (shell wrapper) can pass additional `db_to_eml` flags through as `--db-args
"..."` or a double-dash separator.

---

## 5. File and CLI Design

### 5.1 `extras/ios/ios_extract.sh` (shell wrapper)

Primary user-facing script. Performs dependency checks, then delegates to
`ios_extract.py`.

```
Usage: ios_extract.sh [OPTIONS] <output_dir>

Options:
  --backup-root DIR     Where to store/reuse backups (default: ~/.ios-backups)
  --work-dir DIR        Temp dir for extracted sms.db + Attachments (default: <backup-root>/extracted)
  --udid UDID           Device UDID (default: auto-detect first connected device)
  --passphrase PASS     Backup decryption passphrase (encrypted backups only)
                        Can also be set via IOS_BACKUP_PASSPHRASE env var.
  --no-backup           Skip idevicebackup2; re-use the most recent backup in --backup-root
  --no-convert          Extract only; do not invoke db_to_eml
  --local-handle HANDLE Phone number or email to use as From: address in EML output
  --embed-attachments   Embed attachment payloads in EML (may be large)
  --clobber             Overwrite existing EML files in output_dir
  --debug               Enable verbose logging throughout
  -h, --help            Show this message
```

**Dependency checks performed before anything else:**

1. `idevicebackup2` is on `$PATH`
2. `idevicepair` is on `$PATH`
3. `idevice_id` is on `$PATH`
4. `python3` is on `$PATH`
5. `python3 -c "import iphone_backup_decrypt"` succeeds (for encrypted path)
6. `python3 -c "from chatlogtoeml.cli import apple_db"` succeeds (db_to_eml available)

If checks 1–4 fail → print install instructions for `libimobiledevice-utils` and exit.
If check 5 fails → warn that encrypted backup support requires `pip install iphone-backup-decrypt`, but continue if `--no-backup` or backup is unencrypted.
If check 6 fails → print error about chatlogtoeml install and exit.

### 5.2 `extras/ios/ios_extract.py` (Python backend)

```
Usage: python3 ios_extract.py [OPTIONS]

All options mirror ios_extract.sh (it calls this script directly).
Can also be invoked standalone for testing/scripting.

Environment variables:
  IOS_BACKUP_PASSPHRASE   Passphrase for encrypted backups (avoid shell history exposure)
```

Module structure:

```
ios_extract.py
  main(argv)               # argument parsing, orchestration
  check_libimobiledevice() # version detection and compatibility warning
  detect_device()          # runs idevice_id -l, returns list of UDIDs
  pair_device(udid)        # runs idevicepair validate / pair
  run_backup(udid, backup_root, full=True)
  is_encrypted(backup_path)
  extract_unencrypted(backup_path, work_dir)
  extract_encrypted(backup_path, work_dir, passphrase)
  invoke_db_to_eml(work_dir, output_dir, args)
```

Functions should raise descriptive exceptions (subclasses of `ExtractError`) rather than
calling `sys.exit()` directly, to keep the module testable.

---

## 6. Error Handling and Edge Cases

### 6.1 libimobiledevice version compatibility

iOS 16+ changed the lockdown/pairing protocol. Older libimobiledevice builds fail
silently or produce corrupt backups.

Detection heuristic:
```python
result = subprocess.run(["idevicebackup2", "--version"], capture_output=True, text=True)
# Parse version string. Warn if < 1.3.0.
```

If version is too old or cannot be determined, print a warning:
```
WARNING: The installed libimobiledevice may be too old for iOS 16+.
If backup fails, build from source: https://github.com/libimobiledevice/libimobiledevice
```

### 6.2 Trust prompt timing

On first connect (or after an iOS update resets pairing), the iPhone shows a "Trust this
Computer?" dialog. The script cannot proceed until the user taps "Trust."

Mitigation: After `idevicepair pair` fails, print a clear prompt:
```
Please unlock your iPhone and tap "Trust" when prompted, then press Enter here...
```
Retry pairing after Enter is pressed. Retry up to 3 times before giving up.

### 6.3 Backup in progress / existing backup

`idevicebackup2` handles incremental backups correctly. If a backup for the UDID already
exists in `backup_root`, running without `--full` performs an incremental update
(faster). The `--full` flag forces a complete backup (safer but slower).

### 6.4 Missing passphrase for encrypted backup

If `is_encrypted` returns `True` and no passphrase is available:
1. Check `IOS_BACKUP_PASSPHRASE` environment variable.
2. If not set and `--passphrase` not given, prompt interactively using `getpass.getpass()`.
3. If running non-interactively (stdin not a TTY), exit with a clear error message
   instructing the user to use `--passphrase` or `IOS_BACKUP_PASSPHRASE`.

**Never log or print the passphrase.** Do not write it to disk.

### 6.5 `sms.db` not found in Manifest.db

This can happen if:
- Messages is disabled in iCloud settings and the backup is partial
- The backup is incomplete (device was disconnected)
- The iOS version uses a different domain/path (unlikely but possible)

On failure, print the list of `HomeDomain` paths containing `SMS` from Manifest.db to
help diagnose, then exit non-zero.

### 6.6 Attachment extraction failures

Individual attachment extraction failures should be **logged as warnings, not errors**.
`db_to_eml` handles missing attachments gracefully (records `X-Original-Attachment-Path`
header). The script should continue extracting the remaining attachments.

### 6.7 Concurrent backup / locked database

On iOS, the database may be locked if the device is actively sending/receiving messages
during backup. `idevicebackup2` handles the snapshot protocol so the backup image is
consistent at the moment of capture. The extracted `sms.db` is a copy; it will not be
locked during `db_to_eml` processing.

### 6.8 Multiple devices connected

If `idevice_id -l` returns multiple UDIDs and `--udid` is not specified, print a numbered
list and prompt the user to select one. Do not silently pick the first.

---

## 7. Security Considerations

### 7.1 Passphrase handling

- Accept passphrase via `IOS_BACKUP_PASSPHRASE` env var or `--passphrase` CLI flag (shell
  history risk — document this) or interactive `getpass`.
- Never write the passphrase to disk, log files, or temporary files.
- Derived key caching (the `iOSbackup`-style derived key) is out of scope for this
  design but would be a useful future addition.

### 7.2 Backup storage permissions

The backup root should be created with mode `0700` (user-only read/write). The script
should `os.makedirs(backup_root, mode=0o700, exist_ok=True)`.

### 7.3 Work directory cleanup

The work directory (`--work-dir`) contains a plaintext copy of `sms.db` and all
attachments. After `db_to_eml` completes successfully, the script should offer a
`--clean-work-dir` flag (default: off) that deletes the work directory. The default is
off because re-running `db_to_eml` without a new backup is a common workflow.

### 7.4 Pairing credentials

`idevicepair` writes pairing credentials to:
- `/var/lib/lockdown/<UDID>.plist` (system-wide, requires root) OR
- `~/.config/lockdown/<UDID>.plist` (user-level, preferred)

The script should run as an unprivileged user. If `/var/lib/lockdown` is owned by root
and `~/.config/lockdown` is not writable, print an error explaining the permission
issue.

---

## 8. Integration with `db_to_eml`

No changes to `db_to_eml`, `apple_db.py`, or any existing module are required.

The extractor produces:
```
<work_dir>/
  sms.db                  # → passed as <infile> to db_to_eml
  Attachments/            # → passed as --attachment-root to db_to_eml
```

This layout is identical to what a user would get from a manual macOS backup extraction,
so the existing `--attachment-root` support handles it without modification.

Recommended `db_to_eml` invocation from the extractor:
```
bin/db_to_eml \
  <work_dir>/sms.db \
  <output_dir> \
  --attachment-root <work_dir>/Attachments \
  [--local-handle <handle>] \
  [--embed-attachments] \
  [--clobber] \
  [--debug]
```

---

## 9. Suggested Periodic Archiving Workflow

The intended use case is a cron job or systemd timer:

```bash
# crontab example: run every Sunday at 2am
0 2 * * 0 /path/to/chatlogtoeml/extras/ios/ios_extract.sh \
    --backup-root /mnt/archive/ios-backups \
    --local-handle "+15551234567" \
    --clobber \
    /mnt/archive/imessage-eml/
```

Or with a systemd timer unit for more control over when the device is connected.

For encrypted backups in a non-interactive cron context:
```bash
IOS_BACKUP_PASSPHRASE="$(cat /run/secrets/ios-backup-pass)" \
  extras/ios/ios_extract.sh --backup-root /mnt/archive ...
```

---

## 10. Recommended Development Order

1. **Dependency check functions** — most critical for good UX; test on a fresh Ubuntu VM.
2. **Device detection and pairing** — requires physical iPhone; test interactively first.
3. **Unencrypted backup extraction** — simpler path; good for initial end-to-end test.
4. **`Manifest.db` query + file copy** — pure Python, no device needed after backup.
5. **Encrypted backup extraction** — depends on `iphone-backup-decrypt`; requires a backup with known passphrase for testing.
6. **`db_to_eml` invocation** — straightforward subprocess call; verify output EMLs.
7. **Shell wrapper + argument passthrough** — thin glue; write last.
8. **Error handling hardening** — add retry logic, graceful degradation on partial attachment extraction.

---

## 11. Reference Repositories

| Repo | Role |
|---|---|
| https://github.com/libimobiledevice/libimobiledevice | Core USB protocol library, `idevicebackup2` |
| https://github.com/libimobiledevice/usbmuxd | USB multiplexer daemon |
| https://github.com/libimobiledevice/ifuse | FUSE mount (not needed here, but useful reference for AFC protocol docs) |
| https://github.com/jsharkey13/iphone_backup_decrypt | Python encrypted backup decryption |
| https://github.com/avibrazil/iOSbackup | Alternative Python library with higher-level backup exploration API |

---

## 12. Known Limitations

- **iOS 16+ pairing changes:** Newer iOS versions use a revised lockdown protocol.
  libimobiledevice ≥ 1.3.0 (plus `libtatsu`) is required. Distro packages may be too old.
- **Wi-Fi backup:** `idevicebackup2` supports Wi-Fi sync (`--network` flag) if enabled on
  the device. Not tested in this design but should work identically once paired.
- **Very large backups:** A full backup of a device with many photos/videos can be
  several hundred GB. The extractor only copies `sms.db` and SMS attachments; the full
  backup remains in `backup_root` untouched after extraction. Users should ensure
  sufficient disk space in `backup_root`.
- **SMS vs iMessage attachments in `MediaDomain`:** Some MMS attachments from non-Apple
  senders may land in a different path or domain. The `LIKE 'Library/SMS/Attachments/%'`
  query covers the standard path; edge cases may require inspecting `Manifest.db` manually.
- **iCloud Messages:** If the user has "Messages in iCloud" fully enabled, older messages
  may be offloaded to iCloud and absent from the local device backup. This is an Apple
  limitation; the workaround is to disable "Optimize Storage" in Messages settings before
  backing up.
