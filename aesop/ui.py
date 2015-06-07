import pathlib
from collections import defaultdict
from operator import itemgetter
from itertools import groupby

from flask import Flask, send_from_directory, request, jsonify
from logbook import Logger

from aesop import isocodes, events
from aesop.models import Movie, TVShow, TVShowEpisode, Source, Config, database_proxy, Genre, MovieGenre, TVShowGenre

app = Flask('aesop.ui')
log = Logger('aesop.ui')


@app.route('/')
def root():
    templates = str(pathlib.Path(__file__).with_name('templates'))
    return send_from_directory(templates, 'index.html')


@app.route('/series')
def series():
    series = list(TVShow.select().order_by(TVShow.title).dicts())
    tvshow_genre_map = Genre.select(TVShowGenre.media, Genre.text).join(TVShowGenre).tuples()

    d = defaultdict(list)

    for show_id, text in tvshow_genre_map:
        d[show_id].append(text)

    for tv in series:
        tv['genres'] = d[tv['id']]
    return jsonify({'data': series})


@app.route('/series/<id>')
def singleseries(id):
    tvshow = TVShow.select(TVShow.media_id, TVShow.title).where(TVShow.media_id == id).dicts().get()
    return jsonify({'data': tvshow})


# this and set_watched_movie are not websocket commands because they need data
# back.
@app.route('/series/setwatched/<int:video_id>', methods=['POST'])
def set_watched_series(video_id):
    m = TVShowEpisode.select().where(TVShowEpisode.id == video_id).get()
    with database_proxy.transaction():
        m.watched = not m.watched
        m.save()
        show = m.show
        if all([episode.watched for episode in show.episodes]):
            show.watched = True
            if show.is_dirty():
                show.save()
    return jsonify({'watched': m.watched})


@app.route('/series/<id>/seasons')
def seasons(id):
    tvshow = TVShow.select().where(TVShow.media_id == id).get()
    seasons = tvshow.episodes.select(TVShowEpisode.season, TVShowEpisode.watched).group_by(TVShowEpisode.season, TVShowEpisode.watched).dicts()

    collapsed_seasons = defaultdict(bool)

    for season in seasons:
        watched = season['watched']
        season = season['season']

        if season in collapsed_seasons:
            watched = collapsed_seasons[season] and watched
        collapsed_seasons[season] = watched

    seasons = [dict(season=season, watched=watched) for (season, watched) in collapsed_seasons.items()]
    return jsonify({'data': seasons})


@app.route('/series/<id>/episodes/<int:season>')
def episodes(id, season):
    tvshow = TVShow.select().where(TVShow.media_id == id).get()

    return jsonify({'data': list(tvshow.episodes.select().where(TVShowEpisode.season == season).order_by(TVShowEpisode.episode).dicts())})


@app.route('/movies')
def movies():
    movies = list(Movie.select(Movie.id, Movie.title, Movie.watched, Movie.year).order_by(Movie.title).dicts())
    movie_genre_map = Genre.select(MovieGenre.media, Genre.text).join(MovieGenre).tuples()

    d = defaultdict(list)

    for movie_id, text in movie_genre_map:
        d[movie_id].append(text)

    for m in movies:
        m['genres'] = d[m['id']]
    return jsonify({'data': movies})


@app.route('/movies/<int:id>', methods=['GET', 'POST'])
def movie(id):
    if request.method == 'POST':
        genres = request.json['movie'].pop('genres')

        Movie.update(**request.json['movie']).where(Movie.id == id).execute()
        m = Movie.get(Movie.id == id)
        m.replace_genres([Genre.get_or_create(g) for g in genres])
        return jsonify({'status': 'ok'})
    else:
        movie = Movie.select().where(Movie.id == id).dicts().get()

        q = Genre.select(Genre.text).join(MovieGenre).where(MovieGenre.media == movie['id'])
        movie['genres'] = [g[0] for g in q.tuples()]

        return jsonify({'movie': movie})


@app.route('/movies/setwatched/<int:video_id>', methods=['POST'])
def set_watched_movie(video_id):
    m = Movie.select(Movie.id, Movie.watched).where(Movie.id == video_id).get()
    m.watched = not m.watched
    m.save()
    return jsonify({'watched': m.watched})


@app.route('/genres')
def genres():
    return jsonify({'genres': [g[0] for g in Genre.select(Genre.text).order_by(Genre.text).tuples()]})


@app.route('/update/', methods=['POST'])
def update():
    raise NotImplementedError()


@app.route('/settings/', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        from aesop.models import database
        try:
            with database.transaction():
                Config.delete().execute()
                for setting in request.json['configuration']:
                    Config.create(**setting)

                Source.delete().execute()
                for setting in request.json['sources']:
                    Source.create(**setting)
        except Exception as e:
            events.error.blocking("Settings could not be saved: {!r}".format(str(e)))
            raise
        else:
            events.success.blocking("Settings saved")
    else:
        configuration = []

        for section, values in groupby(list(Config.select(Config.section, Config.key, Config.value).dicts()), key=itemgetter('section')):
            configuration.append({
                'name': section,
                'values': [config_with_help(v) for v in values],
            })

        return jsonify({
            'configuration': configuration,
            'sources': list(Source.select().dicts()),
        })
    return jsonify({'response': 'ok'})


@app.route('/stats/')
def stats():
    series = TVShow.select().count()
    episodes = TVShowEpisode.select().count()
    episodes_watched = TVShowEpisode.select().where(TVShowEpisode.watched == True).count()
    movies = Movie.select().count()
    movies_watched = Movie.select().where(Movie.watched == True).count()

    stats = {
        'series': series,
        'episodes': episodes,
        'episodes watched': episodes_watched,
        'movies': movies,
        'movies watched': movies_watched,
    }

    return jsonify({'stats': stats})


@app.route('/manifest.json')
def manifest():
    return jsonify({
        'name': 'Aesop',
        "start_url": "/",
        "display": "standalone",
    })


@app.route('/search/genres/')
def get_upstream_genres():
    imdb_id = request.values['i']
    video_type = request.values['type']
    upstream = request.values.get('m', 'omdb')

    if upstream == 'omdb':
        import requests
        params = {
            'i': imdb_id,
            'p': 'full',
            'type': video_type,
        }
        resp = requests.get('http://www.omdbapi.com/?', params=params)
        json = resp.json()
        if json['Response'] != 'False':
            genres = json['Genre'].split(', ')
        else:
            genres = []
    else:
        assert False, "Unknown upstream type {!r}".format(upstream)

    return jsonify({'genres': genres})


@app.route('/search/')
def search_upstream():
    query = request.values['q']
    video_type = request.values['type']
    upstream = request.values.get('m', 'omdb')

    if len(query) < 3:
        results = []
    elif upstream == 'omdb':
        import requests
        params = {
            's': query,
            'type': video_type,
        }
        resp = requests.get('http://www.omdbapi.com/', params=params)
        results = resp.json().get('Search', [])

        results = [
            dict(title=t['Title'], year=int(t['Year']), id=t['imdbID'],
                 description='{} {}'.format(t['Year'], t['Title']))
            for t in results
        ]
    else:
        assert False, "Unknown upstream type {!r}".format(upstream)

    return jsonify({'results': list(results)})


help_map = {
    'concurrency': 'Amount of concurrent requests to perform when retrieving video metadata.',
    'frequency': 'How frequently to scan for new videos',
    'theme': 'Website theme to use',
    'seek size': 'Amount of time in seconds to jump forward/backward',
    'subtitles for matching audio': 'Should subtitles be automatically enabled if the audio and subtitles language are the same?',
}

isochoices = [dict(display='-- None --', value='-1')] + sorted([
    dict(display=nicename, value=iso)
    for (iso, nicename) in isocodes.isocodes.items()
], key=itemgetter('display'))

extras_map = {
    'theme': {
        'choices': {
            'cyborg': 'Cyborg',
            'darkly':  'Darkly',
            'flatly': 'Flatly',
            'journal': 'Journal',
            'cosmo': 'Cosmo',
            'cerulean': 'Cerulean',
        },
    },
    'preferred subtitle': {
        'choices': isochoices,
        'typeahead': 'Preferred Subtitle Language',
        'default': '',
    },
    'preferred audio': {
        'choices': isochoices,
        'typeahead': 'Preferred Audio Language',
        'default': '',
    },
    'subtitles for matching audio': {
        'choices': {
            '1': 'Yes',
            '0': 'No',
        },
    },
    'concurrency': {
        'type': 'number',
    },
}


def config_with_help(config):
    config['help'] = help_map.get(config['key'], '')
    config.update(extras_map.get(config['key'], {}))

    if 'typeahead' in config:
        value = config['value']
        choices = config.get('choices', [])
        for choice in choices:
            if choice['value'] == value:
                config['value'] = dict(value=value, display=choice['display'])
                break

    if config['key'] == 'concurrency':
        config['value'] = int(config['value'])
    return config


def main():
    from aesop.models import init
    from aesop.utils import setup_logging
    setup_logging('aesop.ui', 'INFO')
    init()
    app.run(debug=True, host='0.0.0.0')


if __name__ == '__main__':
    main()
