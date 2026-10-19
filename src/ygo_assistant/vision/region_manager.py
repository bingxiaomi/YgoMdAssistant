import math
import os
import tempfile
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pydantic import Field, model_validator

from ..capture.base import Frame
from ..common import Schema


class Region(Schema):
    label: str
    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def inside_image(self):
        if self.x + self.width > 1.00000001 or self.y + self.height > 1.00000001:
            raise ValueError("ROI must be contained in the image")
        return self

    def pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        left, top = int(self.x * width), int(self.y * height)
        right = min(width, max(left + 1, math.ceil((self.x + self.width) * width)))
        bottom = min(height, max(top + 1, math.ceil((self.y + self.height) * height)))
        return left, top, right, bottom


class RegionProfile(Schema):
    schema_version: Literal["1.0"] = "1.0"
    name: str = "default"
    reference_width: int = Field(default=1920, gt=0)
    reference_height: int = Field(default=1080, gt=0)
    regions: dict[str, Region] = Field(min_length=1)

    def crops(self, frame: Frame) -> dict[str, np.ndarray]:
        result = {}
        for name, region in self.regions.items():
            left, top, right, bottom = region.pixels(frame.width, frame.height)
            result[name] = frame.image[top:bottom, left:right].copy()
        return result


def default_profile() -> RegionProfile:
    return RegionProfile(reference_width=2048, reference_height=1152, regions={
        "duel_log": Region(label="决斗日志", x=.817, y=.130, width=.170, height=.770),
        "effect_text": Region(label="效果描述", x=.539, y=.107, width=.459, height=.096),
    })


def load_profile(path: Path) -> RegionProfile:
    try:
        return RegionProfile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid ROI YAML: {exc}") from exc


def save_profile(profile: RegionProfile, path: Path) -> None:
    """Replace atomically, leaving an existing calibration intact on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            yaml.safe_dump(profile.model_dump(), stream, allow_unicode=True, sort_keys=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
