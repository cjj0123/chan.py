import asyncio
import logging
from typing import List, Callable, Any

class WebObject:
    """Mock QObject for Web/Async usage"""
    def __init__(self, parent=None):
        self._parent = parent

class WebSignal:
    """
    Mock PyQt pyqtSignal behavior for Web/Async usage
    """
    def __init__(self, *types):
        self._callbacks: List[Callable] = []

    def connect(self, callback: Callable):
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def emit(self, *args):
        # In an async environment, we might want to push these to a queue or process them in the event loop.
        # For simple callbacks, we just execute them.
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    # Should be scheduled in the correct event loop
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(callback(*args))
                    except RuntimeError:
                        # No running loop, just ignore or log
                        pass
                else:
                    callback(*args)
            except Exception as e:
                logging.error(f"Error in signal callback: {e}")

def pyqtSlot(*types, **kwargs):
    """Mock pyqtSlot decorator"""
    def decorator(func):
        return func
    return decorator
