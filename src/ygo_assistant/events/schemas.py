from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from ..common import Schema


class EventType(StrEnum):
    TURN_START = "TURN_START"
    PHASE_CHANGE = "PHASE_CHANGE"
    CARD_REVEALED = "CARD_REVEALED"
    CARD_MOVED = "CARD_MOVED"
    ACTIVATE_CARD = "ACTIVATE_CARD"
    ACTIVATE_EFFECT = "ACTIVATE_EFFECT"
    CHAIN_LINK_ADDED = "CHAIN_LINK_ADDED"
    CHAIN_RESOLVED = "CHAIN_RESOLVED"
    EFFECT_RESOLVED = "EFFECT_RESOLVED"
    SUMMON_ATTEMPT = "SUMMON_ATTEMPT"
    SUMMON_SUCCESS = "SUMMON_SUCCESS"
    CARD_ADDED_TO_HAND = "CARD_ADDED_TO_HAND"
    CARD_SENT_TO_GRAVE = "CARD_SENT_TO_GRAVE"
    CARD_BANISHED = "CARD_BANISHED"
    CARD_SET = "CARD_SET"
    CARD_DESTROYED = "CARD_DESTROYED"
    LIFE_POINTS_CHANGED = "LIFE_POINTS_CHANGED"
    UNKNOWN_EVENT = "UNKNOWN_EVENT"
    DUEL_FINISHED = "DUEL_FINISHED"


Player = Literal["PLAYER_A", "PLAYER_B"]
Phase = Literal["DRAW", "STANDBY", "MAIN1", "BATTLE", "MAIN2", "END"]


class Evidence(Schema):
    source: Literal["duel_log", "effect_text", "card_detail", "vision", "manual"]
    timestamp_ms: int = Field(ge=0)
    roi: str = Field(min_length=1)
    frame_id: int = Field(ge=0)
    raw_text: str | None = None
    confidence: float = Field(ge=0, le=1)
    image_path: str | None = None
    corrections: list[str] = Field(default_factory=list)


class DuelEvent(Schema):
    schema_version: Literal["1.0"] = "1.0"
    match_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    timestamp_ms: int = Field(ge=0)
    turn: int | None = Field(default=None, ge=1)
    phase: Phase | None = None
    event_type: EventType = EventType.UNKNOWN_EVENT
    actor: Player | None = None
    card_id: int | None = Field(default=None, gt=0)
    card_name: str | None = None
    effect_text: str | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    status: Literal["unresolved", "confirmed", "rejected"] = "unresolved"
    evidence: list[Evidence] = Field(default_factory=list)
    state_version_before: int | None = Field(default=None, ge=0)
    state_version_after: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_versions(self):
        before, after = self.state_version_before, self.state_version_after
        if (before is None) != (after is None):
            raise ValueError("State versions must be assigned together")
        if before is not None and after != before + 1:
            raise ValueError("Applied events must increment state version by one")
        if before is not None and self.status == "rejected":
            raise ValueError("Rejected events cannot advance state")
        return self
