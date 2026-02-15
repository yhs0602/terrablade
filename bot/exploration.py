from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class Observation:
    player_pos: Tuple[float, float]
    nearby_tiles: List[Tuple[int, int]]
    nearby_items: List[object]
    nearby_npcs: List[object]


@dataclass
class Action:
    move_left: bool = False
    move_right: bool = False
    jump: bool = False
    use_item: bool = False
    selected_item: int = 0
    direction: int = 1


@dataclass
class ExplorationConfig:
    prefer_right: bool = True
    jump_if_blocked: bool = True


class ExplorationBot:
    def __init__(self, config: Optional[ExplorationConfig] = None):
        self.config = config or ExplorationConfig()

    def decide(self, obs: Observation) -> Action:
        # Placeholder policy. Will be replaced by tile-aware navigation.
        if self.config.prefer_right:
            return Action(move_right=True, direction=1)
        return Action(move_left=True, direction=-1)
