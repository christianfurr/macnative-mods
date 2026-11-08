"""Merge Switch BOTW 1.6.0 BNP packages in a temporary BCML workspace."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


BASE_TITLE = "01007EF00011E000"
ENGINE = "bcml-runtime/bin/python"


def import_bnps(backend, sources, name=None):
    from extract_destinations import read_index
    from mod_environment import ModError, manager_data, regular
    from mod_import import extract_archive, import_romfs, inspect_tree

    if backend.version != "botw160":
        raise ModError("BNP merging supports Breath of the Wild 1.6.0 for Switch.")
    engine = manager_data() / ENGINE
    if not engine.is_file():
        raise ModError("The local BCML merge engine is missing. See the MacNative Mods setup guide.")
    if not 1 <= len(sources) <= 24 or len(set(sources)) != len(sources):
        raise ModError("Choose between 1 and 24 different BNP files.")
    if name is not None and (not name.strip() or len(name) > 100 or not name.isprintable()):
        raise ModError("Enter a pack name between 1 and 100 characters.")
    image = backend.romfs_image
    index = backend.install.romfs / "runtime-index.bin"
    resources = read_index(index)
    if shutil.disk_usage(backend.root).free < sum(size for _, size in resources.values()) + (2 << 30):
        raise ModError("BNP merging needs temporary space for the game resources plus 2 GB.")

    with tempfile.TemporaryDirectory(prefix="bcml-", dir=backend.root) as directory:
        root = Path(directory).resolve()
        paths, names = [], []
        for i, source in enumerate(sources):
            source = source.expanduser()
            if not regular(source) or source.suffix.lower() != ".bnp":
                raise ModError("Select regular .bnp files from the Switch version of the mod.")
            archive = root / f"input-{i}.7z"
            backend.lib.clone_file(source, archive)
            pack = extract_archive(backend.archive, archive, root / f"pack-{i}")
            inspect_tree(pack)
            metadata = pack / "info.json"
            if not regular(metadata) or metadata.stat().st_size > 1 << 20:
                raise ModError("A BNP is missing readable BCML package information.")
            info = json.loads(metadata.read_text(encoding="utf-8-sig"))
            package_name = info.get("name")
            if info.get("platform") != "switch" or not isinstance(package_name, str) or not package_name.strip():
                raise ModError("Choose BNPs built for Nintendo Switch.")
            names.append(" ".join(package_name.split())[:80])
            paths.append(pack)

        tmp = root / "tmp"
        tmp.mkdir()
        profile = root / "worker.sb"
        profile.write_text('(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)\n'
                           f'(allow file-write* (subpath {json.dumps(str(root))}) (literal "/dev/null"))\n')
        log = root / "merge.log"
        with log.open("wb") as output:
            result = subprocess.run(
                ["/usr/bin/sandbox-exec", "-f", str(profile), str(engine), "-B", "-s",
                 str(Path(__file__).resolve()), "--portable", str(image), str(index), *map(str, paths)],
                cwd=root, env={**os.environ, "TMPDIR": str(tmp)}, stdin=subprocess.DEVNULL,
                stdout=output, stderr=output, timeout=900,
            )
        export = root / "merged"
        merged = export / BASE_TITLE / "romfs"
        if result.returncode or not merged.is_dir():
            tail = log.read_bytes()[-3500:].decode(errors="replace")
            lines = [line.strip() for line in tail.splitlines() if line.strip()]
            reason = next((line for line in reversed(lines) if re.match(r"[\w.]+Error:", line)), "")
            reason = reason.replace(str(root), "merge workspace")[:240]
            raise ModError("BCML could not merge these packages." + (f" {reason}" if reason else ""))
        inspect_tree(merged)
        target = root / "import" / "romfs"
        target.parent.mkdir()
        merged.rename(target)
        summary = "Merged in BCML load order: " + " → ".join(names)
        (target.parent / "README.md").write_text(f"# BCML merge\n\n{summary}\n", encoding="utf-8")
        label = name.strip() if name is not None else (
            names[0] if len(names) == 1 else f"{names[-1]} + {len(names) - 1} packs")
        label = re.sub(r'[/\\:]', "-", label)[:120]
        message = import_romfs(backend, target, label)
        dlc_files = any(path.is_file() for folder in export.iterdir() if folder.name != BASE_TITLE
                        for path in folder.rglob("*"))
        return message + (" DLC-title files were left out." if dlc_files else "")


def unpack(image, index, destination):
    from extract_destinations import read_index

    with image.open("rb") as source:
        length = os.fstat(source.fileno()).st_size
        for name, (offset, size) in sorted(read_index(index).items(), key=lambda item: item[1][0]):
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts or not 0 <= offset <= offset + size <= length:
                raise ValueError("The installed RomFS index has an invalid file.")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            source.seek(offset)
            with target.open("wb") as out:
                remaining = size
                while remaining:
                    block = source.read(min(remaining, 2 << 20))
                    if not block:
                        raise ValueError("The installed RomFS image is incomplete.")
                    out.write(block)
                    remaining -= len(block)


def default_options(path):
    info = json.loads((path / "info.json").read_text(encoding="utf-8-sig"))
    options = info.get("options", {})
    selected = {item["folder"]: True for item in options.get("multi", ()) if item.get("default")}
    for group in options.get("single", ()):
        choices = group.get("options", ())
        choice = next((item for item in choices if item.get("default")), None)
        if choice is None and choices and group.get("required"):
            choice = choices[0]
        if choice is not None:
            selected[choice["folder"]] = True
    return selected


def worker(image, index, packages):
    root = Path.cwd()
    base = root / "base-romfs"
    unpack(image, index, base)
    data = root / "bcml-data"
    settings = {
        "store_dir": str(data / "library"), "game_dir_nx": str(base), "lang": "USen",
        "wiiu": False, "no_cemu": True, "auto_gb": False, "suppress_update": True,
    }
    for folder in (data, data / "bcml"):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "settings.json").write_text(json.dumps(settings))

    from bcml import bcml, install, util

    bcml.reload_settings()
    if util.get_settings("wiiu") or util.get_game_dir() != base:
        raise RuntimeError("BCML did not open its temporary Switch library.")
    for path in packages:
        install.install_mod(path, selects=default_options(path))
    install.refresh_merges()
    install.link_master_mod(root / "merged")


if __name__ == "__main__":
    worker(Path(sys.argv[2]), Path(sys.argv[3]), list(map(Path, sys.argv[4:])))
