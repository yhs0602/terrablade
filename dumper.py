# proxy.py
import asyncio, binascii, datetime, sys

from terraria_construct import payload_structs

UP_HOST, UP_PORT = "127.0.0.1", 7778  # 실제 서버
LISTEN_HOST, LISTEN_PORT = "127.0.0.1", 7777  # 클라이언트가 접속할 포트


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
            need = length - 2
            print(f"{length=}{need=}")
            if len(self.buf) < need:
                return  # 아직 덜 들어옴

            packet = bytes(self.buf[:length])
            del self.buf[:length]

            msg_type = packet[2]
            payload = packet[3:]

            parsed = None
            if msg_type in payload_structs:
                try:
                    parsed = payload_structs[msg_type].parse(payload)
                except Exception as e:
                    parsed = f"<parse error: {e}>"
            else:
                parsed = f'<unknown type: {msg_type}>; "{payload}"'

            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"[{ts}] {self.prefix} type=0x{msg_type:02X} len={length}")
            print(f"raw: {binascii.hexlify(packet).decode()}")
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
