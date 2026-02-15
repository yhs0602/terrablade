import socket, struct
import random
import argparse
import time
import select
import zlib
from pathlib import Path
from typing import Optional
from terraria_construct import payload_structs, TerrariaMessage
from protocol import VersionSpec, resolve_spec

HOST, PORT = "127.0.0.1", 7777
NET_TEXT_MODULE_ID = 1  # NetworkInitializer: NetLiquidModule(0), NetTextModule(1)
_WARNED_FRAME_IMPORTANT = False


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

    def read_string(self) -> str:
        return read_dotnet_string(self)




def parse_tile_section(payload: bytes, tile_frame_important: set[int]):
    # 0x0A payload is deflate-compressed
    global _WARNED_FRAME_IMPORTANT
    if not tile_frame_important:
        if not _WARNED_FRAME_IMPORTANT:
            print("Warning: tileFrameImportant list missing; skipping tile parse (store no tiles).")
            _WARNED_FRAME_IMPORTANT = True
        data = zlib.decompress(payload, wbits=-15)
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
    data = zlib.decompress(payload, wbits=-15)
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
        return TerrariaMessage.parse(packet)

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

    def update_npc(self, npc):
        self.npcs[npc.npc_slot] = npc

    def update_player_pos(self, slot, x, y):
        self.player_pos[slot] = (x, y)


def send(sock, msg_type, payload=None):
    packet = build_packet(msg_type, payload)
    # print(f"Sending packet: {msg_type} {payload}")
    # print(f"Packet: {packet}")
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
    spawn_context: int = 0,
) -> bytes:
    fmt = profile.message_formats.get("player_spawn", "v1")
    if fmt == "v0":
        payload = struct.pack("<Bii", player_slot, spawn_x, spawn_y)
        return build_raw_packet(0x0C, payload)

    # v1 (1.4.4+)
    payload = struct.pack(
        "<BhhihhB",
        player_slot,
        spawn_x,
        spawn_y,
        respawn_timer,
        deaths_pve,
        deaths_pvp,
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
):
    tick = 0.05
    end_time = time.time() + seconds if seconds > 0 else None
    x = start_x
    y = start_y
    moving = True
    next_toggle = time.time() + toggle_interval

    while True:
        now = time.time()
        if end_time is not None and now >= end_time:
            break

        # update last known position from server if available
        for msg in stream.poll_messages():
            if msg.type == 0x0A:
                try:
                    section = parse_tile_section(
                        msg.payload.tile_data, tile_frame_important
                    )
                    state.update_tile_section(section)
                except Exception as e:
                    print(f"Tile section parse failed: {e}")
            elif msg.type == 0x15:
                state.update_item(msg.payload)
            elif msg.type == 0x16:
                state.update_item_owner(msg.payload.item_slot, msg.payload.owner)
            elif msg.type == 0x17:
                state.update_npc(msg.payload)
            elif msg.type == 0x0D and msg.payload.player_slot == player_slot:
                x = msg.payload.position_x
                y = msg.payload.position_y
                state.update_player_pos(player_slot, x, y)

        if toggle and now >= next_toggle:
            moving = not moving
            next_toggle = now + toggle_interval

        if moving:
            x += speed * tick

        packet = build_player_controls_packet(
            profile,
            player_slot=player_slot,
            x=x,
            y=y,
            control_right=moving,
            direction=1,
            selected_item=0,
            send_velocity=moving,
            vel_x=speed if moving else 0.0,
            vel_y=0.0,
        )
        sock.sendall(packet)
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
    sock.sendall(packet)


def send_chat(sock, text: str):
    # NetTextModule client message: module_id + ChatMessage(CommandId + Text)
    # ChatCommandId for SayChatCommand is "Say".
    payload = write_dotnet_string("Say") + write_dotnet_string(text)
    packet = build_netmodule_packet(NET_TEXT_MODULE_ID, payload)
    sock.sendall(packet)


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
    ):
        self.host = host
        self.port = port
        self.password = password
        self.name = name
        self.chat_text = chat_text
        self.uuid = uuid or f"{random.randrange(16**8):08x}-dead-beef-cafe-{random.randrange(16**12):012x}"
        self.profile = profile

    def login(self):
        with socket.create_connection((self.host, self.port)) as s:
            stream = PacketStream(s)
            state = WorldState()
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
            print(f"Connection Approved: slot={msg.payload.player_slot}")

            # $04 Player Appearance
            send(
                s,
                0x04,
                {
                    "player_id": 0,
                    "skin_variant": 4,
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
                },
            )
            print("Player Appearance")

            # send client uuid
            send(s, 0x44, {"client_uuid": self.uuid})

            # $10 Life, $2A Mana, $32 Buffs (응답 기다리지 않고 전송) (https://seancode.com/terrafirma/net.html)
            send(s, 0x10, {"player_slot": 0, "current_health": 500, "max_health": 500})
            send(s, 0x2A, {"player_slot": 0, "mana": 200, "max_mana": 200})
            send(s, 0x32, {"player_slot": 0, "buffs": [0] * 44})
            print("Life, Mana, Buffs")

            # Loadout (0x93 == 147)
            send(s, 0x93, {"loadout": [0, 0, 0, 0]})

            # 인벤토리 슬롯 0..72, $05 반복 전송 (https://seancode.com/terrafirma/net.html)
            for inv in range(350):
                send(
                    s,
                    0x05,
                    {
                        "player_slot": 0,
                        "inventory_slot": inv,
                        "stack": 0,
                        "prefix_id": 0,
                        "item_id": 0,  # 빈 슬롯
                    },
                )

            print("Sent Inventory")
            # $06 World Info 요청 (https://seancode.com/terrafirma/net.html)
            send(s, 0x06)
            print("World Info Requested")
            # 서버는 문제 있으면 $02로 킥. 정상이면 $07 응답 후 Initialized(2)로 승격 (https://seancode.com/terrafirma/net.html)
            world_info = None
            while True:
                msg = stream.recv_message()
                if msg.type == 0x02:
                    raise SystemExit(f"error: {msg.payload.error}")
                if msg.type == 0x07:
                    world_info = msg.payload
                    break
                if msg.type != 0x52:
                    print(f"World Info Other response: {msg}")
            print(f"World Info Response: {world_info}")
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
                            msg.payload.tile_data, profile.tile_frame_important
                        )
                        state.update_tile_section(section)
                    except Exception as e:
                        print(f"Tile section parse failed: {e}")
                elif msg.type == 0x15:
                    state.update_item(msg.payload)
                elif msg.type == 0x16:
                    state.update_item_owner(msg.payload.item_slot, msg.payload.owner)
                elif msg.type == 0x17:
                    state.update_npc(msg.payload)
                elif msg.type == 0x0D:
                    state.update_player_pos(
                        msg.payload.player_slot,
                        msg.payload.position_x,
                        msg.payload.position_y,
                    )
                elif msg.type in (0x31, 0x0C):  # InitialSpawn / PlayerSpawn
                    got_spawn = True
                # 필요시 각 타입 처리:
                # 0x09 status, 0x0A tile rows, 0x0B recalc UV, 0x15/0x16 items, 0x17 NPCs, 0x39 balance, 0x38 named NPCs

            # $0C Player Spawn 전송 → 상태 Playing(10)
            spawn_packet = build_spawn_packet(
                profile,
                player_slot=0,
                spawn_x=world_info.spawn_tile_x,
                spawn_y=world_info.spawn_tile_y,
                respawn_timer=0,
                deaths_pve=0,
                deaths_pvp=0,
                spawn_context=0,
            )
            s.sendall(spawn_packet)

            # 이후 자유롭게 양방향 메시지 교환 가능
            # 예: 채팅 (NetModules/NetTextModule)
            send_chat(s, self.chat_text)
            print(f"Chat sent: {self.chat_text}")
            print(f"Tiles loaded: {state.tile_sections}, entities: items={len(state.items)} npcs={len(state.npcs)}")

            # 간단한 이동 AI: 오른쪽으로만 이동
            if getattr(self, "move_right", False):
                start_x = world_info.spawn_tile_x * 16.0
                start_y = world_info.spawn_tile_y * 16.0
                time.sleep(0.5)
                move_right_loop(
                    s,
                    stream,
                    state,
                    profile,
                    player_slot=0,
                    start_x=start_x,
                    start_y=start_y,
                    seconds=self.move_seconds,
                    speed=self.move_speed,
                    toggle=self.move_toggle,
                    toggle_interval=self.move_toggle_interval,
                    tile_frame_important=profile.tile_frame_important,
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
    parser.add_argument("--decomp-dir", default=None, help="Override decompiled source dir")
    parser.add_argument("--version-string", default=None, help="Override Hello version string")
    parser.add_argument("--move-right", action="store_true")
    parser.add_argument("--move-seconds", type=float, default=5.0)
    parser.add_argument("--move-speed", type=float, default=64.0)
    parser.add_argument("--move-loop", action="store_true")
    parser.add_argument("--move-toggle", action="store_true")
    parser.add_argument("--move-toggle-interval", type=float, default=0.5)
    args = parser.parse_args()

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
    )
    client.move_right = args.move_right
    client.move_seconds = 0.0 if args.move_loop else args.move_seconds
    client.move_speed = args.move_speed
    client.move_toggle = args.move_toggle
    client.move_toggle_interval = args.move_toggle_interval
    client.login()
