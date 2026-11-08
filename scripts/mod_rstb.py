"""Compose the resource-size table for Switch BOTW 1.6.0."""

from pathlib import Path
import struct

from extract_destinations import read_index, unyaz
from mod_demos import _encode_yaz0_window
from mod_environment import ModError


RESOURCE = Path("System/Resource/ResourceSizeTable.product.srsizetable")
POLICY = "botw160-rstb-v1"
MAX_SIZE = 8 << 20
HEADER = struct.Struct("<4sII")
HASH_ENTRY = struct.Struct("<II")
NAME_ENTRY = struct.Struct("<128sI")


def parse(data):
    if not 16 <= len(data) <= MAX_SIZE or data[:4] != b"Yaz0":
        raise ValueError("Expected a Yaz0 resource-size table")
    if not HEADER.size <= struct.unpack_from(">I", data, 4)[0] <= MAX_SIZE:
        raise ValueError("Invalid resource-size table length")
    raw = unyaz(data)
    magic, hashes, names = HEADER.unpack_from(raw)
    split = HEADER.size + hashes * HASH_ENTRY.size
    if magic != b"RSTB" or split + names * NAME_ENTRY.size != len(raw):
        raise ValueError("Invalid resource-size table header")
    hash_table = dict(HASH_ENTRY.iter_unpack(raw[HEADER.size:split]))
    name_table = {}
    for padded, size in NAME_ENTRY.iter_unpack(raw[split:]):
        name, separator, _ = padded.partition(b"\0")
        if not name or not separator or name in name_table:
            raise ValueError("Invalid resource-size table name")
        name_table[name] = size
    if len(hash_table) != hashes:
        raise ValueError("Duplicate resource-size hash")
    return hash_table, name_table


def encode(tables, header):
    hashes, names = tables
    raw = bytearray(HEADER.pack(b"RSTB", len(hashes), len(names)))
    for key, size in sorted(hashes.items()):
        raw.extend(HASH_ENTRY.pack(key, size))
    for key, size in sorted(names.items()):
        raw.extend(NAME_ENTRY.pack(key, size))
    if len(raw) > MAX_SIZE:
        raise ValueError("Merged resource-size table is too large")
    decoded = bytes(raw)
    return header[:4] + struct.pack(">I", len(raw)) + header[8:16] + _encode_yaz0_window(decoded, 0, len(raw))


def stock_bytes(romfs, image_path=None):
    offset, length = read_index(romfs / "runtime-index.bin")[RESOURCE.as_posix()]
    with (image_path or romfs / "romfs.bin").open("rb") as image:
        if offset < 0 or not 16 <= length <= MAX_SIZE:
            raise ValueError("Invalid installed resource-size table")
        image.seek(offset)
        data = image.read(length)
    if len(data) != length:
        raise ValueError("Incomplete installed resource-size table")
    return data


def merge(stock, inputs):
    baseline = parse(stock)
    explicit = ({}, {})
    removed = (set(), set())
    for name, data in inputs:
        try:
            tables = parse(data)
        except (ValueError, struct.error) as error:
            raise ModError(f"{name} has an invalid resource-size table. Re-export the pack before applying.") from error
        for original, table, allocations, deletions in zip(baseline, tables, explicit, removed):
            for key in original.keys() - table.keys():
                deletions.add(key)
            for key, size in table.items():
                if size != original.get(key):
                    allocations[key] = max(allocations.get(key, 0), original.get(key, 0), size)
    if any(allocations.keys() & deletions for allocations, deletions in zip(explicit, removed)):
        raise ModError("The enabled mods disagree about a resource-size entry. Merge these packs in BCML before applying.")
    merged = tuple({key: size for key, size in (original | allocations).items() if key not in deletions}
                   for original, allocations, deletions in zip(baseline, explicit, removed))
    data = encode(merged, stock)
    if parse(data) != merged:
        raise ValueError("Merged resource-size table verification failed")
    return data


def compose(romfs, image_path, packs, destination):
    try:
        stock = stock_bytes(romfs, image_path)

        def bounded_inputs():
            for name, path in packs:
                with path.open("rb") as file:
                    yield name, file.read(MAX_SIZE + 1)

        destination.write_bytes(merge(stock, bounded_inputs()))
    except (KeyError, OSError, ValueError, struct.error) as error:
        raise ModError("Could not prepare a verified BOTW resource-size table. Your applied overlay was kept.") from error
