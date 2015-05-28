import asyncio
import html
import itertools
import os
import string
import time
import traceback

from logbook import Logger, FingersCrossedHandler, default_handler

from aesop.models import Config, Genre, Movie, TVShow, TVShowEpisode, database_proxy
from aesop.utils import get, damerau_levenshtein

log = Logger(__name__)


class SkipIt(Exception):
    pass


@asyncio.coroutine
def convoluted_imdb_lookup(lookup):
    """This function is an atrocity."""

    from aesop.processor.movie import MovieLookup

    media_id = None
    genres = None
    video_type = 'movie' if isinstance(lookup, MovieLookup) else 'series'

    # if we know the year, we'll try and get it based on name and year from
    # omdb, if we're lucky.
    if lookup.year is not None:
        log.debug("Have year, doing specific lookup ({}, {})", lookup.title, lookup.year)
        params = {
            't': lookup.title,
            'type': video_type,
            'y': str(lookup.year),
        }

        resp, json = yield from get('http://www.omdbapi.com/', params=params)

        if json['Response'] != 'False':
            media_id = json['imdbID']
            year = int(json['Year'][:4])
            title = json['Title']

    # we couldn't find the movie, or we don't have a year available
    if media_id is None:
        params = {
            's': lookup.title,
            'type': video_type,
        }

        resp, json = yield from get('http://www.omdbapi.com/', params=params)

        if json.get('Response', 'True') != 'False':
            titles = sorted((
                dict(title=t['Title'], year=t['Year'], id=t['imdbID'], description='{} {}'.format(t['Title'], t['Year']))
                for t in json['Search']),
                key=lambda t: damerau_levenshtein(lookup.title, html.unescape(t['title']))
            )
        else:
            params = {
                'q': lookup.title,
                'tt': 'on',
                'nr': '1',
                'json': '1',
            }

            resp, json = yield from get('http://www.imdb.com/xml/find', params=params)

            titles = itertools.chain(
                json.get('title_popular', []),
                json.get('title_exact', []),
                json.get('title_approx', []),
                json.get('title_substring', []),
            )
            titles = sorted((t for t in titles), key=lambda t: damerau_levenshtein(lookup.title, html.unescape(t['title'])))

        # damerau-levenshtein helps with names like "Agents of S.H.I.E.L.D.",
        # which we translate to "Agents of S H I E L D" to handle terrible
        # torrents named "Agents.of.Shield"
        d = damerau_levenshtein(lookup.title, titles[0]['title'])
        if d <= 10:
            title = titles[0]['title']
            media_id = titles[0]['id']
        elif lookup.year is not None:
            # if we have a year but the damerau-levenshtein distance was too
            # high for the first result, we can cycle through the results based
            # on the year and take a best-guess. This works for titles that
            # have quite different names all over the place, e.g. "The Borrower
            # Arrietty" vs "The Secret World of Arrietty".

            # XXX: If we don't have a lookup year available, it would be nice
            # if we followed up by checking for unique titles, e.g. "Arrietty"
            # only appears in one movie title, so we can quite confidently say
            # that that's the correct one.
            for title in titles:
                if str(lookup.year) in title['description']:
                    media_id = title['id']
                    title = title['title']
                    break

        if media_id is None:
            # if we reach this point, we are, by all accounts, probably wrong.
            # This will work for horribly misnamed movies, e.g. "Jurassic Park
            # - The Lost World", which will correctly map to "The Lost World:
            # Jurassic Park".
            media_id, title = name_jumble_rumble(lookup.title, titles)

        if lookup.year is None:
            params = {
                'i': media_id,
                'p': 'full',
                'type': video_type,
            }
            resp, json = yield from get('http://www.omdbapi.com/?', params=params)
            if json['Response'] != 'False':
                year = int(json['Year'][:4])
                genres = json['Genre'].split(', ')
            else:
                year = None

        # IMDB puts the year in the description. If it's not there, we likely
        # have the wrong title, so we should cycle through again to try and
        # find it.
        elif str(lookup.year) not in titles[0]['description']:
            with FingersCrossedHandler(default_handler):
                for title in titles:
                    log.debug("Prospective title: {!r}", title)
                    if str(lookup.year) in title['description']:
                        media_id = title['id']
                        title = title['title']
                        break
                else:
                    log.error("BUG: Couldn't find anything suitable for {}".format(lookup))
                    raise SkipIt
            year = lookup.year
        else:
            year = lookup.year

    if genres is None:
        params = {
            'i': media_id,
            'p': 'full',
            'type': video_type,
        }
        resp, json = yield from get('http://www.omdbapi.com/?', params=params)
        if json['Response'] != 'False':
            genres = json['Genre'].split(', ')

    return lookup._replace(title=html.unescape(title), year=year, media_id=media_id, genres=genres or [])


def name_jumble_rumble(title, titles):
    import re
    articles = {'a', 'the', 'an'}

    r = re.compile('[%s]' % re.escape(string.punctuation))
    a_words = set(r.sub('', title).lower().split()) - articles

    def score(b):
        b_words = set(r.sub('', b['title']).lower().split()) - articles
        s = len(a_words & b_words)
        return s

    titles = sorted(titles, key=score, reverse=True)
    return titles[0]['id'], titles[0]['title']


def catalog_videos(database, source, max_lookups):
    from aesop.processor.movie import MovieLookup
    from aesop.processor.episode import AnimeLookup, TVShowLookup

    model, lookup_model = {
        'movies': (Movie, MovieLookup),
        'tv': (TVShow, TVShowLookup),
        'anime': (TVShow, AnimeLookup),
    }[source.type]

    log.info("Cataloguing {} videos for {}", source.type, source.path)

    if model == Movie:
        query = model.select(model.path)
        known_paths = set(itertools.chain.from_iterable(m.path.split('|') for m in query))
    else:
        query = TVShowEpisode.select(TVShowEpisode.path).where(TVShowEpisode.path.startswith(source.path))
        known_paths = {m.path for m in query}

    known_video_types = set(Config.get('processor', 'video types', default='avi, mp4, mkv, ogm').replace(' ', '').split(','))

    lookups = []
    paths = []

    log.debug("Known paths {}", known_paths)

    for path in set(known_paths):
        if not os.path.exists(path):
            known_paths.remove(path)
            log.info("{} does not exist, removing from database.")
            if model == Movie:
                Movie.delete().where(
                    (Movie.path == path) |
                    Movie.path.contains(path+'|') |
                    Movie.path.contains('|'+path)
                ).execute()
            else:
                ep = TVShowEpisode.select().where(TVShowEpisode.path == path).get()

                show = ep.show

                with database_proxy.transaction():
                    ep.delete()

                    if not list(show.episodes):
                        show.delete()
                    else:
                        if all([episode.watched for episode in show.episodes]):
                            show.watched = True
                            if show.is_dirty():
                                show.save()

    start_time = time.time()
    successes = 0
    lookup_failures = 0

    for root, dirs, files in os.walk(source.path):
        for path in (os.path.join(root, p) for p in files):
            if '/.AppleDouble/' in path:
                log.debug('Skipping {} as it looks like an Apple double.', path)
                continue

            if os.path.basename(path).startswith('.'):
                continue

            if os.path.splitext(path)[1][1:] not in known_video_types:
                continue

            if '/sample/' in path.lower() or os.path.splitext(path)[0].lower().endswith('-sample'):
                log.debug('Skipping {} as it looks like a sample.', path)
                continue

            if path in known_paths:
                continue

            with FingersCrossedHandler(default_handler):
                try:
                    path_lookups = lookup_model.from_path(path)
                except SkipIt as e:
                    log.error("Skipping path: {} {}", path, str(e))
                except Exception as e:
                    lookup_failures += 1
                    exception = ''.join(traceback.format_exception(e.__class__, e, e.__traceback__))
                    log.error("Error retrieving information for {}: {}", path, exception)
                else:
                    lookups.extend(path_lookups)
                    paths.extend([path]*len(path_lookups))

    loop = asyncio.get_event_loop()

    log.info("{} lookups to do", len(lookups))

    for i in range(0, len(lookups), max_lookups):
        chunk = lookups[i:i+max_lookups]
        f = asyncio.gather(
                *[asyncio.async(c, loop=loop) for c in chunk],
                loop=loop, return_exceptions=True)
        completed = loop.run_until_complete(f)

        with database.transaction():
            for path, lookup in zip(paths[i:i+max_lookups], completed):
                if isinstance(lookup, SkipIt):
                    # logged earlier, no need to log now
                    lookup_failures += 1
                elif isinstance(lookup, Exception):
                    lookup_failures += 1
                    exception = ''.join(traceback.format_exception(lookup.__class__, lookup, lookup.__traceback__))

                    log.error("Error retrieving information for {}: {}", path, exception)
                else:
                    genres = [Genre.get_or_create(text=g) for g in lookup.genres]
                    if source.type == 'movies':
                        save_movie(lookup, path, genres)
                    else:
                        save_episode(lookup, path, genres, source.type)

                    successes += 1
    end_time = time.time()

    log.info("Took {:.2f} seconds to do {} lookups", end_time - start_time, len(lookups))
    log.info("{} lookups failed", lookup_failures)

    return successes, lookup_failures


def save_movie(lookup, path, genres):
    try:
        movie = Movie.get(media_id=lookup.media_id)
    except Movie.DoesNotExist:
        movie = Movie.create(
            media_id=lookup.media_id,
            title=lookup.title,
            path=path,
            year=lookup.year,
        )
        if genres:
            movie.add_genres(genres)
    else:
        assert lookup.cd is not None, "Multiple files for {} ({!r}, {!r}) but not cds".format(lookup.media_id, movie.path, path)
        movie.path = '|'.join(sorted([movie.path, path]))
        movie.save()


def save_episode(lookup, path, genres, source_type):
    try:
        tvshow = TVShowEpisode.get(media_id=lookup.media_id)
    except TVShow.DoesNotExist:
        tvshow = TVShowEpisode.create(media_id=lookup.media_id, title=lookup.title, year=lookup.year, type=source_type)
        if genres:
            tvshow.add_genres(genres)
    else:
        tvshow.watched = False
        if tvshow.is_dirty():
            tvshow.save()

    TVShowEpisode.create(season=lookup.season, episode=lookup.episode, path=path, show=tvshow)
