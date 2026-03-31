#!/usr/bin/env bash
# Bash script to bulk convert Adium chat logs
# Usage: ./adium_convert.sh rootdir outdir
#  where 'rootdir' is the Adium Logs folder or another subfolder containing log files

indir=$1
outdir=$2
logfile=converted_$(date -I).log  # `date -I` may not be supported on all systems
failfile=failed_$(date -I).log    # for unsuccessfully processed files

mkdir -p "$outdir"  # create output dir if it doesn't already exist

# Traditional use of `find` command to bulk-process files based on extension:
#find "$indir" -name '*.chatlog' -exec ./bin/chat_convert {} "$outdir" --no-background \; | tee "$outdir"/"$logfile"
#find "$indir" -name '*.AdiumHTMLLog' -exec ./bin/chat_convert {} "$outdir" --no-background \; | tee -a "$outdir"/"$logfile"
#find "$indir" -name '*.html' -exec ./bin/chat_convert {} "$outdir" --no-background \; | tee -a "$outdir"/"$logfile"

# Improved method, which writes failures to process to a file, in addition to normal success log
# Ref. https://unix.stackexchange.com/questions/195677/bash-error-handling-on-find-exec
find "$indir" -name '*.chatlog' -exec \
bash -c './bin/chat_convert "$1" "$2" --no-background --attach || echo "$1">"$3"' none {} "$outdir" "$outdir"/"$failfile" \; \
| tee "$outdir"/"$logfile"

find "$indir" -name '*.AdiumHTMLLog' -exec \
bash -c './bin/chat_convert "$1" "$2" --no-background --attach || echo "$1">>"$3"' none {} "$outdir" "$outdir"/"$failfile" \; \
| tee -a "$outdir"/"$logfile"
