#!/bin/sh

# this script is from http://trac.adium.im/ticket/6569

# Adium is the legal property of its developers, whose names are listed in the copyright file included
# with this source distribution.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation; either version 2 of the License,
# or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even
# the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program; if not,
# write to the Free Software Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.

# Purpose:
#	Format an Adium .chatlog file as HTML
#
# Usage:
#	format-html.sh LOG ...
#
# Notes:
#	Output is written to a .html file in the same directory as the log
#	xsltproc is used to run the transform

STYLESHEET=$(dirname "$0")/format-html.xsl

for LOG
do
	TITLE=$(basename "$LOG" .chatlog | sed \
's/\([0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]\)T'\
'\([0-9][0-9]\)\.\([0-9][0-9]\)\.\([0-9][0-9]\)/'\
'\1 \2:\3:\4 /')

	OUT=$(echo "${LOG%.chatlog}" | sed -e 's/[ |]/-/g' -e 's/[()]//g').html

	xsltproc -o "$OUT" --stringparam title "$TITLE" "$STYLESHEET" "$LOG"
done
