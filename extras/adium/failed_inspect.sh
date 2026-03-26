#!/usr/bin/env bash
# Inspect log files that failed to be processed

OUTDIR="failedcopies"

mkdir -p "$OUTDIR"

cat "$1" | \
while read -r LINE;
do
  cp -r "$LINE" "$OUTDIR"/
  echo "$LINE"
  head "$LINE" | nl -ba
  echo
done > "$OUTDIR"/summaries.txt
