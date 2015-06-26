#!/usr/bin/python

import os
from enum import Enum

from cffi import FFI

ffi = FFI()


definitions = """
unsigned long mpv_client_api_version(void);
typedef struct mpv_handle mpv_handle;
typedef enum mpv_error {
    MPV_ERROR_SUCCESS = 0,
    MPV_ERROR_EVENT_QUEUE_FULL = -1,
    MPV_ERROR_NOMEM = -2,
    MPV_ERROR_UNINITIALIZED = -3,
    MPV_ERROR_INVALID_PARAMETER = -4,
    MPV_ERROR_OPTION_NOT_FOUND = -5,
    MPV_ERROR_OPTION_FORMAT = -6,
    MPV_ERROR_OPTION_ERROR = -7,
    MPV_ERROR_PROPERTY_NOT_FOUND = -8,
    MPV_ERROR_PROPERTY_FORMAT = -9,
    MPV_ERROR_PROPERTY_UNAVAILABLE = -10,
    MPV_ERROR_PROPERTY_ERROR = -11,
    MPV_ERROR_COMMAND = -12,
    MPV_ERROR_LOADING_FAILED = -13,
    MPV_ERROR_AO_INIT_FAILED = -14,
    MPV_ERROR_VO_INIT_FAILED = -15,
    MPV_ERROR_NOTHING_TO_PLAY = -16,
    MPV_ERROR_UNKNOWN_FORMAT = -17,
    MPV_ERROR_UNSUPPORTED = -18,
    MPV_ERROR_NOT_IMPLEMENTED = -19
} mpv_error;
const char *mpv_error_string(int error);
void mpv_free(void *data);
const char *mpv_client_name(mpv_handle *ctx);
mpv_handle *mpv_create(void);
int mpv_initialize(mpv_handle *ctx);
void mpv_detach_destroy(mpv_handle *ctx);
void mpv_terminate_destroy(mpv_handle *ctx);
mpv_handle *mpv_create_client(mpv_handle *ctx, const char *name);
int mpv_load_config_file(mpv_handle *ctx, const char *filename);
void mpv_suspend(mpv_handle *ctx);
void mpv_resume(mpv_handle *ctx);
int64_t mpv_get_time_us(mpv_handle *ctx);
typedef enum mpv_format {
    MPV_FORMAT_NONE = 0,
    MPV_FORMAT_STRING = 1,
    MPV_FORMAT_OSD_STRING = 2,
    MPV_FORMAT_FLAG = 3,
    MPV_FORMAT_INT64 = 4,
    MPV_FORMAT_DOUBLE = 5,
    MPV_FORMAT_NODE = 6,
    MPV_FORMAT_NODE_ARRAY = 7,
    MPV_FORMAT_NODE_MAP = 8,
    MPV_FORMAT_BYTE_ARRAY = 9
} mpv_format;
typedef struct mpv_node {
    union {
        char *string;
        int flag;
        int64_t int64;
        double double_;
        struct mpv_node_list *list;
        struct mpv_byte_array *ba;
    } u;
    mpv_format format;
} mpv_node;
typedef struct mpv_node_list {
    int num;
    mpv_node *values;
    char **keys;
} mpv_node_list;
typedef struct mpv_byte_array {
    void *data;
    size_t size;
} mpv_byte_array;
void mpv_free_node_contents(mpv_node *node);
int mpv_set_option(mpv_handle *ctx, const char *name, mpv_format format,
                   void *data);
int mpv_set_option_string(mpv_handle *ctx, const char *name, const char *data);
int mpv_command(mpv_handle *ctx, const char **args);
int mpv_command_node(mpv_handle *ctx, mpv_node *args, mpv_node *result);
int mpv_command_string(mpv_handle *ctx, const char *args);
int mpv_command_async(mpv_handle *ctx, uint64_t reply_userdata,
                      const char **args);
int mpv_command_node_async(mpv_handle *ctx, uint64_t reply_userdata,
                           mpv_node *args);
int mpv_set_property(mpv_handle *ctx, const char *name, mpv_format format,
                     void *data);
int mpv_set_property_string(mpv_handle *ctx, const char *name, const char *data);
int mpv_set_property_async(mpv_handle *ctx, uint64_t reply_userdata,
                           const char *name, mpv_format format, void *data);
int mpv_get_property(mpv_handle *ctx, const char *name, mpv_format format,
                     void *data);
char *mpv_get_property_string(mpv_handle *ctx, const char *name);
char *mpv_get_property_osd_string(mpv_handle *ctx, const char *name);
int mpv_get_property_async(mpv_handle *ctx, uint64_t reply_userdata,
                           const char *name, mpv_format format);
int mpv_observe_property(mpv_handle *mpv, uint64_t reply_userdata,
                         const char *name, mpv_format format);
int mpv_unobserve_property(mpv_handle *mpv, uint64_t registered_reply_userdata);
typedef enum mpv_event_id {
    MPV_EVENT_NONE = 0,
    MPV_EVENT_SHUTDOWN = 1,
    MPV_EVENT_LOG_MESSAGE = 2,
    MPV_EVENT_GET_PROPERTY_REPLY = 3,
    MPV_EVENT_SET_PROPERTY_REPLY = 4,
    MPV_EVENT_COMMAND_REPLY = 5,
    MPV_EVENT_START_FILE = 6,
    MPV_EVENT_END_FILE = 7,
    MPV_EVENT_FILE_LOADED = 8,
    MPV_EVENT_TRACKS_CHANGED = 9,
    MPV_EVENT_TRACK_SWITCHED = 10,
    MPV_EVENT_IDLE = 11,
    MPV_EVENT_PAUSE = 12,
    MPV_EVENT_UNPAUSE = 13,
    MPV_EVENT_TICK = 14,
    MPV_EVENT_SCRIPT_INPUT_DISPATCH = 15,
    MPV_EVENT_CLIENT_MESSAGE = 16,
    MPV_EVENT_VIDEO_RECONFIG = 17,
    MPV_EVENT_AUDIO_RECONFIG = 18,
    MPV_EVENT_METADATA_UPDATE = 19,
    MPV_EVENT_SEEK = 20,
    MPV_EVENT_PLAYBACK_RESTART = 21,
    MPV_EVENT_PROPERTY_CHANGE = 22,
    MPV_EVENT_CHAPTER_CHANGE = 23,
    MPV_EVENT_QUEUE_OVERFLOW = 24
} mpv_event_id;
const char *mpv_event_name(mpv_event_id event);
typedef struct mpv_event_property {
    const char *name;
    mpv_format format;
    void *data;
} mpv_event_property;
typedef enum mpv_log_level {
    MPV_LOG_LEVEL_NONE = 0,
    MPV_LOG_LEVEL_FATAL = 10,
    MPV_LOG_LEVEL_ERROR = 20,
    MPV_LOG_LEVEL_WARN = 30,
    MPV_LOG_LEVEL_INFO = 40,
    MPV_LOG_LEVEL_V = 50,
    MPV_LOG_LEVEL_DEBUG = 60,
    MPV_LOG_LEVEL_TRACE = 70,
} mpv_log_level;
typedef struct mpv_event_log_message {
    const char *prefix;
    const char *level;
    const char *text;
    mpv_log_level log_level;
} mpv_event_log_message;
typedef enum mpv_end_file_reason {
    MPV_END_FILE_REASON_EOF = 0,
    MPV_END_FILE_REASON_STOP = 2,
    MPV_END_FILE_REASON_QUIT = 3,
    MPV_END_FILE_REASON_ERROR = 4,
} mpv_end_file_reason;
typedef struct mpv_event_end_file {
    int reason;
    int error;
} mpv_event_end_file;
typedef struct mpv_event_script_input_dispatch {
    int arg0;
    const char *type;
} mpv_event_script_input_dispatch;
typedef struct mpv_event_client_message {
    int num_args;
    const char **args;
} mpv_event_client_message;
typedef struct mpv_event {
    mpv_event_id event_id;
    int error;
    uint64_t reply_userdata;
    void *data;
} mpv_event;
int mpv_request_event(mpv_handle *ctx, mpv_event_id event, int enable);
int mpv_request_log_messages(mpv_handle *ctx, const char *min_level);
mpv_event *mpv_wait_event(mpv_handle *ctx, double timeout);
void mpv_wakeup(mpv_handle *ctx);
void mpv_set_wakeup_callback(mpv_handle *ctx, void (*cb)(void *d), void *d);
int mpv_get_wakeup_pipe(mpv_handle *ctx);
void mpv_wait_async_requests(mpv_handle *ctx);
typedef enum mpv_sub_api {
    MPV_SUB_API_OPENGL_CB = 1
} mpv_sub_api;
void *mpv_get_sub_api(mpv_handle *ctx, mpv_sub_api sub_api);

"""


ffi.cdef(definitions)

libmpv = ffi.verify('#include <mpv/client.h>', libraries=['mpv'])


def client(**kwargs):
    """Return an initialized client. Will be terminated upon garbage collection."""
    client = libmpv.mpv_create()

    for key, value in kwargs.items():
        set_option_string(client, key, value)

    r = libmpv.mpv_initialize(client)

    if r != 0:
        s = libmpv.mpv_error_string(r)
        raise Exception(ffi.string(s))
    return ffi.gc(client, libmpv.mpv_terminate_destroy)


def command(client, *args):
    r = libmpv.mpv_command(client, [ffi.new('char[]', _get_bytes(a)) for a in args] + [ffi.NULL])

    if r != 0:
        s = libmpv.mpv_error_string(r)
        raise Exception(ffi.string(s))


def set_option(client, name, type, value):
    if type == Format.String:
        return set_option_string(client, name)
    value, format = _get_value(type, value)

    r = libmpv.mpv_set_option(client, _get_bytes(name), format, value)
    if r != 0:
        s = libmpv.mpv_error_string(r)

        if r == libmpv.MPV_ERROR_PROPERTY_NOT_FOUND:
            raise AttributeError('{}: {}'.format(ffi.string(s), name))
        else:
            raise ValueError('{}: {}'.format(ffi.string(s), name))


def set_option_string(client, name, value):
    """Set the string representation of a given option."""
    r = libmpv.mpv_set_option_string(client, _get_bytes(name), _get_bytes(value))
    if r != 0:
        s = libmpv.mpv_error_string(r)

        if r == libmpv.MPV_ERROR_PROPERTY_NOT_FOUND:
            raise AttributeError('{}: {}'.format(ffi.string(s), name))
        else:
            raise ValueError('{}: {}'.format(ffi.string(s), name))


def set_property(client, name, type, value):
    if type == Format.String:
        return set_property_string(client, name)

    value, format = _get_value(type, value)

    r = libmpv.mpv_set_property(client, _get_bytes(name), format, value)
    if r != 0:
        s = libmpv.mpv_error_string(r)

        if r == libmpv.MPV_ERROR_PROPERTY_NOT_FOUND:
            raise AttributeError('{}: {}'.format(ffi.string(s), name))
        else:
            raise ValueError('{}: {}'.format(ffi.string(s), name))


def set_property_string(client, name, value):
    """Set the string representation of a given property."""
    r = libmpv.mpv_set_property_string(client, _get_bytes(name), _get_bytes(value))
    if r != 0:
        s = libmpv.mpv_error_string(r)

        if r == libmpv.MPV_ERROR_PROPERTY_NOT_FOUND:
            raise AttributeError('{}: {}'.format(ffi.string(s), name))
        else:
            raise ValueError('{}: {}'.format(ffi.string(s), name))


def get_property(client, name, type):
    """Return a given property of the client, with the given type.

    Raises AttributeError if the property could not be found. Raises ValueError
    if the property could not be retrieved for any other reason.
    """
    if type == Format.String:
        return get_property_string(client, name)
    value, format = _get_value(type)

    r = libmpv.mpv_get_property(client, _get_bytes(name), format, value)
    if r != 0:
        s = libmpv.mpv_error_string(r)

        if r == libmpv.MPV_ERROR_PROPERTY_NOT_FOUND:
            raise AttributeError('{}: {}'.format(ffi.string(s), name))
        else:
            raise ValueError('{}: {}'.format(ffi.string(s), name))

    return value[0]


def get_property_string(client, name):
    """Get the string representation of a given property."""
    s = libmpv.mpv_get_property_string(client, _get_bytes(name))
    s = ffi.gc(s, libmpv.mpv_free)
    if s == ffi.NULL:
        return None

    v = ffi.string(s)
    return v.decode('utf8')


def event_name(event_id):
    return ffi.string(libmpv.mpv_event_name(event_id)).decode('utf8')


def _get_bytes(s):
    if isinstance(s, bytes):
        return s
    return str(s).encode('utf8')


def _value_from_node(node):
    if node.format == libmpv.MPV_FORMAT_DOUBLE:
        return node.u.double_
    elif node.format == libmpv.MPV_FORMAT_INT64:
        return node.u.int64
    elif node.format == libmpv.MPV_FORMAT_FLAG:
        return node.u.flag
    elif node.format == libmpv.MPV_FORMAT_STRING:
        return ffi.string(node.u.string).decode('utf8')

    raise ValueError('Unhandled format {}'.format(node.format))


def _get_value(type, default=None):
    if type == Format.Float:
        c_type, format = ('double *', libmpv.MPV_FORMAT_DOUBLE)
    elif type == Format.Int:
        c_type, format = ('int64_t *', libmpv.MPV_FORMAT_INT64)
    elif type == Format.Flag:
        c_type, format = ('int *', libmpv.MPV_FORMAT_FLAG)
    elif type == Format.Node:
        c_type, format = ('mpv_node *', libmpv.MPV_FORMAT_NODE)

    return ffi.new(c_type, default), format

Format = Enum('Format', 'String Float Int Flag Node')


class Seek(Enum):
    Relative = 'relative'
    Absolute = 'absolute'
    AbsolutePercent = 'absolute-percent'
    Exact = 'exact'
    KeyFrames = 'keyframes'


class PlayListNav(Enum):
    Weak = 'weak'
    Force = 'force'


class CycleDirection(Enum):
    Up = 'up'
    Down = 'down'


class LoadFile(Enum):
    Replace = 'replace'
    Append = 'append'
    AppendPlay = 'append-play'


class Client:
    properties = {
        'aid': (Format.Int, 'rw'),
        'angle': (Format.Int, 'rw'),
        'ass-style-override': (Format.String, 'rw'),
        'ass-use-margins': (Format.Flag, 'rw'),
        'ass-vsfilter-aspect-compat': (Format.Flag, 'rw'),
        'audio': (Format.Int, 'rw'),
        'audio-bitrate': (Format.Float, 'r'),
        'audio-channels': (Format.String, 'r'),
        'audio-codec': (Format.String, 'r'),
        'audio-delay': (Format.Float, 'rw'),
        'audio-format': (Format.String, 'r'),
        'audio-samplerate': (Format.Int, 'r'),
        'avsync': (Format.Float, 'r'),
        'balance': (Format.Int, 'rw'),
        'border': (Format.Flag, 'rw'),
        'brightness': (Format.Int, 'rw'),
        'cache': (Format.Int, 'r'),
        'cache-size': (Format.Int, 'rw'),
        'chapter': (Format.Int, 'rw'),
        'chapters': (Format.Int, 'r'),
        'colormatrix': (Format.String, 'rw'),
        'colormatrix-input-range': (Format.String, 'rw'),
        'colormatrix-output-range': (Format.String, 'rw'),
        'colormatrix-primaries': (Format.String, 'rw'),
        'contrast': (Format.Int, 'rw'),
        'core-idle': (Format.Flag, 'r'),
        'deinterlace': (Format.String, 'rw'),
        'dheight': (Format.Int, 'r'),
        'disc-menu-active': (Format.Flag, 'r'),
        'disc-title': (Format.String, 'rw'),
        'disc-titles': (Format.Int, 'r'),
        'drop-frame-count': (Format.Int, 'r'),
        'dwidth': (Format.Int, 'r'),
        'edition': (Format.Int, 'rw'),
        'editions': (Format.Int, 'r'),
        'eof-reached': (Format.Flag, 'r'),
        'estimated-vf-fps': (Format.Float, 'r'),
        'file-size': (Format.Int, 'r'),
        'filename': (Format.String, 'r'),
        'fps': (Format.Float, 'r'),
        'framedrop': (Format.String, 'rw'),
        'fullscreen': (Format.Flag, 'rw'),
        'gamma': (Format.Float, 'rw'),
        'height': (Format.Int, 'r'),
        'hr-seek': (Format.Flag, 'rw'),
        'hue': (Format.Int, 'rw'),
        'hwdec': (Format.Flag, 'rw'),
        'length': (Format.Float, 'r'),
        'loop': (Format.String, 'rw'),
        'loop-file': (Format.String, 'rw'),
        'media-title': (Format.String, 'r'),
        'mute': (Format.Flag, 'rw'),
        'ontop': (Format.Flag, 'rw'),
        'osd-height': (Format.Int, 'r'),
        'osd-level': (Format.Int, 'rw'),
        'osd-par': (Format.Float, 'r'),
        'osd-scale': (Format.Float, 'rw'),
        'osd-width': (Format.Int, 'r'),
        'panscan': (Format.Float, 'rw'),
        'path': (Format.String, 'r'),
        'pause': (Format.Flag, 'rw'),
        'pause-for-cache': (Format.Flag, 'r'),
        'percent-pos': (Format.Float, 'rw'),
        'playlist-count': (Format.Int, 'r'),
        'playlist-pos': (Format.Int, 'rw'),
        'playtime-remaining': (Format.Float, 'r'),
        'program': (Format.Int, 'w'),
        'pts-association-mode': (Format.String, 'rw'),
        'quvi-format': (Format.String, 'rw'),
        'ratio-pos': (Format.Float, 'rw'),
        'saturation': (Format.Int, 'rw'),
        'secondary-sid': (Format.Int, 'rw'),
        'seekable': (Format.Flag, 'r'),
        'sid': (Format.Int, 'rw'),
        'speed': (Format.Float, 'rw'),
        'stream-capture': (Format.String, 'rw'),
        'stream-end': (Format.Int, 'r'),
        'stream-pos': (Format.Int, 'rw'),
        'sub': (Format.Int, 'rw'),
        'sub-delay': (Format.Float, 'rw'),
        'sub-forced-only': (Format.Flag, 'rw'),
        'sub-pos': (Format.Int, 'rw'),
        'sub-scale': (Format.Float, 'rw'),
        'sub-visibility': (Format.Flag, 'rw'),
        'time-pos': (Format.Float, 'rw'),
        'time-remaining': (Format.Float, 'r'),
        'time-start': (Format.Float, 'r'),
        'total-avsync-change': (Format.Float, 'r'),
        'tv-brightness': (Format.Int, 'rw'),
        'tv-contrast': (Format.Int, 'rw'),
        'tv-hue': (Format.Int, 'rw'),
        'tv-saturation': (Format.Int, 'rw'),
        'vid': (Format.Int, 'rw'),
        'video': (Format.Int, 'rw'),
        'video-align-x': (Format.Float, 'rw'),
        'video-align-y': (Format.Float, 'rw'),
        'video-aspect': (Format.String, 'rw'),
        'video-bitrate': (Format.Float, 'r'),
        'video-codec': (Format.String, 'r'),
        'video-format': (Format.String, 'r'),
        'video-pan-x': (Format.Int, 'rw'),
        'video-pan-y': (Format.Int, 'rw'),
        'video-unscaled': (Format.Flag, 'w'),
        'video-zoom': (Format.Float, 'rw'),
        'volume': (Format.Float, 'rw'),
        'width': (Format.Int, 'r'),
        'window-scale': (Format.Float, 'rw'),
    }

    def __init__(self, **kwargs):
        self.mpv = client(**kwargs)

    def __setattr__(self, attr, value):
        if attr.replace('_', '-') in self.properties:
            attr = attr.replace('_', '-')
            type, access = self.properties[attr]

            if 'w' in access:
                return set_property(self.mpv, attr, type, value)
            else:
                raise AttributeError('{} does not have write access'.format(attr))

        super().__setattr__(attr, value)

    def __getattr__(self, attr):

        if attr.replace('_', '-') in self.properties:
            attr = attr.replace('_', '-')
            type, access = self.properties[attr]

            if 'r' in access:
                return get_property(self.mpv, attr, type)
            else:
                raise AttributeError('{} does not have read access'.format(attr))
        raise AttributeError(attr)

    def loadfile(self, path, add_mode=LoadFile.Replace):
        command(self.mpv, 'loadfile', path, add_mode.value)

    def seek(self, seconds, seek=Seek.Relative):
        return command(self.mpv, 'seek', seconds, seek.value)

    def revert_seek(self):
        # FIXME: support [mode]
        return command(self.mpv, 'revert_seek')

    def frame_step(self):
        return command(self.mpv, 'frame_step')

    def frame_back_step(self):
        return command(self.mpv, 'frame_back_step')

    def cycle(self, property, direction=CycleDirection.Up):
        return command(self.mpv, 'cycle', property, direction.value)

    def playlist_next(self, playlist_nav=PlayListNav.Weak):
        return command(self.mpv, 'playlist_next', playlist_nav.value)

    def playlist_prev(self, playlist_nav=PlayListNav.Weak):
        return command(self.mpv, 'playlist_prev', playlist_nav.value)

    def playlist_clear(self):
        return command(self.mpv, 'playlist_clear')

    def playlist_remove(self, current_or_index='current'):
        return command(self.mpv, 'playlist_remove', current_or_index)

    def playlist_move(self, src, dst):
        return command(self.mpv, 'playlist_move', src, dst)

    def playlist_items(self):
        playlist = get_property(self.mpv, 'playlist', Format.Node)

        try:
            for i in range(playlist.u.list.num):
                m = playlist.u.list.values[i]

                props = {}

                for j in range(m.u.list.num):
                    key = ffi.string(m.u.list.keys[j]).decode('utf8')

                    value = _value_from_node(m.u.list.values[j])
                    props[key] = value

                yield props
        finally:
            libmpv.mpv_free_node_contents(ffi.addressof(playlist))

    def track_list(self):
        track_list = get_property(self.mpv, 'track-list', Format.Node)

        try:
            for i in range(track_list.u.list.num):
                m = track_list.u.list.values[i]

                props = {}

                for j in range(m.u.list.num):
                    key = ffi.string(m.u.list.keys[j]).decode('utf8')

                    value = _value_from_node(m.u.list.values[j])
                    props[key] = value

                yield props
        finally:
            libmpv.mpv_free_node_contents(ffi.addressof(track_list))

    def video_tracks(self):
        for track in self.track_list():
            if track['type'] == 'video':
                yield track

    def audio_tracks(self):
        for track in self.track_list():
            if track['type'] == 'audio':
                yield track

    def subtitles(self):
        for track in self.track_list():
            if track['type'] == 'sub':
                yield track

    def sub_add(self, path, flag='cached', title='n/a', lang=''):
        args = [path, flag, title]
        if lang:
            args.append(lang)

        return command(self.mpv, 'sub_add', *args)

    def sub_remove(self, sid):
        return command(self.mpv, 'sub_remove', sid)

    def sub_reload(self, sid):
        return command(self.mpv, 'sub_reload', sid)

    def osd(self, level):
        return command(self.mpv, 'osd', level)

    def show_text(self, text, duration, level):
        return command(self.mpv, 'show_text', text, duration, level)

    def show_progress(self):
        return command(self.mpv, 'show_progress')

    def stop(self):
        return command(self.mpv, 'stop')


class AsyncioClient(Client):
    def __init__(self, loop=None, **kwargs):
        import asyncio

        super().__init__(**kwargs)
        loop = loop or asyncio.get_event_loop()

        self.fd = libmpv.mpv_get_wakeup_pipe(self.mpv)
        assert self.fd != -1

        loop.add_reader(self.fd, self._read_events)

        self.event_queue = asyncio.Queue()

    def _read_events(self):
        import asyncio
        os.read(self.fd, 256)

        events = []
        while True:
            event = libmpv.mpv_wait_event(self.mpv, 0)
            if event.event_id == libmpv.MPV_EVENT_NONE:
                break

            events.append(event.event_id)

        asyncio.async(asyncio.gather(*[
            self.event_queue.put(e) for e in events]))
