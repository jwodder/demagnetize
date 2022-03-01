class Error(Exception):
    pass


class TrackerError(Error):
    pass


class PeerError(Error):
    pass


class DemagnetizeFailure(Error):
    pass


class UnbencodeError(ValueError):
    pass


class UnknownBEP9MsgType(Exception):
    def __init__(self, msg_type: int) -> None:
        self.msg_type = msg_type


class CellClosedError(Exception):
    pass
