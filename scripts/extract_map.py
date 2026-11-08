#!/usr/bin/env python3
"""Build a private Hyrule terrain map from the player's installed BOTW files.

Requires Python 3.10+ and its standard library. No game files are downloaded or
changed. Generated Nintendo artwork stays outside this source repository.

Format facts: MacNativeGames make_button_icons.py (MIT, Tegra GOB addressing),
https://github.com/aboood40091/BNTX-Extractor (BNTX field layout), and
https://github.com/zeldamods/objmap/blob/master/src/util/map.ts (world bounds).
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
import struct
import zlib
from functools import lru_cache
from pathlib import Path

from extract_destinations import read_index, sources, unyaz


COLUMNS = "ZABCDEFGHIJK"
ROWS = range(10)
WORLD = {"min_x": -6000.0, "max_x": 6000.0, "min_z": -5000.0, "max_z": 5000.0}
DEFAULT_OUTPUT = Path.home() / "Library/Application Support/BOTWEditor/cache/map"


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def gob_offset(x: int, y: int, width_gobs: int, block_height: int) -> int:
    """Tegra block-linear address, with x measured in bytes and y in BC rows."""
    return (
        y // (8 * block_height) * 512 * block_height * width_gobs
        + x // 64 * 512 * block_height
        + y % (8 * block_height) // 8 * 512
        + x % 64 // 32 * 256
        + y % 8 // 2 * 64
        + x % 32 // 16 * 32
        + y % 2 * 16
        + x % 16
    )


@lru_cache(maxsize=8192)
def bc1_palette(first: int, second: int) -> tuple[bytes, ...]:
    def rgb565(value: int) -> tuple[int, int, int]:
        r, g, b = value >> 11, (value >> 5) & 63, value & 31
        return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)

    a, b = rgb565(first), rgb565(second)
    if first > second:
        c = tuple((2 * a[i] + b[i]) // 3 for i in range(3))
        d = tuple((a[i] + 2 * b[i]) // 3 for i in range(3))
        return bytes((*a, 255)), bytes((*b, 255)), bytes((*c, 255)), bytes((*d, 255))
    c = tuple((a[i] + b[i]) // 2 for i in range(3))
    return bytes((*a, 255)), bytes((*b, 255)), bytes((*c, 255)), bytes(4)


def texture(data: bytes) -> tuple[bytes, int, int, int, int, int]:
    if data[:4] == b"Yaz0" and struct.unpack_from(">I", data, 4)[0] > 64 * 1024 * 1024:
        raise ValueError("Unbounded compressed map texture")
    plain = unyaz(data)
    base = plain.find(b"BNTX")
    if plain[:4] != b"FRES" or base < 0:
        raise ValueError("Expected a BFRES map containing BNTX")
    bntx = plain[base:]
    if bntx[12:14] != b"\xff\xfe" or u32(bntx, 0x24) != 1:
        raise ValueError("Expected one little-endian BNTX texture")
    pointer_table = u64(bntx, 0x28)
    brti = u64(bntx, pointer_table)
    if bntx[brti:brti + 4] != b"BRTI":
        raise ValueError("Missing BNTX texture descriptor")
    mips = struct.unpack_from("<H", bntx, brti + 0x16)[0]
    tile_mode = struct.unpack_from("<H", bntx, brti + 0x12)[0]
    fmt = u32(bntx, brti + 0x1c)
    width, height = struct.unpack_from("<II", bntx, brti + 0x24)
    layout, size = u32(bntx, brti + 0x34), u32(bntx, brti + 0x50)
    data_at = u64(bntx, u64(bntx, brti + 0x70))
    if fmt not in (0x1a01, 0x1a06) or mips != 1 or tile_mode != 0:
        raise ValueError(f"Unsupported texture: format={fmt:#x}, mips={mips}, tile mode={tile_mode}")
    if width < 4 or height != width or width > 4096 or layout & ~7:
        raise ValueError("Unexpected map tile dimensions or block layout")
    if data_at < 0 or size < 8 or data_at + size > len(bntx):
        raise ValueError("Texture data is outside BNTX")
    return bntx, width, height, data_at, size, 1 << (layout & 7)


def paste_texture(canvas: bytearray, canvas_width: int, column: int, row: int,
                  source: tuple[bytes, int, int, int, int, int]) -> None:
    bntx, width, height, data_at, data_size, block_height = source
    blocks_x, blocks_y = (width + 3) // 4, (height + 3) // 4
    width_gobs = (blocks_x * 8 + 63) // 64
    stride = canvas_width * 4
    for by in range(blocks_y):
        top = (row * height + by * 4) * stride + column * width * 4
        for bx in range(blocks_x):
            offset = gob_offset(bx * 8, by, width_gobs, block_height)
            if offset + 8 > data_size:
                raise ValueError("Tegra block address is outside texture")
            first, second, indices = struct.unpack_from("<HHI", bntx, data_at + offset)
            colors = bc1_palette(first, second)
            row_bytes = min(4, width - bx * 4) * 4
            for dy in range(4):
                if by * 4 + dy >= height:
                    break
                bits = indices >> (8 * dy)
                pixels = colors[bits & 3] + colors[bits >> 2 & 3] + colors[bits >> 4 & 3] + colors[bits >> 6 & 3]
                target = top + dy * stride + bx * 16
                canvas[target:target + row_bytes] = pixels[:row_bytes]


def png_chunk(stream, kind: bytes, data: bytes) -> None:
    stream.write(struct.pack(">I", len(data)))
    stream.write(kind)
    stream.write(data)
    stream.write(struct.pack(">I", binascii.crc32(kind + data) & 0xffffffff))


def write_png(path: Path, width: int, height: int, rgba: bytearray) -> str:
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as stream:
            os.chmod(temporary, 0o600)
            stream.write(b"\x89PNG\r\n\x1a\n")
            png_chunk(stream, b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            png_chunk(stream, b"sRGB", b"\0")
            compressor = zlib.compressobj(6)
            stride = width * 4
            for row in range(height):
                data = compressor.compress(b"\0" + rgba[row * stride:(row + 1) * stride])
                if data:
                    png_chunk(stream, b"IDAT", data)
            png_chunk(stream, b"IDAT", compressor.flush())
            png_chunk(stream, b"IEND", b"")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def extract(args) -> dict:
    index_path, image_path = sources(args)
    entries = read_index(index_path)
    prefix = f"UI/MapTex/MainField/MapTex{args.level}_"
    tiles = [(column, row, prefix + f"{letter}-{row}.sbmaptex")
             for row in ROWS for column, letter in enumerate(COLUMNS)]
    missing = [name for _, _, name in tiles if name not in entries]
    if missing:
        raise ValueError(f"Missing {len(missing)} base map tiles; first is {missing[0]}")
    canvas = None
    tile_width = tile_height = width = height = 0
    with image_path.open("rb") as image:
        image_size = os.fstat(image.fileno()).st_size
        for number, (column, row, name) in enumerate(tiles, 1):
            offset, size = entries[name]
            if offset < 0 or size < 1 or size > 64 * 1024 * 1024 or offset + size > image_size:
                raise ValueError(f"Invalid map tile extent: {name}")
            image.seek(offset)
            source = texture(image.read(size))
            if canvas is None:
                tile_width, tile_height = source[1:3]
                width, height = tile_width * len(COLUMNS), tile_height * len(ROWS)
                if width * height > 100_000_000:
                    raise ValueError("Map exceeds 100 megapixels; select a lower detail level")
                canvas = bytearray(width * height * 4)
            elif source[1:3] != (tile_width, tile_height):
                raise ValueError(f"Inconsistent tile size: {name}")
            paste_texture(canvas, width, column, row, source)
            if number % 12 == 0:
                print(f"Decoded {number}/{len(tiles)} map tiles", flush=True)
    output = args.output_dir.expanduser()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest = write_png(output / "map.png", width, height, canvas)
    metadata = {
        "schema": 1, "image": "map.png", "image_sha256": digest,
        "width": width, "height": height, "orientation": "north-up",
        "world_bounds": WORLD,
        "world_to_pixel": {"x_scale": width / 12000, "x_offset": width / 2,
                           "z_scale": height / 10000, "z_offset": height / 2},
        "grid": {"columns": list(COLUMNS), "rows": list(ROWS), "tile_world_size": 1000,
                 "tile_width": tile_width, "tile_height": tile_height, "tile_count": len(tiles)},
        "source": {"game": "BOTW", "platform": "Switch", "level": args.level,
                   "path_pattern": prefix + "{column}-{row}.sbmaptex",
                   "pixel_format": "BC1 sRGB", "local_game_assets_only": True},
    }
    path = output / "map.json"
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path("/Applications/Breath of the Wild.app"))
    parser.add_argument("--romfs", type=Path, help="Use an extracted RomFS folder instead")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--level", type=int, choices=(1, 2, 3), default=1,
                        help="1: detailed; 2: smaller; 3: overview. Default: 1")
    args = parser.parse_args()
    try:
        metadata = extract(args)
    except (OSError, ValueError, KeyError, IndexError, struct.error, AssertionError) as error:
        parser.exit(1, f"Cannot extract terrain map: {error}\n")
    print(f"Wrote {metadata['width']}×{metadata['height']} private terrain map to {args.output_dir.expanduser()}")


if __name__ == "__main__":
    main()
