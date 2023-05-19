try:
    from ._version import version as __version__
except ImportError:
    __version__ = "99.0+local"