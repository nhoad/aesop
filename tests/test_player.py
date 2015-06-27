import asyncio
from unittest import mock

import pytest

from aesop.mpv import Client
from aesop.player import Server, VideoPlayer


@pytest.yield_fixture
def server():
    v = Server()
    v.player = mock.MagicMock(VideoPlayer)
    v.player.client = mock.Mock(Client)
    with mock.patch('aesop.player.broadcast_player_property', return_value=result(None)):
        with mock.patch('aesop.models.BaseModel.select'):
            yield v


def run(coro):
    if coro is None:
        return

    loop = asyncio.new_event_loop()
    loop.run_until_complete(coro)
    loop.close()


def result(value):
    f = asyncio.Future()
    f.set_result(value)
    return f


class TestServer:
    def test_ws_next(self, server):
        run(server.ws_next())

    def test_ws_audio(self, server):
        run(server.ws_audio(5))

    def test_ws_play(self, server):
        run(server.ws_play(1, 'tvshow'))

    def test_ws_play_season(self, server):
        run(server.ws_play_season(1, 2))

    def test_ws_previous(self, server):
        run(server.ws_previous())

    def test_ws_queue(self, server):
        run(server.ws_queue(1, 'tvshow'))

    def test_ws_queue_season(self, server):
        run(server.ws_queue_season(1, 2))

    def test_ws_seek_backward(self, server):
        run(server.ws_seek_backward())

    def test_ws_seek_forward(self, server):
        run(server.ws_seek_forward())

    def test_ws_stop(self, server):
        run(server.ws_stop())

    def test_ws_subtitle(self, server):
        run(server.ws_subtitle(0))

    def test_ws_toggle(self, server):
        run(server.ws_toggle())

    def test_ws_volume(self, server):
        run(server.ws_volume(50))
