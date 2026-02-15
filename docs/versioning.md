# 멀티버전 지원 (1449/1455)

## 개요
버전별 차이를 코드 분기 없이 관리하기 위해, 스펙 파일을 통해 설정을 분리합니다.

## 스펙 구조
- 위치: `protocol/specs/*.json`
- 예시:
  - `protocol/specs/1449.json`
  - `protocol/specs/1455.json`

각 스펙에는 다음 정보가 들어갑니다.
- `profile`: 프로파일 이름 (예: `1449`, `1455`)
- `base_dir`: 디컴파일 베이스 디렉터리 (예: `1449`)
- `decomp_dir`: 디컴파일 산출물 폴더
- `version_string`: `Hello(1)` 패킷에 사용되는 버전 문자열
- `message_formats`: 메시지 포맷 버전(예: player_spawn/player_controls)

## 로더
- `protocol/specs.py`의 `resolve_spec()`
- 역할:
  - 스펙 로드
  - 디컴파일 위치 확인
  - `NetMessage.cs`에서 버전 문자열 자동 추론
  - `tileFrameImportant` 캐시 로드/생성

## tileFrameImportant 캐시
- 경로: `data/tile_frame_important_<profile>.txt`
- 디컴파일된 `Main.cs`에서 자동 추출됨
- 타일 섹션(0x0A) 파싱 안정화에 사용

## 실행 예시
```bash
python main.py --profile 1449 --move-right --chat "hello"
python main.py --profile 1455 --move-right --chat "hello"
```

디컴파일 위치가 다르면:
```bash
python main.py --profile 1455 --decomp-dir /path/to/decompiled
```

버전 문자열 추론이 실패하면:
```bash
python main.py --profile 1455 --version-string TerrariaXXX
```
