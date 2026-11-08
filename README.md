# MacNative Mods

MacNative Mods is a standalone macOS mod manager for games built with [MacNativeGames](https://github.com/ly05010419/MacNativeGames). Keep multiple loadouts, arrange their load order, review conflicts, and launch the selected game with that profile applied. It runs independently of BOTW Editor.

[Download MacNative Mods](https://github.com/christianfurr/macnative-mods/releases) · [Setup and mod formats](docs/MODS.md) · [Demo and compatibility catalog](https://christianfurr.github.io/macnative-mods/)

## Get started

1. Download `MacNative.Mods.zip` from the [0.2.4 beta release](https://github.com/christianfurr/macnative-mods/releases/tag/v0.2.4), unzip it, and move **MacNative Mods.app** to Applications.
2. Use an Apple silicon Mac running macOS 26 or later, with Python 3.14 and a supported MacNativeGames helper checkout. This release accepts `b1a49a2` and `9fe3fdc`. Choose **Game tools folder…** if the app cannot locate the checkout.
3. Select the game, choose **Import…**, and enable the mods you want. Drag rows to change priority. Quit the game and choose **Apply & Launch**.

The app uses ad hoc signing. Follow Apple's [Open Anyway instructions](https://support.apple.com/en-us/102445) if macOS blocks the first launch.

## Supported games

| Game | Versions | Verification |
| --- | --- | --- |
| Breath of the Wild | 1.6.0, 1.9.0 | Two three-pack 1.6.0 loadouts reached gameplay on copied saves. Both versions passed synthetic overlay tests. |
| Tears of the Kingdom | 1.0.0, 1.2.1, 1.4.3 | Synthetic overlay tests. |
| Octopath Traveler 0 | 1.0.3, 1.0.4, 1.0.5 | Synthetic overlay tests. |

Import complete Switch RomFS packs, including merged Switch exports from BCML or UKMM. For BOTW 1.6.0, the optional BCML runtime merges compatible Switch BNPs. The [mod guide](docs/MODS.md) covers the runtime, custom OBJ replacements, generated demo mods, profiles, and recovery. Game files and third-party mod downloads come from your own installation and the mod creators.

## Build locally

Run on Apple silicon with Xcode tools and Python 3.

```sh
python3 -B scripts/test_mod_rstb.py
bash scripts/build-mod-manager.sh
```

The app, ZIP, and checksum appear under `build/`. [MIT license](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)
