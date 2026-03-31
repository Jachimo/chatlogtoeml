#!/usr/bin/env bash
# Wrapper to run multi-source db_to_eml with conservative CPU/I/O defaults.
#
# Usage:
#   ./ios_multi_convert.sh <outdir> <source1> [<source2> ...] [-- <extra db_to_eml args>]
#
# Each <source> may be a simple DB path or the extended form:
#   <db_path>::<attachment_root>
# which is forwarded directly to `--source` for `db_to_eml`.
#
# Environment variables
# ---------------------
# OS-level scheduling (applied HERE as a nice/ionice prefix; has no effect if
# you call bin/db_to_eml directly because a Python process cannot change its
# own scheduler class after start-up):
#
#   NICE_LEVEL            nice(1) increment (0-19; default 10)
#   USE_IONICE            1 to enable ionice(1), 0 to skip (default 1)
#   IONICE_CLASS          ionice scheduler class: 1=realtime 2=best-effort 3=idle (default 3)
#   IONICE_LEVEL          priority within class (0-7; default 7 = lowest)
#
# Python-level I/O pacing (passed through to the Python process via env;
# works regardless of whether you use this wrapper or call bin/db_to_eml
# directly):
#
#   ATTACH_READ_PAUSE_MS      Sleep this many ms after reading an attachment (default 15)
#   ATTACH_READ_PAUSE_EVERY   Apply sleep every N-th attachment (default 1)

set -u

usage() {
  echo "Usage: $0 <outdir> <source1> [<source2> ...] [-- <extra db_to_eml args>]"
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 2 ]]; then
  usage
  exit 1
fi

OUTDIR=$1
shift

SOURCES=()
EXTRA_ARGS=()
ADDRESSBOOK=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --)
      shift
      break
      ;;
    --address-book)
      if [[ -n ${2:-} ]]; then
        ADDRESSBOOK=$2
        shift 2
        continue
      else
        echo "Missing value for --address-book"
        exit 1
      fi
      ;;
    *)
      SOURCES+=("$1")
      shift
      ;;
  esac
done

while [[ $# -gt 0 ]]; do
  EXTRA_ARGS+=("$1")
  shift
done

if [[ ${#SOURCES[@]} -eq 0 ]]; then
  echo "No sources provided."
  usage
  exit 1
fi

# Run from repo root so ./bin/db_to_eml resolves.
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR" || exit 1

mkdir -p "$OUTDIR"

# Defaults (can be overridden in environment)
NICE_LEVEL=${NICE_LEVEL:-10}
USE_IONICE=${USE_IONICE:-1}
IONICE_CLASS=${IONICE_CLASS:-3}
IONICE_LEVEL=${IONICE_LEVEL:-7}
ATTACH_READ_PAUSE_MS=${ATTACH_READ_PAUSE_MS:-15}
ATTACH_READ_PAUSE_EVERY=${ATTACH_READ_PAUSE_EVERY:-1}

echo "Outdir: $OUTDIR"
echo "Sources: ${SOURCES[*]}"
if [[ -n "$ADDRESSBOOK" ]]; then
  echo "AddressBook: $ADDRESSBOOK"
fi
echo "Using nice=$NICE_LEVEL ionice_class=$IONICE_CLASS ionice_level=$IONICE_LEVEL attach_pause=${ATTACH_READ_PAUSE_MS}ms every ${ATTACH_READ_PAUSE_EVERY}"

# Build command
CMD=(env "ATTACH_READ_PAUSE_MS=$ATTACH_READ_PAUSE_MS" "ATTACH_READ_PAUSE_EVERY=$ATTACH_READ_PAUSE_EVERY")
if [[ "$USE_IONICE" != "0" ]] && command -v ionice >/dev/null 2>&1; then
  CMD+=(ionice -c "$IONICE_CLASS" -n "$IONICE_LEVEL")
fi
CMD+=(nice -n "$NICE_LEVEL" ./bin/db_to_eml)

# Add each source as a --source arg
for s in "${SOURCES[@]}"; do
  CMD+=(--source "$s")
done

# If provided, validate address book and add to command
if [[ -n "$ADDRESSBOOK" ]]; then
  if [[ ! -f "$ADDRESSBOOK" ]]; then
    echo "Warning: Address book DB not found: $ADDRESSBOOK" >&2
  else
    CMD+=(--address-book "$ADDRESSBOOK")
  fi
fi

# positional infile placeholder, then outdir
CMD+=(- "$OUTDIR")

# forward extra args
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  CMD+=("${EXTRA_ARGS[@]}")
fi

echo "Running: ${CMD[*]}"
exec "${CMD[@]}"
