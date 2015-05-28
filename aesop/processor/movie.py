import collections
import pathlib

import lxml.etree
from logbook import Logger

from aesop.processor import convoluted_imdb_lookup
from aesop.utils import int_to_roman, complete

log = Logger(__name__)


class MovieLookup(collections.namedtuple('Movie', 'media_id title year genres cd')):
    @classmethod
    def from_path(cls, path):
        from guessit import guess_file_info

        # the ' - ' replacement is a nasty hack to make movie titles like "The
        # Lord of The Rings - The Two Towers" search the whole title rather
        # than just the first part.
        file_info = guess_file_info(path.replace(' - ', ' '))

        title = file_info['title']
        year = file_info.get('year', None)
        cd = file_info.get('cdNumber', None)

        if 'part' in file_info:
            part = file_info['part']
            if 'Part {}'.format(part) in path:
                title += ' Part {}'.format(part)
            else:
                # yeah that's right, roman numerals
                title += ' Part {}'.format(int_to_roman(part))

        self = cls(media_id=None, title=title, year=year, genres=[], cd=cd)
        return [self.full_lookup(path)]

    def full_lookup(self, path):
        if self.media_id is not None:
            log.debug("Have IMDB ID, no further lookup necessary for {!r}", self)
            return complete(self)

        path = pathlib.Path(path)
        nfo = path.with_suffix('.nfo')

        log.debug("Attempting NFO read {!r}", nfo)
        try:
            e = lxml.etree.fromstring(nfo.open('rb').read())
        except lxml.etree.XMLSyntaxError as e:
            log.warning("Error reading XML for {!r} {}", nfo, e)
            return convoluted_imdb_lookup(self)
        except FileNotFoundError:
            log.debug("No nfo found, doing lookup")
            return convoluted_imdb_lookup(self)
        else:
            def attr(a):
                try:
                    return e.xpath('./{}'.format(a))[0].text
                except IndexError:
                    return None

            title = attr('title')
            year = attr('year')
            media_id = attr('id')
            genres = e.xpath('./genre/text()')

            new = {}
            if title:
                new['title'] = title
            if year:
                new['year'] = int(year)
            if media_id:
                new['media_id'] = media_id
            if genres:
                new['genres'] = genres

            if any([title is None, year is None, media_id is None, not genres]):
                # we'll do the IMDB lookup, but try and fill out with any
                # information we did have
                return convoluted_imdb_lookup(self._replace(**new))

            return complete(self._replace(**new))
