# MacNative Mods

MacNative Mods manages Switch RomFS mods in a separate macOS app. It uses Apple silicon, macOS 26 or later, Python 3.14, and a clean MacNativeGames helper checkout at [`b1a49a2`](https://github.com/ly05010419/MacNativeGames/tree/b1a49a26650eb31a986e7841f449bb44446c5208) or [`9fe3fdc`](https://github.com/ly05010419/MacNativeGames/tree/9fe3fdc1d08ce5e1a64d120f257d79cc2dc7c0ca). Open the app, select an installed game, and choose **Game tools folder…** if the checkout could not be detected.

| Game | Versions | Verification |
| --- | --- | --- |
| Breath of the Wild | 1.6.0, 1.9.0 | 1.6.0 used with the installed game. Both versions passed synthetic overlay tests. |
| Ocarina of Time (Switch 2) | 1.1.1 (131072) | Short Kokiri Intro verified against the installed native build. |
| Tears of the Kingdom | 1.0.0, 1.2.1, 1.4.3 | Synthetic import, manifest, apply, backup and disable tests. |
| Octopath Traveler 0 | 1.0.3, 1.0.4, 1.0.5 | Synthetic import, manifest, apply, backup and disable tests. |

Each game version gets its own library. On first opening BOTW 1.6.0, MacNative Mods copies the library from the former editor tab and preserves its enabled order.

Download [MacNative Mods 0.2.5](https://github.com/christianfurr/macnative-mods/releases/tag/v0.2.5) or build it with `bash scripts/build-mod-manager.sh`. The app is ad hoc signed. For a downloaded copy, use the standard [macOS Open Anyway flow](https://support.apple.com/guide/mac-help/open-a-mac-app-from-an-unknown-developer-mh40616/mac) if macOS requests it.

## Import and apply

1. Open **MacNative Mods**, select a game, and choose **Import…**. Use **Add Game…** to select a build outside Applications. Select a folder, ZIP, or 7z containing complete Switch RomFS files.
2. Select an imported pack and turn on its **Enable** switch. Use **Move up** or **Move down** to set its priority. When enabled packs contain the same RomFS path, the later pack generally supplies the whole file. Distinct paths combine.
3. Quit the selected game and click **Apply & Launch**. The manager prepares the overlay and opens the selected app. **Apply** prepares the overlay separately.
4. Use the search box and **Enabled** or **Needs Attention** filters to find packs. The inspector shows which enabled pack supplies each shared file.

Drag a mod’s grip to the upper or lower half of another row to place it before or after that mod. The numbers show the full load order even when a filter is active. With a mod row focused, use **Up/Down** to select, **Space** to toggle, **Delete** to open the removal confirmation, or **Command–Up/Down** to reorder. **Command–F** focuses search. The keyboard button in the library shows the same shortcuts.

## Profiles

Version 0.2.0 starts with a **Default** profile containing your existing selections and order. The profile menu lets you create an empty loadout, duplicate the current loadout, rename it, or delete it. The library of imported packs is shared across profiles for the same game version. Each profile remembers its own switches and order. Profile changes apply on the next launch after you choose **Apply & Launch** or **Apply**. The launch bar shows the selected profile and the profile used to prepare the current overlay. An overlay from an older release or an external tool may show as **Untracked overlay** until you click **Apply**. An empty profile prepares the game with mods disabled. Game saves are shared across profiles.

Use **Export current profile…** in the profile menu to create a `.macnativeprofile` file. It contains the game version and the enabled packs in order, identified by name and content fingerprint. To use **Import profile…** on another Mac, first import the matching packs into the same game version's library. The manager lists any missing or different packs and keeps your existing profile selected until the import succeeds.

### Dependencies

RomFS pack authors can put a UTF-8 `macnative-mod.json` beside the `romfs` folder. Use the required packs' displayed library names.

```json
{"requires": ["Base Pack"]}
```

The inspector reports whether a required pack is missing, disabled, or incompatible. An enabled add-on with an unmet requirement blocks **Apply** and **Apply & Launch**. BCML checks dependencies declared by BNPs while it merges them.

To include a description, put a UTF-8 `README.md` or `README.txt` beside the pack's `romfs` folder. The first paragraph under the title appears in the mod details pane.

For BOTW 1.6.0, choose **Add demo mods** to generate **Explore Menu** and **Moonlit Apples** from your own installed game. Explore Menu changes the US English title screen's **Continue** label to **Explore!**. Moonlit Apples recolors the Apple icon in the game's Materials pouch. The source contains the generator. The resulting files stay in the private mod library.

### Ocarina of Time

Use a MacNativeGames OoT v131072 build. Both bundled game data and an external MacNativeGames game-data library are supported. Select OoT, then use **Setup → Game tools folder…** to choose a checkout with the OoT mod tools at `ca3c4ad6`. This choice is separate from the checkout used by other games.

Import Switch 2 RomFS replacements for title ID `0400486024DEC000`. Choose **Import → Add Short Kokiri Intro demo** to generate the cutscene pack from your local app. Enable it, close the game, click **Apply & Launch**, then choose **New Game**. It shortens the bundled opening movie and event. The other opening scenes and the game’s progression still play. If you use the native `OOT_AUTO_SKIP_OPENING` test flag, turn off the demo pack to avoid loading the same replacements twice.

Use **Import → Add Water Temple Wall Fix** to generate a replacement normal map from your own game image. You can also import the [PlayStation, Xbox, or Steam Deck button prompt packs](https://github.com/exgde/oot-switch2-button-prompts/releases/tag/v1.2) as ZIPs. Enable only one prompts pack because they replace the same files.

Other Switch 2 packs that passed the manager's path validation include [Young Link's Gear](https://gamebanana.com/mods/738670), [1998 Hookshot](https://gamebanana.com/mods/738662), [Classic Link Voice](https://gamebanana.com/mods/738175), and [Restored Temple of Time Chants](https://gamebanana.com/mods/738678). Import them as downloaded. Check the game in a disposable save before combining new packs.

The [OoT remake modding project](https://github.com/Kabosune/oot-remake-modding) publishes first-person, FPV drone, and mouse-grab code mods. Those use executable patches and need a separate native port.

## Custom weapon models

MacNative Mods imports triangulated Wavefront OBJ files for supported equipment in Switch BOTW 1.6.0. Import one of the [original demo meshes](../Assets/Models), or give your own OBJ the same filename pattern as `Weapon_Sword_001 - My Sword.obj`. The part after ` - ` becomes the mod name. Enable the mod and click **Apply & Launch** with the game closed. Equip the corresponding weapon in BOTW to see the model.

| Weapon | Filename prefix | Triangle limit | Vertex limit after splitting |
| --- | --- | ---: | ---: |
| Traveler’s Sword | `Weapon_Sword_001` | 88 | 466 |
| Traveler’s Claymore | `Weapon_Lsword_001` | 269 | 1,451 |
| Traveler’s Spear | `Weapon_Spear_001` | 129 | 560 |
| Wooden Shield | `Weapon_Shield_001` | 495 | 1,676 |
| Flameblade blade | `Weapon_Sword_033` | 86 | 307 |
| Frostblade blade | `Weapon_Sword_034` | 47 | 171 |
| Thunderblade blade | `Weapon_Sword_035` | 112 | 509 |

Use the demo OBJs as scale and orientation references. For the sword and spear, place the grip around the origin and extend the blade or shaft toward positive Z in the exported file. Export triangles with UV coordinates in the 0–1 range. Hard edges and UV seams can split a single OBJ position into multiple game vertices. The importer generates flat normals when the OBJ omits them.

Both in-game levels of detail use your mesh. The converter reuses the weapon's material, texture atlas, attachment points, animation, and inventory icon. The OBJ can supply geometry, normals and UVs. Compiled Switch model packs with custom materials or textures can use the existing `romfs/Model/` folder workflow and should include any required resource-size updates. The app builds OBJ replacements privately using the original weapon file from the installed game.

**Crescent Saber** and **Sunwheel Spear** were both equipped and visually checked in BOTW 1.6.0 using a copy of the save. The Traveler's Claymore and Wooden Shield templates passed conversion and buffer checks against the same installation.

### Flameblade stats and fire

In MacNative Mods 0.1.2, importing `Weapon_Sword_033 - Cinderfang.obj` opens the **Customize Flameblade** sheet. Set attack and durability from 1 to 255 and fire capacity from 1 to 8. Leaving a field blank uses the original value. To reproduce **Cinderfang**, enter **58 attack**, **100 durability**, and **8 fire capacity**. Use a freshly acquired Flameblade to get the new starting durability.

The OBJ replaces the blade and leaves the original hilt in place. Charged attacks use the game’s fire behavior, with the original recharge logic. Capacity scales the fire energy reserve from the stock four units. The inventory keeps the Flameblade name and icon. Attack or durability changes replace the shared actor table, so apply one mod that edits that table at a time unless their changes have been merged.

**Cinderfang** was verified in BOTW 1.6.0 at 58 attack and 100 starting durability. A charged swing ignited a dropped wood bundle and the nearby grass on a separate copy of the save. **Rimeglass** and **Stormfork** are Frostblade and Thunderblade model mods. They retain their original stats, elemental effects, and hilts, and can be enabled alongside Cinderfang.

## Folder layouts

Use the selected game’s base title ID. The examples use BOTW’s `01007EF00011E000`. A mod can arrive in any of these layouts. You can select a `romfs` folder directly, and a flat folder with recognizable RomFS roots such as `Actor`, `Pack`, or `UI` also works.

| Layout | Example inside the selected folder or archive |
| --- | --- |
| Mod folder | `My Mod/romfs/Actor/…` |
| Emulator mod folder | `contents/01007EF00011E000/My Mod/romfs/Actor/…` |
| Atmosphère or merged Switch export | `atmosphere/contents/01007EF00011E000/romfs/Actor/…` or `01007EF00011E000/romfs/Actor/…` |

The standard importer accepts complete base-game Switch RomFS files. Use the BCML import below for raw `.bnp` packages. Wii U and Cemu layouts, separate DLC-title overlays, ExeFS patches, and cheat codes are outside the standard workflow. An otherwise usable mixed pack applies its RomFS files and reports that the code is skipped. For an export that contains a DLC-title folder, extract it and choose the base-title folder separately. Use a base export whose changes work on their own.

## BCML and UKMM

For **BOTW 1.6.0**, run `bash scripts/setup-bcml-runtime.sh` once from a checkout or extracted source archive of this repository with `uv`, CMake and Xcode command-line tools available. Choose **Import → Merge BCML BNP packs…**, select the Switch BNPs that belong together, and put the base mod first. **Merge & Import** runs BCML and adds the combined base-game export as one library entry. It uses package defaults and US English. DLC-title files are left out. Allow temporary space for a copy of the installed game resources plus 2 GB.

For a downloaded BNP, Finder’s **Open With → MacNative Mods** opens the same review screen. For a recipe with several packs, select the whole set in the app so you can review their order together.

**BCML merged Switch exports are supported.** In BCML configured for Switch, select your mods, click **Remerge**, then **Export**. Import the resulting ZIP, 7z, or extracted base-title folder in the manager. Export converts BCML's input packages into complete replacement files. [BCML export guide](https://github.com/NiceneNerd/BCML/blob/master/docs/export.md)

UKMM can also merge and deploy Switch RomFS files. In Switch mode, apply your order and deploy the merged output to a local directory. The **Without Name** deployment layout produces the title-ID folder shown above. Import its base-title folder or `romfs` directory. [UKMM deployment manual](https://nicenenerd.github.io/UKMM/setup/deploy.html)

Use BCML or UKMM before importing if you need to combine edits to different records inside one archive or resource. The manager’s priority rule picks one whole file for each shared path.

In **BOTW 1.6.0**, the resource-size table is an exception. When more than one enabled mod supplies it, the manager combines their changes against the installed game’s table. It keeps the largest requested allocation for a shared entry and preserves agreed removals. If packs disagree about removing an entry or supply an invalid table, Apply stops and keeps the previously applied overlay.

## Validation and recovery

In 0.2.5, use **Setup…** in the sidebar to check Python, the game build, and the MacNativeGames tools together. The recovery menu beside **Apply** lets you launch without mods or restore the latest previous overlay and launch it. Both actions leave the selected profile and load order intact. A regular **Apply & Launch** prepares the selected profile again. **Copy launch report…** previews the last launch attempt, including the game version, selected profile, load order, and any startup error the app observed.

Import checks the package layout and validates its paths against the installed game. A usable pack replaces at least one existing file and may also add files. Apply revalidates the enabled packs and stages a manifest with the replacement sizes and hashes and the corresponding stock-file hashes. This confirms path and file integrity. A visible in-game check establishes whether a given mod works with that build, including its resource allocation and dependencies. Supply the matching resource size table when a BOTW resource grows. Both demos fit their original resource sizes. [MacNativeGames RomFS loader](https://github.com/ly05010419/MacNativeGames/blob/b1a49a26650eb31a986e7841f449bb44446c5208/docs/mods.md#breath-of-the-wild)

The active overlay is under `~/Library/Application Support/MacNativeGames/BotW/mods/botw160`. Apply keeps the previous folder beside it as `botw160.backup-*`. **Show backup** reveals it in Finder. To restore one, quit BOTW, move the current `botw160` folder aside if present, rename the chosen backup to `botw160`, then reopen the game. If the manager reports a keyboard-specific overlay, set aside `botw160-keyboard` before applying. That overlay can take priority at launch.

The loaders use the selected game and version folder under MacNativeGames Application Support. [Zelda overlay documentation](https://github.com/ly05010419/MacNativeGames/blob/b1a49a26650eb31a986e7841f449bb44446c5208/docs/mods.md) · [Octopath overlay documentation](https://github.com/ly05010419/MacNativeGames/blob/b1a49a26650eb31a986e7841f449bb44446c5208/games/ot0/README.md)
