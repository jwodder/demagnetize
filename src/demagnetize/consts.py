from . import __version__

#: Client string to use as the User-Agent for HTTP trackers, to send in
#: extended handshakes, and to use as the "Created by" field in Torrent files
CLIENT = f"demagnetize {__version__}"

#: Prefix for generated peer IDs
PEER_ID_PREFIX = "-DM-0030-"

#: "left" value to use when announcing to a tracker for a torrent we have only
#: the magnet link of
LEFT = 65535
# TODO: Look into appropriate values (For comparison, Transmission uses 2^63-1)

#: Number of peers to request per tracker
NUMWANT = 50

#: Extended message ID to declare for receiving BEP 9 messages
UT_METADATA = 42

#: Maximum length of a message to accept from a peer
MAX_PEER_MSG_LEN = 65535

#: Size of BEP 9 "data" message payloads
INFO_CHUNK_SIZE = 16 << 10

#: Overall timeout for interacting with a tracker
TRACKER_TIMEOUT = 30

#: Timeout for sending & receiving a "stopped" announcement to a tracker
TRACKER_STOP_TIMEOUT = 3

#: Maximum number of peers to interact with at once for a single magnet
PEERS_PER_MAGNET_LIMIT = 30

#: Timeout for connecting to a peer and performing the BitTorrent handshake
PEER_HANDSHAKE_TIMEOUT = 60

#: Maximum number of magnet links to operate on at once in batch mode
MAGNET_LIMIT = 50
