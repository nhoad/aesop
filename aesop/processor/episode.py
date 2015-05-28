import asyncio
import collections
import pathlib

import lxml.etree
from logbook import Logger

from aesop.processor import convoluted_imdb_lookup, SkipIt
from aesop.utils import get, complete

log = Logger(__name__)


class TVShowLookup(collections.namedtuple('TVShow', 'media_id title season episode year genres')):
    @property
    def complete(self):
        return all([self.media_id, self.title, self.season is not None, self.episode is not None, self.year])

    @classmethod
    def from_path(cls, path):
        path = pathlib.Path(path)

        self = cls(media_id=None, title=None, season=None, episode=None, year=None, genres=[]).scan_fs(path)
        lookups = self.guessit(path)
        if not lookups[0].complete:
            n = [l.full_lookup(str(path)) for l in lookups]
        else:
            n = [complete(l) for l in lookups]
        return n

    def scan_fs(self, path):
        def attr(a):
            try:
                return e.xpath('./{}'.format(a))[0].text
            except IndexError:
                return None

        episode_xml = path.with_suffix('.nfo')

        episode = None
        season = None
        media_id = None
        title = None
        year = None
        genres = None

        if episode_xml.is_file():
            e = lxml.etree.fromstring(episode_xml.open('rb').read())
            episode = attr('episode')
            season = attr('season')

        # FIXME: privacy thing: only consider up to the source root.
        for parent in path.parents:
            series = parent.joinpath('series.xml')
            if series.is_file():
                e = lxml.etree.fromstring(series.open('rb').read())

                media_id = attr('IMDB') or attr('IMDbId') or attr('media_id')
                title = attr('SeriesName')
                year = attr('ProductionYear')
                genres = e.xpath('./Genres/Genre/text()') or []
                break

        return self._replace(
            media_id=media_id or self.media_id,
            title=title or self.title,
            year=int(year) if year else self.year,
            season=int(season) if season else self.season,
            episode=int(episode) if episode else self.episode,
            genres=genres or self.genres,
        )

    def guessit(self, filename):
        if self.complete:
            return [self]

        from guessit import guess_file_info
        file_info = guess_file_info(filename)

        log.debug("guessit for {} = {!r}", filename, file_info)

        title = file_info['series']
        season = file_info.get('season', 1)
        if 'episodeList' in file_info:
            # a 3+ part multipart episode? who ever heard of that?
            if len(file_info['episodeList']) > 2:
                raise SkipIt('has way too many episode parts ({} > 2)'.format(len(file_info)))
            return [
                self._replace(title=title, season=season, episode=episode)
                for episode in file_info['episodeList']
            ]
        else:
            episode = file_info['episodeNumber']
            return [self._replace(title=title, season=season, episode=episode)]

    def full_lookup(self, path):
        # FIXME: attempt thetvdb lookups?
        return convoluted_imdb_lookup(self)


class AnimeLookup(TVShowLookup):
    @asyncio.coroutine
    def full_lookup(self, path):
        params = {
            'query': self.title,
        }
        resp, json = yield from get('https://hummingbird.me/api/v1/search/anime/', params=params)

        show = json[0]
        title = show['title']
        id = show['id']
        if 'started_airing' in show:
            year = int(show['started_airing'][:4])
        else:
            year = self.year

        resp, json = yield from get('https://hummingbird.me/api/v1/anime/{}'.format(id))
        genres = [p['name'] for p in json['genres']]

        return self._replace(title=title, media_id=id, year=year, genres=genres)
