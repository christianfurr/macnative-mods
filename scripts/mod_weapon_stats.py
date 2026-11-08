"""Write scoped Flameblade stats into both Switch BOTW 1.6.0 actor resources."""

from collections import Counter
from hashlib import sha256
import struct
from zlib import crc32

from extract_destinations import byml, sarc_members, unyaz
from mod_demos import _compact_title_stream, _padded_yaz0


FLAMEBLADE = "Weapon_Sword_033"
ACTOR_PACK = f"Actor/Pack/{FLAMEBLADE}.sbactorpack"
ACTOR_INFO = "Actor/ActorInfo.product.sbyml"


def word(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def compact_actor(data):
    """Minimize Yaz0 bytes, accounting for the flag byte every eight tokens."""
    size = len(data)
    costs = [[0] * (size + 1) for _ in range(8)]
    lengths = [[1] * size for _ in range(8)]
    distances = [0] * size
    for pos in range(size - 1, -1, -1):
        limit = min(size - pos, 273)
        longest = 2
        earliest = max(0, pos - 4096)
        stop = pos + 2
        prefix = data[pos:pos + 3]
        while longest < limit:
            match = data.rfind(prefix, earliest, stop)
            if match < earliest:
                break
            stop = match + 2
            low, high = longest, limit
            while low < high:
                middle = (low + high + 1) // 2
                if data[match:match + middle] == data[pos:pos + middle]:
                    low = middle
                else:
                    high = middle - 1
            if low > longest:
                longest = low
                distances[pos] = pos - match - 1
        for slot in range(8):
            following = costs[(slot + 1) % 8]
            best = 1 + following[pos + 1]
            for length in range(3, longest + 1):
                cost = (2 if length < 18 else 3) + following[pos + length]
                if cost < best:
                    best = cost
                    lengths[slot][pos] = length
            costs[slot][pos] = best + (slot == 0)

    output = bytearray()
    pos = 0
    while pos < size:
        flags = len(output)
        output.append(0)
        for slot in range(8):
            if pos == size:
                break
            length, distance = lengths[slot][pos], distances[pos]
            if length == 1:
                output[flags] |= 0x80 >> slot
                output.append(data[pos])
            elif length < 18:
                output.extend((((length - 2) << 4) | (distance >> 8), distance & 255))
            else:
                output.extend((distance >> 8, distance & 255, length - 18))
            pos += length
    return output


def recode(formats, packed, original, updated):
    if original == updated:
        return packed
    patch = formats.yaz0_patch(packed, original, updated)
    if len(patch) > len(packed) and len(updated) < 16384:
        candidate = packed[:16] + compact_actor(updated)
    else:
        candidate = _compact_title_stream(patch, updated, len(packed))
    return _padded_yaz0(packed, candidate, updated)


def edit_actor_pack(original, attack, durability, fire_capacity):
    start, end = sarc_members(original)[f"Actor/GeneralParamList/{FLAMEBLADE}.bgparamlist"]
    data = bytearray(original[start:end])
    root = 48 + word(data, 20)
    root_id, _, lists, objects, count = struct.unpack_from("<I4H", data, root)
    if (data[:16] != struct.pack("<4sIII", b"AAMP", 2, 3, len(data))
            or root_id != crc32(b"param_root") or lists):
        raise ValueError("Expected the flat Switch Flameblade parameter archive.")

    parameters = {}
    for i in range(count):
        obj = root + objects * 4 + i * 8
        name, refs, size = struct.unpack_from("<I2H", data, obj)
        for j in range(size):
            param = obj + refs * 4 + j * 8
            key, ref = struct.unpack_from("<2I", data, param)
            parameters[name, key] = ref >> 24, param + (ref & 0xffffff) * 4

    references = Counter(offset for _, offset in parameters.values())
    edits = ((b"Attack", b"Power", 24, attack), (b"General", b"Life", 36, durability),
             (b"WeaponCommon", b"ChemicalEnergyMax", 4000, None if fire_capacity is None else 1000 * fire_capacity))
    for obj, key, stock, value in edits:
        if value is None or value == stock:
            continue
        kind, offset = parameters[crc32(obj), crc32(key)]
        if kind != 2 or references[offset] != 1 or word(data, offset) != stock:
            raise ValueError("A Flameblade stat does not match its original integer parameter.")
        struct.pack_into("<I", data, offset, value)
    return original[:start] + data + original[end:]


def edit_actor_info(original, attack, durability):
    keys, _, root = struct.unpack_from("<3I", original, 4)
    document = byml(original)
    index = document["Hashes"].index(crc32(FLAMEBLADE.encode()))
    record = document["Actors"][index]
    if record["name"] != FLAMEBLADE:
        raise ValueError("Flameblade actor table lookup did not match.")

    def field(node, label, kind):
        if original[node] != 0xc1:
            raise ValueError("Expected a Switch BYML dictionary.")
        for i in range(word(original, node) >> 8):
            entry = node + 4 + i * 8
            key = word(original, entry) & 0xffffff
            text = keys + word(original, keys + 4 + key * 4)
            if original[text:original.index(0, text)] == label and original[entry + 3] == kind:
                return entry + 4
        raise ValueError(f"Could not find the typed actor field {label.decode()}.")

    actors = word(original, field(root, b"Actors", 0xc0))
    count = len(document["Actors"])
    if word(original, actors) != (count << 8 | 0xc0) or original[actors + 4 + index] != 0xc1:
        raise ValueError("Unexpected actor table layout.")
    node = word(original, actors + 4 + ((count + 3) & ~3) + 4 * index)
    updated = bytearray(original)
    for key, value in (("attackPower", attack), ("generalLife", durability)):
        if value is not None:
            offset = field(node, key.encode(), 0xd1)
            struct.pack_into("<I", updated, offset, value)
            record[key] = value
    if byml(updated) != document:
        raise ValueError("Flameblade stat readback failed.")
    return bytes(updated)


def weapon_stats(formats, read_stock, attack, durability, fire_capacity):
    actor = read_stock(ACTOR_PACK)
    if sha256(actor).hexdigest() != "c5e32373351f1024032470da09407ba5fca71e9ac850f31ba3dbd3ca521a5115":
        raise ValueError("Expected the original Switch 1.6.0 Flameblade actor pack.")
    original = unyaz(actor)
    updated = edit_actor_pack(original, attack, durability, fire_capacity)
    result = {}
    if updated != original:
        result[ACTOR_PACK] = recode(formats, actor, original, updated)
    if attack not in (None, 24) or durability not in (None, 36):
        info = read_stock(ACTOR_INFO)
        if sha256(info).hexdigest() != "cee85ee00e595034aff9cb782019f7bff40f20b2da7bed221401e4a35a49e4a6":
            raise ValueError("Expected the original Switch 1.6.0 actor table.")
        original = unyaz(info)
        updated = edit_actor_info(original, attack, durability)
        result[ACTOR_INFO] = recode(formats, info, original, updated)
    return result
