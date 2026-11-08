"""Inspect Switch mod packages and import their RomFS through MacNativeGames."""

import os
import json
from pathlib import Path
import re
import stat
import tempfile
import unicodedata

from mod_environment import ModError, present, regular
from mod_demos import make_demos
from mod_models import import_obj
from mod_profiles import DEPENDENCIES, dependencies


DESCRIPTION_FILE = ".description.txt"
README_FILES = ("readme.md", "readme.txt")


def read_description(path):
    try:
        if not regular(path):
            return None
        with path.open("rb") as stream:
            return stream.read(8192).decode("utf-8-sig", errors="ignore").strip() or None
    except OSError:
        return None


def package_description(romfs, source, single):
    wrapper = romfs.parent if romfs.name == "romfs" else romfs
    folders = (wrapper, source) if single and source != wrapper and source.name != "romfs" else (wrapper,)
    for folder in folders:
        for path in sorted(folder.iterdir()):
            if path.name.casefold() not in README_FILES:
                continue
            if text := read_description(path):
                for paragraph in re.split(r"\n\s*\n", text):
                    lines = [line.strip() for line in paragraph.splitlines()
                             if line.strip() and not line.lstrip().startswith("#")]
                    if lines:
                        summary = " ".join(lines)
                        return summary if len(summary) <= 600 else summary[:597].rsplit(" ", 1)[0] + "…"
    return None


REFUSALS = {
    "other_game": "This package has a different Switch title ID.",
    "bcml_package": "Export the BCML pack as complete Switch RomFS files, then import the exported folder or archive.",
    "tkmm_package": "Import a complete Breath of the Wild Switch RomFS folder or archive.",
    "cheats_only": "This package contains cheat codes. Import a Switch RomFS mod to use it here.",
    "nothing": "No Switch RomFS files were found. Pick a romfs folder, a Switch title-ID folder, or its archive.",
    "archive_kind": "Choose a folder or a ZIP, 7z, or RAR archive.",
    "zip_space": "There is not enough disk space to extract this mod.",
    "zip_bad": "The archive could not be read. Extract it separately and import the resulting Switch folder.",
    "zip_case": "The archive contains duplicate file or folder paths.",
    "several": "This pack has too many mod folders. Import them in smaller groups.",
}


def remember_path(paths, name, directory):
    key = unicodedata.normalize("NFD", name).casefold()
    entry = name, directory
    if paths.setdefault(key, entry) != entry:
        raise ModError("The mods contain conflicting file or folder names on the Mac's file system.")


def check_composition_paths(roots):
    paths = {}
    for root in roots:
        for path in root.rglob("*"):
            remember_path(paths, path.relative_to(root).as_posix(), stat.S_ISDIR(path.lstat().st_mode))


def archive_entries(entries):
    """Canonical paths for the upstream ZIP and tar preflight and readback."""
    paths, normalized = {}, []
    for name, directory in entries:
        if directory and name in {".", "./"}:
            normalized.append((".", True))
            continue
        relative = name.removeprefix("./")
        if directory:
            relative = relative.removesuffix("/")
        parts = relative.split("/")
        if (any(part in {"", ".", ".."} for part in parts) or len(os.fsencode(relative)) > 4095
                or any(ord(c) < 32 or c in "\\:" for c in relative)):
            raise ModError("The archive contains an ambiguous or unsupported file path. Re-export it with ordinary relative paths.")
        for depth in range(1, len(parts)):
            remember_path(paths, "/".join(parts[:depth]), True)
        remember_path(paths, relative, directory)
        normalized.append((relative, directory))
    return normalized


def extract_archive(archive, source, destination):
    original = archive._checked
    try:
        # Both extractors pass their actual listing here before writing files.
        # The tar extractor also uses the returned keys after extraction.
        def checked(entries):
            if len(entries) > archive.MAX_ENTRIES:
                return original(entries)
            return original(archive_entries(entries))

        archive._checked = checked
        return archive.extract(source, destination)
    finally:
        archive._checked = original


def dlc_title(name):
    return re.fullmatch(r"01007ef00011(?:f[0-9a-f]{3}|e00[12])", name.lower()) is not None


def inspect_tree(root, *, packages=False):
    """Check roots and descendants before upstream copies or reads them."""
    count = 0
    code = False
    names = {}
    stack = [root]
    while stack:
        path = stack.pop()
        mode = path.lstat().st_mode
        directory = stat.S_ISDIR(mode)
        if not (stat.S_ISREG(mode) or directory):
            raise ModError("Choose a mod with ordinary files and folders. Symbolic links are unsupported.")
        relative = path.relative_to(root)
        if len(os.fsencode(relative)) > 4095 or any(ord(c) < 32 or c in "\\:" for c in str(relative)):
            raise ModError("The mod contains a file name the native loader cannot read.")
        remember_path(names, relative.as_posix(), directory)
        count += 1
        if count > 100000:
            raise ModError("The mod has too many files. Import it in smaller groups.")
        if packages:
            name = path.name.lower()
            if dlc_title(name):
                raise ModError("This pack includes Switch DLC files. Export a base-game Switch RomFS pack separately.")
            inside_romfs = root.name == "romfs" or any(part == "romfs" for part in relative.parts[:-1])
            if name.endswith(".bnp") or (directory and not inside_romfs and name in {"logs", "options"}):
                raise ModError(REFUSALS["bcml_package"])
            if directory and not inside_romfs and name in {"content", "mlc01"}:
                raise ModError("This pack contains Wii U files. Export a Nintendo Switch RomFS pack from BCML.")
            if directory and not inside_romfs and name in {"aoc", "dlc"}:
                raise ModError("This pack includes a DLC folder. Export a base-game Switch RomFS pack separately.")
            code |= name in {"exefs", "cheats"}
        if directory:
            stack.extend(path.iterdir())
    return code


def import_folder(backend, source, name=None):
    if source.name == "romfs":
        return import_romfs(backend, source, name)
    code = inspect_tree(source, packages=True)
    tops = backend.tools.top_folders(backend.install.repo, backend.install.app, backend.install.version)
    found = backend.find.find(source, tops, backend.install.game.title_id)
    candidates = [backend.find.Found(candidate.romfs, None,
                  (*candidate.notes, "exefs_ignored") if candidate.exefs else candidate.notes,
                  candidate.name) for candidate in found if candidate.romfs]
    if not candidates:
        raise ModError("This pack contains no Switch RomFS files. ExeFS patches and cheats are unsupported.")
    ids = import_candidates(backend, source, candidates, name)
    message = f"Imported {len(ids)} mod{'s' if len(ids) != 1 else ''}. Enable the mods you want and choose Apply."
    return message + (" ExeFS patches and cheats are ignored." if code else "")


def import_romfs(backend, source, name):
    wrapper = source.parent
    if dlc_title(wrapper.name) or wrapper.name.lower() in {"dlc", "aoc"}:
        raise ModError("Choose the base-game Switch RomFS folder separately from DLC.")
    if wrapper.name.lower() in {"content", "mlc01"}:
        raise ModError("This pack contains Wii U files. Export a Nintendo Switch RomFS pack from BCML.")
    if backend.find.TITLE.fullmatch(wrapper.name) and wrapper.name.upper() != backend.install.game.title_id:
        raise ModError(REFUSALS["other_game"])
    if (wrapper / "info.json").is_file() and any(present(wrapper / key) for key in ("logs", "options")):
        raise ModError(REFUSALS["bcml_package"])
    inspect_tree(source, packages=True)
    notes = tuple(f"{kind}_ignored" for kind in ("exefs", "cheats") if present(wrapper / kind))
    import_candidates(backend, source, [backend.find.Found(source, None, notes)], name or wrapper.name)
    message = "Imported 1 mod. Enable it and choose Apply."
    return message + (" ExeFS patches and cheats are ignored." if notes else "")


def import_candidates(backend, source, candidates, name):
    original_find = backend.find.find
    original_clone = backend.lib.clone
    descriptions = {candidate.romfs: package_description(candidate.romfs, source, len(candidates) == 1)
                    for candidate in candidates}
    required = {}
    for candidate in candidates:
        romfs = candidate.romfs
        wrapper = romfs.parent if romfs.name == "romfs" else romfs
        locations = (wrapper, source) if len(candidates) == 1 else (wrapper,)
        metadata = next((folder for folder in locations if present(folder / DEPENDENCIES)), None)
        required[romfs] = dependencies(metadata) if metadata is not None else ()

    def clone(runner, folder, destination):
        original_clone(runner, folder, destination)
        if folder.name != "romfs":
            # Flat exports can put their README alongside the RomFS top-level folders.
            for path in destination.iterdir():
                if path.name.casefold() in (*README_FILES, DEPENDENCIES) and regular(path):
                    path.unlink()
        if description := descriptions.get(folder):
            (destination.parent / DESCRIPTION_FILE).write_text(description + "\n", encoding="utf-8")
        if required[folder]:
            (destination.parent / DEPENDENCIES).write_text(
                json.dumps({"requires": required[folder]}, ensure_ascii=False) + "\n", encoding="utf-8")

    try:
        # Keep the description within the upstream importer's rollback boundary.
        backend.find.find = lambda picked, tops, title: candidates
        backend.lib.clone = clone
        return backend.add.add(backend.runner, backend.install.repo, backend.install.app, backend.install.version,
                               backend.library, source, name=name)
    finally:
        backend.find.find = original_find
        backend.lib.clone = original_clone


def import_mod(backend, source, *, attack=None, durability=None, fire_capacity=None):
    source = source.expanduser()
    if not present(source):
        raise ModError("Choose a mod folder or archive that exists.")
    if source.is_symlink():
        raise ModError("Choose the original mod folder or archive.")
    if any(value is not None for value in (attack, durability, fire_capacity)) and (
            source.suffix.lower() != ".obj" or not regular(source)):
        raise ModError("Weapon stats require a regular Flameblade OBJ file.")
    if source.is_dir():
        return import_folder(backend, source)
    if not regular(source):
        raise ModError("Choose a regular mod archive or OBJ model.")
    if source.suffix.lower() == ".obj":
        return import_obj(backend, source, import_romfs, attack=attack, durability=durability,
                          fire_capacity=fire_capacity)
    with tempfile.TemporaryDirectory(prefix="import-", dir=backend.root) as scratch:
        extracted = extract_archive(backend.archive, source, Path(scratch) / "files")
        return import_folder(backend, extracted, source.stem)


def demos(backend):
    with tempfile.TemporaryDirectory(prefix="demos-", dir=backend.root) as scratch:
        root = Path(scratch)
        export = root / "import"
        export.mkdir()
        try:
            generated = make_demos(backend.install.repo, backend.install.app, root)
        except ValueError as error:
            raise ModError("Could not generate the private demos from this app's original Switch 1.6.0 resources.") from error
        for path in generated:
            path = Path(path)
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ModError("The demo generator returned an invalid path.")
            path.rename(export / path.name)
        return import_folder(backend, export, "Demo")
