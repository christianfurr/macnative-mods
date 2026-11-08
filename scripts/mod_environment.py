"""Validate the installed Switch app and coordinate with its native game slot."""

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import stat
import subprocess

PINNED_COMMIT = "b1a49a26650eb31a986e7841f449bb44446c5208"
SUPPORTED_CHECKOUTS = {PINNED_COMMIT, "9fe3fdc1d08ce5e1a64d120f257d79cc2dc7c0ca"}

@dataclass(frozen=True)
class Game:
    name: str
    data_folder: str
    title_id: str
    resources: str
    runtime: str
    versions: dict[str, str]


GAMES = {
    "org.macnativegames.botw": Game(
        "Breath of the Wild", "BotW", "01007EF00011E000", "totk", "totk-native",
        {"1.6.0": "botw160", "1.9.0": "botw190"},
    ),
    "org.macnativegames.totk": Game(
        "Tears of the Kingdom", "TOTK", "0100F2C0115B6000", "totk", "totk-native",
        {"1.0.0": "v0", "1.2.1": "v121", "1.4.3": "v143"},
    ),
    "org.macnativegames.ot0": Game(
        "Octopath Traveler 0", "OT0", "01005270232F2000", "game", "ot0-native",
        {"1.0.3": "v103", "1.0.4": "v104", "1.0.5": "v105"},
    ),
}


class ModError(Exception):
    pass


@dataclass(frozen=True)
class Installation:
    repo: Path
    app: Path
    game: Game
    version: str
    display_version: str
    romfs: Path
    runtime_hash: str

    @property
    def game_data(self):
        return Path.home() / "Library/Application Support/MacNativeGames" / self.game.data_folder


def manager_data():
    return Path.home() / "Library/Application Support/MacNativeMods"


def legacy_data():
    return Path.home() / "Library/Application Support/BOTWEditor"


def present(path):
    return path.exists() or path.is_symlink()


def regular(path):
    return stat.S_ISREG(path.lstat().st_mode)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def legacy_repo():
    records = legacy_data() / "Installations"
    for path in sorted(records.glob("*.json"), reverse=True):
        try:
            if not regular(path) or path.stat().st_size > 1 << 20:
                continue
            record = json.loads(path.read_text())
            if (record["schema"] == 1 and record["status"] == "installed"
                    and record["macnativegames_commit"] == PINNED_COMMIT):
                repo = Path(record["repo"])
                if repo.is_absolute() and repo.is_dir():
                    return repo
        except (OSError, TypeError, ValueError, KeyError):
            continue
    return None


def verify_checkout(repo):
    git = subprocess.run(["/usr/bin/git", "-C", str(repo), "rev-parse", "HEAD"],
                         capture_output=True, text=True, timeout=10)
    if git.returncode or git.stdout.strip() not in SUPPORTED_CHECKOUTS:
        raise ModError("Choose a supported MacNativeGames checkout at b1a49a2 or 9fe3fdc.")
    tools = ("tools/builder", "tools/__init__.py", "games/totk/scripts",
             "games/ot0/scripts/make_mod_manifest.py")
    status = subprocess.run(["/usr/bin/git", "--no-optional-locks", "-C", str(repo), "status", "--porcelain",
                             "--untracked-files=all", "--", *tools], capture_output=True, timeout=10)
    if status.returncode or status.stdout:
        raise ModError("Restore the original MacNativeGames mod tools in the selected checkout.")


def installation(app, repo=None):
    try:
        app = app.expanduser().resolve(strict=True)
        info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
        game = GAMES.get(info.get("CFBundleIdentifier"))
        display = info.get("CFBundleShortVersionString")
        version = game.versions.get(display) if game else None
        if not version:
            raise ModError("Choose a supported MacNativeGames app and version.")
        resources = app / "Contents/Resources" / game.resources
        extracted = resources / "extracted"
        versions = {item.name for item in extracted.iterdir() if item.is_dir()} - {"firmware"}
        romfs = extracted / version / "romfs"
        runtime_name = f"{game.runtime}-{version}" if game.resources == "game" else game.runtime
        runtime = resources / "build" / runtime_name
        if (versions != {version} or not regular(romfs / "runtime-index.bin") or not regular(runtime)
                or (game.resources == "game" and info.get("OT0Version") != version)):
            raise ModError("The app's game files do not match its advertised version.")
        if repo is None:
            stamped = info.get("MNGSourceRepo")
            if isinstance(stamped, str):
                candidate = Path(stamped)
                if candidate.is_absolute() and candidate.is_dir():
                    try:
                        verify_checkout(candidate)
                    except ModError:
                        pass
                    else:
                        repo = candidate
            repo = repo or legacy_repo()
        if repo is None:
            raise ModError("Choose your MacNativeGames checkout to use its RomFS tools.")
        repo = repo.expanduser().resolve(strict=True)
        verify_checkout(repo)
        return Installation(repo, app, game, version, display, romfs, digest(runtime))
    except (OSError, TypeError, ValueError, AttributeError, plistlib.InvalidFileException, subprocess.TimeoutExpired) as error:
        raise ModError("The selected game app or MacNativeGames checkout could not be verified.") from error


def ensure_dir(path):
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ModError("A mod support folder is not a real directory.")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)


@contextmanager
def lock_file(path, *, create):
    flags = (os.O_RDWR | os.O_CREAT) if create else os.O_RDONLY
    descriptor = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise ModError("The mod lock file is invalid.")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = path.lstat()
        if (current.st_dev, current.st_ino) != (details.st_dev, details.st_ino):
            raise ModError("The mod lock changed while opening it. Try again.")
        yield
    finally:
        os.close(descriptor)


def native_game_running(game):
    # Direct development launches may use a different game-slot directory.
    result = subprocess.run(["/bin/ps", "-axo", "comm="], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise ModError("Could not check whether the game is running.")
    return any(Path(line.strip()).name.startswith(game.runtime) for line in result.stdout.splitlines())


def game_running(slot, game):
    try:
        with lock_file(slot, create=False):
            return native_game_running(game)
    except BlockingIOError:
        return True
    except FileNotFoundError:
        return native_game_running(game)


def overlay_signature(folder):
    manifest = folder / "manifest.tsv"
    if folder.is_symlink() or (present(manifest) and not regular(manifest)):
        return None, 0
    if not manifest.is_file():
        return None, 0
    with manifest.open(encoding="utf-8", errors="replace") as stream:
        count = sum(bool(line.strip()) and not line.startswith("#") for line in stream)
    checksum = hashlib.sha256(digest(manifest).encode())
    # Use file identity and content timestamps. macOS can change directory
    # timestamps during a game launch without changing any loadable files.
    for root, dirs, files in os.walk(folder, followlinks=False):
        dirs.sort()
        for name in sorted(files):
            path = Path(root) / name
            st = path.lstat()
            entry = (path.relative_to(folder).as_posix(), st.st_dev, st.st_ino,
                     st.st_mode, st.st_size, st.st_mtime_ns)
            checksum.update(json.dumps(entry).encode())
    return checksum.hexdigest(), count
