#!/usr/bin/env python3
"""Extract real BOTW item icons to the player's private editor cache.

Python 3.10+ standard library only. Reads the installed game's RomFS without
downloading or modifying game files. Nintendo artwork is never bundled here.
ActorInfo's itemUseIconActorName supplies authoritative armor/plant aliases.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
from pathlib import Path

from extract_destinations import byml, read_index, sources, unyaz
from extract_map import gob_offset, paste_texture, texture, u32, u64, write_png


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path.home() / "Library/Application Support/BOTWEditor/cache/items"
ICON_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[0-9]{2})?")
# These are old catalog spellings, not valid replacement grant IDs. Only their
# matching stock artwork is reused; no item/command ID is changed by this tool.
LEGACY_PREFIXES = {"Item_MushroomGet_": "Item_Mushroom_", "Item_InsectGet_": "Animal_Insect_"}


def decode_icon(raw: bytes) -> tuple[bytearray, int, int]:
    if raw[:4] == b"Yaz0" and struct.unpack_from(">I", raw, 4)[0] > 16 * 1024 * 1024:
        raise ValueError("Unbounded compressed icon")
    plain = unyaz(raw)
    base = plain.find(b"BNTX")
    if plain[:4] != b"FRES" or base < 0:
        raise ValueError("Expected BFRES/BNTX item icon")
    bntx = plain[base:]
    if bntx[12:14] != b"\xff\xfe" or u32(bntx, 0x24) != 1:
        raise ValueError("Expected one little-endian icon texture")
    brti = u64(bntx, u64(bntx, 0x28))
    if bntx[brti:brti + 4] != b"BRTI":
        raise ValueError("Missing icon texture descriptor")
    width, height = struct.unpack_from("<II", bntx, brti + 0x24)
    fmt, layout = u32(bntx, brti + 0x1c), u32(bntx, brti + 0x34)
    mips = struct.unpack_from("<H", bntx, brti + 0x16)[0]
    tile_mode = struct.unpack_from("<H", bntx, brti + 0x12)[0]
    size = u32(bntx, brti + 0x50)
    data_at = u64(bntx, u64(bntx, brti + 0x70))
    if not 1 <= width <= 512 or not 1 <= height <= 512 or mips != 1 or tile_mode != 0 or layout & ~7:
        raise ValueError("Unsupported icon dimensions, mips or block layout")
    if size < 4 or data_at + size > len(bntx):
        raise ValueError("Icon data is outside BNTX")
    if fmt in (0x1a01, 0x1a06):
        rgba = bytearray(width * height * 4)
        paste_texture(rgba, width, 0, 0, texture(plain))
        return rgba, width, height
    if fmt not in (0x0b01, 0x0b06) or u32(bntx, brti + 0x58) != 0x05040302:
        raise ValueError(f"Unsupported icon pixel format or channel mapping: {fmt:#x}")
    block_height = 1 << (layout & 7)
    width_gobs = (width * 4 + 63) // 64
    rgba = bytearray(width * height * 4)
    for y in range(height):
        for x in range(0, width, 4):
            offset = gob_offset(x * 4, y, width_gobs, block_height)
            count = min(4, width - x) * 4
            if offset + count > size:
                raise ValueError("Tegra icon block is outside texture")
            target = (y * width + x) * 4
            rgba[target:target + count] = bntx[data_at + offset:data_at + offset + count]
    return rgba, width, height


def resolve_icon(actor: str, actors: dict, stock: dict) -> tuple[str, str] | None:
    seen = set()
    current = actor
    for _ in range(8):
        if current in seen:
            return None
        seen.add(current)
        override = actors.get(current, {}).get("itemUseIconActorName", "")
        if override and override != current:
            current = override
            continue
        if current in stock:
            return current, "actor_metadata" if current != actor else "direct"
        break
    if actor not in actors:
        for old, new in LEGACY_PREFIXES.items():
            candidate = new + actor[len(old):] if actor.startswith(old) else ""
            if candidate in stock:
                return candidate, "legacy_catalog_icon_only"
    return None


def catalog_path(explicit: Path | None) -> Path:
    if explicit:
        return explicit.expanduser()
    for candidate in (ROOT / "Sources/catalog.json", ROOT / "catalog.json"):
        if candidate.is_file():
            return candidate
    raise ValueError("Item catalog is missing; specify --catalog PATH")


def extract(args) -> dict:
    index_path, image_path = sources(args)
    entries = read_index(index_path)
    catalog = json.loads(catalog_path(args.catalog).read_text(encoding="utf-8"))
    catalog_ids = {entry["id"] for entry in catalog}
    if any(not ICON_NAME.fullmatch(actor) for actor in catalog_ids):
        raise ValueError("Unsafe actor ID in item catalog")
    stock = {Path(name).stem: name for name in entries if name.startswith("UI/StockItem/")
             and name.endswith(".sbitemico") and ICON_NAME.fullmatch(Path(name).stem)}
    if not stock:
        raise ValueError("No stock item icons found in the local game")
    output = args.output_dir.expanduser()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    icons = {}
    with image_path.open("rb") as image:
        image_size = os.fstat(image.fileno()).st_size

        def read_file(name: str) -> bytes:
            offset, size = entries[name]
            if offset < 0 or size < 1 or size > 64 * 1024 * 1024 or offset + size > image_size:
                raise ValueError(f"Invalid RomFS file extent: {name}")
            image.seek(offset)
            data = image.read(size)
            if len(data) != size:
                raise ValueError(f"Truncated RomFS file: {name}")
            return data

        info = byml(unyaz(read_file("Actor/ActorInfo.product.sbyml")))
        actors = {entry["name"]: entry for entry in info["Actors"]}
        for number, actor in enumerate(sorted(stock), 1):
            rgba, width, height = decode_icon(read_file(stock[actor]))
            filename = actor + ".png"
            digest = write_png(output / filename, width, height, rgba)
            icons[actor] = {"file": filename, "source_icon": actor, "source": "direct",
                            "width": width, "height": height, "sha256": digest}
            if number % 200 == 0:
                print(f"Decoded {number}/{len(stock)} stock icons", flush=True)
    # Metadata overrides take precedence even if an upgraded armor ID also has
    # its own texture. This follows the game's itemUseIconActorName behavior.
    for actor in sorted(set(actors) | catalog_ids):
        if not ICON_NAME.fullmatch(actor):
            continue
        resolved = resolve_icon(actor, actors, stock)
        if not resolved:
            continue
        source, reason = resolved
        if source == actor:
            continue
        temporary = output / (actor + f".{os.getpid()}.tmp")
        try:
            shutil.copyfile(output / (source + ".png"), temporary)
            os.chmod(temporary, 0o600)
            temporary.replace(output / (actor + ".png"))
        finally:
            temporary.unlink(missing_ok=True)
        icons[actor] = {**icons[source], "file": actor + ".png", "source_icon": source, "source": reason}
    resolved_catalog = {actor: icons[actor] for actor in catalog_ids if actor in icons}
    reasons = {reason: sum(icon["source"] == reason for icon in resolved_catalog.values())
               for reason in ("direct", "actor_metadata", "legacy_catalog_icon_only")}
    manifest = {"schema": 1, "local_game_assets_only": True, "stock_count": len(stock),
                "icon_count": len(icons), "icons": icons,
                "catalog": {"total": len(catalog_ids), "resolved": len(resolved_catalog),
                            "sources": reasons, "missing": sorted(catalog_ids - set(resolved_catalog))}}
    path = output / "manifest.json"
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path("/Applications/Breath of the Wild.app"))
    parser.add_argument("--romfs", type=Path, help="Use an extracted RomFS folder instead")
    parser.add_argument("--catalog", type=Path, help="Editor catalog JSON; detected automatically by default")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        manifest = extract(args)
    except (OSError, ValueError, KeyError, IndexError, TypeError, struct.error, AssertionError) as error:
        parser.exit(1, f"Cannot extract item icons: {error}\n")
    coverage = manifest["catalog"]
    print(f"Wrote {manifest['icon_count']} private item icons; catalog coverage "
          f"{coverage['resolved']}/{coverage['total']} to {args.output_dir.expanduser()}")
    if coverage["missing"]:
        print(f"{len(coverage['missing'])} catalog IDs have no stock icon; use the editor's generic fallback")


if __name__ == "__main__":
    main()
