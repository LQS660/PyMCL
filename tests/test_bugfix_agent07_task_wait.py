# -*- coding: utf-8 -*-
"""Offline regression tests for BackendAPI.wait_task's actual Qt/thread logic.

Load the production method via AST, not a rewritten copy: importing BackendAPI
also initializes global configuration, and constructing it starts network/Java
warmups. The harness uses real Qt signals, QThread and threading.Event without
those unrelated filesystem/network side effects.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
import threading
import time
from types import MethodType, SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread, Qt, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


_BACKEND_PATH = Path(__file__).resolve().parents[1] / "app" / "backend.py"
_TREE = ast.parse(_BACKEND_PATH.read_text(encoding="utf-8"))
_CLASS = next(node for node in _TREE.body
              if isinstance(node, ast.ClassDef) and node.name == "BackendAPI")
_METHOD = next(node for node in _CLASS.body
               if isinstance(node, ast.FunctionDef) and node.name == "wait_task")


def _wait_method(event_type=threading.Event, monotonic=time.monotonic):
    namespace = {
        "threading": SimpleNamespace(Event=event_type),
        "time": SimpleNamespace(monotonic=monotonic),
        "Qt": Qt,
        "tr": lambda text: text,
    }
    module = ast.Module(body=[_METHOD], type_ignores=[])
    exec(compile(module, str(_BACKEND_PATH), "exec"), namespace)
    return namespace["wait_task"]


class _Backend(QObject):
    finished = Signal(str, bool, str)

    def __init__(self, method):
        super().__init__()
        self.wait_task = MethodType(method, self)
        self._task_results = {}
        self.cancelled_ids = []

    def cancel_task(self, task_id):
        self.cancelled_ids.append(task_id)

    def complete(self, task_id, ok, message):
        self._task_results[task_id] = (ok, message)
        self.finished.emit(task_id, ok, message)


def _recording_events():
    instances = []
    entered = threading.Event()

    class RecordingEvent(threading.Event):
        def __init__(self):
            super().__init__()
            self.waits = []
            instances.append(self)

        def wait(self, timeout=None):
            self.waits.append(timeout)
            entered.set()
            return super().wait(timeout)

    return RecordingEvent, instances, entered


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance
    instance.processEvents()


def _assert_disconnected(backend):
    assert backend.receivers("2finished(QString,bool,QString)") == 0


@pytest.mark.parametrize("ok", [True, False])
def test_bugfix_agent07_cached_result_does_not_wait(app, ok):
    event_type, events, _ = _recording_events()
    backend = _Backend(_wait_method(event_type))
    backend._task_results["cached"] = (ok, "already done")
    result = backend.wait_task("cached", timeout=0, cancelled=lambda: True)
    assert result == {"ok": ok, "message": "already done", "task_id": "cached"}
    assert events == []
    assert backend.cancelled_ids == []
    _assert_disconnected(backend)


@pytest.mark.parametrize("timeout", [0, -1])
def test_bugfix_agent07_expired_deadline_never_blocks(app, timeout):
    event_type, events, _ = _recording_events()
    backend = _Backend(_wait_method(event_type))
    result = backend.wait_task("pending", timeout=timeout)
    assert result["timeout"] is True
    assert events[0].waits == []
    assert backend.cancelled_ids == []  # A timeout must not cancel the task.
    _assert_disconnected(backend)


def test_bugfix_agent07_short_timeout_limits_event_wait(app):
    event_type, events, _ = _recording_events()
    backend = _Backend(_wait_method(event_type))
    started = time.monotonic()
    result = backend.wait_task("pending", timeout=0.03)
    elapsed = time.monotonic() - started
    assert result["timeout"] is True
    # Deterministic wait-argument check catches the old 400ms minimum, even on
    # a busy host where a tight elapsed-time assertion would be flaky.
    assert all(0 < seconds <= 0.030001 for seconds in events[0].waits)
    assert elapsed < 2.0
    _assert_disconnected(backend)


def test_bugfix_agent07_pre_cancelled_never_blocks(app):
    event_type, events, _ = _recording_events()
    backend = _Backend(_wait_method(event_type))
    result = backend.wait_task("pending", timeout=5, cancelled=lambda: True)
    assert result == {"ok": False, "message": "已停止", "task_id": "pending"}
    assert backend.cancelled_ids == ["pending"]
    assert events[0].waits == []
    _assert_disconnected(backend)


def test_bugfix_agent07_callback_time_is_included_in_deadline(app):
    now = [0.0]
    waits = []

    class TimedEvent(threading.Event):
        def wait(self, timeout=None):
            waits.append(timeout)
            now[0] += timeout
            return False

    def not_cancelled():
        now[0] += 0.75  # Cancellation checks can themselves take time.
        return False

    backend = _Backend(_wait_method(TimedEvent, monotonic=lambda: now[0]))
    result = backend.wait_task("pending", timeout=1, cancelled=not_cancelled)
    assert result["timeout"] is True
    assert len(waits) == 1
    assert waits[0] == pytest.approx(0.25)
    _assert_disconnected(backend)


def test_bugfix_agent07_cancel_after_wait_disconnects(app):
    event_type, events, _ = _recording_events()
    backend = _Backend(_wait_method(event_type))
    result = backend.wait_task(
        "pending", timeout=2, cancelled=lambda: bool(events[0].waits))
    assert result["ok"] is False and "timeout" not in result
    assert backend.cancelled_ids == ["pending"]
    assert len(events[0].waits) == 1
    _assert_disconnected(backend)


def test_bugfix_agent07_fast_finish_before_subscription(app):
    event_type, events, _ = _recording_events()
    backend = _Backend(_wait_method(event_type))

    class FinishesDuringLookup(dict):
        def __contains__(self, task_id):
            if not self:
                self[task_id] = (True, "fast finish")
                # First cache lookup missed, and completion precedes connect().
                backend.finished.emit(task_id, True, "fast finish")
                return False
            return super().__contains__(task_id)

    backend._task_results = FinishesDuringLookup()
    result = backend.wait_task("fast", timeout=0)
    assert result == {"ok": True, "message": "fast finish", "task_id": "fast"}
    assert events[0].waits == []
    _assert_disconnected(backend)


@pytest.mark.parametrize("ok", [True, False])
def test_bugfix_agent07_qthread_completion_and_unrelated_signal(app, ok):
    event_type, events, entered = _recording_events()
    backend = _Backend(_wait_method(event_type))
    results, errors = [], []

    class Waiter(QThread):
        def run(self):
            try:
                results.append(backend.wait_task("work", timeout=1.5))
            except BaseException as exc:
                errors.append(exc)

    worker = Waiter()
    worker.start()
    try:
        assert entered.wait(2), "QThread did not enter the bounded wait"
        backend.complete("other", not ok, "ignore this task")
        app.processEvents()
        assert not events[0].is_set()
        backend.complete("work", ok, "worker outcome")
        deadline = time.monotonic() + 3
        while worker.isRunning() and time.monotonic() < deadline:
            app.processEvents()
            worker.wait(10)
        assert worker.wait(200), "QThread exceeded the test deadline"
        assert errors == []
        assert results == [{"ok": ok, "message": "worker outcome", "task_id": "work"}]
        _assert_disconnected(backend)
    finally:
        # Never destroy a running QThread, even when a test assertion fails.
        for event in events:
            event.set()
        assert worker.wait(3000), "test QThread did not stop"
