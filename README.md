# Terraria Research Bot Project

이 레포는 테라리아 서버 프로토콜을 분석하고, 프로그램적으로 제어 가능한 클라이언트를 만들어 연구용 에이전트를 구축하기 위한 작업 공간입니다.

## 목표
1) 바닐라 테라리아 서버 소스코드를 확보해 로컬에 저장
2) 서버 소스코드를 바탕으로 네트워크 프로토콜 분석
3) 분석 결과를 토대로 프로그램 제어 가능한 클라이언트(API) 제작
4) 최종적으로는 이 API를 사용해 프로그래밍적으로 테라리아를 클리어할 수 있는 에이전트 연구를 염두에 둠
   - (4번은 별도 스코프로 진행)

## 현재 구성
- `dumper.py`: 패킷/프로토콜 분석을 위한 덤퍼
- `server.py`: 공식 클라이언트의 요청에 적절히 응답하는 모킹 서버
- `server.log`, `dump.log`, `dump2.log`: 덤프 결과 로그
- `TerrariaSourceGetter`: 테라리아 소스코드 디컴파일 도구
- `1449/1.4.4.9-279-Windows-Server/`: 바닐라 테라리아 서버(1.4.4.9) 디컴파일 결과
- `1455/1.4.5.5-Windows-Server/`: 바닐라 테라리아 서버(1.4.5.5) 디컴파일 결과
- `tools/tsg_headless.cs`: 콘솔 환경에서 디컴파일을 자동 수행하는 보조 스크립트

## 진행 계획
1. **바닐라 테라리아 서버 소스코드 확보**
   - `TerrariaSourceGetter`를 사용해 1.4.4.9 서버를 디컴파일
   - 결과물을 `1449/` 폴더에 정리
2. **프로토콜 분석**
   - 디컴파일된 서버 코드를 바탕으로 패킷 구조/흐름을 분석
   - 기존 로그(`server.log`, `dump.log`)와 대조
3. **프로그램 제어 가능한 클라이언트(API) 제작**
   - 분석된 프로토콜 기반으로 안정적인 클라이언트 라이브러리 설계
   - 테스트 가능한 모킹/리플레이 환경 구축
4. **에이전트 연구(별도 스코프)**
   - 위 API를 활용해 자동 플레이/클리어 연구 진행

## 핵심 파일
- `1449/1.4.4.9-279-Windows-Server/Terraria/NetMessage.cs`: 패킷 송수신/프레이밍/전송 로직
- `1449/1.4.4.9-279-Windows-Server/Terraria/MessageBuffer.cs`: 패킷 파싱/핸들링
- `1449/1.4.4.9-279-Windows-Server/Terraria/Netplay.cs`: 네트워크 연결/세션 관리
- `1449/1.4.4.9-279-Windows-Server/Terraria/RemoteClient.cs`: 서버측 클라이언트 상태
- `1449/1.4.4.9-279-Windows-Server/Terraria.ID/MessageID.cs`: 메시지 ID 정의

## 문서
- `docs/protocol_overview.md`: 프로토콜 프레이밍/핸드셰이크 요약
- `docs/client_api.md`: 프로그램 제어 가능한 클라이언트 API 설계 초안
- `docs/versioning.md`: 멀티버전(1449/1455) 지원 구조 및 스펙

## 멀티버전 지원
이 프로젝트는 `protocol/specs/*.json` 스펙을 통해 버전별 차이를 분리합니다.
- `protocol/specs/1449.json`
- `protocol/specs/1455.json`

실행 시 `--profile`로 버전을 선택합니다.
```bash
python main.py --profile 1449 --move-right --chat "hello"
python main.py --profile 1455 --move-right --chat "hello"
```

## 디컴파일 재현 (선택)
```bash
# build (mono 필요)
mcs -r:TerrariaSourceGetter/TerrariaSourceGetter/bin/Release/net462/ICSharpCode.Decompiler.dll \
    -r:TerrariaSourceGetter/TerrariaSourceGetter/bin/Release/net462/Mono.Cecil.dll \
    -r:TerrariaSourceGetter/TerrariaSourceGetter/bin/Release/net462/netstandard.dll \
    -r:TerrariaSourceGetter/TerrariaSourceGetter/bin/Release/net462/System.Reflection.Metadata.dll \
    -r:TerrariaSourceGetter/TerrariaSourceGetter/bin/Release/net462/System.Collections.Immutable.dll \
    -out:tools/tsg_headless.exe tools/tsg_headless.cs

# run
MONO_PATH=TerrariaSourceGetter/TerrariaSourceGetter/bin/Release/net462 \\
  mono tools/tsg_headless.exe 1449/Windows/TerrariaServer.exe 1449/1.4.4.9-279-Windows-Server
```

## 참고
- 이 프로젝트는 연구/학습 목적이며, 서버-클라이언트 통신 구조를 이해하고 재현하는 것을 목표로 합니다.
