# proxy.py
import io
import asyncio, binascii, datetime, sys

import construct

from terraria_construct import payload_structs

UP_HOST, UP_PORT = "127.0.0.1", 7778  # 실제 서버
LISTEN_HOST, LISTEN_PORT = "127.0.0.1", 7777  # 클라이언트가 접속할 포트

construct.setGlobalPrintFullStrings(True)
# construct.setGlobalPrintLimit(0)


def read_7bit_int(stream: io.BytesIO) -> int:
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


def read_dotnet_string(stream: io.BytesIO) -> str:
    length = read_7bit_int(stream)
    data = stream.read(length)
    return data.decode("utf-8", errors="replace")


class PacketDumper:
    def __init__(self, prefix):
        self.prefix = prefix
        self.buf = bytearray()

    def feed(self, data: bytes):
        """데이터를 누적하고 완성된 패킷 단위로 로그 출력"""
        self.buf.extend(data)
        while True:
            # 최소 길이(2바이트 length)는 있어야 함
            if len(self.buf) < 2:
                return
            length = int.from_bytes(self.buf[:2], "little")
            need = length
            print(f"{length=}{need=}")
            if len(self.buf) < need:
                return  # 아직 덜 들어옴

            packet = bytes(self.buf[:length])
            del self.buf[:length]

            msg_type = packet[2]
            payload = packet[3:]

            assert len(payload) == length - 3

            parsed = None
            if msg_type in payload_structs:
                try:
                    stream = io.BytesIO(payload)
                    parsed = payload_structs[msg_type].parse_stream(stream)
                    if stream.tell() != len(payload):
                        print(f"!! leftover {len(payload)-stream.tell()} bytes")
                        print(f"raw: {binascii.hexlify(stream.getvalue()).decode()}")

                    # NetModules (0x52) - decode NetTextModule (id=1)
                    if msg_type == 0x52 and hasattr(parsed, "module_id"):
                        module_id = parsed.module_id
                        if module_id == 1:
                            try:
                                mstream = io.BytesIO(parsed.module_payload)
                                command = read_dotnet_string(mstream)
                                text = read_dotnet_string(mstream)
                                parsed = {
                                    "module_id": module_id,
                                    "module": "NetTextModule",
                                    "command": command,
                                    "text": text,
                                }
                            except Exception as e:
                                parsed = f"<nettext parse error: {e}>"
                except Exception as e:
                    parsed = f"<parse error: {e}>"
            else:
                parsed = f'<unknown type: {msg_type}>; "{payload}"'

            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            if msg_type != 0x05:
                print(f"[{ts}] {self.prefix} type=0x{msg_type:02X} len={length}")
                print(f"raw: {binascii.hexlify(packet).decode()} ({len(packet)} bytes)")
                if parsed is not None:
                    print(f"parsed: {parsed}")
                print(flush=True)


async def pipe(reader, writer, prefix):
    dumper = PacketDumper(prefix)
    while True:
        chunk = await reader.read(65536)
        if not chunk:
            writer.close()
            await writer.wait_closed()
            break
        dumper.feed(chunk)
        writer.write(chunk)
        await writer.drain()


async def handle(client_r, client_w):
    up_r, up_w = await asyncio.open_connection(UP_HOST, UP_PORT)
    asyncio.create_task(pipe(client_r, up_w, "C→S"))
    await pipe(up_r, client_w, "S→C")


async def main():
    srv = await asyncio.start_server(handle, LISTEN_HOST, LISTEN_PORT)
    addrs = ", ".join(str(s.getsockname()) for s in srv.sockets)
    print(f"listening on {addrs}", flush=True)
    async with srv:
        await srv.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
