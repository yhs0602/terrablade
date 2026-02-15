# 클라이언트 API 설계 초안

## 목표
- 테라리아 서버와 **안정적으로 연결/동기화**
- 패킷 단위로 **재현 가능하고 추적 가능한 통신**
- 연구 목적의 **프로그램 제어 가능한 고수준 API** 제공

## 설계 원칙
- 프레이밍(길이/타입)과 페이로드 파싱을 분리
- 패킷 핸들러는 순수하게 유지하고, 상태 변경은 별도 모듈에서 수행
- 로그/리플레이로 **세션 재현** 가능

## 모듈 구성 (제안)
- `client/transport.py`
  - TCP 연결, 재접속, 타임아웃 처리
- `client/framer.py`
  - `length(uint16)` + `type(byte)` + `payload` 프레이밍/언프레이밍
- `client/codec.py`
  - `terraria_construct.py`를 사용한 페이로드 인코딩/디코딩
- `client/dispatcher.py`
  - `messageType -> handler` 매핑, 이벤트 발행
- `state/world.py`, `state/player.py`, `state/entities.py`
  - 월드/플레이어/엔티티 상태 캐시
- `api/client.py`
  - 고수준 API (connect/handshake/move/chat 등)

## 핸드셰이크 플로우 (서버 기준)
1. `Hello(1)` : 버전 문자열 전송 (`"Terraria279"`)
2. 서버 응답:
   - `PlayerInfo(3)` 또는 `RequestPassword(37)`
3. 비밀번호 응답 시 `SendPassword(38)`
4. `SyncPlayer(4)` 외형/이름 전송
5. `Unknown68(68)` : UUID 문자열 전송
6. `PlayerLifeMana(16/42)` + `PlayerBuffs(50)`
7. `SyncEquipment(5)` 인벤토리 전송
8. `RequestWorldData(6)` → 서버 `WorldData(7)`
9. 타일/월드 섹션 수신 후 `PlayerSpawn(12)` 전송

## API 제안 (Python)
```python
from api.client import TerrariaClient, PlayerProfile

profile = PlayerProfile(
    name="Lalala",
    skin_variant=4,
    hair=22,
    colors={...},
    difficulty_flags=0,
)

client = TerrariaClient("127.0.0.1", 7777)
client.connect()
client.handshake(profile, uuid="...", password=None)
client.request_world()
client.spawn()

client.move(left=True, right=False, jump=False)
client.chat("hello world")
```

### 핵심 메서드
- `connect()` / `close()`
- `handshake(profile, uuid, password=None)`
- `request_world()` / `request_tile_section(x, y)`
- `spawn()`
- `move(...)` / `use_item(...)` / `place_tile(...)`
- `chat(text)`

### 이벤트 콜백
- `on_world_data(world)`
- `on_tile_section(section)`
- `on_player_update(player)`
- `on_chat(msg)`
- `on_disconnect(reason)`

## 테스트 전략
- `server.py`(모킹 서버) 기반의 핸드셰이크 재현 테스트
- `dump.log` 리플레이 기반 회귀 테스트
- 패킷 파서/빌더 round-trip 테스트

## 구현 메모
- 패킷 프레이밍은 **2바이트 length** 기준 (서버 소스와 일치)
- `terraria_construct.py`의 문서/파서와 불일치 여부를 점검 필요
