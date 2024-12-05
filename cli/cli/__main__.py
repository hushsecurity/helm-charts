import argparse
import logging
import os
import sys
from .release import release_cmd

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=getattr(logging, LOG_LEVEL),
)


def parse_args():
    p = argparse.ArgumentParser()
    sub_parsers = p.add_subparsers(dest="cmd")
    release = sub_parsers.add_parser("release")
    release.add_argument("chart_name")
    release.set_defaults(func=release_cmd)
    args = p.parse_args()
    if not args.cmd:
        p.print_usage()
        sys.exit(1)
    return args


def main():
    args = parse_args()
    args.func(args)


main()
