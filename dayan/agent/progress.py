"""Per-request progress, isolated across concurrent assistant worker threads."""
from contextlib import contextmanager
from contextvars import ContextVar

_sink=ContextVar('dayan_progress',default=None)


@contextmanager
def progress_scope(callback):
    token=_sink.set(callback)
    try:yield
    finally:_sink.reset(token)


def emit(message):
    callback=_sink.get()
    if callback:callback(str(message))
