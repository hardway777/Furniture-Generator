# Furniture Modular Generator

Furniture Modular Generator is a procedural modeling tool for Blender designed for environment artists, level designers, and archviz creators. It allows you to quickly build parametric modular kitchens, wardrobes, and living room storage directly in Blender, with dedicated pipelines for game engines such as Unreal Engine.

Russian version: [README.ru.md](README.ru.md)

## Features

- Procedural furniture generation for modular kitchen layouts, wardrobes, and storage systems
- Flexible section combinations for standard cabinets, corner cabinets, islands, sink modules, and appliances
- Support for straight, L-shaped, and U-shaped layouts
- Built-in export pipeline for game engines, including Unreal Engine bake tools and collision generation
- PBR material support with automatic texture linking and custom material sets
- Live preview updates while modifying parameters
- Preset management for storing and reusing configurations and debug scenarios

## Installation

1. Download the latest build from `BUILD/FurnitureGenerator-<version>.zip`
2. Open Blender and go to `Edit → Preferences → Add-ons`
3. Click `Install from Disk...` and choose the downloaded archive
4. Enable the `Furniture Generator` add-on

This add-on is designed for Blender 5.2 and newer.

## Quick Start

1. Open Blender and create a new scene
2. Open the right-side panel (`N` panel) and select the `Furniture` tab
3. Set the main cabinet parameters such as depth, height, and section count
4. Click `Generate` to create the furniture layout
5. Use the debug panel to load built-in test scenarios and verify geometry quickly

### Common Parameters

- Depth — cabinet depth
- Height — base cabinet height
- Section Count — number of modular sections
- Live Preview — automatic regeneration when values change
- Wall Thickness — thickness of cabinet walls and panels

## Project Structure

```text
Files/                          # Main add-on package
├── __init__.py                 # Entry point and class registration
├── core.py                     # Shared constants and utility functions
├── strings.py                  # Localized UI text table
├── properties.py               # RNA properties and preset logic
├── operators.py                # Generation and preset operators
├── panels.py                   # N-panel UI panels
├── primitives.py               # Mesh primitives and geometry builders
├── mesh_ops.py                 # Mesh ops, materials, and UBX colliders
├── sections.py                 # Section generation logic
├── row.py                      # Row assembly and layout logic
├── solver.py                   # Parameter solver for cabinet sizing
├── debug_scenes.py             # Debug presets and scenario loader
├── bake.py                     # UE export / bake pipeline
├── export_tables.py            # Doors CSV / drawers TXT engine tables
├── blender_manifest.toml       # Add-on manifest and version
├── gpl-3.0.txt                 # License file
└── textures/                   # User PBR texture sets
    ├── materials.txt           # Material-to-texture mapping
    └── your_texture_files

build_zip.py                    # Build the installable zip archive
lock.py                         # File-based lock system for cooperative editing
verify_*.py                     # Verification scripts
probe_*.py                      # Geometry probes and diagnostic checks
CODE_MAP.md                     # Detailed code map
FILES.md                        # Project file map
AGENT_NOTES.md                  # Durable project notes
AGENT_TASKS.md                  # Work tracking and status
HISTORY.md                      # Development changelog
README.ru.md                    # Russian version of this README
```

For detailed function-level documentation, see `CODE_MAP.md`.

## Section Types

- Standard section — regular cabinet with doors or drawers
- Corner section — specialized 90° corner layout
- Island section — furniture placed away from the wall
- Sink section — cabinet with a sink opening
- Wardrobe section — storage layout with shelves and hanging rods
- Appliance section — specialized base for integrated fixtures

## Unreal Engine Export

Use the `Bake` operation to prepare generated models for export:

1. Open the `Bake` panel
2. Set the asset prefix, for example `Kitchen_01`
3. Optionally split upper cabinets
4. Click `Bake for UE`

The output includes:

- Unified body meshes for static geometry
- Separate meshes for doors and drawers
- UBX collision meshes for physics workflows
- Empty socket objects for export references
- A generated report file describing the bake results
- `<bake>_doors.csv` with every door, the socket it hangs on, its panel size
  and socket transform — import it directly as a UE DataTable
- `<bake>_drawers.txt` listing the maximum travel of each drawer
- `<bake>_shelves.csv` with one row per storage slot — one invisible box per
  functional compartment: the whole niche behind its doors, one single drawer,
  the surface of a countertop, the air under a hanging rod, an entire open
  rack. Shelves and dividers inside a compartment never split its box. Each row
  carries the section, the body, the socket of the opening that reaches it (a
  door socket for a niche, the drawer's own socket for a drawer, empty for an
  open front), the centre and extents in the body frame, the maximum volume in
  litres, and — for a drawer only — its travel depth. Clear repeats Ext: these
  boxes are what the engine turns into its "item inside" collider

## PBR Materials

To add custom PBR materials:

1. Place files inside `Files/textures/`
2. Name them according to your material set, for example:
   - `T_WoodDark_01_BaseColor.jpg`
   - `T_WoodDark_01_Normal.png`
   - `T_WoodDark_01_Roughness.png`
   - `T_WoodDark_01_Metallic.png`
3. Update `Files/textures/materials.txt` to map material names to the texture sets
4. Material nodes are automatically linked when the model is generated

## Development and Validation

Run validation checks from the project root:

```bash
blender --background --python-exit-code 1 --python verify_shelves.py
cmd /c build_zip.cmd
```

See `AGENT_NOTES.md` for repository-specific rules, conventions, and validation details.

## Design Notes

### Colliders

- Collision objects are kept in a dedicated child collection instead of mixed into the visible furniture objects
- UBX colliders are regenerated and realigned after layout changes
- Collision generation can be disabled for preview-only workflows

### Corners and Islands

- Corner and island layouts are mutually exclusive by design
- Corner dimensions are derived from neighboring sections rather than user-defined planar values
- Islands do not receive wall upstands or standard wall-based trim behavior

### Module Import Rules

The codebase follows a stable import order to avoid circular dependencies:

```text
strings → core → mesh_ops → primitives → solver
                                  ↓
                    sections ← row
                       ↓
           properties ← operators
                ↓
        debug_scenes ← panels ← __init__.py
```

See `AGENT_NOTES.md` for the exact rules and caveats.

## License

This project is distributed under the GNU General Public License v3. See `Files/gpl-3.0.txt`.

## Author

hardway777 — https://github.com/hardway777

## Support

For issues or feature requests, open an issue in the repository.

---

Version is read from `Files/blender_manifest.toml`.
