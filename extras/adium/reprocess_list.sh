#!/usr/bin/env bash
# Process a list of files, specified as one per line
# Ignores lines beginning with # char, to allow files to be commented out of list
# USAGE: ./extras/reprocess_list.sh reprocess.txt /path/to/outputdir

LIST="$1"
OUTDIR="$2"

mkdir -p "$OUTDIR"

cat "$LIST" | \
while read -r LINE;
do
  [ "${LINE:0:1}" = "#" ] && continue
  ./bin/chat_convert --no-background --attach "$LINE" "$OUTDIR"
done
