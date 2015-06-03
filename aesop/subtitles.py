import pathlib
import gzip
import asyncio
import hashlib
import os
import struct
import collections

import aiohttp
from aioxmlrpc.client import ServerProxy
from logbook import Logger

from aesop import isocodes, events
from aesop.utils import setup_logging

log = Logger('aesop.subtitles')


AvailableSubtitle = collections.namedtuple('AvailableSubtitle', 'download_count lang url')


def hash_opensubtitles(video_path):
    """Compute a hash using OpenSubtitles' algorithm

    :param string video_path: path of the video
    :return: the hash
    :rtype: string

    """

    log.debug("Calculating opensubtitles hash for {}", video_path)

    bytesize = struct.calcsize(b'<q')
    with open(video_path, 'rb') as f:
        filesize = os.path.getsize(video_path)
        filehash = filesize
        if filesize < 65536 * 2:
            log.info("{} is less than 128kb, not calculating hash", video_path)
            return None, filesize
        for _ in range(65536 // bytesize):
            filebuffer = f.read(bytesize)
            (l_value,) = struct.unpack(b'<q', filebuffer)
            filehash += l_value
            filehash = filehash & 0xFFFFFFFFFFFFFFFF  # to remain as 64bit number
        f.seek(max(0, filesize - 65536), 0)
        for _ in range(65536 // bytesize):
            filebuffer = f.read(bytesize)
            (l_value,) = struct.unpack(b'<q', filebuffer)
            filehash += l_value
            filehash = filehash & 0xFFFFFFFFFFFFFFFF
    returnedhash = '%016x' % filehash

    log.debug(
        "opensubtitles hash for {}: {} ({} bytes)",
        video_path, returnedhash, filesize)

    return returnedhash, filesize


def hash_thesubdb(video_path):
    """Compute a hash using TheSubDB's algorithm

    :param string video_path: path of the video
    :return: the hash
    :rtype: string

    """
    readsize = 64 * 1024
    filesize = os.path.getsize(video_path)
    if filesize < readsize:
        return None, filesize
    with open(video_path, 'rb') as f:
        data = f.read(readsize)
        f.seek(-readsize, os.SEEK_END)
        data += f.read(readsize)
    return hashlib.md5(data).hexdigest(), filesize


@asyncio.coroutine
def from_opensubtitles(media_path, requested_language=None):
    searches = []

    hash, size = hash_opensubtitles(media_path)

    if hash is not None:
        server = ServerProxy('http://api.opensubtitles.org/xml-rpc')
        log.debug("Authenticating to opensubtitles")

        response = yield from server.LogIn('', '', 'eng', 'aesop v0.1')
        token = response['token']

        searches.append({'moviehash': hash, 'moviebytesize': str(size)})

        log.debug("Searching opensubtitles for {}", searches)
        response = yield from server.SearchSubtitles(token, searches)
        raw_subtitles = response['data']

        if not raw_subtitles:
            raw_subtitles = []

        subtitles = []
        for subtitle in raw_subtitles:
            lang = subtitle['SubLanguageID']
            url = subtitle['SubDownloadLink']
            downloads = subtitle['SubDownloadsCnt']
            format = subtitle['SubFormat']

            if format != 'srt':
                continue

            if requested_language is not None and lang != requested_language:
                continue

            sub = AvailableSubtitle(downloads, lang, url)
            subtitles.append(sub)

        yield from server.LogOut(token)
        yield from server.close()
    else:
        subtitles = []

    log.info("{} subtitles for {}", len(subtitles), media_path)

    return subtitles


@asyncio.coroutine
def download_subtitles(path, language):
    nicename = isocodes.nicename(language)
    suffix = '.{}.srt'.format(nicename)
    subpath = pathlib.Path(path).with_suffix(suffix)

    if subpath.is_file():
        log.info("{} already exists, not downloading", subpath)
        return

    subtitles = yield from from_opensubtitles(path, requested_language=language)

    for subtitle in subtitles:
        log.info("Attempting to download {}", subtitle.url)

        resp = yield from aiohttp.request('GET', subtitle.url)
        if resp.status != 200:
            log.info("{} for {}, ignoring", resp.status, subtitle.url)
            continue

        try:
            data = yield from resp.read_and_close()
        except Exception:
            log.exception("Error downloading {}", subtitle.url)
            continue

        try:
            data = gzip.decompress(data)
        except Exception:
            log.exception("Error decompressing {}", subtitle.url)
            continue

        # FIXME: If any subtitles already exist, calculate hash and compare to
        # what was stated - if it's the same, skip it as we're going to replace
        # with the next subtitle.

        try:
            with subpath.open('wb') as f:
                f.write(data)
        except Exception:
            log.exception("Could not write to {}", path)
            continue

        log.info("Downloaded {} subtitle for {} to {}", nicename, path, subpath)
        return subpath


def main():
    listener = events.listener('download-subtitle', 'list-subtitles')

    while True:
        event = yield from listener.wait()

        if event is None:
            break

        if event.type == 'list-subtitles':
            subtitles = yield from from_opensubtitles(event.path)
            languages = sorted(set(s.lang for s in subtitles))
            log.info("Available languages for {}: {}", event.path, languages)
            yield from events.broadcast('available-subtitles', path=event.path, languages=languages)
        else:
            result = yield from download_subtitles(event.path, event.language)
            if result:
                yield from events.broadcast('subtitle-downloaded', path=str(result), video_path=event.path, language=event.language)

if __name__ == '__main__':
    setup_logging('aesop.ui', 'INFO')
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
