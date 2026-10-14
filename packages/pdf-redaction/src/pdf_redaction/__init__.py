"""Folder-level redaction: rules, engines, verification, sessions and publishing.

Privacy rule for every module in this package: never print, log or raise an exception message
that contains a matched value, a redaction term or an original file name. Report categories,
counts and already-redacted paths only.
"""

__version__ = "0.1.0"
