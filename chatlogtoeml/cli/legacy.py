"""Legacy Adium-style CLI ported into the package."""

import argparse
import logging
import os
import sys

from .. import conv_to_eml, eml_attach
from ..parsers import adium_html, adium_xml


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    parser = argparse.ArgumentParser(description='Convert Adium log files to RFC822 MIME text files (.eml)')
    parser.add_argument('infilename', help='Input file')
    parser.add_argument('outdirname', nargs='?', default=os.getcwd(),
                        help='Output directory (optional, defaults to cwd)')
    parser.add_argument('--clobber', action='store_true', help='Overwrite identically-named output files')
    parser.add_argument('--attach', action='store_true', help='Attach original log file to output')
    parser.add_argument('--no-background', action='store_true', help='Strips background color from message text')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode (very verbose output)')
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    if not args.infilename:
        logging.critical("No input file specified.")
        return 1
    infile = args.infilename
    if (not os.path.isfile(infile)) and (os.path.splitext(infile)[-1] != '.chatlog'):
        logging.critical("Input must be a file or a .chatlog bundle.")
        return 1
    if os.path.splitext(infile)[-1] not in ['.chatlog', '.xml', '.AdiumHTMLLog', '.html']:
        logging.critical("Input file suffix not one of the supported types.")
        return 1
    os.makedirs(args.outdirname, exist_ok=True)

    if os.path.isdir(infile) and os.path.splitext(infile)[-1] == '.chatlog':
        logging.debug('Mac OS .chatlog bundle detected: %s', os.path.basename(infile))
        xmlfilename = os.path.splitext(os.path.basename(infile))[0] + '.xml'
        infile = os.path.join(infile, xmlfilename)
        if os.path.isfile(infile):
            logging.debug('XML file found at %s', os.path.sep.join(infile.split(os.path.sep)[-6:]))
        else:
            logging.critical('Bundle detected but inner XML file %s not found', os.path.basename(infile))
            return 1

    outfilename = os.path.splitext(os.path.basename(infile))[0] + '.eml'
    outpath = os.path.join(args.outdirname, outfilename)

    if os.path.isfile(outpath) and not args.clobber:
        logging.critical('Output file %s already exists. Use --clobber to overwrite.', outpath)
        return 1
    if os.path.isfile(outpath):
        logging.warning('File %s exists and will be overwritten.', outpath)

    ext = os.path.splitext(infile)[-1]
    if ext in ['.chatlog', '.xml']:
        logging.debug('XML chat log detected based on file extension.')
        with open(infile, 'rb') as fi:
            conv = adium_xml.toconv(fi)
    elif ext in ['.AdiumHTMLLog', '.html']:
        logging.debug('HTML chat log detected based on file extension.')
        with open(infile, 'r') as fi:
            conv = adium_html.toconv(fi)
    else:
        logging.critical('Unsupported file extension %s', ext)
        return 1

    try:
        eml = conv_to_eml.mimefromconv(conv, args.no_background)
    except ValueError:
        logging.critical('Fatal error while creating MIME document from %s', infile)
        return 1

    if args.attach:
        with open(infile, 'rb') as fi:
            eml = eml_attach.attach(fi, eml)

    eml['X-Converted-By'] = os.path.basename(sys.argv[0])

    try:
        with open(outpath, 'w') as fo:
            fo.write(eml.as_string())
    except IOError:
        logging.critical('I/O Error while opening output: %s', outpath)
        return 1

    print(f"{os.path.basename(infile)}\t{eml['Message-ID']}\x1e")
    return 0


if __name__ == "__main__":
    sys.exit(main())
