# can2yd

A lightweight TCP bridge that exposes a SocketCAN interface using the **Yacht Devices RAW ASCII** protocol over TCP.

It allows any client that speaks the Yacht Devices RAW ASCII protocol — such as [SignalK](https://signalk.org/), [Yacht Devices CAN Log Viewer](https://www.yachtd.com/downloads/#canlog) or [OpenCPN](https://opencpn.org/) — to read and write CAN frames over a standard TCP connection.

---

## How it works

In its default `server` mode, `can2yd` opens a SocketCAN bus and listens on a TCP port. Omitting `MODE` preserves the original server behavior. `TCP_HOST` selects the listen address; if it is unset, the server first tries a dual-stack IPv6 wildcard listener (`::`) and falls back to IPv4 (`0.0.0.0`) if IPv6 is unavailable. For each CAN frame received on the bus, it broadcasts a line to all connected clients in the Yacht Devices RAW ASCII format:

```
hh:mm:ss.ddd R CANID_HEX [DATA_BYTES_HEX...]
```

Clients can also transmit frames by sending either full RAW ASCII `T` lines or the short transmit format:

```
CANID_HEX [DATA_BYTES_HEX...]
```

When a client transmits a frame, `can2yd` forwards it onto the CAN bus and echoes a confirmation back to all connected clients.

In `client` mode, `can2yd` opens a local SocketCAN bus and connects to a remote `can2yd` server. Frames received from the remote server are transmitted on the local CAN bus, and frames received from the local CAN bus are sent back to the server. This lets you bridge two SocketCAN interfaces over the network.

For bridge use, run exactly one side as `MODE=server` and the other side as `MODE=client`. The client transmits only remote `R` frames onto its local CAN bus and ignores server `T` confirmations, preventing the normal confirmation echo from being replayed back into the client-side bus.

---

## Requirements

- Linux host with a SocketCAN interface (physical or virtual: `can0`, `vcan0`, etc.)
- Docker (for containerized deployment)

---

## Usage

### With Docker (recommended)

The image requires the host network and access to the SocketCAN interface, which must be set up on the host before starting the container.

**Set up the CAN interface on the host:**

```bash
# Physical interface (replace can0 and bitrate as appropriate)
sudo ip link set can0 type can bitrate 250000
sudo ip link set can0 up

# Or create a virtual interface for testing
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set vcan0 up
```

**Run the container:**

```bash
docker run --rm \
  --network host \
  --cap-add NET_ADMIN \
  -e MODE=server \
  -e CAN_IFACE=can0 \
  -e TCP_PORT=2223 \
  ghcr.io/macjl/can2yd:latest
```

**Run a client on another host:**

```bash
docker run --rm \
  --network host \
  --cap-add NET_ADMIN \
  -e MODE=client \
  -e CAN_IFACE=can0 \
  -e TCP_HOST=192.168.1.10 \
  -e TCP_PORT=2223 \
  ghcr.io/macjl/can2yd:latest
```

### With Docker Compose

```yaml
services:
  can2yd:
    image: ghcr.io/macjl/can2yd:latest
    restart: unless-stopped
    network_mode: host
    cap_add:
      - NET_ADMIN
    environment:
      MODE: server
      CAN_IFACE: can0
      TCP_PORT: 2223
```

Client side:

```yaml
services:
  can2yd:
    image: ghcr.io/macjl/can2yd:latest
    restart: unless-stopped
    network_mode: host
    cap_add:
      - NET_ADMIN
    environment:
      MODE: client
      CAN_IFACE: can0
      TCP_HOST: 192.168.1.10
      TCP_PORT: 2223
```

### Running directly (without Docker)

```bash
pip install python-can
# Server side
MODE=server CAN_IFACE=can0 TCP_PORT=2223 python can2yd.py

# Client side
MODE=client CAN_IFACE=can0 TCP_HOST=192.168.1.10 TCP_PORT=2223 python can2yd.py
```

---

## Environment variables

| Variable          | Default  | Description                                               |
|-------------------|----------|-----------------------------------------------------------|
| `MODE`            | `server` | `server` to listen for clients, `client` to connect out   |
| `CAN_IFACE`       | `can0`   | SocketCAN interface name                                  |
| `TCP_HOST`        | unset    | Server listen address in `server` mode, default dual-stack `::` with IPv4 fallback; target server host or IP in `client` mode, required |
| `TCP_PORT`        | `2223`   | TCP port to listen on or connect to                       |
| `RECONNECT_DELAY` | `5`      | Client reconnect delay in seconds                         |
| `CAN_TX_QUEUE_LIMIT` | `1024` | Maximum frames pending for transmission to SocketCAN; excess frames are dropped while the CAN interface is saturated |

---

## Protocol

`can2yd` implements the **Yacht Devices RAW ASCII** protocol as documented by Yacht Devices Ltd.

Each line uses the format:

```
hh:mm:ss.ddd D CCCCCCCC DD DD DD DD DD DD DD DD
```

Where:
- `hh:mm:ss.ddd` — UTC timestamp
- `D` — direction: `R` (received from CAN bus) or `T` (transmitted by a client)
- `CCCCCCCC` — 8-digit hex CAN ID (extended 29-bit)
- `DD ...` — data bytes in hex, space-separated

Lines are terminated with `\r\n`.

---

## SignalK integration

In the SignalK server, add a **Yacht Devices RAW TCP** connection:

- **Type:** Yacht Devices RAW TCP
- **Host:** IP address of the host running `can2yd`
- **Port:** `2223` (or the value of `TCP_PORT`)

---

## Building the image

```bash
docker buildx build --platform linux/arm64 -t can2yd .
```

---

## License

MIT — see [LICENSE](LICENSE)
