import socket

from main import recv_message, send


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("0.0.0.0", 7779))
        s.listen()
        while True:
            conn, addr = s.accept()
            with conn:
                print(f"Connected by {addr}")
                while True:
                    msg = recv_message(conn)
                    print(f"Received: {msg}")
                    if msg.type == 0x01:
                        send(conn, 0x03, {"player_slot": 0})
                    if msg.type == 0x06:
                        send(conn, 82, {"network_something": [0, 0, 0, 0]})


if __name__ == "__main__":
    main()
