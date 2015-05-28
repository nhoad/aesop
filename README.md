aesop, a simple media player.

A huge work in progress, but basically a very tiny competitor to Kodi. I've had
issues with Kodi on more than capable hardware for years, so I've given up and
done it myself.

Current features
================
 - Web based, no need to struggle with a keyboard or an IR remote.
 - FAST. Can load up hundreds of items in a second or two, not minutes like
   other media players.
 - Massive concurrency. On my terrible internet connection, I can scan
   about 2500 items a minute as opposed to the 50-100 I can do with Kodi. Keep
   in mind there's a lot of metadata Kodi colllects that aesop does not, so
   this isn't too surprising, but Kodi doesn't have any concurrency so it's
   still a win.
 - Tiny codebase, for those that like simplicity/want to hack it to do what
   they want.

Planned features
================
 - UPnP server that also doesn't suck (I have the basis for this going now)
 - Deluge/RSS integration
 - NFS/FTP/CIFS support
 - A lot of reworking the UI (I'm not a frontend person, I'm sorry)
