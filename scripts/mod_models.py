"""Bake small Wavefront OBJ meshes into rigid Switch BOTW 1.6.0 weapon templates."""

from argparse import Namespace
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import struct
import tempfile

from extract_destinations import read_index, sources, unyaz
from mod_demos import _encode_yaz0_window, _formats, _padded_yaz0
from mod_environment import ModError
from mod_weapon_stats import FLAMEBLADE, weapon_stats


# Elemental templates replace the blade shape and retain the separate hilt.
TEMPLATES = {
    "Weapon_Sword_001": "Traveler's Sword",
    "Weapon_Lsword_001": "Traveler's Claymore",
    "Weapon_Spear_001": "Traveler's Spear",
    "Weapon_Shield_001": "Wooden Shield",
    FLAMEBLADE: "Flameblade",
    "Weapon_Sword_034": "Frostblade",
    "Weapon_Sword_035": "Thunderblade",
}
ELEMENTAL_BLADES = {
    FLAMEBLADE: (1, b"Root__Mt_Sword_033"),
    "Weapon_Sword_034": (1, b"Root__Mt_Sword_034"),
    "Weapon_Sword_035": (0, b"Root__Mt_Sword_035_Blade"),
}
MODEL_NAME = re.compile(r"(Weapon_[A-Za-z]+_\d{3})(?: - (.+))?")
OBJ_LIMIT = 2 << 20


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unit(vector):
    length = math.hypot(*vector)
    require(length > 1e-8, "The mesh contains a zero-length normal or a degenerate triangle.")
    return tuple(value / length for value in vector)


def difference(a, b):
    return tuple(x - y for x, y in zip(a, b))


def cross(a, b):
    x, y, z = a
    i, j, k = b
    return y * k - z * j, z * i - x * k, x * j - y * i


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def obj_index(value, count):
    index = int(value)
    require(-count <= index <= count and index != 0, "A face references a missing OBJ vertex, UV, or normal.")
    return index - 1 if index > 0 else count + index


def read_obj(source):
    with source.open("rb") as file:
        raw = file.read(OBJ_LIMIT + 1)
    require(len(raw) <= OBJ_LIMIT, "The OBJ must be under 2 MiB.")
    positions, uvs, normals, triangles = [], [], [], []
    streams = {"v": (positions, 3), "vt": (uvs, 2), "vn": (normals, 3)}
    for line in raw.decode("utf-8-sig").splitlines():
        fields = line.partition("#")[0].split()
        if not fields:
            continue
        tag, *args = fields
        if tag in streams:
            stream, dimensions = streams[tag]
            require(len(args) == dimensions, f"Each OBJ {tag} row must have {dimensions} values.")
            vector = tuple(map(float, args))
            require(all(math.isfinite(value) and abs(value) <= 20 for value in vector),
                    "OBJ coordinates must be finite and within ±20 game units.")
            stream.append(vector)
        elif tag == "f":
            require(len(args) == 3, "Triangulate the OBJ before exporting it.")
            corners = []
            for argument in args:
                parts = argument.split("/")
                require(1 <= len(parts) <= 3 and parts[0], "Invalid OBJ face reference.")
                parts += [""] * (3 - len(parts))
                position = positions[obj_index(parts[0], len(positions))]
                uv = uvs[obj_index(parts[1], len(uvs))] if parts[1] else (0.5, 0.5)
                normal = normals[obj_index(parts[2], len(normals))] if parts[2] else None
                require(all(0 <= value <= 1 for value in uv), "OBJ UVs must be in the 0–1 range.")
                corners.append((position, (uv[0], 1 - uv[1]), normal))
            triangles.append(corners)
        else:
            require(tag in {"o", "g", "s", "mtllib", "usemtl"}, f"Unsupported OBJ record {tag!r}.")
    require(triangles, "The OBJ has no triangles.")
    return triangles


def vertex_records(triangles, vertex_limit, index_limit):
    require(len(triangles) * 3 <= index_limit, f"This model supports up to {index_limit // 3} triangles.")
    records, lookup, indices = [], {}, []
    for triangle in triangles:
        a, b, c = (corner[0] for corner in triangle)
        # Check the coordinates the GPU will actually receive.
        a, b, c = (struct.unpack("<3e", struct.pack("<3e", *point)) for point in (a, b, c))
        edge, other = difference(b, a), difference(c, a)
        face_normal = unit(cross(edge, other))
        uv_a, uv_b, uv_c = (corner[1] for corner in triangle)
        du, dv = difference(uv_b, uv_a)
        eu, ev = difference(uv_c, uv_a)
        determinant = du * ev - dv * eu
        direction = edge
        if abs(determinant) > 1e-8:
            direction = tuple((x * ev - y * dv) / determinant for x, y in zip(edge, other))
        for position, uv, normal in triangle:
            normal = face_normal if normal is None else unit(normal)
            along = dot(direction, normal)
            projected = tuple(x - along * y for x, y in zip(direction, normal))
            if math.hypot(*projected) <= 1e-8:
                axis = min(range(3), key=lambda axis: abs(normal[axis]))
                projected = cross(tuple(float(i == axis) for i in range(3)), normal)
            tangent = unit(projected)
            sign = -1 if determinant < 0 else 1
            binormal = tuple(sign * value for value in cross(normal, tangent))
            packed_normal = sum((round(value * 511) & 1023) << (10 * i)
                                for i, value in enumerate(normal)) | 3 << 30
            packed_tangent = tuple(round(value * 127) for value in tangent)
            packed_binormal = tuple(round(value * 127) for value in binormal)
            key = position, packed_normal, packed_tangent, packed_binormal, uv, sign
            if key not in lookup:
                lookup[key] = len(records)
                records.append(key)
            indices.append(lookup[key])
    require(len(records) <= vertex_limit, f"This model supports up to {vertex_limit} split vertices.")
    return records, indices


@dataclass(frozen=True)
class MeshSlot:
    header: int
    submesh: int
    indices: int
    index_count: int


class WeaponModel:
    def __init__(self, data, actor=None):
        self.data = bytearray(data)
        require(data[:16] == b"FRES    \x03\x00\x05\x00\xff\xfe\x0c\x00",
                "Expected the Switch BOTW BFRES 5.0.3 template.")
        self.pool = self.read("Q", self.read("Q", 0x90) + 8)
        model = self.read("Q", 0x28)
        blade = ELEMENTAL_BLADES.get(actor)
        counts = (2, 2, 2) if blade else (1, 1, 1)
        require(data[model:model + 4] == b"FMDL" and self.read("3H", model + 104) == counts,
                "The weapon's model and material layout does not match its template.")
        vertex, shape = self.read("2Q", model + 40)
        if blade:
            index, expected_name = blade
            shape += index * 112
            vertex = self.read("Q", shape + 24)
            name = self.read("Q", shape + 16) + 2
            require(data[name:name + len(expected_name) + 1] == expected_name + b"\0",
                    "The elemental blade shape could not be found.")
        require(data[vertex:vertex + 4] == b"FVTX" and data[shape:shape + 4] == b"FSHP",
                "Missing weapon geometry in the template.")
        require(self.read("Q", shape + 24) == vertex and self.read("4B", shape + 102) == (0, 2, 0, 0),
                "Expected a rigid model with two LODs.")
        self.bounds, self.radius = self.read("2Q", shape + 64)
        attrs = self.read("Q", vertex + 16)
        sizes, strides = self.read("2Q", vertex + 56)
        offset, attr_count, buffer_count, _, self.count, skin = self.read("IBBHIH", vertex + 80)
        require((attr_count, buffer_count, skin) == (5, 3, 0), "Unsupported weapon vertex layout.")
        self.uv_format = self.attributes(attrs)
        self.buffers = []
        start = self.pool + offset
        for i, expected_stride in enumerate((8, 12, 4)):
            size = self.read("I", sizes + i * 16)
            stride = self.read("I", strides + i * 16)
            start = (start + 7) & ~7
            require(stride == expected_stride and size == self.count * stride and start + size <= len(data),
                    "Weapon vertex buffer does not match the template layout.")
            self.buffers.append(start)
            start += size
        meshes = self.read("Q", shape + 32)
        self.meshes = [self.mesh(meshes + i * 56) for i in range(2)]

    def read(self, fmt, offset):
        values = struct.unpack_from("<" + fmt, self.data, offset)
        return values[0] if len(values) == 1 else values

    def attributes(self, start):
        values = {}
        for i in range(5):
            entry = start + i * 16
            name = self.read("Q", entry)
            label = bytes(self.data[name + 2:name + 5])
            fmt = struct.unpack_from(">H", self.data, entry + 8)[0]
            values[label] = fmt, *self.read("2H", entry + 12)
        uv = values.pop(b"_u0", None)
        require(uv in {(0x112, 8, 1), (0x512, 8, 1)} and values == {
            b"_p0": (0x515, 0, 0), b"_n0": (0x20E, 0, 1),
            b"_t0": (0x20B, 4, 1), b"_b0": (0x20B, 0, 2),
        }, "Unsupported weapon position, normal, tangent, or UV format.")
        return uv[0]

    def mesh(self, header):
        submesh, _, _, size_ptr, offset, primitive, fmt, count, _, sub_count, _ = self.read("4Q5I2H", header)
        start = self.pool + offset
        require((primitive, fmt, sub_count) == (3, 1, 1) and self.read("2I", submesh) == (0, count)
                and self.read("I", size_ptr) == count * 2 and start + count * 2 <= len(self.data),
                "Unsupported weapon index layout.")
        return MeshSlot(header, submesh, start, count)

    def bake(self, triangles):
        records, indices = vertex_records(triangles, self.count, min(slot.index_count for slot in self.meshes))
        positions, shading, binormals = self.buffers
        # Preserve the template's homogeneous position component.
        w = self.read("H", positions + 6)
        for i in range(self.count):
            p, normal, tangent, binormal, uv, sign = records[i] if i < len(records) else records[0]
            struct.pack_into("<3eH", self.data, positions + i * 8, *p, w)
            start = shading + i * 12
            struct.pack_into("<I4b", self.data, start, normal, *tangent, sign * 127)
            if self.uv_format == 0x112:
                struct.pack_into("<2H", self.data, start + 8, *(round(value * 65535) for value in uv))
            else:
                struct.pack_into("<2e", self.data, start + 8, *uv)
            struct.pack_into("<4b", self.data, binormals + i * 4, *binormal, 0)
        axes = list(zip(*(record[0] for record in records)))
        center = [(min(axis) + max(axis)) / 2 for axis in axes]
        extent = [(max(axis) - min(axis)) / 2 + 0.001 for axis in axes]
        radius = max(math.hypot(*record[0]) for record in records) + 0.001
        for i, slot in enumerate(self.meshes):
            payload = struct.pack(f"<{len(indices)}H", *indices).ljust(slot.index_count * 2, b"\x00")
            self.data[slot.indices:slot.indices + len(payload)] = payload
            struct.pack_into("<2I", self.data, slot.header + 44, len(indices), 0)
            struct.pack_into("<I", self.data, slot.submesh + 4, len(indices))
            for bound in range(2):
                struct.pack_into("<6f", self.data, self.bounds + (2 * i + bound) * 24, *center, *extent)
            struct.pack_into("<f", self.data, self.radius + 4 * i, radius)
        return bytes(self.data)


def stock_resource(image, index, name, max_size):
    offset, size = index[name]
    require(0 <= offset and 16 < size <= max_size and offset + size <= os.fstat(image.fileno()).st_size,
            f"{name} lies outside the installed game's resource budget.")
    image.seek(offset)
    data = image.read(size)
    require(len(data) == size and data[:4] == b"Yaz0" and struct.unpack_from(">I", data, 4)[0] <= max_size,
            f"{name} is not the expected Yaz0 resource.")
    return data


def import_obj(backend, source, import_romfs, *, attack=None, durability=None, fire_capacity=None):
    if backend.install.game.data_folder != "BotW" or backend.install.version != "botw160":
        raise ModError("OBJ model import requires the Switch BOTW 1.6.0 installation.")
    match = MODEL_NAME.fullmatch(source.stem)
    if not match or match[1] not in TEMPLATES:
        raise ModError("Name the OBJ with its weapon ID, such as Weapon_Sword_001 - My Sword.obj. "
                       "Supported IDs are " + ", ".join(TEMPLATES) + ".")
    actor, label = match.groups()
    resource = f"Model/{actor}.sbfres"
    tuned = any(value is not None for value in (attack, durability, fire_capacity))
    if tuned and actor != FLAMEBLADE:
        raise ModError("Attack, durability, and fire capacity are available for Flameblade OBJ mods.")
    if any(value is not None and not 1 <= value <= limit
           for value, limit in ((attack, 255), (durability, 255), (fire_capacity, 8))):
        raise ModError("Use 1–255 for attack and durability, and 1–8 for fire capacity.")
    try:
        index_path, image_path = sources(Namespace(app=backend.install.app, romfs=None))
        index = read_index(index_path)
        with image_path.open("rb") as image:
            stock = stock_resource(image, index, resource, 1 << 20)
            original = unyaz(stock)
            edited = WeaponModel(original, actor).bake(read_obj(source))
            candidate = stock[:16] + _encode_yaz0_window(edited, 0, len(edited))
            require(len(edited) == len(original) and len(candidate) <= len(stock),
                    "The finished model exceeds the original resource budget.")
            files = {resource: _padded_yaz0(stock, candidate, edited)}
            if tuned:
                files.update(weapon_stats(
                    _formats(backend.install.repo), lambda name: stock_resource(image, index, name, 4 << 20),
                    attack, durability, fire_capacity,
                ))
    except (KeyError, OSError, ValueError, struct.error) as error:
        raise ModError(f"Could not import the model. {error}") from error
    with tempfile.TemporaryDirectory(prefix="model-", dir=backend.root) as directory:
        romfs = Path(directory) / "romfs"
        for name, data in files.items():
            replacement = romfs / name
            replacement.parent.mkdir(parents=True, exist_ok=True)
            replacement.write_bytes(data)
        return import_romfs(backend, romfs, label or TEMPLATES[actor] + " Model")
