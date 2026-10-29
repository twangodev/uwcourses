"""Lossless private JSON storage; published SQLite and Parquet stay independent."""

import struct

import pyarrow as pa
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

MAGIC = b"UWJSON\x01\x00"
CODEC = pa.Codec("zstd", compression_level=3)


def pack(value):
    if not isinstance(value, str):
        return value
    raw = value.encode("utf-8")
    if len(raw) < 1024:
        return value
    compressed = MAGIC + struct.pack("<Q", len(raw)) + CODEC.compress(raw).to_pybytes()
    return compressed if len(compressed) * 8 <= len(raw) * 7 else value


def unpack(value):
    if not isinstance(value, bytes) or not value.startswith(MAGIC):
        return value
    size = struct.unpack("<Q", value[len(MAGIC) : len(MAGIC) + 8])[0]
    return CODEC.decompress(value[len(MAGIC) + 8 :], size).to_pybytes().decode("utf-8")


class CompressedText(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return pack(value)

    def process_result_value(self, value, dialect):
        return unpack(value)
