import can
import socket
import select
import os
from datetime import datetime
from collections import deque

# === Configuration via environment variables ===
CAN_IFACE = os.getenv("CAN_IFACE", "can0")
TCP_PORT = int(os.getenv("TCP_PORT", "2223"))

def format_time():
    """Return current UTC time formatted as hh:mm:ss.ddd"""
    now = datetime.utcnow()
    return now.strftime("%H:%M:%S.%f")[:12]

def parse_tx_line(line):
    """Parse a TX line from a client: CAN ID followed by hex bytes"""
    parts = line.strip().split()
    if len(parts) < 2:
        return None, None
    try:
        can_id = int(parts[0], 16)
        data = bytes(int(b, 16) for b in parts[1:])
        return can_id, data
    except ValueError:
        return None, None

class Client:
    """Represents a TCP client with an outgoing send buffer"""
    def __init__(self, sock):
        self.sock = sock
        self.sock.setblocking(False)
        self.send_buffer = deque()

    def enqueue(self, data):
        """Append data to the send buffer"""
        self.send_buffer.append(data)

    def flush(self):
        """Non-blocking flush of the send buffer"""
        while self.send_buffer:
            data = self.send_buffer[0]
            try:
                sent = self.sock.send(data)
                if sent < len(data):
                    # Keep the unsent remainder at the front of the buffer
                    self.send_buffer[0] = data[sent:]
                    return
                else:
                    self.send_buffer.popleft()
            except BlockingIOError:
                return
            except (ConnectionResetError, BrokenPipeError):
                raise

def main():
    bus = can.interface.Bus(channel=CAN_IFACE, interface="socketcan")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("", TCP_PORT))
    server.listen(5)
    server.setblocking(False)

    clients = []

    print(f"[RAW ASCII] Listening on TCP {TCP_PORT}")

    try:
        while True:
            # Build socket lists for select()
            read_sockets = [server] + [c.sock for c in clients]
            write_sockets = [c.sock for c in clients if c.send_buffer]

            ready_to_read, ready_to_write, _ = select.select(read_sockets, write_sockets, [], 0.01)

            # Accept new client connections
            if server in ready_to_read:
                conn, addr = server.accept()
                clients.append(Client(conn))
                print(f"Client connected: {addr}")

            # Read data from connected clients
            for client in clients[:]:
                if client.sock in ready_to_read:
                    try:
                        data = client.sock.recv(1024)
                        if not data:
                            raise ConnectionResetError()
                        # Process each TX line from the client
                        for line in data.decode("ascii").split("\n"):
                            line = line.strip()
                            if not line:
                                continue
                            can_id, payload = parse_tx_line(line)
                            if can_id is not None:
                                # Forward the message onto the CAN bus
                                msg_out = can.Message(arbitration_id=can_id,
                                                      data=payload,
                                                      is_extended_id=True)
                                bus.send(msg_out)

                                # Echo confirmation (direction "T") back to all clients
                                ts = format_time()
                                direction = "T"
                                can_id_hex = f"{can_id:08X}"
                                data_hex = " ".join(f"{b:02X}" for b in payload)
                                confirm = f"{ts} {direction} {can_id_hex} {data_hex}\r\n".encode("ascii")
                                for c in clients:
                                    c.enqueue(confirm)

                    except (ConnectionResetError, BrokenPipeError):
                        clients.remove(client)
                        client.sock.close()

            # Non-blocking flush of outgoing buffers
            for client in clients[:]:
                if client.sock in ready_to_write:
                    try:
                        client.flush()
                    except:
                        clients.remove(client)
                        client.sock.close()

            # Read from the CAN bus and broadcast to all clients
            msg = bus.recv(timeout=0.001)
            if msg:
                ts = format_time()
                direction = "R"
                can_id_hex = f"{msg.arbitration_id:08X}"
                data_hex = " ".join(f"{b:02X}" for b in msg.data[:msg.dlc])
                line = f"{ts} {direction} {can_id_hex} {data_hex}\r\n".encode("ascii")
                for c in clients:
                    c.enqueue(line)

    except KeyboardInterrupt:
        print("Server stopped by user")
    finally:
        for c in clients:
            c.sock.close()
        server.close()

if __name__ == "__main__":
    main()
