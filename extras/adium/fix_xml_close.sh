#/usr/bin/env bash
# Fix Adium XML-based .chatlog files with malformed closing tag
# USAGE ./fix_xml_close.sh failed.log
#  where failed.log is one of the outputs produced by bulk_convert.sh

# This assumes Mac OS / BSD style sed; GNU style sed on Linux may require tweaks to syntax
cat "$1" | \
while read FILENAME;
do
  sed -i '.bkup' 's/<\/?xml>/<\/chat>/' "${FILENAME}";
done
