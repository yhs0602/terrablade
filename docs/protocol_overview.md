# 프로토콜 개요 (Terraria 1.4.4.9 서버)

## 패킷 프레이밍
- 패킷은 `length(uint16, little-endian)` + `messageType(byte)` + `payload`로 구성됩니다.
- `length`는 **전체 패킷 길이(2바이트 길이 필드 포함)** 입니다.
- 수신은 `NetMessage.CheckBytes`가 버퍼에서 길이를 읽고, `MessageBuffer.GetData`로 전달합니다.
- 송신은 `NetMessage.SendData`가 `length`를 계산해 패킷 앞에 씁니다.
- 길이 상한은 `ushort`(최대 65535)이며, 내부 버퍼는 `MessageBuffer.readBufferMax = 131070` 입니다.

참조:
- `1449/1.4.4.9-279-Windows-Server/Terraria/NetMessage.cs`
- `1449/1.4.4.9-279-Windows-Server/Terraria/MessageBuffer.cs`

## 핸드셰이크/상태 흐름 (서버 기준)
- 서버는 `State == 0`일 때 **Hello(1)** 패킷만 허용합니다.
- `Hello(1)`의 버전 문자열이 `Terraria279`와 일치하면:
  - 비밀번호가 없으면 `State = 1`로 전환하고 **PlayerInfo(3)** 를 보냅니다.
  - 비밀번호가 있으면 **RequestPassword(37)** 를 보냅니다.
- 비밀번호 사용 시 클라이언트는 **SendPassword(38)** 로 응답해야 합니다.
- 초기 상태에서 허용되는 예외 타입: 16, 42, 50, 68, 93, 147 등(서버 코드에서 예외 처리).

참조:
- `1449/1.4.4.9-279-Windows-Server/Terraria/MessageBuffer.cs`
- `1449/1.4.4.9-279-Windows-Server/Terraria/NetMessage.cs`

## 로그 기반 초기 시퀀스 (dump.log / server.log)
다음 순서는 실제 덤프에서 반복적으로 관측된 초기 연결 흐름입니다.
1. C→S **Hello(1)** : `"Terraria279"`
2. S→C **PlayerInfo(3)** : `player_slot`, `bool(false)`
3. C→S **SyncPlayer(4)** : 외형/이름/색상 등
4. C→S **Unknown68(68)** : UUID 문자열 (서버는 문자열을 읽고 무시)
5. C→S **PlayerLifeMana(16)** / **Unknown42(42)** : 체력/마나
6. C→S **PlayerBuffs(50)**
7. C→S **SyncEquipment(5)** : 인벤토리/장비 반복
8. C→S **RequestWorldData(6)**
9. S→C **WorldData(7)** : 월드 메타
10. S→C **StatusText(9)** → **TileSection(10)** 등 월드/타일 데이터

참조:
- `server.log`
- `dump.log`

## 메시지 ID 힌트 (중요한 일부)
- `1` Hello
- `2` Kick
- `3` PlayerInfo (서버가 슬롯 전달)
- `4` SyncPlayer (플레이어 외형)
- `5` SyncEquipment (인벤토리/장비)
- `6` RequestWorldData
- `7` WorldData
- `9` StatusTextSize
- `10` TileSection
- `16` PlayerLifeMana
- `42` Player Mana (server send/receive)
- `50` PlayerBuffs
- `68` Unknown68 (로그상 UUID 문자열)
- `147` Loadout

전체 ID 정의는 아래 파일 참고:
- `1449/1.4.4.9-279-Windows-Server/Terraria.ID/MessageID.cs`

## 관련 소스 위치
- `1449/1.4.4.9-279-Windows-Server/Terraria/NetMessage.cs`
- `1449/1.4.4.9-279-Windows-Server/Terraria/MessageBuffer.cs`
- `1449/1.4.4.9-279-Windows-Server/Terraria/Netplay.cs`
- `1449/1.4.4.9-279-Windows-Server/Terraria/RemoteClient.cs`
