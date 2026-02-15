import socket, struct
import random
import argparse
import time
import select
import zlib
import binascii
import json
from pathlib import Path
from typing import Optional
from types import SimpleNamespace
from terraria_construct import payload_structs, TerrariaMessage
from protocol import VersionSpec, resolve_spec
from bot.exploration import (
    ExplorationBot,
    Observation,
    ExplorationConfig,
    Action,
)

HOST, PORT = "127.0.0.1", 7777
NET_TEXT_MODULE_ID = 1  # NetworkInitializer: NetLiquidModule(0), NetTextModule(1)
_WARNED_FRAME_IMPORTANT = False
DEBUG = False
DEBUG_HEX = False
DEBUG_INCLUDE_TILES = False
DEBUG_ALL = False
DEBUG_SUPPRESS_TYPES = {
    0x0D,  # PlayerControls
    0x10,  # PlayerLifeMana
    0x14,  # AreaTileChange
    0x17,  # SyncNPC
    0x1B,  # SyncProjectile
    0x1D,  # KillProjectile
    0x29,  # ItemRotationAndAnimation
    0x52,  # NetModules
    0x98,  # ItemUseSound
}


def _should_log_type(msg_type: int) -> bool:
    if DEBUG_INCLUDE_TILES:
        return True
    if DEBUG_ALL:
        return True
    return msg_type != 0x0A and msg_type not in DEBUG_SUPPRESS_TYPES


def log_packet(direction: str, packet: bytes):
    if not DEBUG:
        return
    if len(packet) < 3:
        print(f"[{direction}] short packet len={len(packet)}")
        if DEBUG_HEX:
            print(binascii.hexlify(packet).decode())
        return
    length = int.from_bytes(packet[:2], "little")
    msg_type = packet[2]
    if not _should_log_type(msg_type):
        return
    print(f"[{direction}] type=0x{msg_type:02X} len={length}")
    if msg_type == 0x52 and length >= 5:
        module_id = int.from_bytes(packet[3:5], "little")
        module_payload = packet[5:length]
        print(
            f"[{direction}] netmodule id={module_id} payload_len={len(module_payload)}"
        )
        if module_id == 0 and len(module_payload) >= 2:
            change_count = int.from_bytes(module_payload[:2], "little")
            print(f"[{direction}] netmodule(NetLiquid) changes={change_count}")
    if DEBUG_HEX:
        print(binascii.hexlify(packet).decode())


def build_packet(msg_type: int, payload_dict=None) -> bytes:
    payload_dict = payload_dict or {}
    payload = payload_structs[msg_type].build(payload_dict)
    length = 3 + len(payload)  # size(2) + type(1) + payload
    return struct.pack("<HB", length, msg_type) + payload


def build_raw_packet(msg_type: int, payload: bytes) -> bytes:
    length = 3 + len(payload)
    return struct.pack("<HB", length, msg_type) + payload


def write_7bit_encoded_int(n: int) -> bytes:
    # .NET BinaryWriter 7-bit encoded int
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n & 0x7F)
    return bytes(out)


def write_dotnet_string(s: str) -> bytes:
    data = s.encode("utf-8")
    return write_7bit_encoded_int(len(data)) + data


def read_7bit_encoded_int(stream) -> int:
    result = 0
    shift = 0
    while True:
        b = stream.read(1)
        if not b:
            raise EOFError("unexpected EOF while reading 7-bit int")
        byte = b[0]
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            return result
        shift += 7
        if shift > 35:
            raise ValueError("7-bit int too large")


def read_dotnet_string(stream) -> str:
    length = read_7bit_encoded_int(stream)
    data = stream.read(length)
    return data.decode("utf-8", errors="replace")


class ByteReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise EOFError("unexpected EOF")
        out = self.data[self.pos : self.pos + n]
        self.pos += n
        return out

    def read_byte(self) -> int:
        return self.read(1)[0]

    def read_int16(self) -> int:
        return struct.unpack("<h", self.read(2))[0]

    def read_uint16(self) -> int:
        return struct.unpack("<H", self.read(2))[0]

    def read_int32(self) -> int:
        return struct.unpack("<i", self.read(4))[0]

    def read_float(self) -> float:
        return struct.unpack("<f", self.read(4))[0]

    def read_int8(self) -> int:
        return struct.unpack("<b", self.read(1))[0]

    def read_string(self) -> str:
        return read_dotnet_string(self)


def decode_teleport(payload: bytes):
    # Based on MessageBuffer.cs case 65
    r = ByteReader(payload)
    bits = r.read_byte()
    target = r.read_int16()
    x = r.read_float()
    y = r.read_float()
    style = r.read_byte()
    mode = 0
    if bits & 0x01:
        mode += 1
    if bits & 0x02:
        mode += 2
    flags = {
        "to_npc_or_style1": bool(bits & 0x01),
        "style2": bool(bits & 0x02),
        "flag9": bool(bits & 0x04),
        "has_extra": bool(bits & 0x08),
    }
    extra = None
    if flags["has_extra"]:
        extra = r.read_int32()
    return {
        "flags_raw": bits,
        "mode": mode,
        "target": target,
        "x": x,
        "y": y,
        "style": style,
        "flags": flags,
        "extra": extra,
    }


def decode_player_death_reason(reader: ByteReader) -> dict:
    bits = reader.read_byte()
    reason = {"flags_raw": bits}
    if bits & 0x01:
        reason["source_player"] = reader.read_int16()
    if bits & 0x02:
        reason["source_npc"] = reader.read_int16()
    if bits & 0x04:
        reason["source_projectile_index"] = reader.read_int16()
    if bits & 0x08:
        reason["source_other"] = reader.read_byte()
    if bits & 0x10:
        reason["source_projectile_type"] = reader.read_int16()
    if bits & 0x20:
        reason["source_item_type"] = reader.read_int16()
    if bits & 0x40:
        reason["source_item_prefix"] = reader.read_byte()
    if bits & 0x80:
        reason["custom_reason"] = reader.read_string()
    return reason


def decode_player_hurt_v2(payload: bytes) -> dict:
    r = ByteReader(payload)
    player_slot = r.read_byte()
    reason = decode_player_death_reason(r)
    damage = r.read_int16()
    hit_dir = r.read_byte() - 1
    flags = r.read_byte()
    crit = bool(flags & 0x01)
    pvp = bool(flags & 0x02)
    cooldown = r.read_int8()
    return {
        "player_slot": player_slot,
        "reason": reason,
        "damage": damage,
        "hit_dir": hit_dir,
        "crit": crit,
        "pvp": pvp,
        "cooldown": cooldown,
    }


def decode_player_death_v2(payload: bytes) -> dict:
    r = ByteReader(payload)
    player_slot = r.read_byte()
    reason = decode_player_death_reason(r)
    damage = r.read_int16()
    hit_dir = r.read_byte() - 1
    flags = r.read_byte()
    pvp = bool(flags & 0x01)
    return {
        "player_slot": player_slot,
        "reason": reason,
        "damage": damage,
        "hit_dir": hit_dir,
        "pvp": pvp,
    }


def _decompress_tile_block(payload: bytes) -> bytes:
    # Tile blocks are deflate-compressed with zlib header in 1.4.4+.
    try:
        return zlib.decompress(payload)
    except zlib.error:
        # fallback: raw deflate (older captures or malformed)
        return zlib.decompress(payload, wbits=-15)


def parse_tile_section(payload: bytes, tile_frame_important: set[int]):
    # 0x0A payload is deflate-compressed
    global _WARNED_FRAME_IMPORTANT
    if not tile_frame_important:
        if not _WARNED_FRAME_IMPORTANT:
            print(
                "Warning: tileFrameImportant list missing; skipping tile parse (store no tiles)."
            )
            _WARNED_FRAME_IMPORTANT = True
        data = _decompress_tile_block(payload)
        r = ByteReader(data)
        x_start = r.read_int32()
        y_start = r.read_int32()
        width = r.read_int16()
        height = r.read_int16()
        return {
            "x_start": x_start,
            "y_start": y_start,
            "width": width,
            "height": height,
            "tiles": {},
        }
    data = _decompress_tile_block(payload)
    r = ByteReader(data)
    x_start = r.read_int32()
    y_start = r.read_int32()
    width = r.read_int16()
    height = r.read_int16()

    tiles = {}
    rle = 0
    last_tile = None

    for y in range(y_start, y_start + height):
        for x in range(x_start, x_start + width):
            if rle != 0:
                rle -= 1
                if last_tile and last_tile["active"]:
                    tiles[(x, y)] = last_tile["type"]
                continue

            b4 = r.read_byte()
            b3 = b2 = b = 0

            if b4 & 1:
                b3 = r.read_byte()
                if b3 & 1:
                    b2 = r.read_byte()
                    if b2 & 1:
                        b = r.read_byte()

            active = False
            tile_type = None

            if b4 & 2:
                active = True
                if b4 & 0x20:
                    tile_type = r.read_uint16()
                else:
                    tile_type = r.read_byte()

                if tile_type in tile_frame_important:
                    _ = r.read_int16()
                    _ = r.read_int16()
                if b2 & 8:
                    _ = r.read_byte()  # tile color

            if b4 & 4:
                _ = r.read_byte()  # wall
                if b2 & 0x10:
                    _ = r.read_byte()  # wall color

            liquid_type = (b4 & 0x18) >> 3
            if liquid_type != 0:
                _ = r.read_byte()

            if b2 & 0x40:
                _ = r.read_byte()  # wall high byte

            rle_flag = (b4 & 0xC0) >> 6
            if rle_flag == 1:
                rle = r.read_byte()
            elif rle_flag in (2, 3):
                rle = r.read_int16()
            else:
                rle = 0

            last_tile = {"active": active, "type": tile_type}
            if active:
                tiles[(x, y)] = tile_type

    return {
        "x_start": x_start,
        "y_start": y_start,
        "width": width,
        "height": height,
        "tiles": tiles,
    }


def build_netmodule_packet(module_id: int, payload: bytes) -> bytes:
    length = 2 + 1 + 2 + len(payload)
    return struct.pack("<HBH", length, 0x52, module_id) + payload


def recv_exact(sock, n):
    # print(f"Receiving {n} bytes")
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        # print(f"Received chunk: {chunk}")
        if not chunk:
            raise ConnectionError(f"disconnected, {len(buf)}/{n}")
        buf += chunk
    return buf


class PacketStream:
    def __init__(self, sock):
        self.sock = sock
        self.buf = bytearray()

    def _feed(self, data: bytes):
        self.buf.extend(data)

    def _next_message(self):
        if len(self.buf) < 2:
            return None
        length = int.from_bytes(self.buf[:2], "little")
        if len(self.buf) < length:
            return None
        packet = bytes(self.buf[:length])
        del self.buf[:length]
        log_packet("S→C", packet)
        try:
            return TerrariaMessage.parse(packet)
        except Exception as e:
            if DEBUG:
                msg_type = packet[2] if len(packet) >= 3 else None
                print(f"Parse error for type=0x{msg_type:02X}: {e}")
            msg_type = packet[2] if len(packet) >= 3 else 0
            payload = packet[3:] if len(packet) >= 3 else b""
            return SimpleNamespace(type=msg_type, payload=SimpleNamespace(raw=payload))

    def recv_message(self):
        while True:
            msg = self._next_message()
            if msg is not None:
                return msg
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("disconnected while waiting for message")
            self._feed(chunk)

    def poll_messages(self, max_messages: int = 50):
        # Non-blocking poll using select; returns any fully parsed messages.
        msgs = []
        while True:
            r, _, _ = select.select([self.sock], [], [], 0)
            if not r:
                break
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("disconnected during poll")
            self._feed(chunk)

        while len(msgs) < max_messages:
            msg = self._next_message()
            if msg is None:
                break
            msgs.append(msg)
        return msgs


class WorldState:
    def __init__(self):
        self.tiles = {}  # (x,y) -> tile_type
        self.items = {}  # item_slot -> item dict
        self.npcs = {}  # npc_slot -> npc dict
        self.player_pos = {}  # player_slot -> (x,y)
        self.tile_sections = 0

    def update_tile_section(self, section):
        self.tiles.update(section["tiles"])
        self.tile_sections += 1

    def update_item(self, item):
        self.items[item.item_slot] = item

    def update_item_owner(self, item_slot, owner):
        if item_slot in self.items:
            self.items[item_slot].owner = owner

    def remove_item(self, item_slot):
        if item_slot in self.items:
            del self.items[item_slot]

    def update_npc(self, npc):
        self.npcs[npc.npc_slot] = npc

    def update_player_pos(self, slot, x, y):
        self.player_pos[slot] = (x, y)

    def is_solid(self, tx: int, ty: int) -> bool:
        # TODO: use solid tile metadata; for now treat any active tile as solid.
        return (tx, ty) in self.tiles

    def get_tile(self, tx: int, ty: int):
        return self.tiles.get((tx, ty))

    def get_tile_at_world(self, x: float, y: float):
        tx = int(x // 16)
        ty = int(y // 16)
        return self.get_tile(tx, ty)

    def get_nearby_tiles(self, x: float, y: float, radius_tiles: int = 3):
        tx = int(x // 16)
        ty = int(y // 16)
        out = []
        for dy in range(-radius_tiles, radius_tiles + 1):
            for dx in range(-radius_tiles, radius_tiles + 1):
                tile_type = self.get_tile(tx + dx, ty + dy)
                if tile_type is not None:
                    out.append({"x": tx + dx, "y": ty + dy, "type": tile_type})
        return out

    def get_nearby_items(self, x: float, y: float, radius_px: float = 160.0):
        out = []
        r2 = radius_px * radius_px
        for item in self.items.values():
            try:
                dx = item.position_x - x
                dy = item.position_y - y
            except Exception:
                continue
            if dx * dx + dy * dy <= r2:
                out.append(item)
        return out

    def get_nearby_npcs(self, x: float, y: float, radius_px: float = 320.0):
        out = []
        r2 = radius_px * radius_px
        for npc in self.npcs.values():
            try:
                dx = npc.position_x - x
                dy = npc.position_y - y
            except Exception:
                continue
            if dx * dx + dy * dy <= r2:
                out.append(npc)
        return out


class TeleportTracker:
    def __init__(self):
        self.pending = {}  # target -> count

    def sent(self, target: int) -> bool:
        before = self.pending.get(target, 0)
        self.pending[target] = before + 1
        return before == 0

    def ack(self, target: int) -> bool:
        if target in self.pending:
            self.pending[target] = max(0, self.pending[target] - 1)
            if self.pending[target] == 0:
                del self.pending[target]
                return True
        return False

    def status(self):
        return dict(self.pending)


class InventoryState:
    def __init__(self, size: int):
        self.size = size
        self.slots = [None] * size

    def clear(self):
        self.slots = [None] * self.size

    def find_empty_slot(self):
        for i, item in enumerate(self.slots):
            if item is None or item.get("item_id", 0) == 0 or item.get("stack", 0) == 0:
                return i
        return None

    def set_slot(self, idx: int, item_id: int, stack: int, prefix_id: int = 0):
        if idx < 0 or idx >= self.size:
            return
        self.slots[idx] = {
            "item_id": item_id,
            "stack": stack,
            "prefix_id": prefix_id,
        }


def _to_jsonable(obj):
    if obj is None or isinstance(obj, (int, float, str, bool)):
        return obj
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if hasattr(obj, "items"):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if hasattr(obj, "__dict__"):
        return {k: _to_jsonable(v) for k, v in obj.__dict__.items()}
    return repr(obj)


def dump_state(
    state: WorldState,
    path: Path,
    player_slot: int | None = None,
    radius_tiles: int = 10,
):
    player_pos = state.player_pos.get(player_slot) if player_slot is not None else None
    summary = {
        "tiles_loaded": len(state.tiles),
        "tile_sections": state.tile_sections,
        "items": len(state.items),
        "npcs": len(state.npcs),
        "player_pos": player_pos,
    }
    nearby_tiles = []
    nearby_items = []
    nearby_npcs = []
    if player_pos:
        px, py = player_pos
        nearby_tiles = state.get_nearby_tiles(px, py, radius_tiles=radius_tiles)
        nearby_items = [_to_jsonable(i) for i in state.get_nearby_items(px, py)]
        nearby_npcs = [_to_jsonable(n) for n in state.get_nearby_npcs(px, py)]

    data = {
        "summary": summary,
        "nearby_tiles": nearby_tiles,
        "items": [_to_jsonable(i) for i in state.items.values()],
        "npcs": [_to_jsonable(n) for n in state.npcs.values()],
        "nearby_items": nearby_items,
        "nearby_npcs": nearby_npcs,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=True, indent=2))
    print(f"State dumped to {path}")


def send(sock, msg_type, payload=None):
    packet = build_packet(msg_type, payload)
    send_raw(sock, packet)


def send_raw(sock, packet: bytes):
    log_packet("C→S", packet)
    sock.sendall(packet)


def build_player_controls_packet(
    profile: VersionSpec,
    player_slot: int,
    x: float,
    y: float,
    control_right: bool,
    selected_item: int = 0,
    control_left: bool = False,
    control_up: bool = False,
    control_down: bool = False,
    control_jump: bool = False,
    control_use_item: bool = False,
    direction: int = 1,
    send_velocity: bool = False,
    vel_x: float = 0.0,
    vel_y: float = 0.0,
    grav_dir: int = 1,
) -> bytes:
    fmt = profile.message_formats.get("player_controls", "v1")
    if fmt == "v0":
        # Legacy format: control_flags + selected_item + position + velocity + flags
        control_flags = 0
        control_flags |= int(control_up) << 0
        control_flags |= int(control_down) << 1
        control_flags |= int(control_left) << 2
        control_flags |= int(control_right) << 3
        control_flags |= int(control_jump) << 4
        control_flags |= int(control_use_item) << 5
        payload = struct.pack(
            "<BBBffffB",
            player_slot,
            control_flags,
            selected_item,
            x,
            y,
            vel_x,
            vel_y,
            0,
        )
        return build_raw_packet(0x0D, payload)

    # v1 (1.4.4+)
    flags1 = 0
    flags1 |= int(control_up) << 0
    flags1 |= int(control_down) << 1
    flags1 |= int(control_left) << 2
    flags1 |= int(control_right) << 3
    flags1 |= int(control_jump) << 4
    flags1 |= int(control_use_item) << 5
    flags1 |= int(direction == 1) << 6

    flags2 = 0
    flags2 |= int(send_velocity) << 2
    flags2 |= int(grav_dir == 1) << 4

    flags3 = 0
    flags4 = 0

    payload = struct.pack(
        "<BBBBBBff",
        player_slot,
        flags1,
        flags2,
        flags3,
        flags4,
        selected_item,
        x,
        y,
    )
    if send_velocity:
        payload += struct.pack("<ff", vel_x, vel_y)
    return build_raw_packet(0x0D, payload)


def build_spawn_packet(
    profile: VersionSpec,
    player_slot: int,
    spawn_x: int,
    spawn_y: int,
    respawn_timer: int = 0,
    deaths_pve: int = 0,
    deaths_pvp: int = 0,
    team: int = 0,
    spawn_context: int = 0,
) -> bytes:
    fmt = profile.message_formats.get("player_spawn", "v1")
    if fmt == "v0":
        payload = struct.pack("<Bii", player_slot, spawn_x, spawn_y)
        return build_raw_packet(0x0C, payload)

    # v1 (1.4.4+)
    payload = struct.pack(
        "<BhhihhBB",
        player_slot,
        spawn_x,
        spawn_y,
        respawn_timer,
        deaths_pve,
        deaths_pvp,
        team,
        spawn_context,
    )
    return build_raw_packet(0x0C, payload)


def move_right_loop(
    sock,
    stream: PacketStream,
    state: WorldState,
    profile: VersionSpec,
    player_slot: int,
    start_x: float,
    start_y: float,
    seconds: float,
    speed: float,
    toggle: bool,
    toggle_interval: float,
    tile_frame_important: set[int],
    use_physics: bool = True,
    teleport_tracker: TeleportTracker | None = None,
    inventory: InventoryState | None = None,
    auto_pickup: bool = True,
    pickup_radius: float | None = None,
):
    tick = 1.0 / 60.0
    end_time = time.time() + seconds if seconds > 0 else None
    x = start_x
    y = start_y
    vx = 0.0
    vy = 0.0
    on_ground = False
    moving = True
    next_toggle = time.time() + toggle_interval
    max_run = speed / 60.0  # speed is px/sec
    accel = 0.1
    friction = 0.05
    gravity = 0.3
    max_fall = 10.0
    player_width = 20
    player_height = 42

    if teleport_tracker is None:
        teleport_tracker = TeleportTracker()
    if inventory is None:
        inventory = InventoryState(59)

    while True:
        now = time.time()
        if end_time is not None and now >= end_time:
            break

        # update last known position from server if available
        for msg in stream.poll_messages():
            if msg.type == 0x0A:
                try:
                    section = parse_tile_section(msg.payload, tile_frame_important)
                    state.update_tile_section(section)
                except Exception as e:
                    print(f"Tile section parse failed: {e}")
            elif msg.type == 0x15:
                state.update_item(msg.payload)
            elif msg.type == 0x16:
                state.update_item_owner(msg.payload.item_slot, msg.payload.owner)
                if msg.payload.owner == player_slot:
                    print(f"Picked up item slot={msg.payload.item_slot}")
                if auto_pickup:
                    try_pickup_reserved_items(
                        sock,
                        state,
                        inventory,
                        profile,
                        player_slot,
                        state.player_pos.get(player_slot) or (x, y),
                        radius_px=pickup_radius,
                    )
            elif msg.type == 0x97:
                item_slot = getattr(msg.payload, "item_slot", None)
                if item_slot is None and isinstance(msg.payload, (bytes, bytearray)):
                    if len(msg.payload) >= 2:
                        item_slot = struct.unpack("<h", msg.payload[:2])[0]
                if item_slot is not None:
                    state.remove_item(item_slot)
            elif msg.type == 0x17:
                state.update_npc(msg.payload)
            elif msg.type == 0x1A and msg.payload.player_slot == player_slot:
                print(
                    f"Took damage: dmg={msg.payload.damage} crit={msg.payload.critical}"
                )
            elif msg.type == 0x2C and msg.payload.player_slot == player_slot:
                print(
                    f"Killed: dmg={msg.payload.damage} dir={msg.payload.hit_direction}"
                )
            elif msg.type == 0x75:
                info = decode_player_hurt_v2(msg.payload)
                if info["player_slot"] == player_slot:
                    print(
                        f"Took damage(v2): dmg={info['damage']} crit={info['crit']} pvp={info['pvp']} dir={info['hit_dir']}"
                    )
            elif msg.type == 0x76:
                info = decode_player_death_v2(msg.payload)
                if info["player_slot"] == player_slot:
                    print(
                        f"Killed(v2): dmg={info['damage']} pvp={info['pvp']} dir={info['hit_dir']}"
                    )
            elif msg.type == 0x0D and msg.payload.player_slot == player_slot:
                x = msg.payload.position_x
                y = msg.payload.position_y
                state.update_player_pos(player_slot, x, y)
            elif msg.type == 0x41:
                info = decode_teleport(msg.payload)
                if info["mode"] in (0, 2):
                    if teleport_tracker.sent(info["target"]):
                        print(
                            f"Teleport pending: target={info['target']} pending={teleport_tracker.status()}"
                        )
                    if info["target"] == player_slot:
                        send_raw(sock, build_teleport_ack_packet(info["target"]))
                        if teleport_tracker.ack(info["target"]):
                            print(
                                f"Teleport acked: target={info['target']} pending={teleport_tracker.status()}"
                            )
                elif info["mode"] == 3:
                    if teleport_tracker.ack(info["target"]):
                        print(
                            f"Teleport acked: target={info['target']} pending={teleport_tracker.status()}"
                        )
                print(
                    "Teleport packet: "
                    f"flags_raw=0x{info['flags_raw']:02X} flags={info['flags']} "
                    f"target={info['target']} pos=({info['x']:.2f},{info['y']:.2f}) "
                    f"style={info['style']} extra={info['extra']}"
                )

        if toggle and now >= next_toggle:
            moving = not moving
            next_toggle = now + toggle_interval

        if use_physics:
            # basic physics: horizontal accel + gravity, with simple tile collision
            if moving:
                vx = min(max_run, vx + accel)
            else:
                if vx > 0:
                    vx = max(0.0, vx - friction)
                elif vx < 0:
                    vx = min(0.0, vx + friction)
            vy = min(max_fall, vy + gravity)

            # move X with collision
            new_x = x + vx
            if vx > 0:
                top = int(y // 16)
                bottom = int((y + player_height - 1) // 16)
                start_tx = int((x + player_width - 1) // 16) + 1
                end_tx = int((new_x + player_width - 1) // 16)
                collided = False
                for tx in range(start_tx, end_tx + 1):
                    for ty in range(top, bottom + 1):
                        if state.is_solid(tx, ty):
                            new_x = tx * 16 - player_width
                            vx = 0.0
                            collided = True
                            break
                    if collided:
                        break
            elif vx < 0:
                top = int(y // 16)
                bottom = int((y + player_height - 1) // 16)
                start_tx = int(x // 16) - 1
                end_tx = int(new_x // 16)
                collided = False
                for tx in range(start_tx, end_tx - 1, -1):
                    for ty in range(top, bottom + 1):
                        if state.is_solid(tx, ty):
                            new_x = (tx + 1) * 16
                            vx = 0.0
                            collided = True
                            break
                    if collided:
                        break
            x = new_x

            # move Y with collision
            new_y = y + vy
            on_ground = False
            if vy > 0:
                left = int(x // 16)
                right = int((x + player_width - 1) // 16)
                start_ty = int((y + player_height - 1) // 16) + 1
                end_ty = int((new_y + player_height - 1) // 16)
                collided = False
                for ty in range(start_ty, end_ty + 1):
                    for tx in range(left, right + 1):
                        if state.is_solid(tx, ty):
                            new_y = ty * 16 - player_height
                            vy = 0.0
                            on_ground = True
                            collided = True
                            break
                    if collided:
                        break
            elif vy < 0:
                left = int(x // 16)
                right = int((x + player_width - 1) // 16)
                start_ty = int(y // 16) - 1
                end_ty = int(new_y // 16)
                collided = False
                for ty in range(start_ty, end_ty - 1, -1):
                    for tx in range(left, right + 1):
                        if state.is_solid(tx, ty):
                            new_y = (ty + 1) * 16
                            vy = 0.0
                            collided = True
                            break
                    if collided:
                        break
            y = new_y
        else:
            if moving:
                x += speed * tick

        state.update_player_pos(player_slot, x, y)

        if auto_pickup and inventory and player_slot in state.player_pos:
            try_pickup_reserved_items(
                sock,
                state,
                inventory,
                profile,
                player_slot,
                state.player_pos.get(player_slot),
                radius_px=pickup_radius,
            )

        packet = build_player_controls_packet(
            profile,
            player_slot=player_slot,
            x=x,
            y=y,
            control_right=moving,
            direction=1,
            selected_item=0,
            send_velocity=True,
            vel_x=vx,
            vel_y=vy,
        )
        send_raw(sock, packet)
        time.sleep(tick)

    # stop movement
    packet = build_player_controls_packet(
        profile,
        player_slot=player_slot,
        x=x,
        y=y,
        control_right=False,
        direction=1,
        selected_item=0,
        send_velocity=False,
    )
    send_raw(sock, packet)
    return x, y, vx, vy


def idle_loop(
    sock,
    stream: PacketStream,
    state: WorldState,
    profile: VersionSpec,
    player_slot: int,
    x: float,
    y: float,
    interval: float,
    teleport_tracker: TeleportTracker | None = None,
    inventory: InventoryState | None = None,
    auto_pickup: bool = True,
    pickup_radius: float | None = None,
):
    last_send = time.time()
    vx = 0.0
    vy = 0.0
    if teleport_tracker is None:
        teleport_tracker = TeleportTracker()
    if inventory is None:
        inventory = InventoryState(59)
    while True:
        for msg in stream.poll_messages():
            if msg.type == 0x0A:
                try:
                    section = parse_tile_section(
                        msg.payload, profile.tile_frame_important
                    )
                    state.update_tile_section(section)
                except Exception as e:
                    print(f"Tile section parse failed: {e}")
            elif msg.type == 0x15:
                state.update_item(msg.payload)
            elif msg.type == 0x16:
                state.update_item_owner(msg.payload.item_slot, msg.payload.owner)
                if msg.payload.owner == player_slot:
                    print(f"Picked up item slot={msg.payload.item_slot}")
                if auto_pickup:
                    try_pickup_reserved_items(
                        sock,
                        state,
                        inventory,
                        profile,
                        player_slot,
                        state.player_pos.get(player_slot) or (x, y),
                        radius_px=pickup_radius,
                    )
            elif msg.type == 0x97:
                item_slot = getattr(msg.payload, "item_slot", None)
                if item_slot is None and isinstance(msg.payload, (bytes, bytearray)):
                    if len(msg.payload) >= 2:
                        item_slot = struct.unpack("<h", msg.payload[:2])[0]
                if item_slot is not None:
                    state.remove_item(item_slot)
            elif msg.type == 0x17:
                state.update_npc(msg.payload)
            elif msg.type == 0x1A and msg.payload.player_slot == player_slot:
                print(
                    f"Took damage: dmg={msg.payload.damage} crit={msg.payload.critical}"
                )
            elif msg.type == 0x2C and msg.payload.player_slot == player_slot:
                print(
                    f"Killed: dmg={msg.payload.damage} dir={msg.payload.hit_direction}"
                )
            elif msg.type == 0x75:
                info = decode_player_hurt_v2(msg.payload)
                if info["player_slot"] == player_slot:
                    print(
                        f"Took damage(v2): dmg={info['damage']} crit={info['crit']} pvp={info['pvp']} dir={info['hit_dir']}"
                    )
            elif msg.type == 0x76:
                info = decode_player_death_v2(msg.payload)
                if info["player_slot"] == player_slot:
                    print(
                        f"Killed(v2): dmg={info['damage']} pvp={info['pvp']} dir={info['hit_dir']}"
                    )
            elif msg.type == 0x0D and msg.payload.player_slot == player_slot:
                x = msg.payload.position_x
                y = msg.payload.position_y
                state.update_player_pos(player_slot, x, y)
            elif msg.type == 0x41:
                info = decode_teleport(msg.payload)
                if info["mode"] in (0, 2):
                    if teleport_tracker.sent(info["target"]):
                        print(
                            f"Teleport pending: target={info['target']} pending={teleport_tracker.status()}"
                        )
                    if info["target"] == player_slot:
                        send_raw(sock, build_teleport_ack_packet(info["target"]))
                        if teleport_tracker.ack(info["target"]):
                            print(
                                f"Teleport acked: target={info['target']} pending={teleport_tracker.status()}"
                            )
                elif info["mode"] == 3:
                    if teleport_tracker.ack(info["target"]):
                        print(
                            f"Teleport acked: target={info['target']} pending={teleport_tracker.status()}"
                        )
                print(
                    "Teleport packet: "
                    f"flags_raw=0x{info['flags_raw']:02X} flags={info['flags']} "
                    f"target={info['target']} pos=({info['x']:.2f},{info['y']:.2f}) "
                    f"style={info['style']} extra={info['extra']}"
                )

        now = time.time()
        if interval > 0 and now - last_send >= interval:
            state.update_player_pos(player_slot, x, y)
            if auto_pickup and inventory and player_slot in state.player_pos:
                try_pickup_reserved_items(
                    sock,
                    state,
                    inventory,
                    profile,
                    player_slot,
                    state.player_pos.get(player_slot),
                    radius_px=pickup_radius,
                )
            packet = build_player_controls_packet(
                profile,
                player_slot=player_slot,
                x=x,
                y=y,
                control_right=False,
                direction=1,
                selected_item=0,
                send_velocity=True,
                vel_x=vx,
                vel_y=vy,
            )
            send_raw(sock, packet)
            last_send = now
        time.sleep(0.01)


def explore_loop(
    sock,
    stream: PacketStream,
    state: WorldState,
    profile: VersionSpec,
    player_slot: int,
    bot: ExplorationBot,
    interval: float,
    sense_radius: int,
    teleport_tracker: TeleportTracker | None = None,
    inventory: InventoryState | None = None,
    auto_pickup: bool = True,
    pickup_radius: float | None = None,
):
    tick = 1.0 / 60.0
    last_decide = 0.0
    action = Action()
    x = 0.0
    y = 0.0
    vx = 0.0
    vy = 0.0
    on_ground = False
    max_run = 64.0 / 60.0
    accel = 0.1
    friction = 0.05
    gravity = 0.3
    max_fall = 10.0
    player_width = 20
    player_height = 42
    if teleport_tracker is None:
        teleport_tracker = TeleportTracker()
    if inventory is None:
        inventory = InventoryState(59)
    while True:
        for msg in stream.poll_messages():
            if msg.type == 0x0A:
                try:
                    section = parse_tile_section(
                        msg.payload, profile.tile_frame_important
                    )
                    state.update_tile_section(section)
                except Exception as e:
                    print(f"Tile section parse failed: {e}")
            elif msg.type == 0x15:
                state.update_item(msg.payload)
            elif msg.type == 0x16:
                state.update_item_owner(msg.payload.item_slot, msg.payload.owner)
                if msg.payload.owner == player_slot:
                    print(f"Picked up item slot={msg.payload.item_slot}")
                if auto_pickup:
                    try_pickup_reserved_items(
                        sock,
                        state,
                        inventory,
                        profile,
                        player_slot,
                        state.player_pos.get(player_slot) or (x, y),
                        radius_px=pickup_radius,
                    )
            elif msg.type == 0x97:
                item_slot = getattr(msg.payload, "item_slot", None)
                if item_slot is None and isinstance(msg.payload, (bytes, bytearray)):
                    if len(msg.payload) >= 2:
                        item_slot = struct.unpack("<h", msg.payload[:2])[0]
                if item_slot is not None:
                    state.remove_item(item_slot)
            elif msg.type == 0x17:
                state.update_npc(msg.payload)
            elif msg.type == 0x1A and msg.payload.player_slot == player_slot:
                print(
                    f"Took damage: dmg={msg.payload.damage} crit={msg.payload.critical}"
                )
            elif msg.type == 0x2C and msg.payload.player_slot == player_slot:
                print(
                    f"Killed: dmg={msg.payload.damage} dir={msg.payload.hit_direction}"
                )
            elif msg.type == 0x75:
                info = decode_player_hurt_v2(msg.payload)
                if info["player_slot"] == player_slot:
                    print(
                        f"Took damage(v2): dmg={info['damage']} crit={info['crit']} pvp={info['pvp']} dir={info['hit_dir']}"
                    )
            elif msg.type == 0x76:
                info = decode_player_death_v2(msg.payload)
                if info["player_slot"] == player_slot:
                    print(
                        f"Killed(v2): dmg={info['damage']} pvp={info['pvp']} dir={info['hit_dir']}"
                    )
            elif msg.type == 0x0D and msg.payload.player_slot == player_slot:
                x = msg.payload.position_x
                y = msg.payload.position_y
                state.update_player_pos(player_slot, x, y)
            elif msg.type == 0x41:
                info = decode_teleport(msg.payload)
                if info["mode"] in (0, 2):
                    if teleport_tracker.sent(info["target"]):
                        print(
                            f"Teleport pending: target={info['target']} pending={teleport_tracker.status()}"
                        )
                    if info["target"] == player_slot:
                        send_raw(sock, build_teleport_ack_packet(info["target"]))
                        if teleport_tracker.ack(info["target"]):
                            print(
                                f"Teleport acked: target={info['target']} pending={teleport_tracker.status()}"
                            )
                elif info["mode"] == 3:
                    if teleport_tracker.ack(info["target"]):
                        print(
                            f"Teleport acked: target={info['target']} pending={teleport_tracker.status()}"
                        )
                print(
                    "Teleport packet: "
                    f"flags_raw=0x{info['flags_raw']:02X} flags={info['flags']} "
                    f"target={info['target']} pos=({info['x']:.2f},{info['y']:.2f}) "
                    f"style={info['style']} extra={info['extra']}"
                )

        now = time.time()
        if interval <= 0 or now - last_decide >= interval:
            pos = state.player_pos.get(player_slot) or (x, y)
            x, y = pos
            obs = Observation(
                player_pos=pos,
                nearby_tiles=state.get_nearby_tiles(x, y, radius_tiles=sense_radius),
                nearby_items=state.get_nearby_items(x, y),
                nearby_npcs=state.get_nearby_npcs(x, y),
            )
            action = bot.decide(obs)
            last_decide = now

        # physics step driven by current action
        if action.move_right and not action.move_left:
            vx = min(max_run, vx + accel)
        elif action.move_left and not action.move_right:
            vx = max(-max_run, vx - accel)
        else:
            if vx > 0:
                vx = max(0.0, vx - friction)
            elif vx < 0:
                vx = min(0.0, vx + friction)

        if action.jump and on_ground:
            vy = -5.5
            on_ground = False
        vy = min(max_fall, vy + gravity)

        # move X with collision
        new_x = x + vx
        if vx > 0:
            top = int(y // 16)
            bottom = int((y + player_height - 1) // 16)
            start_tx = int((x + player_width - 1) // 16) + 1
            end_tx = int((new_x + player_width - 1) // 16)
            collided = False
            for tx in range(start_tx, end_tx + 1):
                for ty in range(top, bottom + 1):
                    if state.is_solid(tx, ty):
                        new_x = tx * 16 - player_width
                        vx = 0.0
                        collided = True
                        break
                if collided:
                    break
        elif vx < 0:
            top = int(y // 16)
            bottom = int((y + player_height - 1) // 16)
            start_tx = int(x // 16) - 1
            end_tx = int(new_x // 16)
            collided = False
            for tx in range(start_tx, end_tx - 1, -1):
                for ty in range(top, bottom + 1):
                    if state.is_solid(tx, ty):
                        new_x = (tx + 1) * 16
                        vx = 0.0
                        collided = True
                        break
                if collided:
                    break
        x = new_x

        # move Y with collision
        new_y = y + vy
        on_ground = False
        if vy > 0:
            left = int(x // 16)
            right = int((x + player_width - 1) // 16)
            start_ty = int((y + player_height - 1) // 16) + 1
            end_ty = int((new_y + player_height - 1) // 16)
            collided = False
            for ty in range(start_ty, end_ty + 1):
                for tx in range(left, right + 1):
                    if state.is_solid(tx, ty):
                        new_y = ty * 16 - player_height
                        vy = 0.0
                        on_ground = True
                        collided = True
                        break
                if collided:
                    break
        elif vy < 0:
            left = int(x // 16)
            right = int((x + player_width - 1) // 16)
            start_ty = int(y // 16) - 1
            end_ty = int(new_y // 16)
            collided = False
            for ty in range(start_ty, end_ty - 1, -1):
                for tx in range(left, right + 1):
                    if state.is_solid(tx, ty):
                        new_y = (ty + 1) * 16
                        vy = 0.0
                        collided = True
                        break
                if collided:
                    break
        y = new_y
        state.update_player_pos(player_slot, x, y)

        if auto_pickup and inventory and player_slot in state.player_pos:
            try_pickup_reserved_items(
                sock,
                state,
                inventory,
                profile,
                player_slot,
                state.player_pos.get(player_slot),
                radius_px=pickup_radius,
            )

        packet = build_player_controls_packet(
            profile,
            player_slot=player_slot,
            x=x,
            y=y,
            control_left=action.move_left,
            control_right=action.move_right,
            control_jump=action.jump,
            control_use_item=action.use_item,
            direction=action.direction,
            selected_item=action.selected_item,
            send_velocity=True,
            vel_x=vx,
            vel_y=vy,
        )
        send_raw(sock, packet)
        time.sleep(tick)


def send_chat(sock, text: str):
    # NetTextModule client message: module_id + ChatMessage(CommandId + Text)
    # ChatCommandId for SayChatCommand is "Say".
    payload = write_dotnet_string("Say") + write_dotnet_string(text)
    packet = build_netmodule_packet(NET_TEXT_MODULE_ID, payload)
    send_raw(sock, packet)


def _pack_color(c: dict) -> bytes:
    return struct.pack("<BBB", c["r"], c["g"], c["b"])


def build_sync_player_packet(profile: VersionSpec, payload: dict) -> bytes:
    fmt = profile.message_formats.get("sync_player", "v0")
    name = payload["name"]
    if len(name) > profile.name_len:
        print(f"Name too long, trimming to {profile.name_len} chars.")
        name = name[: profile.name_len]

    hide_vis = payload.get("hide_visuals", 0) & 0xFF
    hide_vis2 = payload.get("hide_visuals_2", 0) & 0xFF
    hide_vis_mask = hide_vis | (hide_vis2 << 8)

    base = bytearray()
    base.append(payload["player_id"] & 0xFF)

    if fmt == "v1":
        base.append(payload.get("skin_variant", 0) & 0xFF)
        base.append(payload.get("voice_variant", 1) & 0xFF)
        base.extend(struct.pack("<f", payload.get("voice_pitch_offset", 0.0)))
        base.append(payload.get("hair", 0) & 0xFF)
    else:
        base.append(payload.get("skin_variant", 0) & 0xFF)
        base.append(payload.get("hair", 0) & 0xFF)

    base.extend(write_dotnet_string(name))
    base.append(payload.get("hair_dye", 0) & 0xFF)
    base.extend(struct.pack("<H", hide_vis_mask))
    base.append(payload.get("hide_misc", 0) & 0xFF)
    base.extend(_pack_color(payload["hair_color"]))
    base.extend(_pack_color(payload["skin_color"]))
    base.extend(_pack_color(payload["eye_color"]))
    base.extend(_pack_color(payload["shirt_color"]))
    base.extend(_pack_color(payload["undershirt_color"]))
    base.extend(_pack_color(payload["pants_color"]))
    base.extend(_pack_color(payload["shoe_color"]))
    base.append(payload.get("difficulty_flags", 0) & 0xFF)
    base.append(payload.get("torch_flags", 0) & 0xFF)
    base.append(payload.get("shimmer_flags", 0) & 0xFF)

    return build_raw_packet(0x04, bytes(base))


def build_sync_equipment_packet(profile: VersionSpec, payload: dict) -> bytes:
    fmt = profile.message_formats.get("sync_equipment", "v0")
    base = bytearray()
    base.append(payload["player_slot"] & 0xFF)
    base.extend(struct.pack("<h", payload["inventory_slot"]))
    base.extend(struct.pack("<h", payload["stack"]))
    base.append(payload["prefix_id"] & 0xFF)
    base.extend(struct.pack("<h", payload["item_id"]))
    if fmt == "v1":
        base.append(payload.get("flags", 0) & 0xFF)
    return build_raw_packet(0x05, bytes(base))


def build_teleport_ack_packet(target: int) -> bytes:
    # NetMessage.TrySendData(65, ..., number=3, number2=target)
    bits = 0x01 | 0x02
    payload = struct.pack("<BhffB", bits, target, 0.0, 0.0, 0)
    return build_raw_packet(0x41, payload)


def build_remove_item_packet(item_slot: int) -> bytes:
    payload = struct.pack("<h", item_slot)
    return build_raw_packet(0x97, payload)


def try_pickup_reserved_items(
    sock,
    state: WorldState,
    inventory: InventoryState,
    profile: VersionSpec,
    player_slot: int,
    player_pos: tuple[float, float] | None,
    radius_px: float | None = None,
):
    if player_pos is None:
        return
    px, py = player_pos
    r2 = None if radius_px is None or radius_px < 0 else radius_px * radius_px
    # iterate over a snapshot to allow deletion
    for item_slot, item in list(state.items.items()):
        owner = getattr(item, "owner", None)
        if owner != player_slot:
            continue
        try:
            dx = item.position_x - px
            dy = item.position_y - py
        except Exception:
            continue
        if r2 is not None and dx * dx + dy * dy > r2:
            continue
        item_id = getattr(item, "item_id", 0)
        stack = getattr(item, "stack", 0)
        prefix_id = getattr(item, "prefix_id", 0)
        if item_id == 0 or stack <= 0:
            continue
        slot = inventory.find_empty_slot()
        if slot is None:
            return
        # update inventory on server
        send_raw(
            sock,
            build_sync_equipment_packet(
                profile,
                {
                    "player_slot": player_slot,
                    "inventory_slot": slot,
                    "stack": stack,
                    "prefix_id": prefix_id,
                    "item_id": item_id,
                    "flags": 0,
                },
            ),
        )
        inventory.set_slot(slot, item_id, stack, prefix_id)
        # remove world item
        send_raw(sock, build_remove_item_packet(item_slot))
        if item_slot in state.items:
            del state.items[item_slot]


def build_player_buffs_packet(
    profile: VersionSpec, player_slot: int, buffs=None
) -> bytes:
    fmt = profile.message_formats.get("player_buffs", "v0")
    base = bytearray()
    base.append(player_slot & 0xFF)
    if fmt == "v1":
        # v1: sequence of UInt16 buff IDs terminated by 0
        buffs = buffs or []
        for buff_id in buffs:
            base.extend(struct.pack("<H", buff_id))
        base.extend(struct.pack("<H", 0))
    else:
        # v0: fixed-size array (default 44)
        if buffs is None:
            buffs = [0] * 44
        for buff_id in buffs:
            base.extend(struct.pack("<H", buff_id))
    return build_raw_packet(0x32, bytes(base))


class TerrariaClient:
    def __init__(
        self,
        host: str,
        port: str,
        password: Optional[str] = None,
        name: str = "BotUser",
        chat_text: str = "hello",
        uuid: Optional[str] = None,
        profile: VersionSpec | None = None,
        inventory_count: int = 59,
        worldinfo_retry: float = 2.0,
        auto_pickup: bool = True,
        pickup_radius: float | None = 42.0,
    ):
        self.host = host
        self.port = port
        self.password = password
        self.name = name
        self.chat_text = chat_text
        self.uuid = (
            uuid
            or f"{random.randrange(16**8):08x}-dead-beef-cafe-{random.randrange(16**12):012x}"
        )
        self.profile = profile
        self.inventory_count = inventory_count
        self.worldinfo_retry = worldinfo_retry
        self.auto_pickup = auto_pickup
        self.pickup_radius = pickup_radius

    def login(self):
        with socket.create_connection((self.host, self.port)) as s:
            stream = PacketStream(s)
            state = WorldState()
            teleport_tracker = TeleportTracker()
            inventory = InventoryState(self.inventory_count)
            profile = self.profile
            if profile is None:
                raise RuntimeError("Version profile is required.")
            # $01 Connect Request: "Terraria<version>"
            send(s, 0x01, {"version": profile.version_string})
            print("Connected to server")
            # 응답: $03 승인 or $25 비번요구 or $02 차단
            msg = stream.recv_message()
            if msg.type == 0x25:  # Request Password
                print("Request Password")
                send(s, 0x26, {"password": self.password})  # $26 Login with Password
                msg = stream.recv_message()
            if msg.type == 0x02:
                print("Banned or error")
                raise SystemExit(f"banned or error: {msg.payload.error}")
            assert msg.type == 0x03
            player_slot = msg.payload.player_slot
            print(f"Connection Approved: slot={player_slot}")

            # $04 Player Appearance
            sync_player_payload = {
                "player_id": player_slot,
                "skin_variant": 4,
                "voice_variant": 1,
                "voice_pitch_offset": 0.0,
                "hair": 22,
                "name": self.name,
                "hair_dye": 0,
                "hide_visuals": 0,
                "hide_visuals_2": 0,
                "hide_misc": 0,
                "hair_color": {"r": 0, "g": 0, "b": 0},
                "skin_color": {"r": 255, "g": 224, "b": 189},
                "eye_color": {"r": 64, "g": 64, "b": 64},
                "shirt_color": {"r": 100, "g": 100, "b": 100},
                "undershirt_color": {"r": 100, "g": 100, "b": 100},
                "pants_color": {"r": 100, "g": 100, "b": 100},
                "shoe_color": {"r": 50, "g": 50, "b": 50},
                "difficulty_flags": 4,
                "torch_flags": 24,
                "shimmer_flags": 0,
            }
            send_raw(s, build_sync_player_packet(profile, sync_player_payload))
            print("Player Appearance")

            # send client uuid
            send(s, 0x44, {"client_uuid": self.uuid})

            # $10 Life, $2A Mana, $32 Buffs (응답 기다리지 않고 전송) (https://seancode.com/terrafirma/net.html)
            send(
                s,
                0x10,
                {"player_slot": player_slot, "current_health": 500, "max_health": 500},
            )
            send(
                s,
                0x2A,
                {"player_slot": player_slot, "mana": 200, "max_mana": 200},
            )
            send_raw(
                s, build_player_buffs_packet(profile, player_slot=player_slot, buffs=[])
            )
            print("Life, Mana, Buffs")

            # Loadout (0x93 == 147)
            send(s, 0x93, {"loadout": [0, 0, 0, 0]})

            # 인벤토리 슬롯 0..72, $05 반복 전송 (https://seancode.com/terrafirma/net.html)
            for inv in range(self.inventory_count):
                send_raw(
                    s,
                    build_sync_equipment_packet(
                        profile,
                        {
                            "player_slot": player_slot,
                            "inventory_slot": inv,
                            "stack": 0,
                            "prefix_id": 0,
                            "item_id": 0,
                            "flags": 0,
                        },
                    ),
                )
                inventory.set_slot(inv, 0, 0, 0)

            print("Sent Inventory")
            # $06 World Info 요청 (https://seancode.com/terrafirma/net.html)
            send(s, 0x06)
            print("World Info Requested")
            # 서버는 문제 있으면 $02로 킥. 정상이면 $07 응답 후 Initialized(2)로 승격 (https://seancode.com/terrafirma/net.html)
            world_info = None
            last_worldinfo_send = time.time()
            warn_at = time.time() + 5.0
            while world_info is None:
                msgs = stream.poll_messages()
                if not msgs:
                    if (
                        self.worldinfo_retry
                        and time.time() - last_worldinfo_send > self.worldinfo_retry
                    ):
                        print("Re-sending World Info request...")
                        send(s, 0x06)
                        last_worldinfo_send = time.time()
                    if DEBUG and time.time() >= warn_at:
                        print("Still waiting for world info...")
                        warn_at = time.time() + 5.0
                    time.sleep(0.01)
                    continue
                for msg in msgs:
                    if msg.type == 0x02:
                        raise SystemExit(f"error: {msg.payload.error}")
                    if msg.type == 0x07:
                        world_info = msg.payload
                        break
                    if msg.type != 0x52:
                        print(f"World Info Other response: {msg}")
            print(f"World Info Response: {world_info}")
            fallback_pos = (
                world_info.spawn_tile_x * 16.0,
                world_info.spawn_tile_y * 16.0,
            )
            state.update_player_pos(player_slot, *fallback_pos)
            # $08 초기 타일 데이터 요청. $07에서 받은 스폰 X,Y 사용 (https://seancode.com/terrafirma/net.html)
            send(
                s,
                0x08,
                {
                    "spawn_x": world_info.spawn_tile_x,
                    "spawn_y": world_info.spawn_tile_y,
                },
            )

            # 서버는 $09, 여러 개의 $0A, $0B, $15, $16, $17, $31, $39, $38 순으로 보냄 (https://seancode.com/terrafirma/net.html)
            got_spawn = False
            while not got_spawn:
                msg = stream.recv_message()
                if msg.type == 0x0A:  # Tile section
                    try:
                        section = parse_tile_section(
                            msg.payload, profile.tile_frame_important
                        )
                        state.update_tile_section(section)
                    except Exception as e:
                        print(f"Tile section parse failed: {e}")
                elif msg.type == 0x15:
                    state.update_item(msg.payload)
                elif msg.type == 0x16:
                    state.update_item_owner(msg.payload.item_slot, msg.payload.owner)
                    if msg.payload.owner == player_slot:
                        print(f"Picked up item slot={msg.payload.item_slot}")
                    if self.auto_pickup:
                        try_pickup_reserved_items(
                            s,
                            state,
                            inventory,
                            profile,
                            player_slot,
                            state.player_pos.get(player_slot) or fallback_pos,
                            radius_px=self.pickup_radius,
                        )
                elif msg.type == 0x97:
                    item_slot = getattr(msg.payload, "item_slot", None)
                    if item_slot is None and isinstance(
                        msg.payload, (bytes, bytearray)
                    ):
                        if len(msg.payload) >= 2:
                            item_slot = struct.unpack("<h", msg.payload[:2])[0]
                    if item_slot is not None:
                        state.remove_item(item_slot)
                elif msg.type == 0x17:
                    state.update_npc(msg.payload)
                elif msg.type == 0x1A and msg.payload.player_slot == player_slot:
                    print(
                        f"Took damage: dmg={msg.payload.damage} crit={msg.payload.critical}"
                    )
                elif msg.type == 0x2C and msg.payload.player_slot == player_slot:
                    print(
                        f"Killed: dmg={msg.payload.damage} dir={msg.payload.hit_direction}"
                    )
                elif msg.type == 0x75:
                    info = decode_player_hurt_v2(msg.payload)
                    if info["player_slot"] == player_slot:
                        print(
                            f"Took damage(v2): dmg={info['damage']} crit={info['crit']} pvp={info['pvp']} dir={info['hit_dir']}"
                        )
                elif msg.type == 0x76:
                    info = decode_player_death_v2(msg.payload)
                    if info["player_slot"] == player_slot:
                        print(
                            f"Killed(v2): dmg={info['damage']} pvp={info['pvp']} dir={info['hit_dir']}"
                        )
                elif msg.type == 0x0D:
                    state.update_player_pos(
                        msg.payload.player_slot,
                        msg.payload.position_x,
                        msg.payload.position_y,
                    )
                elif msg.type == 0x41:
                    info = decode_teleport(msg.payload)
                    if info["mode"] in (0, 2):
                        if teleport_tracker.sent(info["target"]):
                            print(
                                f"Teleport pending: target={info['target']} pending={teleport_tracker.status()}"
                            )
                        if info["target"] == player_slot:
                            send_raw(s, build_teleport_ack_packet(info["target"]))
                            if teleport_tracker.ack(info["target"]):
                                print(
                                    f"Teleport acked: target={info['target']} pending={teleport_tracker.status()}"
                                )
                    elif info["mode"] == 3:
                        if teleport_tracker.ack(info["target"]):
                            print(
                                f"Teleport acked: target={info['target']} pending={teleport_tracker.status()}"
                            )
                    print(
                        "Teleport packet: "
                        f"flags_raw=0x{info['flags_raw']:02X} flags={info['flags']} "
                        f"target={info['target']} pos=({info['x']:.2f},{info['y']:.2f}) "
                        f"style={info['style']} extra={info['extra']}"
                    )
                elif msg.type in (0x31, 0x0C):  # InitialSpawn / PlayerSpawn
                    got_spawn = True
                # 필요시 각 타입 처리:
                # 0x09 status, 0x0A tile rows, 0x0B recalc UV, 0x15/0x16 items, 0x17 NPCs, 0x39 balance, 0x38 named NPCs

            # $0C Player Spawn 전송 → 상태 Playing(10)
            spawn_packet = build_spawn_packet(
                profile,
                player_slot=player_slot,
                spawn_x=world_info.spawn_tile_x,
                spawn_y=world_info.spawn_tile_y,
                respawn_timer=0,
                deaths_pve=0,
                deaths_pvp=0,
                team=0,
                spawn_context=0,
            )
            send_raw(s, spawn_packet)

            # 이후 자유롭게 양방향 메시지 교환 가능
            # 예: 채팅 (NetModules/NetTextModule)
            send_chat(s, self.chat_text)
            print(f"Chat sent: {self.chat_text}")
            print(
                f"Tiles loaded: {state.tile_sections}, entities: items={len(state.items)} npcs={len(state.npcs)}"
            )

            # 간단한 이동 AI: 오른쪽으로만 이동
            if getattr(self, "explore", False):
                bot = ExplorationBot(
                    ExplorationConfig(
                        prefer_right=not getattr(self, "explore_left", False),
                        jump_if_blocked=True,
                    )
                )
                explore_loop(
                    s,
                    stream,
                    state,
                    profile,
                    player_slot=player_slot,
                    bot=bot,
                    interval=self.explore_interval,
                    sense_radius=self.explore_radius,
                    teleport_tracker=teleport_tracker,
                    inventory=inventory,
                    auto_pickup=self.auto_pickup,
                    pickup_radius=self.pickup_radius,
                )
            elif getattr(self, "move_right", False):
                start_x = world_info.spawn_tile_x * 16.0
                start_y = world_info.spawn_tile_y * 16.0
                time.sleep(0.5)
                x, y, vx, vy = move_right_loop(
                    s,
                    stream,
                    state,
                    profile,
                    player_slot=player_slot,
                    start_x=start_x,
                    start_y=start_y,
                    seconds=self.move_seconds,
                    speed=self.move_speed,
                    toggle=self.move_toggle,
                    toggle_interval=self.move_toggle_interval,
                    tile_frame_important=profile.tile_frame_important,
                    use_physics=self.use_physics,
                    teleport_tracker=teleport_tracker,
                    inventory=inventory,
                    auto_pickup=self.auto_pickup,
                    pickup_radius=self.pickup_radius,
                )
            else:
                x = world_info.spawn_tile_x * 16.0
                y = world_info.spawn_tile_y * 16.0

            if self.auto_pickup:
                try_pickup_reserved_items(
                    s,
                    state,
                    inventory,
                    profile,
                    player_slot,
                    (x, y),
                    radius_px=self.pickup_radius,
                )

            if getattr(self, "sense", False):
                tiles = state.get_nearby_tiles(x, y, radius_tiles=self.sense_radius)
                items = state.get_nearby_items(x, y)
                npcs = state.get_nearby_npcs(x, y)
                print(f"Sense: tiles={len(tiles)} items={len(items)} npcs={len(npcs)}")

            if getattr(self, "dump_state", False):
                dump_state(
                    state,
                    Path(self.dump_path),
                    player_slot=player_slot,
                    radius_tiles=self.dump_radius,
                )

            if getattr(self, "stay_connected", False):
                idle_loop(
                    s,
                    stream,
                    state,
                    profile,
                    player_slot=player_slot,
                    x=x,
                    y=y,
                    interval=self.idle_interval,
                    teleport_tracker=teleport_tracker,
                    inventory=inventory,
                    auto_pickup=self.auto_pickup,
                    pickup_radius=self.pickup_radius,
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--name", default="BotUser")
    parser.add_argument("--password", default=None)
    parser.add_argument("--chat", default="hello")
    parser.add_argument("--uuid", default=None)
    parser.add_argument("--profile", default="1449", help="e.g. 1449 or 1455")
    parser.add_argument(
        "--decomp-dir", default=None, help="Override decompiled source dir"
    )
    parser.add_argument(
        "--version-string", default=None, help="Override Hello version string"
    )
    parser.add_argument("--move-right", action="store_true")
    parser.add_argument("--move-seconds", type=float, default=5.0)
    parser.add_argument("--move-speed", type=float, default=64.0)
    parser.add_argument("--move-loop", action="store_true")
    parser.add_argument("--move-toggle", action="store_true")
    parser.add_argument("--move-toggle-interval", type=float, default=0.5)
    parser.add_argument("--explore", action="store_true")
    parser.add_argument("--explore-left", action="store_true")
    parser.add_argument("--explore-interval", type=float, default=0.1)
    parser.add_argument("--explore-radius", type=int, default=6)
    parser.add_argument(
        "--no-physics",
        action="store_true",
        help="Disable client-side physics (legacy linear movement).",
    )
    parser.add_argument("--stay", action="store_true")
    parser.add_argument("--idle-interval", type=float, default=0.25)
    parser.add_argument("--dump-state", action="store_true")
    parser.add_argument(
        "--dump-path", default="data/state_dump.json", help="Path for state dump JSON."
    )
    parser.add_argument("--dump-radius", type=int, default=10)
    parser.add_argument("--sense", action="store_true")
    parser.add_argument("--sense-radius", type=int, default=5)
    parser.add_argument(
        "--pickup-radius",
        type=float,
        default=42.0,
        help="Auto-pickup radius in pixels (-1 = no distance check). Default matches client grab range.",
    )
    parser.add_argument(
        "--no-pickup",
        action="store_true",
        help="Disable auto pickup for reserved items.",
    )
    parser.add_argument(
        "--inventory-count",
        type=int,
        default=59,
        help="Number of inventory slots to sync (default 59). Use 0 to skip.",
    )
    parser.add_argument(
        "--worldinfo-retry",
        type=float,
        default=2.0,
        help="Seconds between re-sending world info request (0 to disable).",
    )
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--debug-hex", action="store_true")
    parser.add_argument("--debug-tiles", action="store_true")
    parser.add_argument(
        "--debug-all",
        action="store_true",
        help="Log all packet types (except tiles unless --debug-tiles).",
    )
    args = parser.parse_args()

    DEBUG = args.debug
    DEBUG_HEX = args.debug_hex
    DEBUG_INCLUDE_TILES = args.debug_tiles
    DEBUG_ALL = args.debug_all

    repo_root = Path(__file__).resolve().parent
    profile = resolve_spec(
        args.profile, repo_root, args.decomp_dir, args.version_string
    )
    client = TerrariaClient(
        args.host,
        args.port,
        password=args.password,
        name=args.name,
        chat_text=args.chat,
        uuid=args.uuid,
        profile=profile,
        inventory_count=args.inventory_count,
        worldinfo_retry=args.worldinfo_retry,
        auto_pickup=not args.no_pickup,
        pickup_radius=None if args.pickup_radius < 0 else args.pickup_radius,
    )
    client.move_right = args.move_right
    client.move_seconds = 0.0 if args.move_loop else args.move_seconds
    client.move_speed = args.move_speed
    client.move_toggle = args.move_toggle
    client.move_toggle_interval = args.move_toggle_interval
    client.explore = args.explore
    client.explore_left = args.explore_left
    client.explore_interval = args.explore_interval
    client.explore_radius = args.explore_radius
    client.use_physics = not args.no_physics
    client.stay_connected = args.stay
    client.idle_interval = args.idle_interval
    client.dump_state = args.dump_state
    client.dump_path = args.dump_path
    client.dump_radius = args.dump_radius
    client.sense = args.sense
    client.sense_radius = args.sense_radius
    client.login()
