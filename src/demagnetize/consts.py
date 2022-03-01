from . import __version__

CLIENT = f"demagnetize {__version__}"

PEER_ID_PREFIX = "-DM-0010-"

# "left" value to use when announcing to a tracker for a torrent we have only
# the magnet URL of
LEFT = 65535
# TODO: Look into appropriate values (For comparison, Transmission uses 2^63-1)

NUMWANT = 50

UT_METADATA = 42

MAX_PEER_MSG_LEN = 65535

MAX_REQUEST_LENGTH = 1 << 14

KEEPALIVE_PERIOD = 120

INFO_CHUNK_SIZE = 16 << 10

TRACKER_TIMEOUT = 30
