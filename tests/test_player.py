import asyncio
from unittest import mock

import pytest


@pytest.yield_fixture
def loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def result(value):
    f = asyncio.Future()
    f.set_result(value)
    return f


class TestPlaybackMetadata:
    @pytest.mark.parametrize('isoname,audio_streams,switch_audio,match_subtitles,expected_result', [
        ('eng', {}, 1, 1, True),
        ('rus', {}, 1, 1, False),
        ('eng', {1: 'eng'}, 1, 0, False),
        ('eng', {1: 'rus'}, 1, 0, True),
    ])
    def test_check_subtitle_preference(self, isoname, audio_streams, switch_audio, match_subtitles, expected_result, loop):
        from aesop.player import PlaybackMetadata
        from aesop.models import Config
        meta = PlaybackMetadata(player=mock.Mock())

        meta.audio_streams = audio_streams
        meta.player.set_subtitle.return_value = result(None)
        meta.player.switch_audio = result(switch_audio)

        def config_get(section, key):
            if key == 'preferred subtitle':
                return 'eng'
            elif key == 'subtitles for matching audio':
                return match_subtitles
            else:
                assert False, "Unknown key {}".format(key)

        with mock.patch.object(Config, 'get', config_get):
            coro = meta.check_subtitle_preference('1', isoname)
            set_subtitle = loop.run_until_complete(coro)

        assert set_subtitle == expected_result
