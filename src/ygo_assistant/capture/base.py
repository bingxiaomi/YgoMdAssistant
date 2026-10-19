from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np


@dataclass(frozen=True, slots=True)
class Frame:
    frame_id: int
    timestamp_ms: int
    image: np.ndarray
    source: Literal["live_window", "video_file"]
    width: int
    height: int
    capture_backend: str | None = None
    source_timestamp_100ns: int | None = None

    def __post_init__(self) -> None:
        if self.frame_id < 0 or self.timestamp_ms < 0:
            raise ValueError("Frame ID and timestamp must be nonnegative")
        if self.source not in ("live_window", "video_file"):
            raise ValueError("Unsupported frame source")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Frame dimensions must be positive")
        if self.image.dtype != np.uint8 or self.image.shape != (self.height, self.width, 3):
            raise ValueError("Frame image must be H x W x 3 uint8 BGR")


class CaptureBackend(Protocol):
    source: str
    ended: bool
    def read(self) -> Frame | None: ...
    def close(self) -> None: ...
