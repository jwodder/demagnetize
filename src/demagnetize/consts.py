from . import __version__

CLIENT = f"demagnetize {__version__}"

PEER_ID_PREFIX = "-DM-0010-"

# "left" value to use when announcing to a tracker for a torrent we have only
# the magnet URL of
LEFT = 65535
# TODO: Look into appropriate values (For comparison, Transmission uses 2^63-1)

NUMWANT = 50
