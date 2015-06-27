import asyncio
import json
import pathlib
import re

from datetime import timedelta
from operator import itemgetter

import websockets
from logbook import Logger

from aesop import events, isocodes
from aesop.models import TVShowEpisode, Movie, Config, TVShow, init
from aesop.mpv import AsyncioClient, LoadFile, libmpv, event_name
from aesop.utils import setup_logging, get_language

log = Logger('aesop.player')


class VideoPlayer:
    def __init__(self, **kwargs):
        self.client = AsyncioClient(**kwargs)
        self.subtitle_downloads = {}

        asyncio.async(self.client_event_handler())

    @property
    def audio(self):
        try:
            return self.client.audio
        except ValueError:
            return 0

    @property
    def sub(self):
        try:
            return self.client.sub
        except ValueError:
            return 0

    @property
    def length(self):
        try:
            return self.client.length
        except ValueError:
            return 0

    @property
    def path(self):
        return self.client.path

    @property
    def paused(self):
        return self.client.pause

    @paused.setter
    def paused(self, v):
        self.client.pause = v

    @property
    def percent_pos(self):
        try:
            return self.client.percent_pos
        except ValueError:
            return 0.0

    @property
    def volume(self):
        try:
            return self.client.volume
        except ValueError:
            return 50

    @property
    def has_chapters(self):
        try:
            return bool(self.client.chapters)
        except ValueError:
            return False

    @property
    def length(self):
        try:
            return self.client.length
        except ValueError:
            return 0.0

    @property
    def time_pos(self):
        try:
            return self.client.time_pos
        except ValueError:
            return 0.0

    def get_progress(self):
        time_pos, length = self.time_pos, self.length

        if length <= 0.0:
            return ''

        progress = str(timedelta(seconds=time_pos)).split('.')[0]
        length = str(timedelta(seconds=length)).split('.')[0]
        return '{} / {}'.format(progress, length)

    def play(self, media_file, append=False):
        self.client.loadfile(
            media_file,
            add_mode=LoadFile.Append if append else LoadFile.Replace
        )

    def stop(self):
        self.client.stop()

    def set_volume(self, amount):
        self.client.volume = amount

    def seek_backward(self, seek_size):
        if self.has_chapters:
            self.client.chapters -= 1
        else:
            self.client.seek(-seek_size)

    def seek_forward(self, seek_size):
        if self.has_chapters:
            self.client.chapters += 1
        else:
            self.client.seek(seek_size)

    def load_srt_subtitle(self, path, language):
        self.client.sub_add(path, title=language, lang=language)

    @asyncio.coroutine
    def set_subtitle(self, sid):
        if isinstance(sid, str) and sid.startswith('download_'):
            offset = len('download_')
            lang = sid[offset:]
            yield from events.broadcast(
                'download-subtitle',
                path=self.client.path, language=lang)
            return

        log.info('Setting subtitle to {}', sid)
        self.client.sub = sid

    def set_audio(self, aid):
        log.info('Setting subtitle to {}', aid)
        self.client.audio = aid

    def add_available_srt_subtitles(self):
        path = pathlib.Path(self.client.path)
        glob = '{}*.srt'.format(path.stem)
        glob = re.sub(r'\[', '[[]', glob)
        glob = re.sub(r'(?<!\[)\]', '[]]', glob)

        for subtitle in path.parent.glob(glob):
            subtitle = pathlib.Path(subtitle)
            language = get_language(subtitle)

            if language is not None:
                log.debug("Adding {} as {}", subtitle, language)
                self.load_srt_subtitle(str(subtitle), language)
            else:
                log.debug("Couldn't figure out a language for {}", subtitle)

    @asyncio.coroutine
    def client_event_handler(self):
        while True:
            event = yield from self.client.event_queue.get()

            log.debug('mpv event received {}', event_name(event))

            if event == libmpv.MPV_EVENT_START_FILE:
                yield from self.update_playback_info()

    @asyncio.coroutine
    def update_playback_info(self):
        self.subtitle_downloads.clear()
        self.add_available_srt_subtitles()

        media = get_movie_or_tv_show(self.client.path)
        now_playing = media.title
        log.info('now playing {}', now_playing)
        asyncio.async(asyncio.gather(
            self.broadcast_now_playing(),
            self.broadcast_volume(),
            self.broadcast_available_subtitles(),
            self.broadcast_available_audio(),
            events.broadcast('list-subtitles', path=self.client.path),
        ))

        if (self.sub != 0 and
                self.audio == self.sub and
                not int(Config.get('player', 'subtitles for matching audio'))):
            log.info("Disabling subtitle as it's the same as the language")
            self.client.sub = 0

    @asyncio.coroutine
    def broadcast_now_playing(self):
        if self.client.path is None:
            now_playing = None
        else:
            media = get_movie_or_tv_show(self.client.path)
            now_playing = media.title

        yield from broadcast_player_property('now_playing', now_playing)

    @asyncio.coroutine
    def broadcast_volume(self):
        volume = self.volume
        yield from broadcast_player_property('volume', volume)

    @asyncio.coroutine
    def broadcast_subtitle(self):
        yield from broadcast_player_property('selected_subtitle', self.client.sub)

    @asyncio.coroutine
    def broadcast_available_audio(self):
        audio_streams = [
            dict(value=aid, display=isocodes.nicename(alang))
            for (aid, alang) in self.client.audio_tracks()
        ]

        if len(audio_streams) <= 1:
            audio_streams = None
        else:
            audio_streams = sorted(audio_streams, key=itemgetter('display'))

        yield from broadcast_player_property('available_audio', audio_streams)

    @asyncio.coroutine
    def broadcast_available_subtitles(self):
        subtitles = [
            dict(value=sid, display=isocodes.nicename(slang))
            for (sid, slang) in self.client.subtitles()
        ]

        if self.subtitle_downloads:
            subtitles.extend([
                dict(value='download_{}'.format(slang), display=nicename)
                for (slang, nicename) in self.subtitle_downloads.items()
            ])

        if not subtitles:
            subtitles = None
        else:
            subtitles = sorted(subtitles, key=itemgetter('display'))

        yield from broadcast_player_property('available_subtitles', subtitles)

    @asyncio.coroutine
    def broadcast_all_properties(self):
        yield from asyncio.gather(
            self.broadcast_now_playing(),
            self.broadcast_available_subtitles(),
            self.broadcast_available_audio(),
            self.broadcast_subtitle(),
            broadcast_player_property('selected_audio', str(self.audio)),
            self.broadcast_volume(),
        )


class Server:
    @asyncio.coroutine
    def start(self):
        alang = Config.get('player', 'preferred audio', default='eng')
        slang = Config.get('player', 'preferred subtitle', default='eng')
        vo = Config.get('player', 'video output', default='auto')
        self.player = VideoPlayer(alang=alang, slang=slang, vo=vo)

        asyncio.async(self.update_per_second())
        asyncio.async(self.event_listener())

        yield from websockets.serve(self.handle_websocket, '0.0.0.0', 5002)

    @asyncio.coroutine
    def update_per_second(self):
        while True:
            path = self.player.path

            if path:
                percent = self.player.percent_pos
                progress = self.player.get_progress()

                yield from asyncio.gather(
                    broadcast_player_property('progress_percent', percent),
                    broadcast_player_property('progress_text', progress),
                )
            yield from asyncio.sleep(1)

    @asyncio.coroutine
    def event_listener(self):
        listener = events.listener('new-client', 'subtitle-downloaded', 'available-subtitles')

        while True:
            event = yield from listener.wait()

            if event is None:
                break

            if event.type == 'subtitle-downloaded':
                if self.player.client.path == event.video_path:
                    log.debug("Adding downloaded {} as {}", event.path, event.language)
                    self.player.subtitle_downloads.pop(event.language)
                    self.player.load_srt_subtitle(event.path, event.language)
            elif event.type == 'new-client':
                yield from self.player.broadcast_all_properties()
            elif event.type == 'available-subtitles':
                current_languages = set(
                    s.get('lang', 'Unknown Language') for s in self.player.subtitles()
                )

                for lang in event.languages:
                    if lang in current_languages:
                        continue
                    nicename = isocodes.nicename(lang) if isocodes.exists(lang) else '{} (Unknown)'.format(lang)
                    self.player.subtitle_downloads[lang] = '{} (Download)'.format(nicename)
                yield from self.player.broadcast_available_subtitles()

    @asyncio.coroutine
    def handle_websocket(self, websocket, path):
        client = ':'.join(map(str, websocket.writer.get_extra_info('peername')))
        log.info("New client {}", client)

        yield from events.broadcast('new-client', private=True)

        while True:
            message = yield from websocket.recv()

            if message is None:
                return

            message = json.loads(message)

            method, arguments = message['command'], message.get('arguments', {})

            yield from self._run_command(method, arguments)

    @asyncio.coroutine
    def _run_command(self, method, arguments):
        callable = getattr(self, 'ws_{}'.format(method), None)

        if callable is None:
            log.warning('Unhandled command {} {}', method, arguments)
        else:
            try:
                coro = callable(**arguments)
                if coro is not None:
                    yield from coro
            except Exception:
                log.exception('Error running {!r}', method)

    def ws_next(self):
        self.player.client.playlist_next()

    def ws_previous(self):
        self.player.client.playlist_prev()

    def ws_toggle(self):
        self.player.paused = not self.player.paused

    def ws_play(self, id, type, append=False):
        if type == 'movie':
            model = Movie
        else:
            model = TVShowEpisode

        path = model.select(model.path).where(model.id == int(id)).get().path

        self.player.play(path, append=append)

    @asyncio.coroutine
    def ws_stop(self):
        self.player.stop()
        yield from self.player.broadcast_all_properties()

    def ws_queue(self, id, type):
        self.ws_play(id, type, append=True)

    @asyncio.coroutine
    def ws_subtitle(self, sid):
        log.debug('subtitle({})', sid)
        self.player.set_subtitle(sid or 0)
        yield from self.player.broadcast_subtitle()

    @asyncio.coroutine
    def ws_audio(self, aid):
        log.debug('audio({})', aid)
        self.player.set_audio(aid or 0)
        yield from broadcast_player_property('selected_audio', str(self.player.audio))

    @asyncio.coroutine
    def ws_volume(self, volume):
        log.debug('volume({})', volume)
        self.player.set_volume(volume)
        yield from self.player.broadcast_volume()

    @asyncio.coroutine
    def ws_seek_forward(self):
        seek_size = int(Config.get('player', 'seek size', default=15))
        self.player.seek_forward(seek_size)

    @asyncio.coroutine
    def ws_seek_backward(self):
        seek_size = int(Config.get('player', 'seek size', default=15))
        self.player.seek_backward(seek_size)

    @asyncio.coroutine
    def ws_play_season(self, id, season, append=False):
        # FIXME: would be great if it was configurable to play the whole season or only unwatched
        query = TVShowEpisode.select(TVShowEpisode.path).join(TVShow).where(
            TVShow.media_id == id,
            TVShowEpisode.season == season,
        ).order_by(TVShowEpisode.episode)
        paths = [tv.path for tv in query]

        first = True
        for path in paths:
            log.debug("queuing {}", path)
            if first:
                self.player.play(path, append=append)
                append = True
                first = False
            else:
                self.player.play(path, append=append)

    @asyncio.coroutine
    def ws_queue_season(self, id, season):
        return self.ws_play_season(id, season, append=True)


def get_movie_or_tv_show(path):
    try:
        media = TVShowEpisode.select().where(TVShowEpisode.path == path).get()
    except TVShowEpisode.DoesNotExist:
        media = Movie.select().where(Movie.path == path).get()
    return media


@asyncio.coroutine
def broadcast_player_property(attribute, value):
    yield from events.broadcast(type='player', attribute=attribute, value=value)


if __name__ == '__main__':
    setup_logging('aesop.player', 'INFO')
    init()
    server = Server()
    asyncio.get_event_loop().run_until_complete(server.start())
    log.info("Player started on port 5002")
    asyncio.get_event_loop().run_forever()
