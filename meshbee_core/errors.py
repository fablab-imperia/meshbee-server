"""The outcomes a service reports to whoever called it.

Three classes, deliberately. They exist so services can say what went wrong
without importing a web framework: the API maps them to status codes, the MQTT
handler logs them. Anything finer-grained belongs in the message.
"""


class CoreError(Exception):
    """Base class, so a caller can catch every service failure at once."""


class NotFound(CoreError):
    """The row the caller named does not exist."""


class Conflict(CoreError):
    """The write collides with something already stored."""


class InvalidData(CoreError):
    """The request is well-formed but asks for something that is not allowed."""
