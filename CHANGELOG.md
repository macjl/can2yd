# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Added

- Client mode for connecting a local SocketCAN interface to a remote can2yd server.
- Configurable server listen address through `TCP_HOST`, with dual-stack IPv6 listening by default and IPv4 fallback.
- Configurable client reconnect delay and bounded SocketCAN transmit queue.
- Regression tests for protocol parsing and CAN transmit queue recovery.

### Changed

- Server mode remains the default for backward compatibility.
- The bridge drains SocketCAN receive queues in bounded batches to handle busy CAN networks.
- Docker image defaults now expose `MODE`, `TCP_HOST`, and `RECONNECT_DELAY`.

### Fixed

- Bidirectional forwarding now includes CAN frames originated by other local SocketCAN sockets, such as Signal K.
- SocketCAN transmit buffer saturation no longer stops the bridge; pending frames are retried and excess frames are bounded.
- RAW ASCII timestamps use timezone-aware UTC datetimes.
