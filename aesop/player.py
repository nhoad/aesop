import asyncio
import collections
import json
import os
import pathlib
import re
import itertools

from asyncio.subprocess import PIPE
from datetime import timedelta
from operator import itemgetter

import websockets
from logbook import Logger

from aesop import events, isocodes
from aesop.models import TVShowEpisode, Movie, Config, TVShow, init
from aesop.utils import setup_logging, get_language

log = Logger('aesop.player')


class VideoPlayerMeta(type):
    _command_map = {
        'next': ('pt_step', 1),
        'previous': ('pt_step', -1),
        'switch_subtitles': 'sub_select',
        'toggle': 'pause',
    }

    _simple_commands = ['mute', 'stop']

    for cmd in _simple_commands:
        _command_map[cmd] = cmd

    attribute = collections.namedtuple('attribute', 'coerce default')

    # FIXME: support full attribute list
    _attrs = {
        'time_pos': attribute(float, 0.0),
        'percent_pos': attribute(float, 0.0),
        'time_pos': attribute(float, 0.0),
        'time_pos': attribute(float, 0.0),
        'osdlevel': attribute(int, 0),
        'speed': attribute(float, 1.0),
        'path': attribute(str, 1.0),
        'length': attribute(float, -1),
        'switch_audio': attribute(int, 0),
        'sub': attribute(int, 0),
        'sub_source': attribute(int, 0),
        'pause': attribute(str, 0),
    }

    def __new__(cls, name, bases, attrs):
        for attr_name, cmd in cls._command_map.items():
            attrs[attr_name] = cls.make_method(cls, attr_name, cmd)

        for attr_name, params in cls._attrs.items():
            attrs[attr_name] = cls.make_attr(cls, attr_name, params.coerce, params.default)

        return super().__new__(cls, name, bases, attrs)

    def make_method(cls, attr_name, cmd):
        def method(self):
            if isinstance(cmd, str):
                return self.command(cmd)
            else:
                assert isinstance(cmd, tuple)
                return self.command(*cmd)
        return method

    def make_attr(cls, attr_name, coerce, default):
        @property
        @asyncio.coroutine
        def method(self):
            try:
                r = yield from self.get_property(attr_name)
            except AttributeError:
                r = default
            return coerce(r)
        return method


class VideoPlayer(metaclass=VideoPlayerMeta):
    # properties that mplayer doesn't report status messages for when setting
    _callbackless_properties = [
        'sub',
    ]

    def __init__(self):
        self.started = asyncio.Event()

        self.command_lock = asyncio.Lock()

        self.metadata = PlaybackMetadata(self)
        self._property_callbacks = []

    @asyncio.coroutine
    def get_progress(self):
        time_pos, length = yield from asyncio.gather(self.time_pos, self.length)

        if length <= 0.0:
            return ''

        progress = str(timedelta(seconds=time_pos)).split('.')[0]
        length = str(timedelta(seconds=length)).split('.')[0]
        return '{} / {}'.format(progress, length)

    @asyncio.coroutine
    def start_mplayer(self):
        proc = asyncio.subprocess.create_subprocess_exec(
            'mplayer',
            '-fs',  # fullscreen
            '-v',  # log 'EOF code' to stdout when videos finish
            '-slave',  # listen for stdin commands
            '-quiet',  # we don't need stdout every 100ms
            '-idle',  # don't quit when media isn't playing
            '-identify',  # log stream info to stdout for metadata
            '-osdlevel', '0',  # don't show OSD stuff

            #'nodefault-bindings:conf=/dev/null', '-noconfig', 'all',
            stdin=PIPE, stdout=PIPE, stderr=open(os.devnull, 'w'))

        proc = yield from proc

        self.started.set()

        self.proc = proc
        self.stdin = proc.stdin
        self.stdout = proc.stdout
        self.stderr = proc.stderr

        # reset the volume to a known state
        asyncio.async(self.reset_volume())
        asyncio.async(self.watch_for_metadata(self.stdout))

    @asyncio.coroutine
    def command(self, name, *args, pausing_keep_force=True):
        yield from self.started.wait()

        with (yield from self.command_lock):
            cmd = ' '.join(map(str, args))
            cmd = '{} {}\n'.format(name, cmd)

            # not exiting the pause loop for a pause toggle doesn't really work
            if pausing_keep_force:
                cmd = '{} {}'.format('pausing_keep_force', cmd)

            self.stdin.write(cmd.encode('utf8'))

            try:
                yield from self.stdin.drain()
            except ConnectionResetError:
                return

    @asyncio.coroutine
    def get_percent_pos(self):
        return self.command('get_percent_pos')

    @asyncio.coroutine
    def toggle(self):
        return self.command('pause', pausing_keep_force=False)

    @asyncio.coroutine
    def play(self, media_file, append=False):
        # FIXME: quote this properly
        return self.command('loadfile', '"{}"'.format(media_file), int(append), pausing_keep_force=append)

    @asyncio.coroutine
    def reset_volume(self):
        return self.set_volume(50)

    @asyncio.coroutine
    def set_volume(self, amount, absolute=True):
        return self.command('volume', amount, int(absolute))

    @property
    @asyncio.coroutine
    def volume(self):
        try:
            v = yield from self.get_property('volume')
        except AttributeError:
            v = None

        log.info("volume = {!r}", v)
        return v

    @asyncio.coroutine
    def seek_backward(self, seek_size):
        if self.metadata.has_chapters:
            return self.command('seek_chapter', -1, 0)
        return self.command('seek', -seek_size, 0)

    @asyncio.coroutine
    def seek_forward(self, seek_size):
        if self.metadata.has_chapters:
            return self.command('seek_chapter', 1, 0)
        return self.command('seek', seek_size, 0)

    @asyncio.coroutine
    def load_srt_subtitle(self, path):
        return self.command('sub_load', '"{}"'.format(path))

    @asyncio.coroutine
    def set_subtitle(self, sid):
        if sid.startswith('demux_'):
            offset = len('demux_')
            command = 'sub_demux'
        elif sid.startswith('download_'):
            offset = len('download_')
            lang = sid[offset:]
            yield from events.broadcast(
                'download-subtitle',
                path=self.metadata.filename, language=lang)
            return
        else:
            assert sid.startswith('file_'), sid
            offset = len('file_')
            command = 'sub_file'

        log.info('Setting subtitle to {}', sid)
        sid = sid[offset:]
        yield from self.command(command, sid)

    @asyncio.coroutine
    def set_audio(self, sid):
        return self.set_property('switch_audio', sid)

    @asyncio.coroutine
    def watch_for_metadata(self, stream):
        while True:
            line = yield from stream.readline()
            if not line:
                break

            try:
                line = line.strip().decode('utf8')
            except UnicodeDecodeError:
                if line.startswith('ID_FILENAME'):
                    yield from self.metdata.update_playback_info('filename', None)
                #log.warning("Error decoding line {!r}", line)
                continue

            if line.startswith('ANS_') or line.lower().startswith('ID_AUDIO_TRACK'):
                line = re.sub(r'(?:ANS_|ID_)(.+)', r'\1', line)
                key, value = line.split('=', 1)
                self.answer_get_property(key.lower(), value)
            elif line.startswith('ID_'):
                key, value = line.split('=', 1)
                key = key.lower()[3:]
                yield from self.metadata.update_playback_info(key, value)
            elif line.startswith('EOF code: 1'):
                assert self.metadata.filename is not None, "How can a video finish that we didn't know about?"

                m = get_movie_or_tv_show(self.metadata.filename)
                m.watched = True
                m.save()

                if isinstance(m, TVShowEpisode):
                    show = m.show
                    if all([episode.watched for episode in show.episodes]):
                        show.watched = True
                        if show.is_dirty():
                            show.save()

                self.metadata.reset()

                # can't yield from this because this loop is what handles these
                # requests.
                asyncio.async(self.metadata.broadcast_all_properties())
            else:
                continue

    @asyncio.coroutine
    def set_property(self, name, value):
        yield from self.started.wait()

        if self.proc.returncode is not None:
            raise AttributeError('mplayer unexpectedly terminated')

        log.debug("setting {}={}", name, value)

        # XXX: disabled this because I can't actually see mplayer reporting
        # values at all when set?
        #future = asyncio.Future()
        #if name in self._callbackless_properties:
        #    log.debug("early bail")
        #    future.set_result(None)
        #else:
        #    future.property_name = name
        #    self._property_callbacks.append(future)

        #yield from self.command('set_property', name, value)

        #try:
        #    yield from future
        #except AttributeError:
        #    log.debug('Attribute error from setting {}', name)

    @asyncio.coroutine
    def get_property(self, name):
        yield from self.started.wait()

        if self.proc.returncode is not None:
            raise AttributeError('mplayer unexpectedly terminated')

        future = asyncio.Future()
        future.property_name = name
        self._property_callbacks.append(future)

        yield from self.command('get_property', name)

        result = yield from future

        return result

    def answer_get_property(self, key, value):
        log.debug("answering {}={}", key, value)
        if not self._property_callbacks:
            log.critical("Tried to respond to a property that wasn't asked for: {}: {}", key, value)
            return
        future = self._property_callbacks.pop(0)

        if key == 'error':
            future.set_exception(AttributeError(future.property_name))
        else:
            if not property_matches(key, future.property_name):
                log.warning("Key doesn't match what was asked {} != {}", key, future.property_name)
            future.set_result(value)


class PlaybackMetadata:
    """Class for storing metadata about the currently playing video."""
    def __init__(self, player):
        self.player = player
        self.reset()

    def reset(self):
        self.filename = None
        self.audio_streams = {}
        self.subtitle_streams = {}
        self.subtitle_files = {}
        self.subtitle_file_language_map = {}
        self.subtitle_downloads = {}
        self.has_chapters = False

    def add_available_srt_subtitles(self):
        path = pathlib.Path(self.filename)
        glob = '{}*.srt'.format(path.stem)
        glob = re.sub(r'\[', '[[]', glob)
        glob = re.sub(r'(?<!\[)\]', '[]]', glob)

        coros = []

        for subtitle in path.parent.glob(glob):
            subtitle = pathlib.Path(subtitle)
            language = get_language(subtitle)

            if language is not None:
                self.subtitle_file_language_map[str(subtitle)] = language

                coro = self.player.load_srt_subtitle(subtitle)
                coros.append(coro)

        asyncio.async(asyncio.gather(*coros))

    @asyncio.coroutine
    def update_playback_info(self, key, value):
        sub_or_audio_match = re.match(r'(?P<type>[sa])id_(?P<id>\d+)_lang', key)

        if key == 'filename':
            self.filename = value

            if self.filename is not None:
                self.add_available_srt_subtitles()

                media = get_movie_or_tv_show(self.filename)
                now_playing = media.title
                log.info('now playing {}', now_playing)

                asyncio.async(events.broadcast('list-subtitles', path=self.filename))

            asyncio.async(asyncio.gather(
                self.broadcast_now_playing(),
                self.broadcast_volume(),
            ))
        elif key == 'video_id':
            self.reset()
        elif key.startswith('file_sub_id'):
            self.file_sub_id = value
        elif key.startswith('file_sub_filename'):
            lang = self.subtitle_file_language_map[value]
            self.subtitle_files[self.file_sub_id] = lang
            track_id = 'file_{}'.format(self.file_sub_id)
            self.file_sub_id = None
            asyncio.async(asyncio.gather(
                self.broadcast_available_subtitles(),
                self.check_subtitle_preference(track_id, lang),
            ))
        elif sub_or_audio_match:
            track_type, track_id = sub_or_audio_match.groups()
            if track_type == 's':
                self.subtitle_streams[track_id] = value
                asyncio.async(asyncio.gather(
                    self.broadcast_available_subtitles(),
                    self.check_subtitle_preference(track_id, value),
                ))
            elif track_type == 'a':
                self.audio_streams[track_id] = value
                asyncio.async(asyncio.gather(
                    self.broadcast_available_audio(),
                    self.check_audio_preference('demux_{}'.format(track_id), value),
                ))
            else:
                assert False, 'unhandled track type {}'.format(track_type)
        elif key == 'exit':
            log.info('CLIENT INITIATED STOP')
            asyncio.get_event_loop().stop()
        elif key.startswith('chapter'):
            self.has_chapters = True
        else:
            log.debug('\tunknown property {}={}', key, value)

    @asyncio.coroutine
    def check_audio_preference(self, aid, isoname):
        s = Config.get('player', 'preferred audio')

        if isoname == s:
            log.info('Setting audio to {}', isocodes.nicename(isoname))
            yield from self.player.set_audio(aid)

    @asyncio.coroutine
    def check_subtitle_preference(self, sid, isoname):
        s = Config.get('player', 'preferred subtitle')

        if isoname == s:
            audio = yield from self.player.switch_audio
            alang = self.audio_streams.get(audio)
            if (alang == isoname and
                    not int(Config.get('player', 'subtitles for matching audio'))):
                log.info('Not setting subtitle as subtitle and language match.')
                return False

            log.info('Setting subtitle to {}', isocodes.nicename(isoname))
            yield from self.player.set_subtitle(sid)

            return True

        return False

    @asyncio.coroutine
    def broadcast_now_playing(self):
        if self.filename is None:
            now_playing = None
        else:
            media = get_movie_or_tv_show(self.filename)
            now_playing = media.title

        yield from broadcast_player_property('now_playing', now_playing)

    @asyncio.coroutine
    def broadcast_volume(self):
        volume = yield from self.player.volume
        yield from broadcast_player_property('volume', volume)

    @asyncio.coroutine
    def broadcast_subtitle(self):
        sub_source, sub = yield from asyncio.gather(
            self.player.sub_source,
            self.player.sub,
        )

        prefix = [
            'file_',
            'vobsub_',
            'demux_',
        ][sub_source]

        subtitle = '{}{}'.format(prefix, sub)

        yield from broadcast_player_property('selected_subtitle', subtitle)

    @asyncio.coroutine
    def broadcast_available_audio(self):
        audio_streams = [
            dict(value=aid, display=isocodes.nicename(alang))
            for (aid, alang) in self.audio_streams.items()
        ]

        if len(audio_streams) <= 1:
            audio_streams = None
        else:
            audio_streams = sorted(audio_streams, key=itemgetter('display'))

        yield from broadcast_player_property('available_audio', audio_streams)

    @asyncio.coroutine
    def broadcast_available_subtitles(self):
        subtitles = []
        if self.subtitle_streams:
            subtitles.extend([
                dict(value='demux_{}'.format(sid), display=isocodes.nicename(slang))
                for (sid, slang) in self.subtitle_streams.items()
            ])

        if self.subtitle_files:
            subtitles.extend([
                dict(value='file_{}'.format(sid), display=isocodes.nicename(slang))
                for (sid, slang) in self.subtitle_files.items()
            ])

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
        audio, sub = yield from asyncio.gather(
            self.player.switch_audio,
            self.player.sub,
        )

        yield from asyncio.gather(
            self.broadcast_now_playing(),
            self.broadcast_available_subtitles(),
            self.broadcast_available_audio(),
            self.broadcast_subtitle(),
            broadcast_player_property('selected_audio', str(audio)),
            self.broadcast_volume(),
        )


class Server:
    simple_actions = [
        'next',
        'previous',
        'toggle',
    ]

    @asyncio.coroutine
    def start(self):
        self.player = VideoPlayer()

        yield from self.player.start_mplayer()

        asyncio.async(self.update_per_second())
        asyncio.async(self.event_listener())

        yield from websockets.serve(self.handle_websocket, '0.0.0.0', 5002)

    @asyncio.coroutine
    def update_per_second(self):
        while True:
            path, pause, percent, progress = yield from asyncio.gather(
                self.player.path,
                self.player.pause,
                self.player.percent_pos,
                self.player.get_progress(),
            )

            if path != '(null)' or pause == 'no':
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
                if self.player.metadata.filename == event.video_path:
                    # FIXME: if that path was already loaded, trim the old one then readd it.
                    self.player.metadata.subtitle_downloads.pop(event.language)
                    self.player.metadata.subtitle_file_language_map[event.path] = event.language
                    asyncio.async(self.player.load_srt_subtitle(event.path))
            elif event.type == 'new-client':
                yield from self.player.metadata.broadcast_all_properties()
            elif event.type == 'available-subtitles':
                current_languages = set(itertools.chain(
                    self.player.metadata.subtitle_file_language_map.values(),
                    self.player.metadata.subtitle_streams.values(),
                ))

                for lang in event.languages:
                    if lang in current_languages:
                        continue
                    nicename = isocodes.nicename(lang) if isocodes.exists(lang) else '{} (Unknown)'.format(lang)
                    self.player.metadata.subtitle_downloads[lang] = '{} (Download)'.format(nicename)
                yield from self.player.metadata.broadcast_available_subtitles()

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

        if method in self.simple_actions:
            try:
                yield from getattr(self.player, method)()
            except Exception:
                log.exception('Error running {!r}', method)

        elif callable is None:
            log.warning('Unhandled command {} {}', method, arguments)
        else:
            try:
                yield from callable(**arguments)
            except Exception:
                log.exception('Error running {!r}', method)

    @asyncio.coroutine
    def ws_play(self, id, type, append=False):
        if type == 'movie':
            model = Movie
        else:
            model = TVShowEpisode

        path = model.select(model.path).where(model.id == int(id)).get().path

        yield from self.player.play(path, append=append)

    @asyncio.coroutine
    def ws_stop(self):
        yield from self.player.stop()
        self.player.metadata.reset()
        yield from self.player.metadata.broadcast_all_properties()

    @asyncio.coroutine
    def ws_queue(self, id, type):
        return self.ws_play(id, type, append=True)

    @asyncio.coroutine
    def ws_subtitle(self, sid):
        log.debug('subtitle({})', sid)
        yield from self.player.set_subtitle(sid or 'demux_-1')
        yield from self.player.metadata.broadcast_subtitle()

    @asyncio.coroutine
    def ws_audio(self, aid):
        log.debug('audio({})', aid)
        yield from self.player.set_audio(aid or '-1')
        yield from broadcast_player_property('selected_audio', str((yield from self.player.switch_audio)))

    @asyncio.coroutine
    def ws_volume(self, volume):
        log.debug('volume({})', volume)
        yield from self.player.set_volume(volume)
        yield from self.player.metadata.broadcast_volume()

    @asyncio.coroutine
    def ws_seek_forward(self):
        seek_size = int(Config.get('player', 'seek size', default=15))
        yield from self.player.seek_forward(seek_size)

    @asyncio.coroutine
    def ws_seek_backward(self):
        seek_size = int(Config.get('player', 'seek size', default=15))
        yield from self.player.seek_backward(seek_size)

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
                yield from self.player.play(path, append=append)
                append = True
                first = False
            else:
                yield from self.player.play(path, append=append)

    @asyncio.coroutine
    def ws_queue_season(self, id, season):
        return self.ws_play_season(id, season, append=True)


def get_movie_or_tv_show(path):
    try:
        media = TVShowEpisode.select().where(TVShowEpisode.path == path).get()
    except TVShowEpisode.DoesNotExist:
        media = Movie.select().where(Movie.path == path).get()
    return media


def property_matches(a, b):
    a, b = sorted([a, b])

    if a == b:
        return True
    elif a == 'audio_track' and b == 'switch_audio':
        return True
    else:
        return False


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
