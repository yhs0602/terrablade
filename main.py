import socket, struct
from terraria_construct import payload_structs, TerrariaMessage

HOST, PORT = "127.0.0.1", 7778


def build_packet(msg_type: int, payload_dict=None) -> bytes:
    payload_dict = payload_dict or {}
    payload = payload_structs[msg_type].build(payload_dict)
    length = 1 + len(payload)  # type + payload (UInt16)
    return struct.pack("<HB", length, msg_type) + payload


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


def recv_message(sock):
    # read length, then rest
    length_bytes = recv_exact(sock, 2)
    (length,) = struct.unpack("<h", length_bytes)
    body = recv_exact(sock, length - 2)  #  - 2  # includes 1-byte type
    packet = length_bytes + body  # TerrariaMessage expects length+type+payload
    print(f"Packet: {packet} with length {length}")
    return TerrariaMessage.parse(packet)


def send(sock, msg_type, payload=None):
    packet = build_packet(msg_type, payload)
    # print(f"Sending packet: {msg_type} {payload}")
    # print(f"Packet: {packet}")
    sock.sendall(packet)


def login():
    with socket.create_connection((HOST, PORT)) as s:
        # $01 Connect Request: "Terraria<version>"
        send(
            s, 0x01, {"version": "Terraria279"}
        )  # 예시 버전 문자열 (https://seancode.com/terrafirma/net.html)
        print("Connected to server")

        # 응답: $03 승인 or $25 비번요구 or $02 차단
        msg = recv_message(s)
        if msg.type == 0x25:  # Request Password
            print("Request Password")
            send(s, 0x26, {"password": "password"})  # $26 Login with Password
            msg = recv_message(
                s
            )  # 다시 $03 승인 or $02 실패 (https://seancode.com/terrafirma/net.html)
        if msg.type == 0x02:
            print("Banned or error")
            raise SystemExit(f"banned or error: {msg.payload.error}")
        assert (
            msg.type == 0x03
        )  # Connection Approved, 이제 상태 Initializing(1) (https://seancode.com/terrafirma/net.html)
        print(f"Connection Approved: slot={msg.payload.player_slot}")

        # $04 Player Appearance
        send(
            s,
            0x04,
            {
                "player_id": 0,
                "skin_variant": 4,
                "hair": 22,
                "name": "Lalala",
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
        send(s, 0x44, {"client_uuid": "09e9b400-f2f1-461f-b5b3-8d8bb649a94b"})

        # $10 Life, $2A Mana, $32 Buffs (응답 기다리지 않고 전송) (https://seancode.com/terrafirma/net.html)
        send(s, 0x10, {"player_slot": 0, "current_health": 500, "max_health": 500})
        send(s, 0x2A, {"player_slot": 0, "mana": 200, "max_mana": 200})
        send(s, 0x32, {"player_slot": 0, "buffs": [0] * 22})
        print("Life, Mana, Buffs")

        # Don't know what this is 0x93
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
        print("World Info Request")
        # 서버는 문제 있으면 $02로 킥. 정상이면 $07 응답 후 Initialized(2)로 승격 (https://seancode.com/terrafirma/net.html)
        world_info = None
        while True:
            msg = recv_message(s)
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
            {"spawn_x": world_info.spawn_tile_x, "spawn_y": world_info.spawn_tile_y},
        )

        # 서버는 $09, 여러 개의 $0A, $0B, $15, $16, $17, $31, $39, $38 순으로 보냄 (https://seancode.com/terrafirma/net.html)
        got_spawn = False
        while not got_spawn:
            msg = recv_message(s)
            if msg.type == 0x31:  # Spawn 지시
                got_spawn = True
            # 필요시 각 타입 처리:
            # 0x09 status, 0x0A tile rows, 0x0B recalc UV, 0x15/0x16 items, 0x17 NPCs, 0x39 balance, 0x38 named NPCs

        # $0C Player Spawn 전송 → 상태 Playing(10) (https://seancode.com/terrafirma/net.html)
        send(
            s,
            0x0C,
            {
                "player_slot": 0,
                "spawn_x": world_info.spawn_tile_x,
                "spawn_y": world_info.spawn_tile_y,
            },
        )

        # 이후 자유롭게 양방향 메시지 교환 가능
        # 예: 채팅
        # send(s, 0x19, {"player_slot": 0, "text_color": {"r":255,"g":255,"b":255}, "chat_text": "hello"})


if __name__ == "__main__":
    login()
