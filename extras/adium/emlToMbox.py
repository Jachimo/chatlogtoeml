#!/usr/bin/env python3

"""Converts a directory full of .eml files to a single Unix "mbox" file.
This is similar to http://www.cosmicsoft.net/emlxconvert.html

Accepts as input either an individual .eml file or a directory containing one
or more .eml files.

Usage:
$ ./emlToMbox.py inputdir/ output.mbox
$ ./emlToMbox.py input.eml output.mbox

STATUS:  Lightly tested using Python 3.9.1 
"""

import os
import sys
import mailbox

DEBUG = True


def main(args):
    infile_name = args[1]
    dest_name = args[2]
    
    if DEBUG:
        print("Input is:  " + infile_name)
        print("Output is: " + dest_name)
    
    dest_mbox = mailbox.mbox(dest_name, create=True)  # if dest doesn't exist create it
    dest_mbox.lock()  # lock the mbox file
    
    if os.path.isdir(infile_name):
        if DEBUG:
            print("Detected directory as input, using directory mode")
        count = 0
        for filename in os.listdir(infile_name):
            if os.path.splitext(filename)[-1] == ".eml":
                try:
                    fi = open(os.path.join(infile_name, filename), 'r')
                except OSError:
                    sys.stderr.write("Error while opening " + filename + "\n")
                    dest_mbox.close()
                    raise
                add_msg_to_mbox(fi, dest_mbox)
                count += 1
                fi.close()
        if DEBUG:
            print("Processed " + str(count) + " total messages.")

    elif os.path.splitext(infile_name)[-1] == ".eml":
        if DEBUG:
            print("Detected .eml file as input, using single file mode")
        try:
            fi = open(infile_name, 'r')
        except OSError:
            sys.stderr.write("Error while opening " + infile_name + "\n")
            dest_mbox.close()
            raise
        add_msg_to_mbox(fi, dest_mbox)
        fi.close()

    dest_mbox.flush()
    dest_mbox.close()  # close/unlock the mbox file
    return 0


def add_msg_to_mbox(fi, dest_mbox):
    """Add a message file to a destination mailbox"""
    try:
        dest_mbox.add(fi)
    except mailbox.Error:
        dest_mbox.close()
        raise


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.stderr.write("Usage: ./emlToMbox.py input outbox.mbox\n")
        sys.exit(1)
    sys.exit(main(sys.argv))
