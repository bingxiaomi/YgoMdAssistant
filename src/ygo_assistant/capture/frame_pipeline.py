"""One producer, bounded latest-frame delivery, no per-frame Qt event backlog."""
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Protocol

from .base import Frame

logger = logging.getLogger(__name__)


class FrameReader(Protocol):
    source: str
    ended: bool
    def read(self) -> Frame | None: ...
    def close(self) -> None: ...


class LatestFrames:
    def __init__(self, capacity: int):
        if capacity < 1:
            raise ValueError("Frame queue capacity must be positive")
        self._frames = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self.dropped = 0

    def put(self, frame: Frame) -> None:
        with self._lock:
            if len(self._frames) == self._frames.maxlen:
                self.dropped += 1
            self._frames.append(frame)

    def latest(self) -> Frame | None:
        with self._lock:
            if not self._frames:
                return None
            frame = self._frames.pop()
            self.dropped += len(self._frames)
            self._frames.clear()
            return frame

    def clear(self) -> None:
        with self._lock:
            self._frames.clear()

    def __len__(self):
        with self._lock:
            return len(self._frames)


@dataclass(frozen=True)
class PipelineStatus:
    message: str = "等待输入"
    error: str | None = None
    fps: float = 0
    frame_count: int = 0
    duration_ms: int = 0
    capture_ms: float = 0
    received: int = 0


class FramePipeline:
    def __init__(self, factory: Callable[[], FrameReader], *, live: bool,
                 capture_fps: int = 30, capacity: int = 2):
        self.frames = LatestFrames(capacity)
        self._factory = factory
        self.live = live
        self._fps = capture_fps
        self._condition = threading.Condition()
        self._stop = False
        self._paused = not live
        self._seek_index = None
        self._status = PipelineStatus(message="正在连接")
        self._thread = threading.Thread(target=self._run, name="frame-capture", daemon=True)

    @property
    def status(self) -> PipelineStatus:
        return self._status

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def start(self) -> None:
        self._thread.start()

    def set_paused(self, paused: bool) -> None:
        with self._condition:
            self._paused = paused
            self._condition.notify_all()

    def seek_frame(self, index: int) -> None:
        if self.live:
            return
        with self._condition:
            self._seek_index = max(0, index)
            self.frames.clear()
            self._condition.notify_all()

    def request_stop(self) -> None:
        with self._condition:
            self._stop = True
            self._condition.notify_all()

    def join(self, timeout: float = 2) -> bool:
        self._thread.join(timeout)
        return not self.alive

    def _run(self) -> None:
        reader = None
        try:
            # COM/DXGI and VideoCapture are created, used and released on this thread.
            reader = self._factory()
            fps = self._fps if self.live else reader.fps
            count = 0 if self.live else reader.frame_count
            duration = 0 if self.live else reader.duration_ms
            received = 0
            initial = True
            last_pts = None
            deadline = time.monotonic()
            while True:
                with self._condition:
                    while self._paused and not initial and self._seek_index is None and not self._stop:
                        self._condition.wait()
                        deadline = time.monotonic()
                        last_pts = None
                    if self._stop:
                        break
                    seek_index, self._seek_index = self._seek_index, None
                    if seek_index is None and not initial:
                        remaining = deadline - time.monotonic()
                        if remaining > 0:
                            self._condition.wait(remaining)
                            continue
                if seek_index is not None:
                    reader.seek_frame(seek_index)
                    self.frames.clear()
                    deadline = time.monotonic()
                    last_pts = None
                before = time.perf_counter()
                frame = reader.read()
                elapsed = (time.perf_counter() - before) * 1000
                if frame is None:
                    if reader.ended:
                        with self._condition:
                            self._paused = True
                        self._status = PipelineStatus("录像播放结束，可跳转或回到开头", fps=fps,
                                                      frame_count=count, duration_ms=duration, received=received)
                    else:
                        if getattr(reader, "suspended", False):
                            self.frames.clear()
                        self._status = PipelineStatus(getattr(reader, "status_message", "等待输入新帧"),
                                                      fps=fps, capture_ms=elapsed, received=received)
                        deadline = time.monotonic() + 1 / fps
                    initial = False
                    continue
                received += 1
                if received == 1:
                    logger.info("First frame source=%s backend=%s native_size=%dx%d source_timestamp_100ns=%s",
                                frame.source, frame.capture_backend, frame.width, frame.height,
                                frame.source_timestamp_100ns)
                self.frames.put(frame)
                self._status = PipelineStatus(getattr(reader, "status_message", "实时采集中") if self.live else "录像已就绪", fps=fps,
                                              frame_count=count, duration_ms=duration,
                                              capture_ms=elapsed, received=received)
                initial = False
                # PTS-aware pacing; CFR interval for first frame and live source.
                interval = 1 / fps if self.live or last_pts is None else max(0.001, (frame.timestamp_ms - last_pts) / 1000)
                last_pts = frame.timestamp_ms
                deadline = max(deadline + interval, time.monotonic())
        except Exception as exc:
            logger.exception("Frame source failed")
            self._status = PipelineStatus(message="采集已停止", error=str(exc))
        finally:
            if reader is not None:
                try:
                    reader.close()
                except Exception:
                    logger.exception("Failed to release frame source")
            logger.info("Frame worker finished received=%d dropped=%d", self._status.received, self.frames.dropped)
