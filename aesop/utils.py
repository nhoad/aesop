import asyncio
import os
from urllib.parse import urlparse

import aiohttp


def damerau_levenshtein(first_string, second_string):
    """Returns the Damerau-Levenshtein edit distance between two strings."""
    previous = None
    prev_a = None

    current = [i for i, x in enumerate(second_string, 1)] + [0]

    for a_pos, a in enumerate(first_string):
        prev_b = None
        previously_previous, previous, current = previous, current, [0] * len(second_string) + [a_pos+1]

        for b_pos, b in enumerate(second_string):
            cost = int(a != b)
            deletion = previous[b_pos] + 1
            insertion = current[b_pos-1] + 1
            substitution = previous[b_pos-1] + cost

            current[b_pos] = min(deletion, insertion, substitution)

            if prev_b and prev_a and a == prev_b and b == prev_a and a != b:
                current[b_pos] = min(current[b_pos], previously_previous[b_pos-2] + cost)

            prev_b = b
        prev_a = a
    return current[len(second_string) - 1]


def complete(value):
    """asyncio equivalent to `twisted.internet.defer.succeed`"""
    f = asyncio.Future()
    f.set_result(value)
    return f


roman_numeral_table = [
    ('M', 1000),
    ('CM', 900),
    ('D', 500),
    ('CD', 400),
    ('C', 100),
    ('XC', 90),
    ('L', 50),
    ('XL', 40),
    ('X', 10),
    ('IX', 9),
    ('V', 5),
    ('IV', 4),
    ('I', 1)
]


def int_to_roman(num):
    def parts():
        nonlocal num
        for letter, value in roman_numeral_table:
            while value <= num:
                num -= value
                yield letter
    return ''.join(parts())


class RequestManager:
    """Gross class for managing active requests.

    The only thing it really does is make sure that anything using `get()`
    won't send out duplicate requests. This is useful when trying to download
    metadata for new series.
    """

    # FIXME: make this connection map configurable.
    connection_map = {
        'www.omdbapi.com': 20,
    }

    current_requests = {}
    limits = {}
    CONN_POOL = aiohttp.TCPConnector()

    count = 0

    @classmethod
    def get_pool(cls, key):
        if key not in cls.limits:
            limit = cls.connection_map.get(key, 50)
            cls.limits[key] = asyncio.BoundedSemaphore(limit)
        return cls.limits[key]

    def __init__(self, url, **kwargs):
        self.url = url
        self.kwargs = kwargs
        self.callbacks = []

        RequestManager.count += 1

    @asyncio.coroutine
    def run(self):
        key = urlparse(self.url).netloc

        p = self.get_pool(key)
        with (yield from p):
            response = yield from aiohttp.request('GET', self.url, connector=self.CONN_POOL, **self.kwargs)

        try:
            json = yield from response.json()
        except Exception as e:
            for cb in self.callbacks:
                cb.set_exception(e)
        else:
            for cb in self.callbacks:
                cb.set_result((response, json))

    def wait_for(self):
        self.callbacks.append(asyncio.Future())
        return self.callbacks[-1]


def get(url, **kwargs):
    full_url = url + '&'.join(sorted('='.join(kv) for kv in kwargs.get('params', {}).items()))

    if full_url in RequestManager.current_requests:
        return RequestManager.current_requests[full_url].wait_for()

    r = RequestManager(url, **kwargs)
    RequestManager.current_requests[full_url] = r
    asyncio.async(r.run())

    cb = r.wait_for()

    @cb.add_done_callback
    def callback(result):
        del RequestManager.current_requests[full_url]

    return r.wait_for()


def setup_logging(name, level):
    from logbook import RotatingFileHandler, lookup_level
    path = os.path.expanduser('~/.config/aesop/{}.log'.format(name))
    level = lookup_level(level)
    RotatingFileHandler(path, level=level).push_application()


def get_language(path):
    from aesop import isocodes

    for suffix in path.suffixes:
        suffix = suffix[1:]

        try:
            isoname = isocodes.isoname(suffix.title())
        except KeyError:
            pass
        else:
            return isoname

        if len(suffix) not in {2, 3}:
            continue

        suffix = suffix.lower()

        if len(suffix) == 2:
            try:
                suffix = isocodes.iso2to3(suffix)
            except KeyError:
                continue

        try:
            isocodes.nicename(suffix)
        except KeyError:
            pass
        else:
            return suffix
