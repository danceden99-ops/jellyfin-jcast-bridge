"""
CastV2 Protocol Implementation — manual protobuf encode/decode for CastMessage.

The Google Cast V2 protocol uses Protocol Buffers for message serialisation.
CastMessage is a simple, stable schema (7 fields), so we implement the wire
format directly to avoid requiring ``protoc`` or the heavy ``protobuf`` package.

Wire format reference:
    https://protobuf.dev/programming-guides/encoding/

CastMessage schema (cast_channel.proto):
    message CastMessage {
      enum ProtocolVersion { CASTV2_1_0 = 0; }
      required ProtocolVersion protocol_version = 1;
      required string source_id      = 2;
      required string destination_id = 3;
      required string namespace      = 4;
      enum PayloadType { STRING = 0; BINARY = 1; }
      required PayloadType payload_type = 5;
      optional string payload_utf8     = 6;
      optional bytes  payload_binary   = 7;
    }

Framing:
    Each message on the TLS socket is preceded by a 4-byte big-endian length
    prefix giving the size of the serialised CastMessage that follows.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ProtocolVersion(IntEnum):
    CASTV2_1_0 = 0


class PayloadType(IntEnum):
    STRING = 0
    BINARY = 1


# ---------------------------------------------------------------------------
# CastMessage data class
# ---------------------------------------------------------------------------

@dataclass
class CastMessage:
    """A single Cast V2 protocol message."""

    source_id: str
    destination_id: str
    namespace: str
    payload_utf8: Optional[str] = None
    payload_binary: Optional[bytes] = None
    protocol_version: ProtocolVersion = ProtocolVersion.CASTV2_1_0

    @property
    def payload_type(self) -> PayloadType:
        if self.payload_binary is not None:
            return PayloadType.BINARY
        return PayloadType.STRING


# ---------------------------------------------------------------------------
# Low-level protobuf helpers
# ---------------------------------------------------------------------------

def _encode_varint(value: int) -> bytes:
    """Encode *value* as a protobuf base-128 varint."""
    parts: list[int] = []
    while value > 0x7F:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    parts.append(value & 0x7F)
    return bytes(parts)


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Decode a varint starting at *pos*.  Returns ``(value, new_pos)``."""
    result = 0
    shift = 0
    while pos < len(data):
        byte = data[pos]
        result |= (byte & 0x7F) << shift
        pos += 1
        if not (byte & 0x80):
            break
        shift += 7
    return result, pos


def _encode_field_varint(field_number: int, value: int) -> bytes:
    tag = (field_number << 3) | 0  # wire-type 0
    return _encode_varint(tag) + _encode_varint(value)


def _encode_field_bytes(field_number: int, value: bytes) -> bytes:
    tag = (field_number << 3) | 2  # wire-type 2
    return _encode_varint(tag) + _encode_varint(len(value)) + value


def _encode_field_string(field_number: int, value: str) -> bytes:
    return _encode_field_bytes(field_number, value.encode("utf-8"))


# ---------------------------------------------------------------------------
# Encode / decode CastMessage
# ---------------------------------------------------------------------------

def encode_cast_message(msg: CastMessage) -> bytes:
    """Serialise a :class:`CastMessage` to raw protobuf bytes (no length prefix)."""
    buf = bytearray()
    buf.extend(_encode_field_varint(1, int(msg.protocol_version)))
    buf.extend(_encode_field_string(2, msg.source_id))
    buf.extend(_encode_field_string(3, msg.destination_id))
    buf.extend(_encode_field_string(4, msg.namespace))
    buf.extend(_encode_field_varint(5, int(msg.payload_type)))
    if msg.payload_utf8 is not None:
        buf.extend(_encode_field_string(6, msg.payload_utf8))
    if msg.payload_binary is not None:
        buf.extend(_encode_field_bytes(7, msg.payload_binary))
    return bytes(buf)


def decode_cast_message(data: bytes) -> CastMessage:
    """Deserialise raw protobuf bytes into a :class:`CastMessage`."""
    pos = 0
    fields: dict[int, int | bytes] = {}

    while pos < len(data):
        tag, pos = _decode_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x07

        if wire_type == 0:  # varint
            value, pos = _decode_varint(data, pos)
            fields[field_number] = value
        elif wire_type == 2:  # length-delimited
            length, pos = _decode_varint(data, pos)
            fields[field_number] = data[pos : pos + length]
            pos += length
        else:
            raise ValueError(
                f"Unsupported protobuf wire type {wire_type} at field {field_number}"
            )

    return CastMessage(
        protocol_version=ProtocolVersion(fields.get(1, 0)),
        source_id=fields[2].decode("utf-8") if isinstance(fields.get(2), (bytes, bytearray)) else "",
        destination_id=fields[3].decode("utf-8") if isinstance(fields.get(3), (bytes, bytearray)) else "",
        namespace=fields[4].decode("utf-8") if isinstance(fields.get(4), (bytes, bytearray)) else "",
        payload_utf8=(
            fields[6].decode("utf-8")
            if 6 in fields and isinstance(fields[6], (bytes, bytearray))
            else None
        ),
        payload_binary=fields.get(7) if isinstance(fields.get(7), (bytes, bytearray)) else None,
    )


# ---------------------------------------------------------------------------
# Framing helpers
# ---------------------------------------------------------------------------

def frame_message(msg: CastMessage) -> bytes:
    """Encode *msg* and prepend the 4-byte big-endian length prefix."""
    body = encode_cast_message(msg)
    return struct.pack(">I", len(body)) + body


def read_length_prefix(header: bytes) -> int:
    """Unpack the 4-byte big-endian length prefix."""
    return struct.unpack(">I", header[:4])[0]
