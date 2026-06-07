"""
NetProbe Protocol — packet definitions and (de)serialization.

Data packet layout (big-endian):
  type(1B) | seq_num(4B) | total_pkts(4B) | payload_len(2B) | checksum(4B) | payload(N B)

ACK packet layout:
  type(1B) | ack_num(4B) | checksum(4B)

FIN / FIN_ACK packets carry an optional SHA-256 hash in the payload field.
"""

import struct
import zlib
from dataclasses import dataclass, field
from typing import Optional

# Packet type constants
PKT_DATA    = 0x01
PKT_ACK     = 0x02
PKT_FIN     = 0x03
PKT_FIN_ACK = 0x04

# Header sizes
DATA_HEADER_FMT = "!B I I H I"   # type, seq, total, plen, crc
DATA_HEADER_SIZE = struct.calcsize(DATA_HEADER_FMT)  # 15 bytes

ACK_HEADER_FMT  = "!B I I"       # type, ack_num, crc
ACK_HEADER_SIZE = struct.calcsize(ACK_HEADER_FMT)    # 9 bytes


@dataclass
class DataPacket:
    seq_num: int
    total_pkts: int
    payload: bytes
    pkt_type: int = PKT_DATA

    def to_bytes(self) -> bytes:
        payload_len = len(self.payload)
        # Compute checksum over header fields + payload
        header_no_crc = struct.pack("!B I I H", self.pkt_type, self.seq_num,
                                    self.total_pkts, payload_len)
        checksum = zlib.crc32(header_no_crc + self.payload) & 0xFFFFFFFF
        header = struct.pack(DATA_HEADER_FMT, self.pkt_type, self.seq_num,
                             self.total_pkts, payload_len, checksum)
        return header + self.payload

    @staticmethod
    def from_bytes(data: bytes) -> Optional["DataPacket"]:
        if len(data) < DATA_HEADER_SIZE:
            return None
        pkt_type, seq_num, total_pkts, payload_len, checksum = struct.unpack(
            DATA_HEADER_FMT, data[:DATA_HEADER_SIZE]
        )
        payload = data[DATA_HEADER_SIZE: DATA_HEADER_SIZE + payload_len]
        if len(payload) != payload_len:
            return None
        header_no_crc = struct.pack("!B I I H", pkt_type, seq_num, total_pkts, payload_len)
        expected = zlib.crc32(header_no_crc + payload) & 0xFFFFFFFF
        if expected != checksum:
            return None
        pkt = DataPacket(seq_num=seq_num, total_pkts=total_pkts,
                         payload=payload, pkt_type=pkt_type)
        return pkt


@dataclass
class AckPacket:
    ack_num: int
    pkt_type: int = PKT_ACK

    def to_bytes(self) -> bytes:
        header_no_crc = struct.pack("!B I", self.pkt_type, self.ack_num)
        checksum = zlib.crc32(header_no_crc) & 0xFFFFFFFF
        return struct.pack(ACK_HEADER_FMT, self.pkt_type, self.ack_num, checksum)

    @staticmethod
    def from_bytes(data: bytes) -> Optional["AckPacket"]:
        if len(data) < ACK_HEADER_SIZE:
            return None
        pkt_type, ack_num, checksum = struct.unpack(ACK_HEADER_FMT, data[:ACK_HEADER_SIZE])
        header_no_crc = struct.pack("!B I", pkt_type, ack_num)
        expected = zlib.crc32(header_no_crc) & 0xFFFFFFFF
        if expected != checksum:
            return None
        return AckPacket(ack_num=ack_num, pkt_type=pkt_type)


def parse_packet(data: bytes):
    """Return a DataPacket or AckPacket depending on the first byte, or None on error."""
    if not data:
        return None
    pkt_type = data[0]
    if pkt_type in (PKT_DATA, PKT_FIN):
        return DataPacket.from_bytes(data)
    if pkt_type in (PKT_ACK, PKT_FIN_ACK):
        return AckPacket.from_bytes(data)
    return None
