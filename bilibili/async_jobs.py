"""Bounded background jobs; completion is delivered through Qt queued signals."""
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class JobSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class BackgroundJob(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = JobSignals()

    def run(self):
        try:
            self.signals.result.emit(self.function())
        except Exception as error:
            self.signals.error.emit(str(error))
        finally:
            self.signals.finished.emit()


class BackgroundPool(QObject):
    def __init__(self, parent=None, workers=2):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(workers)
        self.active = set()

    def submit(self, function, result=None, error=None):
        job = BackgroundJob(function)
        self.active.add(job)
        if result:
            job.signals.result.connect(result)
        if error:
            job.signals.error.connect(error)
        job.signals.finished.connect(lambda: self.active.discard(job))
        self.pool.start(job)
        return job

    def discard_queued(self):
        for job in tuple(self.active):
            try:
                if self.pool.tryTake(job):
                    self.active.discard(job)
            except RuntimeError:
                # A completed runnable may be awaiting its queued finished signal.
                pass
