"""Exceptions raised by fenecon_modbus."""


class FeneconError(Exception):
    """Base class for all errors raised by this library."""


class FeneconConnectionError(FeneconError):
    """The FEMS could not be reached or the connection was lost."""


class FeneconTimeoutError(FeneconConnectionError):
    """The FEMS did not answer within the configured timeout."""


class FeneconInvalidResponseError(FeneconError):
    """The FEMS answered with an error or with data that cannot be decoded."""
