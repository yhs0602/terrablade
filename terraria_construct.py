"""
Construct-based definitions of Terraria network protocol messages.

This module defines Python constructs for each message type in the Terraria network protocol,
as documented on the seancode.com TerraFirma network protocol page【588973514146224†L150-L199】【588973514146224†L420-L423】. Each message begins with a 4‑byte little‑endian
length field (the number of bytes following the length), followed by a 1‑byte message
ID, and then a payload whose structure depends on the message ID.  The definitions
below model only the payloads; a general message parser at the end combines the
length, ID and payload to parse complete packets.  Strings use ASCII and are read to
EOF, since their lengths are derived from the enclosing message length【588973514146224†L46-L56】.

Note: some messages include variable‑length tile data or arrays whose exact size
depends on flags in the payload (e.g. tile row data in message $0A, tile block data
in $14, NPC AI arrays in $17).  In these cases, the definitions below parse the
fixed‑layout fields and then consume the remainder of the payload as raw bytes.
Applications using these constructs should interpret those bytes according to the
protocol specification.
"""

from construct import (
    Computed,
    If,
    Int16ul,
    Int64ul,
    Int8sl,
    Optional,
    PascalString,
    Struct,
    Byte,
    Int16sl,
    Int32sl,
    Float32l,
    Array,
    GreedyBytes,
    Switch,
    FixedSized,
)

# -------------------------------------------------------------------------------
# Basic helper structures
# -------------------------------------------------------------------------------

# A 24‑bit RGB colour used throughout the protocol【588973514146224†L78-L96】.
Color = Struct(
    "r" / Byte,
    "g" / Byte,
    "b" / Byte,
)

# A buff applied to an NPC (message $36)【588973514146224†L1130-L1145】.
NPCBuff = Struct(
    "buff_type" / Byte,
    "buff_time" / Int16sl,
)

# -------------------------------------------------------------------------------
# Payload structures for each message type
# -------------------------------------------------------------------------------

payload_structs = {
    # $01 — Connect Request
    0x01: Struct("version" / PascalString(lengthfield=Byte, encoding="ascii")),
    # $02 — Fatal Error
    0x02: Struct("error" / PascalString(lengthfield=Byte, encoding="ascii")),
    # $03 — Connection Approved
    0x03: Struct(
        "player_slot" / Byte,
        "some_bool" / Byte,
    ),
    # $04 — Player Appearance【588973514146224†L78-L97】
    0x04: Struct(
        "player_id" / Byte,  # Player ID
        "skin_variant" / Byte,  # Skin Varient
        "hair" / Byte,  # >162면 서버가 0으로 클램프
        "name"
        / PascalString(
            lengthfield=Byte, encoding="ascii"
        ),  # String (7-bit length-prefixed)
        "hair_dye" / Byte,
        "hide_visuals" / Byte,
        "hide_visuals_2" / Byte,
        "hide_misc" / Byte,
        "hair_color" / Color,  # 3 bytes RGB
        "skin_color" / Color,
        "eye_color" / Color,
        "shirt_color" / Color,
        "undershirt_color" / Color,
        "pants_color" / Color,
        "shoe_color" / Color,
        "difficulty_flags" / Byte,  # bitflags
        "torch_flags" / Byte,  # bitflags
        "shimmer_flags" / Byte,  # bitflags
    ),
    # $05 — Set Inventory
    0x05: Struct(
        "player_slot" / Byte,
        "inventory_slot" / Int16sl,
        "stack" / Int16sl,
        "prefix_id" / Byte,
        "item_id" / Int16sl,
    ),
    # $06 — Request World Information (no payload)
    0x06: Struct(),
    # $07 — World Information
    0x07: Struct(
        "game_time" / Int32sl,
        "day_and_moon_info" / Byte,
        "moon_phase" / Byte,
        "max_tiles_x" / Int16sl,
        "max_tiles_y" / Int16sl,
        "spawn_tile_x" / Int16sl,
        "spawn_tile_y" / Int16sl,
        "ground_level_y" / Int16sl,
        "rock_layer_y" / Int16sl,
        "world_id" / Int32sl,
        "world_name" / PascalString(lengthfield=Byte, encoding="ascii"),
        "game_mode" / Byte,
        "world_unique_id" / Array(16, Byte),
        "world_generator_version" / Int64ul,
        "moon_type" / Byte,
        "forest_background" / Byte,
        "forest2_background" / Byte,
        "forest3_background" / Byte,
        "forest4_background" / Byte,
        "corruption_background" / Byte,
        "jungle_background" / Byte,
        "snow_background" / Byte,
        "hallow_background" / Byte,
        "crimson_background" / Byte,
        "desert_background" / Byte,
        "ocean_background" / Byte,
        "mushroom_background" / Byte,
        "underworld_background" / Byte,
        "ice_back_style" / Byte,
        "jungle_back_style" / Byte,
        "hell_back_style" / Byte,
        "wind_speed_target" / Float32l,
        "num_clouds" / Byte,
        "tree_x" / Array(3, Int32sl),
        "tree_style" / Array(4, Byte),
        "cave_back_x" / Array(3, Int32sl),
        "cave_back_style" / Array(4, Byte),
        "forst_tree_tops" / Byte,
        "forst2_tree_tops" / Byte,
        "forst3_tree_tops" / Byte,
        "forst4_tree_tops" / Byte,
        "corruption_tree_tops" / Byte,
        "jungle_tree_tops" / Byte,
        "snow_tree_tops" / Byte,
        "hallow_tree_tops" / Byte,
        "crimson_tree_tops" / Byte,
        "desert_tree_tops" / Byte,
        "ocean_tree_tops" / Byte,
        "mushroom_tree_tops" / Byte,
        "underworld_tree_tops" / Byte,
        "max_raining" / Float32l,
        "event_info_1" / Byte,  # prehard
        "event_info_2" / Byte,  # mech
        "event_info_3" / Byte,  # slimeking...
        "event_info_4" / Byte,  # moonlord...
        "event_info_5" / Byte,  # pirates...
        "event_info_6" / Byte,  # combatbook...
        "event_info_7" / Byte,  # boughtcat...
        "event_info_8" / Byte,  # 0516world...
        "event_info_9" / Byte,  # unlock slime spawn...
        "event_info_10" / Byte,  # no traps...
        "sundial_cooldown" / Byte,
        "moondial_coondial" / Byte,
        "copper" / Int16sl,
        "iron" / Int16sl,
        "silver" / Int16sl,
        "gold" / Int16sl,
        "cobalt" / Int16sl,
        "mythril" / Int16sl,
        "adamantite" / Int16sl,
        "invasion_type" / Int8sl,
        "lobby_id" / Int64ul,
        "sandstorm" / Float32l,
    ),
    # $08 — Request initial tile data【588973514146224†L201-L213】
    0x08: Struct(
        "spawn_x" / Int32sl,
        "spawn_y" / Int32sl,
    ),
    # $09 — Statusbar text【588973514146224†L214-L225】
    0x09: Struct(
        "num_messages" / Int32sl,
        "status_text" / PascalString(lengthfield=Byte, encoding="ascii"),
        "number2" / Byte,
    ),
    # $0A — Tile Row Data (variable tile data)【588973514146224†L233-L275】
    0x0A: Struct(
        "compressed" / Byte,
        "tile_x" / Int32sl,
        "tile_y" / Int32sl,
        "width" / Int16sl,
        "height" / Int16sl,
        # The rest of the payload is variable‑length tile data encoded using flags.
        "tile_data" / GreedyBytes,
    ),
    # $0B — Recalculate U/V【588973514146224†L277-L289】
    0x0B: Struct(
        "start_x" / Int32sl,
        "start_y" / Int32sl,
        "end_x" / Int32sl,
        "end_y" / Int32sl,
    ),
    # $0C — Spawn Player【588973514146224†L290-L300】
    0x0C: Struct(
        "player_slot" / Byte,
        "spawn_x" / Int32sl,
        "spawn_y" / Int32sl,
    ),
    # $0D — Player Control【588973514146224†L311-L334】
    0x0D: Struct(
        "player_slot" / Byte,
        "control_flags" / Byte,
        "selected_item_slot" / Byte,
        "position_x" / Float32l,
        "position_y" / Float32l,
        "velocity_x" / Float32l,
        "velocity_y" / Float32l,
        "flags" / Byte,
    ),
    # $0E — Set Player Activity【588973514146224†L351-L359】
    0x0E: Struct(
        "player_slot" / Byte,
        "active" / Byte,
    ),
    # $0F — Unused (no payload)
    0x0F: Struct(),
    # $10 — Set Player Life【588973514146224†L365-L375】
    0x10: Struct(
        "player_slot" / Byte,
        "current_health" / Int16sl,
        "max_health" / Int16sl,
    ),
    # $11 — Modify Tile【588973514146224†L388-L416】
    0x11: Struct(
        "modify_mode" / Byte,
        "tile_x" / Int32sl,
        "tile_y" / Int32sl,
        "tile_wall_id" / Byte,
        "tile_variant" / Byte,
    ),
    # $12 — Set Time【588973514146224†L425-L436】
    0x12: Struct(
        "day_night" / Byte,
        "time" / Int32sl,
        "sun_mod_y" / Int16sl,
        "moon_mod_y" / Int16sl,
    ),
    # $13 — Open/Close Door【588973514146224†L437-L447】
    0x13: Struct(
        "open" / Byte,
        "tile_x" / Int32sl,
        "tile_y" / Int32sl,
        "facing" / Byte,
    ),
    # $14 — Tile Block (variable tile data)【588973514146224†L457-L471】
    0x14: Struct(
        "length" / Int16sl,
        "tile_x" / Int32sl,
        "tile_y" / Int32sl,
        # The remainder of the payload contains length×length tile entries, encoded
        # like message $0A but without RLE.
        "tile_data" / GreedyBytes,
    ),
    # $15 — Update Item【588973514146224†L482-L499】
    0x15: Struct(
        "item_slot" / Int16sl,
        "position_x" / Float32l,
        "position_y" / Float32l,
        "velocity_x" / Float32l,
        "velocity_y" / Float32l,
        "stack" / Int16sl,
        "prefix_id" / Byte,
        "own_ignore" / Byte,
        "item_id" / Int16sl,
    ),
    # $16 — Set Owner of Item【588973514146224†L512-L521】
    0x16: Struct(
        "item_slot" / Int16sl,
        "owner" / Byte,
    ),
    # $17 — Update NPC【588973514146224†L531-L556】
    0x17: Struct(
        "npc_slot" / Int16sl,
        "position_x" / Float32l,
        "position_y" / Float32l,
        "velocity_x" / Float32l,
        "velocity_y" / Float32l,
        "target" / Int16sl,
        "flags1" / Byte,
        "flags2" / Byte,
        "ai0" / If(lambda this: this.flags1 & 0x04, Float32l),
        "ai1" / If(lambda this: this.flags1 & 0x08, Float32l),
        "ai2" / If(lambda this: this.flags1 & 0x10, Float32l),
        "ai3" / If(lambda this: this.flags1 & 0x20, Float32l),
        "ai" / Computed(lambda this: [this.ai0, this.ai1, this.ai2, this.ai3]),
        "npc_id" / Int16sl,
        "player_count_for_multiplayer_difficulty_override" / Optional(Byte),
        "strength_multiplier" / Optional(Float32l),
        "life_bytes" / Optional(Byte),
        "life_byte" / If(lambda this: this.life_bytes == 1 and this.flags1 & 128, Byte),
        "life_int16"
        / If(lambda this: this.life_bytes == 2 and this.flags1 & 128, Int16ul),
        "life_int32"
        / If(lambda this: this.life_bytes == 4 and this.flags1 & 128, Int32sl),
        # "life" / Computed(lambda this: this.life_byte if this.life_bytes == 1 else (this.life_int16 if this.life_bytes == 2 else this.life_int32)),
        "release_owner" / Optional(Byte),
    ),
    # $18 — Strike NPC【588973514146224†L561-L574】
    0x18: Struct(
        "npc_slot" / Int16sl,
        "player_slot" / Byte,
    ),
    # $19 — Chat【588973514146224†L581-L602】
    0x19: Struct(
        "player_slot" / Byte,
        "text_color" / Color,
        "chat_text" / PascalString(lengthfield=Byte, encoding="ascii"),
    ),
    # $1A — Damage Player or PvP【588973514146224†L604-L617】
    0x1A: Struct(
        "player_slot" / Byte,
        "hit_direction" / Byte,
        "damage" / Int16sl,
        "pvp" / Byte,
        "critical" / Byte,
        "death_text" / PascalString(lengthfield=Byte, encoding="ascii"),
    ),
    # $1B — Update Projectile【588973514146224†L627-L645】
    0x1B: Struct(
        "projectile_id" / Int16sl,
        "position_x" / Float32l,
        "position_y" / Float32l,
        "velocity_x" / Float32l,
        "velocity_y" / Float32l,
        "knockback" / Float32l,
        "damage" / Int16sl,
        "owner" / Byte,
        "projectile_type" / Int16sl,
        "ai" / Array(4, Float32l),
    ),
    # $1C — Damage NPC【588973514146224†L656-L669】
    0x1C: Struct(
        "npc_slot" / Int16sl,
        "damage" / Int16sl,
        "knockback" / Float32l,
        "direction" / Byte,
        "critical" / Byte,
    ),
    # $1D — Destroy Projectile【588973514146224†L679-L688】
    0x1D: Struct(
        "projectile_id" / Int16sl,
        "owner" / Byte,
    ),
    # $1E — Toggle PvP【588973514146224†L698-L707】
    0x1E: Struct(
        "player_slot" / Byte,
        "pvp" / Byte,
    ),
    # $1F — Request Open Chest【588973514146224†L719-L728】
    0x1F: Struct(
        "tile_x" / Int32sl,
        "tile_y" / Int32sl,
    ),
    # $20 — Set Chest Item【588973514146224†L729-L741】
    0x20: Struct(
        "chest_slot" / Int16sl,
        "item_slot" / Byte,
        "stack" / Int16sl,
        "prefix_id" / Byte,
        "item_id" / Int16sl,
    ),
    # $21 — Open/Close chest【588973514146224†L752-L762】
    0x21: Struct(
        "chest_slot" / Int16sl,
        "tile_x" / Int32sl,
        "tile_y" / Int32sl,
    ),
    # $22 — Destroy chest【588973514146224†L774-L783】
    0x22: Struct(
        "tile_x" / Int32sl,
        "tile_y" / Int32sl,
    ),
    # $23 — Heal Player【588973514146224†L784-L793】
    0x23: Struct(
        "player_slot" / Byte,
        "heal" / Int16sl,
    ),
    # $24 — Set Zones【588973514146224†L804-L821】
    0x24: Struct(
        "player_slot" / Byte,
        "zone_flags" / Byte,
    ),
    # $25 — Request Password (no payload)【588973514146224†L832-L839】
    0x25: Struct(),
    # $26 — Login with Password【588973514146224†L842-L848】
    0x26: Struct(
        "password" / PascalString(lengthfield=Byte, encoding="ascii"),
    ),
    # $27 — Unassign item【588973514146224†L850-L858】
    0x27: Struct(
        "item_slot" / Int16sl,
    ),
    # $28 — Talk to NPC【588973514146224†L860-L869】
    0x28: Struct(
        "player_slot" / Byte,
        "npc_slot" / Int16sl,
    ),
    # $29 — Animate player flail【588973514146224†L880-L890】
    0x29: Struct(
        "player_slot" / Byte,
        "item_rotation" / Float32l,
        "item_animation" / Int16sl,
    ),
    # $2A — Set Player Mana【588973514146224†L900-L910】
    0x2A: Struct(
        "player_slot" / Byte,
        "mana" / Int16sl,
        "max_mana" / Int16sl,
    ),
    # $2B — Replenish Mana【588973514146224†L921-L930】
    0x2B: Struct(
        "player_slot" / Byte,
        "amount" / Int16sl,
    ),
    # $2C — Kill Player【588973514146224†L942-L954】
    0x2C: Struct(
        "player_slot" / Byte,
        "hit_direction" / Byte,
        "damage" / Int16sl,
        "pvp" / Byte,
        "death_message" / PascalString(lengthfield=Byte, encoding="ascii"),
    ),
    # $2D — Change Party【588973514146224†L965-L979】
    0x2D: Struct(
        "player_slot" / Byte,
        "team" / Byte,
    ),
    # $2E — Read Sign【588973514146224†L991-L1000】
    0x2E: Struct(
        "tile_x" / Int32sl,
        "tile_y" / Int32sl,
    ),
    # $2F — Set Sign Text【588973514146224†L1001-L1012】
    0x2F: Struct(
        "sign_slot" / Int16sl,
        "sign_x" / Int32sl,
        "sign_y" / Int32sl,
        "sign_text" / PascalString(lengthfield=Byte, encoding="ascii"),
    ),
    # $30 — Adjust Liquid【588973514146224†L1021-L1032】
    0x30: Struct(
        "tile_x" / Int32sl,
        "tile_y" / Int32sl,
        "liquid_amount" / Byte,
        "liquid_type" / Byte,
    ),
    # $31 — Spawn (no payload)【588973514146224†L1041-L1047】
    0x31: Struct(),
    # $32 — Set Player Buffs【588973514146224†L1049-L1058】
    0x32: Struct(
        "player_slot" / Byte,
        "buffs" / Array(44, Int16ul),
    ),
    # $33 — Old Man's Answer【588973514146224†L1071-L1080】
    0x33: Struct(
        "player_slot" / Byte,
        "answer" / Byte,
    ),
    # $34 — Unlock Chest or Door【588973514146224†L1090-L1101】
    0x34: Struct(
        "player_slot" / Byte,
        "unlock" / Byte,
        "tile_x" / Int32sl,
        "tile_y" / Int32sl,
    ),
    # $35 — Add an NPC Buff【588973514146224†L1111-L1121】
    0x35: Struct(
        "npc_slot" / Int16sl,
        "buff_type" / Byte,
        "buff_time" / Int16sl,
    ),
    # $36 — Set NPC Buffs【588973514146224†L1130-L1145】
    0x36: Struct(
        "npc_slot" / Int16sl,
        "npc_buffs" / Array(5, NPCBuff),
    ),
    # $37 — Add Player Buff【588973514146224†L1146-L1155】
    0x37: Struct(
        "player_slot" / Byte,
        "buff_type" / Byte,
        "buff_time" / Int16sl,
    ),
    # $38 — Set NPC Name【588973514146224†L1166-L1174】
    0x38: Struct(
        "npc_slot" / Int16sl,
        "npc_name" / PascalString(lengthfield=Byte, encoding="ascii"),
    ),
    # $39 — Sets Balance Stats【588973514146224†L1176-L1185】
    0x39: Struct(
        "hallowed" / Byte,
        "corruption" / Byte,
    ),
    # $3A — Play Harp【588973514146224†L1186-L1195】
    0x3A: Struct(
        "player_slot" / Byte,
        "note" / Float32l,
    ),
    # $3B — Flip Switch【588973514146224†L1205-L1214】
    0x3B: Struct(
        "tile_x" / Int32sl,
        "tile_y" / Int32sl,
    ),
    # $3C — Move NPC Home【588973514146224†L1223-L1233】
    0x3C: Struct(
        "npc_slot" / Int16sl,
        "home_x" / Int16sl,
        "home_y" / Int16sl,
        "homeless" / Byte,
    ),
    # $3D — Summon Boss or Invasion【588973514146224†L1244-L1252】
    0x3D: Struct(
        "player_id" / Int32sl,
        "boss_type" / Int32sl,
    ),
    # $3E — Ninja/Shadow Dodge【588973514146224†L1254-L1262】
    0x3E: Struct(
        "player_id" / Int32sl,
        "dodge_type" / Int32sl,
    ),
    # $3F — Paint Tile【588973514146224†L1272-L1282】
    0x3F: Struct(
        "tile_x" / Int32sl,
        "tile_y" / Int32sl,
        "color" / Byte,
    ),
    # $40 — Paint Wall【588973514146224†L1291-L1301】
    0x40: Struct(
        "wall_x" / Int32sl,
        "wall_y" / Int32sl,
        "color" / Byte,
    ),
    # $41 — Teleport Player/NPC【588973514146224†L1310-L1323】
    0x41: Struct(
        "flags" / Byte,
        "player_slot" / Int16sl,
        "destination_x" / Float32l,
        "destination_y" / Float32l,
    ),
    # $42 — Heal Player【588973514146224†L1333-L1342】
    0x42: Struct(
        "player_slot" / Byte,
        "heal_amount" / Int16sl,
    ),
    # $44 — Unknown【588973514146224†L1351-L1358】
    0x44: Struct(
        "client_uuid" / PascalString(lengthfield=Byte, encoding="ascii"),
    ),
    0x52: Struct(
        "network_something" / Array(4, Byte),
    ),
    0x93: Struct(
        "loadout" / Array(4, Byte),
    ),
}

# -------------------------------------------------------------------------------
# General packet structure
# -------------------------------------------------------------------------------

# Parses a complete Terraria message consisting of a 4‑byte length, 1‑byte message
# type and a payload.  The message length includes the type and payload bytes but
# excludes the 4‑byte length prefix【588973514146224†L27-L33】.  FixedSized ensures that the
# payload parser consumes exactly (length ‑ 1) bytes for the chosen message type.
TerrariaMessage = Struct(
    "length" / Int16ul,
    "type" / Byte,
    "payload"
    / FixedSized(
        lambda this: this.length - 3,
        Switch(lambda this: this.type, payload_structs, default=GreedyBytes),
    ),
)

__all__ = [
    "Color",
    "NPCBuff",
    "payload_structs",
    "TerrariaMessage",
]
