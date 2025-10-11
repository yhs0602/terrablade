import socket, struct
from terraria_construct import payload_structs, TerrariaMessage

HOST, PORT = "127.0.0.1", 7777


def build_packet(msg_type: int, payload_dict=None) -> bytes:
    payload_dict = payload_dict or {}
    payload = payload_structs[msg_type].build(payload_dict)
    length = 1 + len(payload)  # type(1) + payload
    return struct.pack("<IB", length, msg_type) + payload


def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("disconnected")
        buf += chunk
    return buf


def recv_message(sock):
    # read length, then rest
    length_bytes = recv_exact(sock, 4)
    (length,) = struct.unpack("<i", length_bytes)
    body = recv_exact(sock, length)  # includes 1-byte type
    packet = length_bytes + body  # TerrariaMessage expects length+type+payload
    return TerrariaMessage.parse(packet)


def send(sock, msg_type, payload=None):
    packet = build_packet(msg_type, payload)
    print(f"Sending packet: {msg_type} {payload}")
    print(f"Packet: {packet}")
    sock.sendall(packet)


def login():
    with socket.create_connection((HOST, PORT)) as s:
        # $01 Connect Request: "Terraria<version>"
        send(
            s, 0x01, {"version": "Terraria1449"}
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
        print("Connection Approved")

        # $04 Player Appearance
        send(
            s,
            0x04,
            {
                "player_slot": 0,
                "hair_style": 0,
                "gender": 0,
                "hair_color": {"r": 0, "g": 0, "b": 0},
                "skin_color": {"r": 255, "g": 224, "b": 189},
                "eye_color": {"r": 64, "g": 64, "b": 64},
                "shirt_color": {"r": 100, "g": 100, "b": 100},
                "undershirt_color": {"r": 100, "g": 100, "b": 100},
                "pants_color": {"r": 100, "g": 100, "b": 100},
                "shoe_color": {"r": 50, "g": 50, "b": 50},
                "difficulty": 0,
                "player_name": "Player",
            },
        )

        # $10 Life, $2A Mana, $32 Buffs (응답 기다리지 않고 전송) (https://seancode.com/terrafirma/net.html)
        send(s, 0x10, {"player_slot": 0, "current_health": 100, "max_health": 100})
        send(s, 0x2A, {"player_slot": 0, "mana": 20, "max_mana": 20})
        send(s, 0x32, {"player_slot": 0, "buffs": [0] * 10})

        # 인벤토리 슬롯 0..72, $05 반복 전송 (https://seancode.com/terrafirma/net.html)
        for inv in range(73):
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

        # $06 World Info 요청 (https://seancode.com/terrafirma/net.html)
        send(s, 0x06)

        # 서버는 문제 있으면 $02로 킥. 정상이면 $07 응답 후 Initialized(2)로 승격 (https://seancode.com/terrafirma/net.html)
        world_info = None
        while True:
            msg = recv_message(s)
            if msg.type == 0x02:
                raise SystemExit(f"error: {msg.payload.error}")
            if msg.type == 0x07:
                world_info = msg.payload
                break

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
