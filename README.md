# can2yd

A lightweight TCP bridge that exposes a SocketCAN interface using the **Yacht Devices RAW ASCII** protocol over TCP.

It allows any client that speaks the Yacht Devices RAW ASCII protocol — such as [SignalK](https://signalk.org/), [Yacht Devices CAN Log Viewer](https://www.yachtd.com/downloads/#canlog) or [OpenCPN](https://opencpn.org/) — to read and write CAN frames over a standard TCP connection.

---

## How it works

`can2yd` opens a SocketCAN bus and listens on a TCP port. For each CAN frame received on the bus, it broadcasts a line to all connected clients in the Yacht Devices RAW ASCII format:

```
hh:mm:ss.ddd R CANID_HEX [DATA_BYTES_HEX...]
```

Clients can also transmit frames by sending lines in the same format with direction `T`:

```
CANID_HEX [DATA_BYTES_HEX...]
```

When a client transmits a frame, `can2yd` forwards it onto the CAN bus and echoes a confirmation back to all connected clients.

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
  -e CAN_IFACE=can0 \
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
      CAN_IFACE: can0
      TCP_PORT: 2223
```

### Running directly (without Docker)

```bash
pip install python-can
CAN_IFACE=can0 TCP_PORT=2223 python can2yd.py
```

---

## Environment variables

| Variable    | Default | Description                        |
|-------------|---------|------------------------------------|
| `CAN_IFACE` | `can0`  | SocketCAN interface name           |
| `TCP_PORT`  | `2223`  | TCP port to listen on              |

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
