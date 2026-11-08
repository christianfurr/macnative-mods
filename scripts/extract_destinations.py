#!/usr/bin/env python3
"""Extract a private BOTW live-editor destination catalog from your own installed game.

No Nintendo data is included in this script. Standard-library Python 3.10+ only.
Format references: https://github.com/zeldamods/oead (SARC, Yaz0, BYML),
https://github.com/zeldamods/msyt (MSBT). Readers adapted from MacNativeGames'
location_markers.py and prepare_shader_seed.py (MIT; see THIRD_PARTY_NOTICES.md); no downloaded game data is used.
"""
import argparse
import json
import math
import os
import re
import struct
from pathlib import Path


def sarc_members(data):
    if data[:4] != b'SARC' or len(data) < 32:
        raise ValueError('Expected a SARC archive')
    endian = '<' if data[6:8] == b'\xff\xfe' else '>'
    header = struct.unpack_from(endian + 'H', data, 4)[0]
    start = struct.unpack_from(endian + 'I', data, 12)[0]
    if data[header:header + 4] != b'SFAT':
        raise ValueError('Missing SARC file table')
    count = struct.unpack_from(endian + 'H', data, header + 6)[0]
    nodes = header + 12
    names = nodes + 16 * count + 8
    if data[names - 8:names - 4] != b'SFNT':
        raise ValueError('Missing SARC names')
    files = {}
    for i in range(count):
        _, attributes, lo, hi = struct.unpack_from(endian + 'IIII', data, nodes + i * 16)
        name_at = names + (attributes & 0xffffff) * 4
        name = data[name_at:data.index(0, name_at)].decode('utf-8')
        if not 0 <= lo <= hi <= len(data) - start:
            raise ValueError('SARC member is outside archive')
        files[name] = (start + lo, start + hi)
    return files


def member(archive, name):
    lo, hi = sarc_members(archive)[name]
    return archive[lo:hi]


def unyaz(data):
    return yaz0(data) if data[:4] == b'Yaz0' else data


def yaz0(data):
    """Yaz0 (Breath of the Wild's compression): a code byte, then 8 items, a literal byte or a back reference of
    (distance, length)."""
    if data[:4] != b'Yaz0':
        raise ValueError('expected Yaz0')
    size = struct.unpack_from('>I', data, 4)[0]
    if size > 512 << 20:
        raise ValueError('unbounded Yaz0 file')
    out, o, i, n = bytearray(size), 0, 16, len(data)
    try:
        while o < size:
            code = data[i]; i += 1
            for bit in (0x80, 0x40, 0x20, 0x10, 8, 4, 2, 1):
                if o >= size:
                    break
                if code & bit:
                    out[o] = data[i]; o += 1; i += 1
                    continue
                first = data[i]; dist = ((first & 0xF) << 8 | data[i+1]) + 1; length = first >> 4; i += 2
                if length:
                    length += 2
                else:
                    length = data[i] + 0x12; i += 1
                length = min(length, size - o)
                src = o - dist
                if src < 0:
                    raise ValueError('Yaz0 back reference before the start')
                if dist >= length:
                    out[o:o+length] = out[src:src+length]
                else:
                    for k in range(length):
                        out[o+k] = out[src+k]
                o += length
    except IndexError:
        raise ValueError('truncated Yaz0 file') from None
    return bytes(out)


def byml(data):
    """Minimal little-endian BYML v2+ reader (Switch): dict/array/string/int/float/bool/int64/uint/uint64."""
    assert data[:2] == b'YB', data[:4]
    hash_off, str_off, root_off = struct.unpack_from('<III', data, 4)
    def strtab(off):
        if not off: return []
        assert data[off] == 0xc2
        n = struct.unpack_from('<I', data, off)[0] >> 8
        offs = struct.unpack_from('<%dI' % (n + 1), data, off + 4)
        return [data[off + offs[i]:off + offs[i + 1] - 1].decode('utf-8', 'replace') for i in range(n)]
    hashes, strings = strtab(hash_off), strtab(str_off)
    def node(t, v, pos):
        if t == 0xa0: return strings[v]
        if t == 0xd0: return bool(v)
        if t == 0xd1: return struct.unpack('<i', struct.pack('<I', v))[0]
        if t == 0xd2: return struct.unpack('<f', struct.pack('<I', v))[0]
        if t == 0xd3: return v
        if t == 0xd4: return struct.unpack_from('<q', data, v)[0]
        if t == 0xd5: return struct.unpack_from('<Q', data, v)[0]
        if t == 0xd6: return struct.unpack_from('<d', data, v)[0]
        if t in (0xc0, 0xc1): return container(v)
        if t == 0xff: return None
        raise ValueError('byml node type %#x at %#x' % (t, pos))
    def container(off):
        t = data[off]; n = struct.unpack_from('<I', data, off)[0] >> 8
        if t == 0xc0:
            types = data[off + 4:off + 4 + n]; vals = off + 4 + ((n + 3) & ~3)
            return [node(types[i], struct.unpack_from('<I', data, vals + i * 4)[0], vals + i * 4) for i in range(n)]
        if t == 0xc1:
            out = {}
            for i in range(n):
                e = off + 4 + i * 8; key = struct.unpack_from('<I', data, e)[0] & 0xffffff; ty = data[e + 3]
                out[hashes[key]] = node(ty, struct.unpack_from('<I', data, e + 4)[0], e + 4)
            return out
        raise ValueError('byml root type %#x' % t)
    return container(root_off)

def msbt_labels(data):
    """label -> text (first attribute-free text of each entry) for an MSBT (little-endian on Switch)."""
    assert data[:8] == b'MsgStdBn'
    bom = data[8:10]; e = '<' if bom == b'\xff\xfe' else '>'
    nsec = struct.unpack_from(e + 'H', data, 0x0e)[0]; pos = 0x20; sections = {}
    for _ in range(nsec):
        name = data[pos:pos + 4]; size = struct.unpack_from(e + 'I', data, pos + 4)[0]
        sections[name] = data[pos + 0x10:pos + 0x10 + size]; pos = pos + 0x10 + ((size + 15) & ~15)
    lbl, txt = sections[b'LBL1'], sections[b'TXT2']
    groups = struct.unpack_from(e + 'I', lbl, 0)[0]; labels = {}
    for g in range(groups):
        cnt, off = struct.unpack_from(e + 'II', lbl, 4 + g * 8)
        for _ in range(cnt):
            ln = lbl[off]; name = lbl[off + 1:off + 1 + ln].decode(); idx = struct.unpack_from(e + 'I', lbl, off + 1 + ln)[0]
            labels[idx] = name; off += 1 + ln + 4
    n = struct.unpack_from(e + 'I', txt, 0)[0]; offs = struct.unpack_from(e + '%dI' % n, txt, 4)
    texts = {}
    for i in range(n):
        end = offs[i + 1] if i + 1 < n else len(txt)
        raw = txt[offs[i]:end]
        s = raw.decode('utf-16-le' if e == '<' else 'utf-16-be', 'replace')
        texts[labels.get(i, str(i))] = s.split('\x00')[0]
    return texts


def read_index(path):
    if path.suffix == '.json':
        return {entry['path']: (entry['offset'], entry['size'])
                for entry in json.loads(path.read_text())['files']}
    data = path.read_bytes()
    if data[:8] != b'TOTKRFS1':
        raise ValueError('Unsupported runtime RomFS index')
    count, strings = struct.unpack_from('<QQ', data, 8)
    if count > 1000000 or strings != 24 + count * 24 or strings >= len(data):
        raise ValueError('Invalid runtime RomFS index')
    files = {}
    for i in range(count):
        offset, size, name, length = struct.unpack_from('<QQII', data, 24 + i * 24)
        at = strings + name
        if length < 2 or at + length > len(data) or data[at + length - 1] != 0:
            raise ValueError('Invalid runtime RomFS name')
        files[data[at:at + length - 1].decode('utf-8')] = (offset, size)
    return files


def sources(args):
    if args.romfs:
        folder = args.romfs.expanduser()
        index = folder / 'index.json'
        if not index.is_file():
            index = folder / 'runtime-index.bin'
        return index, folder / 'romfs.bin'
    app = args.app.expanduser()
    index = app / 'Contents/Resources/totk/extracted/botw160/romfs/runtime-index.bin'
    image = app / 'Contents/Helpers/GameData-botw160.bundle/Contents/Resources/romfs.bin'
    if not image.is_file():
        image = index.parent / 'romfs.bin'
    return index, image


def clean(value):
    return ' '.join(str(value).split()).replace('\x00', '')


def extract(args):
    index_path, image_path = sources(args)
    files = read_index(index_path)
    with image_path.open('rb') as image:
        image_size = os.fstat(image.fileno()).st_size
        def read_file(name):
            offset, size = files[name]
            if offset < 0 or size < 1 or size > 256 * 1024 * 1024 or offset + size > image_size:
                raise ValueError('Invalid RomFS file extent: ' + name)
            image.seek(offset)
            data = image.read(size)
            if len(data) != size:
                raise ValueError('Truncated RomFS file: ' + name)
            return data
        boot = read_file('Pack/Bootup.pack')
        static = byml(unyaz(member(boot, 'Map/MainField/Static.smubin')))
        lang = args.lang
        names = {}
        message_pack = 'Pack/Bootup_' + lang + '.pack'
        if message_pack in files:
            messages = unyaz(member(read_file(message_pack), 'Message/Msg_' + lang + '.product.ssarc'))
            names = msbt_labels(member(messages, 'StaticMsg/LocationMarker.msbt'))
        starts = {entry['PosName']: entry for entry in static['StartPos'] if entry.get('PosName')}
        rows = []
        for marker in static['LocationMarker']:
            identifier = marker.get('MessageID', '')
            if re.fullmatch(r'Dungeon(?:0[0-9]{2}|1[01][0-9])', identifier):
                kind = 'shrine'
            elif re.fullmatch(r'Tower(?:0[1-9]|1[0-5])', identifier):
                kind = 'tower'
            else:
                continue
            if not marker.get('WarpDestMapName', '').startswith('MainField/'):
                raise ValueError('Destination is outside MainField: ' + identifier)
            start = starts[marker['WarpDestPosName']]
            position = start['Translate']
            x, y, z = (float(position[axis]) for axis in 'XYZ')
            if not all(math.isfinite(n) for n in (x, y, z)) or abs(x) > 6000 or abs(z) > 6000 or not -1000 <= y <= 3000:
                raise ValueError('Invalid world position: ' + identifier)
            name = clean(names.get(identifier, identifier)) or identifier
            rows.append((identifier, name, kind, x, y, z))
    if len({row[0] for row in rows}) != len(rows):
        raise ValueError('Duplicate destination IDs')
    if sum(row[2] == 'shrine' for row in rows) != 120 or sum(row[2] == 'tower' for row in rows) != 15:
        raise ValueError('Expected exactly 120 base shrines and 15 towers')
    return sorted(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, default=Path('/Applications/Breath of the Wild.app'))
    parser.add_argument('--romfs', type=Path, help='Use extracted RomFS folder instead of installed app')
    parser.add_argument('--lang', default='USen', help='Game message language, default USen')
    parser.add_argument('--output', type=Path, default=Path.home() / 'Library/Application Support/MacNativeGames/BotW/editor-destinations.tsv')
    args = parser.parse_args()
    try:
        rows = extract(args)
        output = args.output.expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + '.tmp')
        with temporary.open('w', encoding='utf-8', newline='\n') as stream:
            os.chmod(temporary, 0o600)
            for identifier, name, kind, x, y, z in rows:
                stream.write(f'{identifier}\t{name}\t{kind}\t{x:.6f}\t{y:.6f}\t{z:.6f}\n')
        temporary.replace(output)
        translated = sum(row[0] != row[1] for row in rows)
        print(f'Wrote {len(rows)} destinations (120 shrines, 15 towers; {translated} localized names) to {output}')
    except (OSError, ValueError, KeyError, IndexError, struct.error, AssertionError) as error:
        parser.exit(1, f'Cannot extract destinations: {error}\n')


if __name__ == '__main__':
    main()
