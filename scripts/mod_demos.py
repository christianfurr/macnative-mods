"""Build two private Switch BOTW 1.6.0 demo packs from the player's RomFS."""

from argparse import Namespace
from hashlib import sha256
import importlib.util
import os
from pathlib import Path
import struct
import sys

from extract_destinations import member, msbt_labels, read_index, sarc_members, sources, unyaz
from extract_items import decode_icon
from extract_map import gob_offset, u32, u64


EDITOR_REPO = Path(__file__).resolve().parents[1]
TITLE_PATH = "Pack/Bootup_USen.pack"
MESSAGE_PATH = "Message/Msg_USen.product.ssarc"
TITLE_TEXT = "LayoutMsg/Title_00.msbt"
APPLE_PATH = "UI/StockItem/Item_Fruit_A.sbitemico"
STOCK = {
    TITLE_PATH: (1907587, "7cbbf80596b47f16818d70c98b11c3770642bd02eeae38e4b35d9c18bacd9f85"),
    APPLE_PATH: (24681, "d9ab34aa44e3f6e23b7001e0da33b50aa1469746b7c4dec5e9f426b2337773b3"),
}


def _formats(repo: Path):
    """Use the installed MacNativeGames checkout's SARC/Yaz0 writers."""
    path = repo / "games/totk/scripts/make_botw_button_icons.py"
    if not path.is_file():
        raise ValueError("The matching MacNativeGames checkout is required to generate demo mods")
    spec = importlib.util.spec_from_file_location("_botw_demo_formats", path)
    if spec is None or spec.loader is None:
        raise ValueError("Cannot load the MacNativeGames archive helpers")
    formats = importlib.util.module_from_spec(spec)
    original_path = sys.path[:]
    write_bytecode = sys.dont_write_bytecode
    try:
        sys.path.insert(0, str(path.parent))
        sys.dont_write_bytecode = True
        spec.loader.exec_module(formats)
    finally:
        sys.dont_write_bytecode = write_bytecode
        sys.path[:] = original_path
    return formats


def _read_stock(image, index: dict, name: str) -> bytes:
    expected_size, expected_sha = STOCK[name]
    offset, size = index.get(name, (-1, 0))
    if offset < 0 or size != expected_size or offset + size > os.fstat(image.fileno()).st_size:
        raise ValueError(f"Demo needs the original Switch 1.6.0 resource {name}")
    image.seek(offset)
    data = image.read(size)
    if len(data) != size or sha256(data).hexdigest() != expected_sha:
        raise ValueError(f"Original Switch 1.6.0 resource did not match for {name}")
    return data


def _encode_yaz0_window(data: bytes, start: int, end: int, *, complete_group: bool = False) -> bytes:
    """Encode a bounded Yaz0 slice using the preceding 4 KiB of decoded data."""
    tokens = []
    position = start
    while position < end:
        limit = min(273, end - position)
        best_length, stored_distance = 2, 0
        if limit >= 3 and position:
            earliest = max(0, position - 4096)
            prefix = data[position:position + 3]
            candidate = data.rfind(prefix, earliest, position + 2)
            for _ in range(24):
                if candidate < earliest:
                    break
                minimum = best_length + 1
                if data[candidate:candidate + minimum] == data[position:position + minimum]:
                    low, high = minimum, limit
                    while low < high:
                        length = (low + high + 1) // 2
                        if data[candidate:candidate + length] == data[position:position + length]:
                            low = length
                        else:
                            high = length - 1
                    best_length, stored_distance = low, position - candidate - 1
                    if best_length == limit:
                        break
                candidate = data.rfind(prefix, earliest, candidate + 2)
        length = best_length if best_length >= 3 else 1
        tokens.append((position, length, stored_distance))
        position += length

    # A window followed by stock tokens must end at an eight-token group
    # boundary. Split one long copy into literals and a shorter copy.
    extra_literals = -len(tokens) % 8
    if complete_group and extra_literals:
        for index in reversed(range(len(tokens))):
            offset, length, distance = tokens[index]
            if length >= extra_literals + 3:
                literals = [(offset + step, 1, 0) for step in range(extra_literals)]
                remaining = (offset + extra_literals, length - extra_literals, distance)
                tokens[index:index + 1] = [*literals, remaining]
                break
        else:
            return b""

    result = bytearray()
    for index in range(0, len(tokens), 8):
        group = tokens[index:index + 8]
        result.append(sum((length == 1) << (7 - bit) for bit, (_, length, _) in enumerate(group)))
        for offset, length, distance in group:
            if length == 1:
                result.append(data[offset])
            elif length < 18:
                result.extend((((length - 2) << 4) | (distance >> 8), distance & 255))
            else:
                result.extend((distance >> 8, distance & 255, length - 18))
    return bytes(result)


def _yaz0_windows(packed: bytes, size: int):
    """Yield approximately 4 KiB decoded windows at encoded group boundaries."""
    encoded_start = encoded = 16
    decoded_start = decoded = 0
    while decoded < size:
        flags = packed[encoded]
        encoded += 1
        for bit in range(8):
            if decoded >= size:
                break
            if flags & (0x80 >> bit):
                encoded += 1
                decoded += 1
            else:
                length = packed[encoded] >> 4
                encoded += 2
                if length:
                    decoded += length + 2
                else:
                    decoded += packed[encoded] + 18
                    encoded += 1
        if decoded - decoded_start >= 4096 or decoded >= size:
            yield encoded_start, encoded, decoded_start, min(decoded, size)
            encoded_start, decoded_start = encoded, decoded


def _compact_title_stream(packed: bytes, decoded: bytes, byte_limit: int) -> bytes:
    """Keep stock groups except for windows that reduce the encoded size."""
    if len(packed) <= byte_limit:
        return packed
    parts = []
    cursor = 0
    bytes_to_save = len(packed) - byte_limit
    for start, end, low, high in _yaz0_windows(packed, len(decoded)):
        replacement = _encode_yaz0_window(decoded, low, high, complete_group=high < len(decoded))
        if not replacement or len(replacement) >= end - start:
            continue
        parts.extend((packed[cursor:start], replacement))
        cursor = end
        bytes_to_save -= end - start - len(replacement)
        if bytes_to_save <= 0:
            return b"".join([*parts, packed[cursor:]])
    raise ValueError("Title edit could not fit the original resource size")


def _padded_yaz0(original: bytes, candidate: bytes, decoded: bytes) -> bytes:
    if (original[:4] != b"Yaz0" or candidate[:16] != original[:16] or
            len(candidate) > len(original)):
        raise ValueError("Demo would exceed the game's original resource size")
    result = candidate.ljust(len(original), b"\x00")
    if unyaz(result) != decoded:
        raise ValueError("Demo Yaz0 round trip failed")
    return result


def _explore_menu(formats, original: bytes) -> bytes:
    packed_messages = member(original, MESSAGE_PATH)
    messages = unyaz(packed_messages)
    start, end = sarc_members(messages)[TITLE_TEXT]
    title = messages[start:end]
    labels = msbt_labels(title)
    stock_text = "Continue".encode("utf-16-le")
    replacement = "Explore!".encode("utf-16-le")
    if labels.get("0000") != "Continue" or title.count(stock_text) != 1:
        raise ValueError("Expected the original US English Continue label")
    edited_title = title.replace(stock_text, replacement)
    if len(edited_title) != len(title) or msbt_labels(edited_title) != {**labels, "0000": "Explore!"}:
        raise ValueError("Title text validation failed")

    edited_messages = messages[:start] + edited_title + messages[end:]
    if packed_messages[:4] != b"Yaz0" or len(edited_messages) != len(messages):
        raise ValueError("Expected the original fixed-size title message archive")
    patched = formats.yaz0_patch(packed_messages, messages, edited_messages)
    compact = _compact_title_stream(patched, edited_messages, len(packed_messages))
    packed = _padded_yaz0(packed_messages, compact, edited_messages)
    result = formats.sarc_put(original, MESSAGE_PATH, packed)
    original_members = sarc_members(original)
    updated_members = sarc_members(result)
    if len(result) != len(original) or original_members != updated_members:
        raise ValueError("Title pack members changed unexpectedly")
    for name, (start, end) in updated_members.items():
        old_start, old_end = original_members[name]
        expected = packed if name == MESSAGE_PATH else original[old_start:old_end]
        if result[start:end] != expected:
            raise ValueError(f"Title pack round trip changed {name} unexpectedly")
    return result


def _moonlit_apples(original: bytes) -> bytes:
    before = unyaz(original)
    base = before.find(b"BNTX")
    if before[:4] != b"FRES" or base != 0x1000 or len(before) != 159920:
        raise ValueError("Expected the original Apple BFRES icon")
    texture = before[base:]
    descriptor = u64(texture, u64(texture, 0x28))
    width, height = struct.unpack_from("<II", texture, descriptor + 0x24)
    mips = struct.unpack_from("<H", texture, descriptor + 0x16)[0]
    tile_mode = struct.unpack_from("<H", texture, descriptor + 0x12)[0]
    format_code = u32(texture, descriptor + 0x1c)
    layout = u32(texture, descriptor + 0x34)
    channels = u32(texture, descriptor + 0x58)
    size = u32(texture, descriptor + 0x50)
    data_at = base + u64(texture, u64(texture, descriptor + 0x70))
    if (texture[12:14] != b"\xff\xfe" or u32(texture, 0x24) != 1 or
            texture[descriptor:descriptor + 4] != b"BRTI" or
            (width, height, mips, tile_mode, format_code, layout, channels, size, data_at) !=
            (144, 144, 1, 0, 0x0b06, 4, 0x05040302, 147456, 0x2000) or
            data_at + size > len(before)):
        raise ValueError("Expected the stock 144×144 RGBA8 Apple texture layout")

    pixels, decoded_width, decoded_height = decode_icon(before)
    if (decoded_width, decoded_height) != (width, height):
        raise ValueError("Apple texture dimensions could not be verified")
    after = bytearray(before)
    expected_pixels = bytearray(pixels)
    width_gobs = (width * 4 + 63) // 64
    changed = 0
    for y in range(height):
        for x in range(width):
            tiled_offset = gob_offset(x * 4, y, width_gobs, 1 << layout)
            if tiled_offset + 4 > size:
                raise ValueError("Apple pixel lies outside the texture extent")
            tiled = data_at + tiled_offset
            linear = (y * width + x) * 4
            red, _, blue, alpha = before[tiled:tiled + 4]
            if alpha and red != blue:
                # Drop two bits from the swapped channels so the recolor fits
                # the stock resource budget. Preserve green and the alpha mask.
                after[tiled] = expected_pixels[linear] = blue & 0xfc
                after[tiled + 2] = expected_pixels[linear + 2] = red & 0xfc
                changed += 1
    decoded, new_width, new_height = decode_icon(bytes(after))
    if changed < 1024 or (new_width, new_height) != (width, height) or decoded != expected_pixels:
        raise ValueError("Apple recolor pixel verification failed")
    edited = bytes(after)
    payload = _encode_yaz0_window(edited, 0, len(edited))
    return _padded_yaz0(original, original[:16] + payload, edited)


def make_demos(repo: Path, app: Path, temporary_dir: Path) -> tuple[Path, Path]:
    """Create private Explore Menu and Moonlit Apples folders, each with romfs/."""
    repo, app, temporary_dir = repo.resolve(), app.resolve(), temporary_dir.resolve()
    if not temporary_dir.is_dir() or any(temporary_dir.is_relative_to(root) for root in (EDITOR_REPO, repo, app)):
        raise ValueError("Demo files require a private staging directory outside both checkouts and the game app")

    formats = _formats(repo)
    index_path, image_path = sources(Namespace(app=app, romfs=None))
    manifest = formats.make_mod_manifest
    if not image_path.is_file():
        image_path = manifest.app_image_dir(app, "botw160") / "romfs.bin"
    reserved = manifest.app_overlays(app, "botw160").keys() | manifest.build_patches(index_path.parent)[1].keys()
    collision = reserved & STOCK.keys()
    if collision:
        raise ValueError(f"The game app already overlays {', '.join(sorted(collision))}")

    index = read_index(index_path)
    with image_path.open("rb") as image:
        title = _explore_menu(formats, _read_stock(image, index, TITLE_PATH))
        apples = _moonlit_apples(_read_stock(image, index, APPLE_PATH))

    title_root = temporary_dir / "Explore Menu"
    apple_root = temporary_dir / "Moonlit Apples"
    if any(root.exists() or root.is_symlink() for root in (title_root, apple_root)):
        raise ValueError("Demo staging already contains an Explore Menu or Moonlit Apples folder")
    for root, relative, data in ((title_root, TITLE_PATH, title), (apple_root, APPLE_PATH, apples)):
        root.mkdir(mode=0o700)
        target = root / "romfs" / relative
        target.parent.mkdir(parents=True)
        with target.open("xb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(data)
    return title_root, apple_root
