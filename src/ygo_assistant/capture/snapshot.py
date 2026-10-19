import json
from datetime import datetime
from pathlib import Path

import cv2

from .base import Frame
from ..vision.region_manager import RegionProfile


def save_snapshot(frame: Frame, profile: RegionProfile, directory: Path) -> Path:
    target = directory / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target.mkdir(parents=True)
    images = {"frame": frame.image, **profile.crops(frame)}
    files = {}
    for name, image in images.items():
        filename = "frame.png" if name == "frame" else f"roi_{len(files):02d}.png"
        success, encoded = cv2.imencode(".png", image)
        if not success:
            raise RuntimeError(f"截图编码失败：{name}")
        (target / filename).write_bytes(encoded.tobytes())
        files[name] = filename
    metadata = dict(schema_version="1.0", source=frame.source, frame_id=frame.frame_id,
                    timestamp_ms=frame.timestamp_ms, width=frame.width, height=frame.height,
                    capture_backend=frame.capture_backend, source_timestamp_100ns=frame.source_timestamp_100ns,
                    profile=profile.model_dump(), files=files)
    (target / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
