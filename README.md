# chatlogtoeml

Conversion tool to migrate various flavors of instant messaging and SMS logs to RFC822 .eml files for archiving.

Originally known as "adiumToEML", but now expanded to handle other types of logs, including the output of [imessage-exporter](https://github.com/Jachimo/imessage-exporter).

## Usage

## Adium Log Conversion

From within the adiumtoeml directory:   
`$ ./adiumToEml.py chatlogfile [outputdir]`

If `outputdir` is not specified, the working directory will be used instead.

In most cases, you probably want to call this from a wrapper script, e.g. with `find` and `xargs` in order to run it on the entire Adium Logs directory.
(Usually `~/Documents/Adium/Logs` or potentially also `~/Library/Application Support/Adium/Logs`, but could be placed elsewhere.)

Most Adium logs end in either `.AdiumHTMLLog` or `.chatlog`, although the tool will also process files ending in `.html` or `.xml`.

Written and tested using Python 3.9.

## Dependencies

A few packages not included in Python's standard library are required for operation, and can be installed using `pip`.
These are:

* `pytz` - timezone handling support
* `py-dateutil` - extensions to the python `datetime` module, including timezone-aware date parsing

## Known Bugs / Limitations

### Incomplete Adium Facebook Chat Logs

Adium logs of Facebook chat conversations (from the period when Facebook was using an open standards, XMPP-compatible chat service) seem to be frequently malformed.
Although the tool attempts to link Facebook user IDs to real names (stored as 'aliases' in the XML), this is only occasionally possible.
Also, some logs appear to only contain one side (usually the remote) of the conversation, for reasons that are not clear.

A possible cause is related to how Facebook handled multiple-device support: received messages were likely 'broadcast' to all signed-in devices, but transmitted messages from a device other than the computer running Adium were not re-sent out by Facebook's servers, and thus are not included in the Adium log.

### Malformed Adium XML Logs

It appears that some versions of Adium produced malformed XML log files.
Missing `</chat>` tags are particularly common in some periods (most are dated around early 2003, and the issue was apparently fixed by mid-2004).
These files can be easily fixed using the Mac OS `sed` command:

    sed -i '.bkup' 's/<\/?xml>/<\/chat>/' broken.chatlog

A small Bash script which runs this command against a list of files is included in the `/extras` directory as `fix_xml_close.sh`.
It is designed to be run against the `failed_YYYY-MM-DD.log` files produced by the `bulk_convert.sh` script.
Original files are preserved with the extension `.bkup` added, so they won't be picked up by the processor on future runs.

#### Illegal XML Characters

Despite writing files that claim to be well-formed XML 1.0, it appears that some versions of Adium did not sanitize their inputs very well.
The existence of ASCII control characters (such as hex 0x19, reportedly misused by Microsoft products for 'smart single quote' and seen in copied/pasted content) are especially problematic, as they terminate XML parsing when encountered, and the normal Python `.encode()` and `.decode()` tricks don't seem to strip them.
The `adium_xml.py` input processor attempts to strip these characters if initial XML parsing fails.

### Bad Log File Names

Examples have been found of Adium HTML-based log files with strange separator characters in the date written into the filename.
(An example is `20050219` on an AdiumHTMLLog file.)
These files will cause processing errors and should be renamed by hand, replacing the non-ASCII chars with dashes.

### Trivial Logs

"Trivial" logs, meaning those without any actual human-generated messages and only system/status messages, do not have enough information to be usefully represented as MIME .eml documents.
As a result, they are skipped when processing.
It is possible that a future version of this converter might be able to process them into a different output format, such as JSON.

## Licensing

See the LICENSE file for more information.

Released under the GPL v2 or later. Contains various components licensed under the GPL and MIT licenses.

Modifications and improvements are welcomed and encouraged.
Please feel free to fork this project; pull requests will be considered as long as they do not break core functionality.

This software is provided without warranty and without any representations as to its functionality for a particular purpose.
End-user support is not available. 

## References

- Information on the various 'flavors' of Adium log formats can be found [in this Github Gist](https://gist.github.com/kadin2048/ffe811e56c8e8fb6ceb8bade09439341).
