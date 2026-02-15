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
        # Minimal tile-aware policy:
        # move in the preferred direction, jump if a solid tile blocks the body.
        direction = 1 if self.config.prefer_right else -1
        tiles = set()
        for t in obs.nearby_tiles:
            if isinstance(t, dict):
                tx = t.get("x")
                ty = t.get("y")
                if tx is not None and ty is not None:
                    tiles.add((tx, ty))
            elif isinstance(t, (list, tuple)) and len(t) >= 2:
                tiles.add((t[0], t[1]))
        px, py = obs.player_pos

        player_width = 20
        player_height = 42
        front_x = px + (player_width if direction > 0 else -1)
        mid_y = py + player_height * 0.5
        foot_y = py + player_height - 1

        tx = int(front_x // 16)
        ty_mid = int(mid_y // 16)
        ty_foot = int(foot_y // 16)

        blocked = (tx, ty_mid) in tiles or (tx, ty_foot) in tiles

        action = Action(
            move_right=direction > 0,
            move_left=direction < 0,
            direction=direction,
        )
        if blocked and self.config.jump_if_blocked:
            action.jump = True
        return action
