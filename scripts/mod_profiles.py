"""Share loadouts by content identity and check declared pack dependencies."""

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata

from mod_environment import ModError, present, regular


DEPENDENCIES = "macnative-mod.json"
PROFILE_LIMIT = 1 << 20


def key(name):
    return unicodedata.normalize("NFC", name).casefold()


def dependencies(folder):
    path = folder / DEPENDENCIES
    if not present(path):
        return ()
    try:
        if not regular(path) or path.stat().st_size > 16384:
            raise ValueError
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        values = data.get("requires", [])
        if (not isinstance(values, list) or len(values) > 32
                or any(not isinstance(name, str) or not 1 <= len(name) <= 160
                       or name != name.strip() or not name.isprintable() for name in values)
                or len({key(name) for name in values}) != len(values)):
            raise ValueError
        return tuple(values)
    except (AttributeError, OSError, ValueError):
        raise ModError(f"{DEPENDENCIES} must contain a list of required mod names.") from None


def dependency_issues(library, mods):
    installed = {}
    for mod in mods:
        installed.setdefault(key(mod.name), []).append(mod)
    issues = {}
    for mod in mods:
        problems = []
        try:
            required = dependencies(library.path(mod.id))
        except ModError as error:
            issues[mod.id] = [str(error)]
            continue
        for name in required:
            candidates = [other for other in installed.get(key(name), ()) if other.id != mod.id]
            if not candidates:
                problems.append(f"Install {name}.")
            elif not any(other.validation.valid for other in candidates):
                problems.append(f"{name} is incompatible with this game.")
            elif not any(other.validation.valid and other.enabled for other in candidates):
                problems.append(f"Enable {name} in this profile.")
        if problems:
            issues[mod.id] = problems
    return issues


def fingerprint(folder):
    root = folder / "romfs"
    digest = hashlib.sha256()
    for file in sorted(root.rglob("*")):
        if file.is_file():
            name = unicodedata.normalize("NFC", file.relative_to(root).as_posix()).encode()
            with file.open("rb") as stream:
                data = hashlib.file_digest(stream, "sha256").digest()
            digest.update(len(name).to_bytes(4, "big") + name + data)
    digest.update(json.dumps(sorted(key(name) for name in dependencies(folder))).encode())
    return digest.hexdigest()


def export_profile(backend, target):
    state = backend.library.state
    target = target.expanduser()
    if target.suffix.lower() != ".macnativeprofile" or (present(target) and not regular(target)):
        raise ModError("Choose a regular .macnativeprofile file.")
    pack = {
        "format": 1, "title_id": backend.game.title_id, "version": backend.version,
        "name": state["selected_profile"],
        "mods": [{"name": state["names"].get(i, i), "sha256": fingerprint(backend.library.path(i))}
                 for i in state["enabled"]],
    }
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            json.dump(pack, output, ensure_ascii=False, indent=2)
            output.write("\n")
            if output.tell() > PROFILE_LIMIT:
                raise ModError("This profile is too large to share.")
            output.close()
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return f"Exported {pack['name']} with {len(pack['mods'])} enabled mods.", {}


def import_profile(backend, source):
    source = source.expanduser()
    if source.suffix.lower() != ".macnativeprofile" or not regular(source) or source.stat().st_size > PROFILE_LIMIT:
        raise ModError("Choose a readable .macnativeprofile file under 1 MB.")
    try:
        pack = json.loads(source.read_text(encoding="utf-8-sig"))
        title, version, name, entries = (pack[field] for field in ("title_id", "version", "name", "mods"))
        if (pack.get("format") != 1 or not isinstance(name, str) or not 1 <= len(name) <= 48
                or name != name.strip() or not name.isprintable() or not isinstance(entries, list)
                or any(not isinstance(item, dict) or not isinstance(item.get("name"), str)
                       or not 1 <= len(item["name"]) <= 512 or not item["name"].isprintable()
                       or not isinstance(item.get("sha256"), str)
                       or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in entries)):
            raise ValueError
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ModError("This profile file has an unsupported format.") from None
    if (title, version) != (backend.game.title_id, backend.version):
        raise ModError("This profile belongs to a different game or version.")
    state = backend.library.state
    profiles = state["profiles"]
    if len(profiles) >= 64:
        raise ModError("This game already has 64 profiles.")
    candidates = {}
    for mod_id in state["order"]:
        if backend.lib.validation(backend.library, mod_id).valid:
            candidates.setdefault(key(state["names"].get(mod_id, mod_id)), []).append(mod_id)
    hashes, resolved, missing = {}, [], []
    for item in entries:
        matches = candidates.get(key(item["name"]), ())
        for mod_id in matches:
            if mod_id not in hashes:
                hashes[mod_id] = fingerprint(backend.library.path(mod_id))
        match = next((i for i in matches if i not in resolved and hashes[i] == item["sha256"]), None)
        if match is None:
            missing.append(item["name"])
        else:
            resolved.append(match)
    if missing:
        preview = ", ".join(missing[:6])
        if len(missing) > 6:
            preview += f", and {len(missing) - 6} more"
        raise ModError(f"Install the matching mod packs, then import this profile again. Required: {preview}.")
    original = name
    used = {key(existing) for existing in profiles}
    number = 2
    while key(name) in used:
        suffix = f" ({number})"
        name = original[:48 - len(suffix)].rstrip() + suffix
        number += 1
    profiles[state["selected_profile"]] = {field: list(state[field]) for field in ("order", "enabled")}
    order = resolved + [i for i in state["order"] if i not in resolved]
    profiles[name] = {"order": order, "enabled": resolved}
    state["order"], state["enabled"], state["selected_profile"] = order, resolved, name
    backend.lib.save(backend.library)
    return f"Imported profile {name} with {len(resolved)} enabled mods.", {}
