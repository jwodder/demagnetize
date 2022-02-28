class Error(Exception):
    pass


class TrackerError(Error):
    pass


class DemagnetizeFailure(Error):
    pass


class UnbencodeError(ValueError):
    pass
