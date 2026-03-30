#!/usr/bin/env bash
# Bash script to convert iOS/macOS Messages DB exports to EML.
# Usage:
#   ./ios_convert.sh <sms_root_or_db> <outdir> [AddressBook.sqlitedb] [-- <extra db_to_eml args>]
#
# Examples:
#   ./ios_convert.sh "/path/to/Library/SMS" "/tmp/out"
#   ./ios_convert.sh "/path/to/Library/SMS/sms.db" "/tmp/out" "/path/to/AddressBook.sqlitedb" -- --clobber
#
# Notes:
# - Runs conversion through "nice" and "ionice" (if available).
# - If a directory is provided, this script will process sms.db/chat.db found within it (or recursively beneath it).

set -u

usage() {
  echo "Usage: $0 <sms_root_or_db> <outdir> [AddressBook.sqlitedb] [-- <extra db_to_eml args>]"
}

# Fast-path help/usage.
if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

# Require source + output root.
if [[ $# -lt 2 ]]; then
  usage
  exit 1
fi

# Peel off required args first.
SOURCE_ARG=$1
OUTDIR=$2
shift 2

# Optional AddressBook path in arg3.
ADDRESSBOOK=""
if [[ $# -gt 0 && ${1:-} != "--" ]]; then
  ADDRESSBOOK=$1
  shift
fi

# Optional delimiter before passthrough args.
if [[ ${1:-} == "--" ]]; then
  shift
fi

# Remaining args pass straight to db_to_eml.
EXTRA_ARGS=("$@")

# Run from repo root so ./bin/db_to_eml resolves.
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR" || exit 1

# Prepare output + per-run logs.
mkdir -p "$OUTDIR"

LOGFILE="converted_ios_$(date -I).log"
FAILFILE="failed_ios_$(date -I).log"
: > "$OUTDIR/$LOGFILE"
: > "$OUTDIR/$FAILFILE"

if [[ -n "$ADDRESSBOOK" && ! -f "$ADDRESSBOOK" ]]; then
  echo "Address Book DB not found: $ADDRESSBOOK"
  exit 1
fi

# Resolve DB inputs from file or directory.
DB_LIST=()
if [[ -f "$SOURCE_ARG" ]]; then
  DB_LIST+=("$SOURCE_ARG")
elif [[ -d "$SOURCE_ARG" ]]; then
  if [[ -f "$SOURCE_ARG/sms.db" ]]; then
    DB_LIST+=("$SOURCE_ARG/sms.db")
  fi
  if [[ -f "$SOURCE_ARG/chat.db" ]]; then
    DB_LIST+=("$SOURCE_ARG/chat.db")
  fi
  if [[ ${#DB_LIST[@]} -eq 0 ]]; then
    while IFS= read -r db; do
      DB_LIST+=("$db")
    done < <(find "$SOURCE_ARG" -type f \( -name 'sms.db' -o -name 'chat.db' \) | sort)
  fi
else
  echo "Input path does not exist: $SOURCE_ARG"
  exit 1
fi

if [[ ${#DB_LIST[@]} -eq 0 ]]; then
  echo "No sms.db/chat.db files found under: $SOURCE_ARG"
  exit 1
fi

# Lower CPU scheduling priority unless overridden.
NICE_LEVEL=${NICE_LEVEL:-10}
# Lower I/O scheduling priority unless disabled.
USE_IONICE=${USE_IONICE:-1}
IONICE_CLASS=${IONICE_CLASS:-3}
# Pace attachment reads in parser (milliseconds, every N attachments).
ATTACH_READ_PAUSE_MS=${ATTACH_READ_PAUSE_MS:-15}
ATTACH_READ_PAUSE_EVERY=${ATTACH_READ_PAUSE_EVERY:-1}

echo "Found ${#DB_LIST[@]} DB file(s)." | tee -a "$OUTDIR/$LOGFILE"
echo "Using nice level: $NICE_LEVEL" | tee -a "$OUTDIR/$LOGFILE"
if [[ "$USE_IONICE" != "0" ]] && command -v ionice >/dev/null 2>&1; then
  echo "Using ionice class: $IONICE_CLASS" | tee -a "$OUTDIR/$LOGFILE"
else
  echo "ionice unavailable/disabled; continuing without I/O priority hint" | tee -a "$OUTDIR/$LOGFILE"
fi
echo "Attachment pacing: ${ATTACH_READ_PAUSE_MS}ms every ${ATTACH_READ_PAUSE_EVERY} attachment(s)" | tee -a "$OUTDIR/$LOGFILE"

for DB_PATH in "${DB_LIST[@]}"; do
  DB_DIR=$(dirname "$DB_PATH")
  # iOS/macOS exports usually keep attachments beside the DB.
  ATTACH_ROOT="$DB_DIR/Attachments"

  # Multi-DB runs get per-DB output subdirs.
  TARGET_OUTDIR="$OUTDIR"
  if [[ ${#DB_LIST[@]} -gt 1 ]]; then
    SAFE_DB_NAME=$(echo "$DB_PATH" | sed 's#[/ ]#_#g; s#[^A-Za-z0-9._-]#_#g')
    TARGET_OUTDIR="$OUTDIR/$SAFE_DB_NAME"
    mkdir -p "$TARGET_OUTDIR"
  fi

  # Build command as an array to preserve quoting.
  CMD=(env "ATTACH_READ_PAUSE_MS=$ATTACH_READ_PAUSE_MS" "ATTACH_READ_PAUSE_EVERY=$ATTACH_READ_PAUSE_EVERY")
  if [[ "$USE_IONICE" != "0" ]] && command -v ionice >/dev/null 2>&1; then
    CMD+=(ionice -c "$IONICE_CLASS")
  fi
  CMD+=(nice -n "$NICE_LEVEL" ./bin/db_to_eml "$DB_PATH" "$TARGET_OUTDIR")

  if [[ -n "$ADDRESSBOOK" ]]; then
    CMD+=(--address-book "$ADDRESSBOOK")
  fi
  if [[ -d "$ATTACH_ROOT" ]]; then
    CMD+=(--attachment-root "$ATTACH_ROOT")
  else
    echo "Warning: attachment root not found for $DB_PATH ($ATTACH_ROOT); continuing without --attachment-root" | tee -a "$OUTDIR/$LOGFILE"
  fi

  # Forward any caller-provided db_to_eml options.
  CMD+=("${EXTRA_ARGS[@]}")

  echo "Converting DB: $DB_PATH" | tee -a "$OUTDIR/$LOGFILE"
  if "${CMD[@]}" >> "$OUTDIR/$LOGFILE" 2>&1; then
    echo "OK: $DB_PATH" | tee -a "$OUTDIR/$LOGFILE"
  else
    echo "FAILED: $DB_PATH" | tee -a "$OUTDIR/$LOGFILE"
    echo "$DB_PATH" >> "$OUTDIR/$FAILFILE"
  fi

done

if [[ -s "$OUTDIR/$FAILFILE" ]]; then
  echo "Completed with failures. See $OUTDIR/$FAILFILE and $OUTDIR/$LOGFILE"
  exit 2
fi

echo "Completed successfully. See $OUTDIR/$LOGFILE"
