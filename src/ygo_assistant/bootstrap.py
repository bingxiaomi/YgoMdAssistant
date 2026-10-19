import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from .common import Schema


class AppConfig(Schema):
    title: str = "YGO Tactical Assistant"
    mode: Literal["replay", "live"] = "replay"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_directory: Path = Path("logs")
    capture_fps: int = Field(default=30, ge=1, le=120)
    capture_backend: Literal["wgc", "dxcam"] = "wgc"
    frame_queue_size: int = Field(default=2, ge=1, le=120)
    preview_fps: int = Field(default=30, ge=1, le=60)
    regions_path: Path = Path("configs/regions.yaml")
    snapshot_directory: Path = Path("data/captures")
    ocr_confidence_threshold: float = Field(default=0.85, ge=0, le=1)
    search_budget_ms: int = Field(default=1000, ge=1)
    model_backend: str = "disabled"


def load_config(path: Path | None = None) -> AppConfig:
    if path is None:
        return AppConfig()
    try:
        with path.open(encoding="utf-8") as stream:
            value = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML configuration: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Configuration must be a YAML mapping")
    config = AppConfig.model_validate(value)
    for name in ("log_directory", "regions_path", "snapshot_directory"):
        value = getattr(config, name)
        if not value.is_absolute():
            setattr(config, name, (path.resolve().parent / value).resolve())
    return config


def configure_logging(config: AppConfig) -> None:
    config.log_directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        config.log_directory / "assistant.log", maxBytes=5_000_000,
        backupCount=3, encoding="utf-8",
    )
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(), handler], force=True,
    )
