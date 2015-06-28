import argparse

import logbook

from aesop.models import init, database_proxy, Config, Source
from aesop.processor import catalog_videos
from aesop import events
from aesop.utils import setup_logging

log = logbook.Logger('aesop.processor')

parser = argparse.ArgumentParser()
parser.add_argument(
    '--log-level',
    default='INFO',
    help="Log Level. Must be one of CRITICAL, ERROR, WARNING, INFO or DEBUG")

options = parser.parse_args()

try:
    setup_logging('aesop.processor', 'INFO')
except LookupError:
    parser.error("--log-level must be one of CRITICAL, ERROR, WARNING, INFO or DEBUG")

init()

max_lookups = int(Config.get('processor', 'concurrency', default=50))

sources = list(Source.select(Source.path, Source.type))

events.info.blocking("Starting scan")
log.info("Starting scan")

total = unscanned = removed = 0
for source in sources:
    t, u, r = catalog_videos(database_proxy, source, max_lookups)

    total += t
    unscanned += u
    removed += r

msg = "Scan complete. {} new items, {} could not be added. {} items were removed from the db".format(total, unscanned, removed)
log.info(msg)
events.info.blocking(msg)

if not sources:
    msg = "You don't have any sources defined"
    events.error.blocking(msg)
    log.critical(msg)
