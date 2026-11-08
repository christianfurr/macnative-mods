#!/usr/bin/env python3
"""JSON command line for the MacNative Mods library."""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

# This script can run from the signed editor app's Resources directory.
sys.dont_write_bytecode = True

from mod_environment import (
    ModError, manager_data, legacy_data, ensure_dir,
    game_running, installation, lock_file, native_game_running, overlay_signature,
    present, regular,
)
from mod_import import DESCRIPTION_FILE, REFUSALS, check_composition_paths, demos, import_mod, inspect_tree, read_description
from mod_bcml import import_bnps
from mod_profiles import dependency_issues, export_profile, import_profile
import mod_rstb


LIBRARY_MARKER = ".botw-editor-library-v1"
MOD_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,79}\Z")
VALIDATION = {
    "no_romfs": "No RomFS data.",
    "no_app_romfs": "The installed game is missing its RomFS index.",
    "misspelt": "A file name differs from the game's name only by letter case.",
    "other_version": "A versioned file targets a different game version.",
    "only_adds": "This mod does not replace any file in the installed game.",
    "all_taken": "The app already supplies the files this mod would replace.",
}


class JSONParser(argparse.ArgumentParser):
    def error(self, message):
        raise ModError("Invalid mod command or arguments.")


class Backend:
    def __init__(self, install):
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        sys.path.insert(0, str(install.repo))
        from tools.builder import mod_add, mod_applied, mod_archive, mod_find, mod_library, mod_tools
        from tools.builder.ports import CommandRunner, RealClock

        self.install = install
        self.add, self.applied, self.archive, self.find = mod_add, mod_applied, mod_archive, mod_find
        self.lib, self.tools = mod_library, mod_tools
        self.runner = CommandRunner(RealClock())
        manifest, self.folder = mod_tools.tools(install.repo)
        self.version = install.version
        self.game = install.game
        mod_library.TITLE_IDS[self.version] = self.game.title_id
        self.load = install.game_data / "mods" / self.version
        self.slot = install.game_data / "game-slot/lock"
        self.root = manager_data() / "mod-library" / self.version
        self.library = None
        self.ot_manifest = None
        self.romfs_image = install.romfs / "romfs.bin"
        if self.game.data_folder == "OT0":
            self.configure_octopath()
        else:
            manifest.IMAGE_DIR = None
            if not (install.romfs / "romfs.bin").is_file():
                manifest.IMAGE_DIR = manifest.app_image_dir(install.app, self.version)
                self.romfs_image = manifest.image_file(install.romfs)
                if not self.romfs_image.is_file():
                    raise ModError("Open the game once to locate its data folder.")

    def configure_octopath(self):
        if not (self.install.romfs / "romfs.bin").is_file():
            raise ModError("The Octopath Traveler 0 app is missing its RomFS image.")
        script = self.install.repo / "games/ot0/scripts/make_mod_manifest.py"
        spec = importlib.util.spec_from_file_location("octopath_manifest", script)
        self.ot_manifest = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ot_manifest)

        def validate(repo, app, version, mod):
            lines, _, added, misspelt = self.ot_manifest.manifest(mod / "romfs", self.install.romfs)
            replaced = len(lines) - len(added)
            reason = "misspelt" if misspelt else "" if replaced else "only_adds"
            return self.tools.Validation(not reason, reason, replaced, len(added),
                                         misspelt=tuple(name for name, _ in misspelt))

        self.tools.validate = validate
        self.tools.top_folders = lambda *_: {
            name.split("/", 1)[0]
            for name in self.ot_manifest.read_index(self.install.romfs / "runtime-index.bin")
        }

    def migrate_legacy_library(self):
        old = legacy_data() / "mod-library" / self.version
        marker = old / LIBRARY_MARKER
        if self.version != "botw160" or present(self.root) or not present(marker):
            return
        if old.is_symlink() or not regular(marker) or marker.read_text() != "BOTW Editor Mod Library 1\n":
            raise ModError("The old BOTW mod library could not be verified.")
        with lock_file(old.parent / ".lock", create=True):
            inspect_tree(old)
            with tempfile.TemporaryDirectory(prefix=".legacy-", dir=self.root.parent) as directory:
                staged = Path(directory) / self.version
                shutil.copytree(old, staged, copy_function=self.lib.clone_file)
                (staged / LIBRARY_MARKER).write_text("MacNative Mods Library 1\n")
                staged.rename(self.root)

    def open_library(self):
        self.migrate_legacy_library()
        ensure_dir(self.root)
        marker = self.root / LIBRARY_MARKER
        if not present(marker):
            if any(self.root.iterdir()):
                raise ModError("The editor mod library already contains unrecognized files.")
            with marker.open("x", encoding="utf-8") as stream:
                stream.write("MacNative Mods Library 1\n")
        if not regular(marker) or marker.read_text() != "MacNative Mods Library 1\n":
            raise ModError("The editor mod library ownership marker is invalid.")
        for leftover in (self.add.UNZIP, self.lib.STATE + ".partial"):
            if present(self.root / leftover):
                raise ModError("The mod library has unfinished staging files. Set them aside before retrying.")
        state_path = self.root / self.lib.STATE
        if present(state_path):
            if not regular(state_path):
                raise ModError("The mod library record is invalid.")
            state = json.loads(state_path.read_text())
            if not isinstance(state, dict) or state.get("format") != 1:
                raise ModError("The mod library record is invalid.")
            order, enabled = state.get("order"), state.get("enabled")
            if (not isinstance(order, list) or any(not isinstance(i, str) or not MOD_ID.fullmatch(i) for i in order)
                    or len(set(order)) != len(order) or not isinstance(enabled, list)
                    or any(not isinstance(i, str) or i not in order for i in enabled) or len(set(enabled)) != len(enabled)):
                raise ModError("The mod library record contains invalid mod entries.")
            for mod_id in order:
                folder = self.root / mod_id
                if not folder.is_dir() or folder.is_symlink():
                    raise ModError("An imported mod folder is missing or invalid.")
                inspect_tree(folder)
        self.library = self.lib.open_library(manager_data(), self.version, self.load)
        state = self.library.state
        state.setdefault("profiles", {"Default": {"order": [], "enabled": []}})
        state.setdefault("selected_profile", "Default")
        profiles = state["profiles"]
        if (not isinstance(profiles, dict) or not 1 <= len(profiles) <= 64
                or not isinstance(state["selected_profile"], str)
                or state["selected_profile"] not in profiles):
            raise ModError("The mod profile record is invalid.")
        for name, profile in profiles.items():
            if (not valid_profile_name(name) or not isinstance(profile, dict)
                    or any(not isinstance(profile.get(key), list)
                           or any(not isinstance(i, str) or not MOD_ID.fullmatch(i) for i in profile[key])
                           or len(set(profile[key])) != len(profile[key]) for key in ("order", "enabled"))
                    or not set(profile["enabled"]).issubset(profile["order"])):
                raise ModError("The mod profile record is invalid.")

    def profile_command(self, args):
        state = self.library.state
        profiles = state["profiles"]
        current = state["selected_profile"]
        name = args.name.strip()
        if args.action in ("profile-create", "profile-rename"):
            if not valid_profile_name(name):
                raise ModError("Enter a profile name between 1 and 48 characters.")
            duplicate = next((existing for existing in profiles if existing.casefold() == name.casefold()), None)
            if duplicate is not None and not (args.action == "profile-rename" and duplicate == current):
                raise ModError("A profile already uses that name.")
        snapshot = {key: list(state[key]) for key in ("order", "enabled")}
        if args.action == "profile-rename":
            profiles[name] = profiles.pop(current)
        elif args.action == "profile-create":
            if len(profiles) >= 64:
                raise ModError("This game already has 64 profiles.")
            profiles[current] = snapshot
            profiles[name] = {"order": snapshot["order"], "enabled": snapshot["enabled"] if args.copy else []}
        elif name not in profiles:
            raise ModError("The selected profile no longer exists.")
        elif args.action == "profile-select":
            if name == current:
                return f"{name} is already selected.", {}
            profiles[current] = snapshot
        else:
            if len(profiles) == 1 or name != current:
                raise ModError("Select a profile to delete and keep at least one profile.")
            del profiles[current]
            name = next(iter(profiles))
        if args.action != "profile-rename":
            order = snapshot["order"]
            saved = profiles[name]
            restored = [i for i in saved["order"] if i in order]
            restored.extend(i for i in order if i not in restored)
            state["order"] = restored
            state["enabled"] = [i for i in restored if i in saved["enabled"]
                                and self.lib.validation(self.library, i).valid]
        state["selected_profile"] = name
        self.lib.save(self.library)
        return f"Profile selected: {name}.", {}

    def blocked(self):
        keyboard = self.load.with_name(self.version + "-keyboard") / "manifest.tsv"
        if self.ot_manifest is None and present(keyboard):
            return f"The keyboard overlay can take priority. Move {self.version}-keyboard out of the game’s mods folder before applying."
        manifest = self.load / "manifest.tsv"
        if self.load.is_symlink() or (present(self.load) and not self.load.is_dir()) or (present(manifest) and not regular(manifest)):
            return "Set aside the existing overlay. The game needs a real mod folder with a regular manifest."
        return None

    def state(self, ok, message, **extra):
        overlay, count = overlay_signature(self.load)
        library = self.library
        mods = self.lib.mods(library)
        requirements = dependency_issues(library, mods)
        tables = self.resource_tables()
        return {
            "ok": ok, "message": message, "version": self.install.display_version,
            "game_name": self.game.name,
            "can_make_demos": self.version == "botw160",
            "game_running": game_running(self.slot, self.game), "pending": self.pending(overlay, count, tables),
            "profiles": list(library.state["profiles"]), "selected_profile": library.state["selected_profile"],
            "applied_files": count, "blocked_reason": self.blocked(),
            "dependency_blocker": self.dependency_blocker(mods, requirements),
            "merged_paths": [mod_rstb.RESOURCE.as_posix()] if tables else [],
            "mods": [
                {"id": mod.id, "name": mod.name, "enabled": mod.enabled,
                 "valid": mod.validation.valid,
                 "description": read_description(library.path(mod.id) / DESCRIPTION_FILE),
                 "detail": VALIDATION.get(mod.validation.reason, "Ready for Switch RomFS") + (
                     " ExeFS patches and cheats are ignored." if mod.validation.code == "not_for_game"
                     or {"exefs_ignored", "cheats_ignored"}.intersection(mod.notes) else ""),
                 "replaced": mod.validation.replaced, "added": mod.validation.added,
                 "dependency_issues": requirements.get(mod.id, []),
                 "conflicts": list(mod.conflicts)}
                for mod in mods
            ],
            **extra,
        }

    def dependency_blocker(self, mods=None, issues=None):
        mods = self.lib.mods(self.library) if mods is None else mods
        issues = dependency_issues(self.library, mods) if issues is None else issues
        for mod in mods:
            if mod.enabled and mod.id in issues:
                return f"{mod.name} needs attention. " + " ".join(issues[mod.id])
        return None

    def resource_tables(self):
        if self.version != "botw160":
            return []
        state = self.library.state
        tables = []
        for mod_id in state["enabled"]:
            path = self.library.path(mod_id) / "romfs" / mod_rstb.RESOURCE
            if path.is_file():
                tables.append((state["names"].get(mod_id, mod_id), path))
        return tables if len(tables) > 1 else []

    def applied_key(self, overlay, tables):
        extra = (self.install.runtime_hash, overlay)
        if tables:
            extra += (mod_rstb.POLICY,)
        return self.applied.applied_key(self.library, extra)

    def pending(self, overlay, count, tables=None):
        state = self.library.state
        key = self.applied_key(overlay, self.resource_tables() if tables is None else tables)
        return state["applied_failed"] or (bool(count or state["enabled"]) and state["applied"] != key)

    def remove(self, mod_id):
        # Retain the imported copy, including any files added after import.
        recovery = Path(tempfile.mkdtemp(prefix=".removed-", dir=self.root))
        destination = recovery / mod_id
        self.library.path(mod_id).rename(destination)
        try:
            for profile in self.library.state["profiles"].values():
                for key in ("order", "enabled"):
                    profile[key] = [item for item in profile[key] if item != mod_id]
            self.lib.remove(self.library, mod_id)
        except Exception:
            destination.rename(self.library.path(mod_id))
            recovery.rmdir()
            raise
        return "Removed from the library. A local recovery copy is kept."

    def apply(self):
        ensure_dir(self.load.parent)
        ensure_dir(self.slot.parent)
        try:
            with lock_file(self.slot, create=True):
                if native_game_running(self.game):
                    raise ModError(f"Quit {self.game.name} before applying mods.")
                if blocked := self.blocked():
                    raise ModError(blocked)
                return self.apply_locked()
        except BlockingIOError as error:
            raise ModError(f"Quit {self.game.name} before applying mods.") from error

    def apply_locked(self):
        library = self.library
        if reason := self.dependency_blocker():
            raise ModError(reason)
        if not library.state["enabled"] and library.state["applied"] is None and not present(self.load):
            raise ModError("Enable a mod before applying. Any existing overlay stays in place.")
        check_composition_paths(library.path(mod_id) / "romfs" for mod_id in library.state["enabled"])
        before = self.load.lstat() if present(self.load) else None
        previous_overlay = overlay_signature(self.load)
        backup = None
        tables = self.resource_tables()
        with tempfile.TemporaryDirectory(prefix=".botw-editor-stage-", dir=self.load.parent) as directory:
            scratch = Path(directory)
            source = scratch / "source"
            for mod_id in library.state["enabled"]:
                check = self.tools.validate(self.install.repo, self.install.app, self.version, library.path(mod_id))
                if not check.valid:
                    raise ModError("An enabled mod no longer matches this app. Disable it or import it again before applying.")
                shutil.copytree(library.path(mod_id) / "romfs", source / "romfs",
                                dirs_exist_ok=True, copy_function=self.lib.clone_file)
            if tables:
                mod_rstb.compose(self.install.romfs, self.romfs_image, tables, source / "romfs" / mod_rstb.RESOURCE)
            staged = scratch / self.version
            if library.state["enabled"]:
                self.stage_overlay(source, staged)
            if ((self.load.lstat() if present(self.load) else None) != before
                    or overlay_signature(self.load) != previous_overlay):
                raise ModError("The active overlay changed while staging mods. Try again.")
            if blocked := self.blocked():
                raise ModError(blocked)
            if native_game_running(self.game):
                raise ModError(f"Quit {self.game.name} before applying mods.")
            previous_key, previous_failed = library.state["applied"], library.state["applied_failed"]
            if before is not None:
                backup = self.folder.backup_name(self.load)
                self.load.rename(backup)
            installed = False
            try:
                if staged.exists():
                    staged.rename(self.load)
                    installed = True
                overlay, count = overlay_signature(self.load)
                library.state["applied"] = self.applied_key(overlay, tables)
                library.state["applied_failed"] = False
                self.lib.save(library)
            except Exception:
                library.state["applied"], library.state["applied_failed"] = previous_key, previous_failed
                if installed:
                    self.load.rename(staged)
                if backup is not None and not present(self.load):
                    backup.rename(self.load)
                raise
        message = f"Applied {count} RomFS files. Open the game to load them." if count else "Mods are disabled for the next game launch."
        if tables:
            message += f" Merged resource sizes from {len(tables)} packs."
        return message, {"backup": backup.name} if backup is not None else {}

    def stage_overlay(self, source, staged):
        if self.ot_manifest:
            romfs = source / "romfs"
            lines, _, _, misspelt = self.ot_manifest.manifest(romfs, self.install.romfs)
            if misspelt or not lines:
                raise ModError("The selected mods did not produce a valid Octopath Traveler 0 overlay.")
            (romfs / "manifest.tsv").write_text(
                "# path\tsize\tsha256\toriginal_sha256\n" + "\n".join(lines) + "\n"
            )
            romfs.rename(staged)
            return
        # The Zelda installer normally stages inside the live mods folder.
        # Point it inside our private transaction until the overlay is ready.
        original = self.folder.mods_folder
        self.folder.mods_folder = lambda version: staged
        try:
            installed = self.folder.install(source, self.version, self.install.app, sys.executable,
                                            self.install.repo / "games/totk", say=lambda _: None)
        finally:
            self.folder.mods_folder = original
        if installed is None:
            raise ModError("The enabled mods produced no loadable files. Review the selected mods.")

    def run(self, args):
        action = args.action
        if action == "status":
            return "Mod library ready.", {}
        if action == "profile-export":
            return export_profile(self, args.path)
        if action == "profile-import":
            return import_profile(self, args.path)
        if action.startswith("profile-"):
            return self.profile_command(args)
        if blocked := self.blocked():
            raise ModError(blocked)
        if action == "import":
            return import_mod(self, args.path, attack=args.attack, durability=args.durability,
                              fire_capacity=args.fire_capacity), {}
        if action == "import-bnp":
            return import_bnps(self, args.paths, args.name), {}
        if action == "demos":
            if self.version != "botw160":
                raise ModError("The demos are for Breath of the Wild 1.6.0.")
            return demos(self), {}
        if action == "apply":
            return self.apply()
        if action == "prepare-launch":
            if reason := self.dependency_blocker():
                raise ModError(reason)
            if game_running(self.slot, self.game) or native_game_running(self.game):
                raise ModError(f"{self.game.name} is already running.")
            extra = {}
            if self.pending(*overlay_signature(self.load)):
                _, extra = self.apply()
            return "Profile ready to launch.", extra
        if args.id not in self.library.state["order"]:
            raise ModError("The selected mod is no longer in the library.")
        if action == "toggle":
            if args.setting == "on" and not self.lib.validation(self.library, args.id).valid:
                raise ModError("This mod is invalid for the installed game.")
            self.lib.set_enabled(self.library, args.id, args.setting == "on")
        elif action == "move":
            self.lib.move(self.library, args.id, -1 if args.direction == "up" else 1)
        elif action == "move-to":
            order = self.library.state["order"]
            if args.anchor not in order:
                raise ModError("The drop target is no longer in the library.")
            if args.id != args.anchor:
                order.remove(args.id)
                order.insert(order.index(args.anchor) + (args.side == "after"), args.id)
                enabled = set(self.library.state["enabled"])
                self.library.state["enabled"] = [item for item in order if item in enabled]
                self.lib.save(self.library)
        elif action == "remove":
            return self.remove(args.id), {}
        return "Selection saved. Choose Apply to update the next game launch.", {}


def valid_profile_name(name):
    return 1 <= len(name) <= 48 and name == name.strip() and name.isprintable()


def arguments(argv):
    parser = JSONParser()
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--repo", type=Path)
    commands = parser.add_subparsers(dest="action", required=True, parser_class=JSONParser)
    for action in ("status", "apply", "demos", "prepare-launch"):
        commands.add_parser(action)
    for action in ("profile-create", "profile-select", "profile-rename", "profile-delete"):
        profile = commands.add_parser(action)
        profile.add_argument("name")
        if action == "profile-create":
            profile.add_argument("--copy", action="store_true")
    for action in ("profile-export", "profile-import"):
        commands.add_parser(action).add_argument("path", type=Path)
    importing = commands.add_parser("import")
    importing.add_argument("path", type=Path)
    importing.add_argument("--attack", type=int)
    importing.add_argument("--durability", type=int)
    importing.add_argument("--fire-capacity", type=int)
    bnp = commands.add_parser("import-bnp")
    bnp.add_argument("--name")
    bnp.add_argument("paths", type=Path, nargs="+")
    toggle = commands.add_parser("toggle")
    toggle.add_argument("id")
    toggle.add_argument("setting", choices=("on", "off"))
    move = commands.add_parser("move")
    move.add_argument("id")
    move.add_argument("direction", choices=("up", "down"))
    reorder = commands.add_parser("move-to")
    reorder.add_argument("id")
    reorder.add_argument("anchor")
    reorder.add_argument("side", choices=("before", "after"))
    commands.add_parser("remove").add_argument("id")
    return parser.parse_args(argv)


def execute(args):
    backend = Backend(installation(args.app, args.repo))
    ensure_dir(backend.root.parent)
    try:
        with lock_file(backend.root.parent / ".lock", create=True):
            backend.open_library()
            try:
                message, extra = backend.run(args)
                return backend.state(True, message, **extra)
            except backend.find.Refused as error:
                return backend.state(False, REFUSALS.get(error.reason, "The mod package could not be safely imported."))
            except backend.folder.InstallError:
                return backend.state(False, "The game rejected the staged mod files. Check for wrong-case names or conflicting assets.")
            except ModError as error:
                return backend.state(False, str(error))
            except subprocess.TimeoutExpired:
                return backend.state(False, "The mod operation timed out. Try importing fewer packages.")
            except (OSError, ValueError):
                return backend.state(False, "Could not finish the mod operation. Check free space and file permissions.")
    except BlockingIOError as error:
        raise ModError("The mod library is busy. Wait for the current operation to finish.") from error


def main(argv=None):
    try:
        args = arguments(argv)
        with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
            result = execute(args)
    except ModError as error:
        result = {"ok": False, "message": str(error)}
    except Exception:
        result = {"ok": False, "message": "The mod library could not be opened. Check the selected game and checkout, then retry."}
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
