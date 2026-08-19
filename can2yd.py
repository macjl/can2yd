import socket
import select
import os
import time
from datetime import datetime, timezone
from collections import deque

# === Configuration via environment variables ===
CAN_IFACE = os.getenv("CAN_IFACE", "can0")
TCP_PORT = int(os.getenv("TCP_PORT", "2223"))
TCP_HOST = os.getenv("TCP_HOST")
MODE = os.getenv("MODE", os.getenv("CAN2YD_MODE", "server")).lower()
RECONNECT_DELAY = float(os.getenv("RECONNECT_DELAY", "5"))
DEFAULT_LISTEN_HOSTS = ("::", "0.0.0.0")
CAN_DRAIN_LIMIT = 256
CAN_TX_BATCH = 64
CAN_TX_QUEUE_LIMIT = int(os.getenv("CAN_TX_QUEUE_LIMIT", "1024"))
CAN_TX_ERROR_LOG_INTERVAL = 5

def open_can_bus():
    """Open the configured SocketCAN bus."""
    import can

    return can.interface.Bus(channel=CAN_IFACE, interface="socketcan")

def make_can_message(can_id, payload):
    """Create a python-can message for an extended 29-bit CAN id."""
    import can

    return can.Message(arbitration_id=can_id,
                       data=payload,
                       is_extended_id=True)

def receive_can_messages(bus, limit=CAN_DRAIN_LIMIT):
    """Yield pending CAN frames without letting a busy bus starve TCP I/O."""
    for _ in range(limit):
        msg = bus.recv(timeout=0)
        if msg is None:
            return
        yield msg

def flush_can_tx_queue(bus, tx_queue, limit=CAN_TX_BATCH):
    """Try to send a bounded batch of pending frames without blocking."""
    sent_frames = []
    for _ in range(limit):
        if not tx_queue:
            break
        can_id, payload = tx_queue[0]
        try:
            bus.send(make_can_message(can_id, payload), timeout=0)
        except Exception as exc:
            return sent_frames, exc
        sent_frames.append(tx_queue.popleft())
    return sent_frames, None

def create_server_socket(host, port):
    """Create a TCP server socket bound to host:port."""
    last_error = None
    for family, socktype, proto, _, sockaddr in socket.getaddrinfo(
        host, port, socket.AF_UNSPEC, socket.SOCK_STREAM, 0, socket.AI_PASSIVE
    ):
        server = socket.socket(family, socktype, proto)
        try:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6 and hasattr(socket, "IPV6_V6ONLY"):
                try:
                    server.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                except OSError:
                    pass
            server.bind(sockaddr)
            server.listen(5)
            server.setblocking(False)
            return server
        except OSError as exc:
            last_error = exc
            server.close()
    if last_error is not None:
        raise last_error
    raise OSError(f"No address found for {host}:{port}")

def create_default_server_socket(port):
    """Prefer dual-stack IPv6, then fall back to IPv4 when IPv6 is unavailable."""
    last_error = None
    for host in DEFAULT_LISTEN_HOSTS:
        try:
            return create_server_socket(host, port), host
        except OSError as exc:
            last_error = exc
    raise last_error

def format_time():
    """Return current UTC time formatted as hh:mm:ss.ddd"""
    now = datetime.now(timezone.utc)
    return now.strftime("%H:%M:%S.%f")[:12]

def format_raw_line(can_id, payload, direction):
    """Format one CAN frame as a Yacht Devices RAW ASCII line."""
    ts = format_time()
    can_id_hex = f"{can_id:08X}"
    data_hex = " ".join(f"{b:02X}" for b in payload)
    return f"{ts} {direction} {can_id_hex} {data_hex}\r\n"

def parse_tx_line(line):
    """Parse a client TX line.

    Accepts the short format used by can2yd clients:
        CANID_HEX [DATA_BYTES_HEX...]

    Also accepts full Yacht Devices RAW ASCII lines:
        hh:mm:ss.ddd D CANID_HEX [DATA_BYTES_HEX...]
    """
    parts = line.strip().split()
    if len(parts) < 1:
        return None, None
    if len(parts) >= 3 and parts[1] in ("R", "T"):
        parts = parts[2:]
    if len(parts) < 1:
        return None, None
    try:
        can_id = int(parts[0], 16)
        data = bytes(int(b, 16) for b in parts[1:])
        if not 0 <= can_id <= 0x1FFFFFFF or len(data) > 8:
            return None, None
        return can_id, data
    except ValueError:
        return None, None

def parse_raw_line(line):
    """Parse a Yacht Devices RAW ASCII line."""
    parts = line.strip().split()
    if len(parts) < 3:
        return None, None, None
    direction = parts[1]
    if direction not in ("R", "T"):
        return None, None, None
    can_id, data = parse_tx_line(" ".join(parts[2:]))
    return direction, can_id, data

class Client:
    """Represents a TCP client with an outgoing send buffer"""
    def __init__(self, sock):
        self.sock = sock
        self.sock.setblocking(False)
        self.send_buffer = deque()
        self.recv_buffer = ""

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
    if MODE == "client":
        run_client()
    elif MODE == "server":
        run_server()
    else:
        raise SystemExit("MODE must be 'server' or 'client'")

def run_server():
    bus = open_can_bus()

    if TCP_HOST:
        server = create_server_socket(TCP_HOST, TCP_PORT)
        listen_host = TCP_HOST
    else:
        server, listen_host = create_default_server_socket(TCP_PORT)

    clients = []
    can_tx_queue = deque()
    dropped_can_frames = 0
    next_can_error_log = 0

    print(f"[RAW ASCII] Server listening on {listen_host}:{TCP_PORT}, CAN {CAN_IFACE}")

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
                        client.recv_buffer += data.decode("ascii", errors="ignore")
                        lines = client.recv_buffer.split("\n")
                        client.recv_buffer = lines.pop()
                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue
                            can_id, payload = parse_tx_line(line)
                            if can_id is not None:
                                if len(can_tx_queue) < CAN_TX_QUEUE_LIMIT:
                                    can_tx_queue.append((can_id, payload))
                                else:
                                    dropped_can_frames += 1

                    except (ConnectionResetError, BrokenPipeError):
                        clients.remove(client)
                        client.sock.close()

            sent_frames, can_tx_error = flush_can_tx_queue(bus, can_tx_queue)
            for can_id, payload in sent_frames:
                # Echo confirmation only after the frame reached SocketCAN.
                confirm = format_raw_line(can_id, payload, "T").encode("ascii")
                for client in clients:
                    client.enqueue(confirm)

            if can_tx_error is not None:
                now = time.monotonic()
                if now >= next_can_error_log:
                    print(
                        f"CAN transmit stalled: {can_tx_error} "
                        f"(queued={len(can_tx_queue)}, dropped={dropped_can_frames})"
                    )
                    next_can_error_log = now + CAN_TX_ERROR_LOG_INTERVAL

            # Non-blocking flush of outgoing buffers
            for client in clients[:]:
                if client.sock in ready_to_write:
                    try:
                        client.flush()
                    except:
                        clients.remove(client)
                        client.sock.close()

            # Drain a bounded batch so a busy CAN bus does not accumulate
            # frames faster than this loop can forward them.
            for msg in receive_can_messages(bus):
                line = format_raw_line(msg.arbitration_id, msg.data[:msg.dlc], "R").encode("ascii")
                for c in clients:
                    c.enqueue(line)

    except KeyboardInterrupt:
        print("Server stopped by user")
    finally:
        for c in clients:
            c.sock.close()
        server.close()
        bus.shutdown()

def run_client():
    if not TCP_HOST:
        raise SystemExit("TCP_HOST is required when MODE=client")

    bus = open_can_bus()
    print(f"[RAW ASCII] Client using CAN {CAN_IFACE}, server {TCP_HOST}:{TCP_PORT}")

    try:
        while True:
            sock = None
            try:
                sock = socket.create_connection((TCP_HOST, TCP_PORT))
                sock.setblocking(False)
                print(f"Connected to server: {TCP_HOST}:{TCP_PORT}")
                bridge_client_socket(bus, sock)
            except KeyboardInterrupt:
                raise
            except OSError as exc:
                print(f"Client connection error: {exc}")
            finally:
                if sock is not None:
                    sock.close()
            print(f"Reconnecting in {RECONNECT_DELAY:g}s")
            time.sleep(RECONNECT_DELAY)
    except KeyboardInterrupt:
        print("Client stopped by user")
    finally:
        bus.shutdown()

def bridge_client_socket(bus, sock):
    peer = Client(sock)
    rx_buffer = ""
    tx_buffer = deque()
    can_tx_queue = deque()
    dropped_can_frames = 0
    next_can_error_log = 0

    while True:
        ready_to_read, ready_to_write, _ = select.select(
            [peer.sock],
            [peer.sock] if tx_buffer else [],
            [],
            0.01
        )

        if peer.sock in ready_to_read:
            data = peer.sock.recv(4096)
            if not data:
                raise ConnectionResetError("server closed the connection")
            rx_buffer += data.decode("ascii", errors="ignore")
            lines = rx_buffer.split("\n")
            rx_buffer = lines.pop()
            for line in lines:
                direction, can_id, payload = parse_raw_line(line)
                # A can2yd client bridges only remote bus frames into its
                # local CAN bus. "T" lines are server confirmations for frames
                # that came from a TCP client, so replaying them locally would
                # create an obvious echo path.
                if direction != "R" or can_id is None:
                    continue
                if len(can_tx_queue) < CAN_TX_QUEUE_LIMIT:
                    can_tx_queue.append((can_id, payload))
                else:
                    dropped_can_frames += 1

        _, can_tx_error = flush_can_tx_queue(bus, can_tx_queue)
        if can_tx_error is not None:
            now = time.monotonic()
            if now >= next_can_error_log:
                print(
                    f"CAN transmit stalled: {can_tx_error} "
                    f"(queued={len(can_tx_queue)}, dropped={dropped_can_frames})"
                )
                next_can_error_log = now + CAN_TX_ERROR_LOG_INTERVAL

        # Drain pending local CAN frames. Reading only one frame per loop
        # would starve locally-originated traffic behind a busy remote feed.
        for msg in receive_can_messages(bus):
            payload = msg.data[:msg.dlc]
            tx_line = f"{msg.arbitration_id:08X} {' '.join(f'{b:02X}' for b in payload)}\r\n"
            tx_buffer.append(tx_line.encode("ascii"))

        if peer.sock in ready_to_write:
            while tx_buffer:
                chunk = tx_buffer[0]
                try:
                    sent = peer.sock.send(chunk)
                    if sent < len(chunk):
                        tx_buffer[0] = chunk[sent:]
                        break
                    tx_buffer.popleft()
                except BlockingIOError:
                    break

if __name__ == "__main__":
    main()
