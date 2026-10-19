import math
from pathlib import Path

import cv2

from .base import Frame


class VideoCapture:
    source = "video_file"

    def __init__(self, path: Path):
        if not path.is_file():
            raise ValueError(f"录像不存在：{path}")
        self._capture = cv2.VideoCapture(str(path))
        if not self._capture.isOpened():
            self._capture.release()
            raise ValueError(f"无法解码录像：{path.name}")
        fps = self._capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            self.close()
            raise ValueError("录像缺少有效帧率，无法建立时间轴")
        self.fps = fps
        self.frame_count = max(0, int(self._capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        self.duration_ms = round(self.frame_count / fps * 1000)
        self._next_id = 0
        self.ended = False

    def read(self) -> Frame | None:
        success, image = self._capture.read()
        if not success:
            self.ended = True
            return None
        frame_id = self._next_id
        self._next_id += 1
        # Prefer presentation timestamps; deterministic CFR fallback for backends without PTS.
        pts = self._capture.get(cv2.CAP_PROP_POS_MSEC)
        timestamp = round(pts) if math.isfinite(pts) and (pts > 0 or frame_id == 0) else round(frame_id / self.fps * 1000)
        return Frame(frame_id, timestamp, image, self.source, image.shape[1], image.shape[0])

    def seek_frame(self, index: int) -> None:
        index = max(0, min(index, self.frame_count - 1)) if self.frame_count else max(0, index)
        if not self._capture.set(cv2.CAP_PROP_POS_FRAMES, index):
            raise RuntimeError("该录像不支持时间跳转")
        self._next_id = index
        self.ended = False

    def close(self) -> None:
        self._capture.release()
