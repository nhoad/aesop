import asyncio
import json
from collections import namedtuple

import asyncio_redis
import websockets
from logbook import Logger

from aesop.utils import setup_logging

log = Logger('aesop.events')


EVENTS_CHANNEL = 'aesop-events'


def add_blocking(func):
    def blocking(*args, **kwargs):
        try:
            loop = asyncio.get_event_loop()
        except Exception:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        coro = func(*args, **kwargs)
        return loop.run_until_complete(coro)
    func.blocking = blocking
    return func


@asyncio.coroutine
@add_blocking
def info(message):
    return notify(message, level='info')


@asyncio.coroutine
@add_blocking
def error(message):
    return notify(message, level='error')


@asyncio.coroutine
@add_blocking
def warning(message):
    return notify(message, level='warning')


@asyncio.coroutine
@add_blocking
def success(message):
    return notify(message, level='success')


@asyncio.coroutine
@add_blocking
def notify(message, **kwargs):
    return broadcast(message=message, type='notification', **kwargs)


@asyncio.coroutine
@add_blocking
def broadcast(type, **kwargs):
    connection = yield from _get_connection()

    kwargs['type'] = type
    yield from connection.publish(EVENTS_CHANNEL, json.dumps(kwargs))

    connection.close()


@asyncio.coroutine
def _get_connection():
    connection = yield from asyncio_redis.Connection.create(host='localhost', port=6379)
    return connection


def listener(*events):
    ev = EventListener(events)
    asyncio.async(ev.start())
    return ev


class EventListener:
    def __init__(self, event_types):
        self.event_types = event_types
        self.waiters = []

    @asyncio.coroutine
    def start(self):
        self.connection = yield from _get_connection()
        self._subscriber = yield from self.connection.start_subscribe()

        yield from self._subscriber.subscribe([EVENTS_CHANNEL])

        yield from self._runner()

    @asyncio.coroutine
    def _runner(self):
        while True:
            event = yield from self._subscriber.next_published()
            event = json.loads(event.value)
            attrs = sorted(set(list(event.keys()) + ['private', 'type']))
            event.setdefault('private', False)
            event = namedtuple('Event', attrs)(**event)

            if self.event_types and event.type not in self.event_types:
                continue

            if event.type == 'shutdown':
                self.connection.close()
                event = None

            waiters, self.waiters = self.waiters, []

            for waiter in waiters:
                waiter.set_result(event)

    @asyncio.coroutine
    def wait(self):
        self.waiters.append(asyncio.Future())
        return self.waiters[-1]

    def close(self):
        self.connection.close()


@asyncio.coroutine
def server(websocket, path):
    client = ':'.join(map(str, websocket.writer.get_extra_info('peername')))
    log.info("New client {}", client)

    yield from broadcast('new-client', private=True)

    _listener = listener()

    while True:
        event = yield from _listener.wait()
        if event is None:
            break
        if event.private:
            continue

        log.info("{} <- {!r}", client, event)

        try:
            yield from websocket.send(json.dumps(event._asdict()))
        except websockets.InvalidState:
            _listener.close()
            return


def main():
    setup_logging('aesop.events')
    loop = asyncio.get_event_loop()
    loop.run_until_complete(websockets.serve(server, '0.0.0.0', 5001))
    log.info("Client event server started on port 5001")
    loop.run_forever()


if __name__ == '__main__':
    main()
