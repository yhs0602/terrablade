# Terraria Exploration Bot Plan

## Purpose
Build a programmatically controlled Terraria client that can explore the world, map it, and make safe movement decisions using server-tracked state. The bot is research-oriented and should remain compatible with vanilla server behavior across versions 1.4.4.9 (1449) and 1.4.5.5 (1455).

## Scope
- In scope: protocol-level client, world state sync, exploration behavior, safety checks, logging, and reproducible experiments.
- Out of scope: full game completion AI, combat optimization, and advanced multi-agent coordination (tracked separately).

## Assets We Already Have
- Decompiled vanilla server sources for 1449 and 1455 (`1449/`, `1455/`).
- Decompiled tModLoader sources (`tModLoader-decomp/`) for cross-referencing behavior.
- Packet parsing, basic login, chat, and movement in `main.py`.
- World/tile/entity tracking in `WorldState`.
- Multi-version protocol specs under `protocol/specs/`.

## Target Architecture
- **Protocol Layer**: version-aware framing, message parsing, and message builders.
- **State Layer**: world model (tiles, liquids, entities, player state), time, and inventory.
- **Perception Layer**: extract local observations (nearby tiles/entities, hazards, goals).
- **Navigation Layer**: short-horizon movement decisions based on obstacles and goals.
- **Behavior Layer**: exploration policy (wander, map coverage, return-to-spawn, avoid danger).
- **Safety Layer**: teleport handling, bounds checks, and disconnect/retry control.
- **Evaluation Layer**: logging + metrics (coverage %, distance, deaths, loot count).

## Milestones
1. **Stable Baseline Client**
   - Reliable handshake, world info, tile stream, and inventory sync.
   - Teleport tracking/ack and no parse crashes.
2. **World Model & Sensing**
   - Tile solidity, liquid info, entity tracking.
   - Stable APIs: `get_nearby_tiles`, `get_nearby_items`, `get_nearby_npcs`.
3. **Exploration Behavior v1**
   - Simple policy: move forward, avoid solid tiles, jump over obstacles.
   - Safe idle and reconnect logic.
4. **Mapping & Coverage**
   - Map tiles to local cache and compute explored coverage.
   - Persist snapshots to JSON for offline analysis.
5. **Behavior v2**
   - Heuristics: return-to-surface, avoid lava, follow caves, gather loot.
6. **Multi-Version Robustness**
   - Profile-based parse/build with tests for both 1449 and 1455.
   - Version regression checklist.

## Execution Plan (Now)
1. Create bot scaffolding module for exploration decision making.
2. Document how to run decompilation and where to look for vanilla logic.
3. Add minimal control loop wiring when ready (after validating tile solidity).

## Open Risks
- Protocol variability and optional fields (many messages are variable length).
- Client-side physics vs server authority differences.
- Tile solidity metadata requires accurate tile tables or server-derived rules.

## Next Work Items
- Extract tile metadata (solid/solidTop) and frame importance into a versioned table.
- Implement `ExplorationBot.decide()` and integrate an `--explore` mode.
- Add replayable capture logs for deterministic debugging.
