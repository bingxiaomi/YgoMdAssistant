from typing import Literal

from pydantic import Field

from ..common import Schema
from ..events.schemas import Phase, Player


class PlayerState(Schema):
    life_points: int | None = Field(default=None, ge=0)
    hand_count: int | None = Field(default=None, ge=0)
    deck_count: int | None = Field(default=None, ge=0)


class CardInstance(Schema):
    instance_id: str = Field(min_length=1)
    card_id: int | None = Field(default=None, gt=0)
    controller: Player | None = None
    zone: Literal["hand", "deck", "monster", "spell_trap", "graveyard", "banished", "extra", "unknown"] = "unknown"
    confidence: float = Field(default=0, ge=0, le=1)


class ChainLink(Schema):
    link_number: int = Field(ge=1)
    event_id: str
    actor: Player | None = None
    card_instance_id: str | None = None
    status: Literal["pending", "resolved", "negated", "unknown"] = "unknown"


class DuelState(Schema):
    schema_version: Literal["1.0"] = "1.0"
    state_kind: Literal["observation", "reconstructed"] = "observation"
    match_id: str = Field(min_length=1)
    state_version: int = Field(default=0, ge=0)
    turn_number: int | None = Field(default=None, ge=1)
    active_player: Player | None = None
    phase: Phase | None = None
    players: dict[Player, PlayerState] = Field(default_factory=lambda: {
        "PLAYER_A": PlayerState(), "PLAYER_B": PlayerState(),
    })
    visible_cards: list[CardInstance] = Field(default_factory=list)
    known_hidden_cards: list[CardInstance] = Field(default_factory=list)
    unknown_card_counts: dict[Player, int | None] = Field(default_factory=lambda: {
        "PLAYER_A": None, "PLAYER_B": None,
    })
    chain: list[ChainLink] = Field(default_factory=list)
    pending_effects: list[str] = Field(default_factory=list)
    used_effects: list[str] = Field(default_factory=list)
    summon_restrictions: list[str] = Field(default_factory=list)
    legal_actions: list[str] | None = None
    observation_confidence: float = Field(default=0, ge=0, le=1)
    unresolved_events: list[str] = Field(default_factory=list)
