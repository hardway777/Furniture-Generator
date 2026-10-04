# -*- coding: utf-8 -*-
"""Headless check of the "Export FBX & Tables" operator.

Run from a Blender binary:

  blender.exe --background --python-exit-code 1 --python verify_fbx.py

This file was written BEFORE the operator existed. That order is the point:
the new build path is caught by a verification scene first and written second,
so a spec claim that does not hold fails here rather than in someone's editor.

Two names in the task spec were checked against Blender instead of trusted,
and neither survives contact with it:

  * `bpy.ops.export_scene.fbx` has no `use_sockets` keyword - passing it
    raises `TypeError: keyword "use_sockets" unrecognized`. Sockets survive
    because the SOCKET_ empties are objects linked into the BAKE collection
    and `EMPTY` is one of the exportable object types;
  * `opengl_trace` is not one of the 1033 icons in the UILayout enum.

So the assertions pin BEHAVIOUR - "the file contains the sockets" - rather
than the spelling of a keyword, which is what the caller actually cares about.

Covered here:
  * the exporter surface still offers what the operator needs, and EMPTY is
    exportable (the whole point of the operator);
  * Bake behaves exactly as it did before, both before and after the new
    operator runs - the new path must not disturb it;
  * the FBX lands at the path the user picked, is a real FBX binary, and
    carries every SOCKET_ name and every body mesh name;
  * the three tables are written NEXT TO THE FBX, in a directory of their
    own - which is the only thing that distinguishes this from plain Bake;
  * the selection is left clean.
"""
import csv
import os
import sys

import bpy

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import Files as fg
fg.register()
from Files import debug_scenes as ds

OUT = os.path.join(ROOT, ".agent_tmp", "fbx_out")
SCENES = ("full_l_kitchen", "bedside_dresser")
TABLES = ("_doors.csv", "_drawers.txt", "_shelves.csv")


def parse_csv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def build(key, props):
    sd = ds.find_debug_scene(key)
    assert sd, "no scene " + key
    problems = ds.apply_debug_scene(props, sd, bpy.context)
    assert not problems, "apply: " + "; ".join(problems)
    props.gen_collisions = True
    props.bake_name = "FBX_" + key
    props.bake_split_upper = True
    assert bpy.ops.kitchen.generate_kitchen() == {'FINISHED'}, "generate " + key


def check_exporter_surface():
    """What the operator is allowed to ask the FBX exporter for."""
    print("\n=== exporter surface ===", flush=True)
    rna = bpy.ops.export_scene.fbx.get_rna_type()
    props = {p.identifier: p for p in rna.properties
             if not p.identifier.startswith("bl_")}
    for need in ("filepath", "use_selection", "path_mode", "object_types",
                 "apply_unit_scale", "global_scale", "axis_forward", "axis_up"):
        assert need in props, "exporter no longer offers " + need

    modes = [e.identifier for e in props["path_mode"].enum_items]
    assert "COPY" in modes, "path_mode lost COPY: %r" % modes

    # Empties are how a socket reaches the engine. If EMPTY ever leaves this
    # enum the operator would silently ship a furniture set with no hinges.
    otypes = [e.identifier for e in props["object_types"].enum_items]
    assert "EMPTY" in otypes, "empties are not exportable: %r" % otypes

    icons = bpy.types.UILayout.bl_rna.functions["operator"].parameters["icon"]
    icon_names = {e.identifier for e in icons.enum_items}
    assert "EXPORT" in icon_names, "the Bake button's own icon vanished"

    # Printed, never asserted: if Blender ever grows a real `use_sockets`, or
    # the panel gains `opengl_trace`, someone should notice and switch - but
    # nothing here may go red over a name the spec invented.
    print("  exporter offers use_sockets:", "use_sockets" in props)
    print("  icon opengl_trace exists    :", "opengl_trace" in icon_names)
    print("  object_types                :", otypes)
    print("  PASS")


def check_export(key):
    print("\n=== " + key + " ===", flush=True)
    clear_scene()
    props = bpy.context.scene.kitchen_props
    build(key, props)

    blend_dir = os.path.join(OUT, key)
    fbx_dir = os.path.join(blend_dir, "fbx")
    os.makedirs(fbx_dir, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(blend_dir, key + ".blend"))

    # --- baseline: Bake on its own, before anything new runs -----------------
    assert bpy.ops.kitchen.bake_export() == {'FINISHED'}, "bake before export"
    blend_doors = os.path.join(blend_dir, props.bake_name + "_doors.csv")
    baseline = parse_csv(blend_doors)
    assert baseline, "bake produced no door rows"

    coll = bpy.data.collections.get("BAKE_" + props.bake_name)
    assert coll is not None, "no BAKE collection for " + props.bake_name
    assert not os.path.isfile(os.path.join(fbx_dir, props.bake_name + "_doors.csv")), \
        "the FBX directory must start empty, or the placement check proves nothing"

    # --- the operator --------------------------------------------------------
    fbx_path = os.path.join(fbx_dir, props.bake_name + ".fbx")
    result = bpy.ops.kitchen.export_fbx(filepath=fbx_path)
    assert result == {'FINISHED'}, "export_fbx returned %r" % (result,)

    # It must not leave the scene in a state the user did not ask for.
    still_selected = [o.name for o in bpy.context.view_layer.objects if o.select_get()]
    assert not still_selected, "left selected: %r" % still_selected[:5]

    # --- the file itself -----------------------------------------------------
    assert os.path.isfile(fbx_path), "no FBX at the path the user picked: " + fbx_path
    size = os.path.getsize(fbx_path)
    assert size > 10000, "FBX implausibly small: %d bytes" % size

    with open(fbx_path, "rb") as fh:
        data = fh.read()
    assert data[:20].startswith(b"Kaydara FBX Binary"), "not an FBX binary"

    # Re-read the collection: the operator re-bakes, so this is the state the
    # file was written from.
    coll = bpy.data.collections.get("BAKE_" + props.bake_name)
    assert coll is not None, "the operator lost the BAKE collection"
    members = list(coll.all_objects)
    sockets = sorted(o.name for o in members if o.name.startswith("SOCKET_"))
    meshes = sorted(o.name for o in members if o.type == "MESH")
    assert sockets, "no sockets to preserve"
    assert meshes, "no meshes to export"

    # FBX binary length-prefixes node names, so they sit in the file as plain
    # contiguous ASCII. Measured, not assumed - see the probe that informed
    # this test.
    lost_sockets = [s for s in sockets if s.encode("ascii") not in data]
    assert not lost_sockets, "sockets lost in the FBX: %r" % lost_sockets[:5]
    lost_meshes = [m for m in meshes if m.encode("ascii") not in data]
    assert not lost_meshes, "meshes lost in the FBX: %r" % lost_meshes[:5]

    # --- tables next to the FBX ---------------------------------------------
    for suffix in TABLES:
        path = os.path.join(fbx_dir, props.bake_name + suffix)
        assert os.path.isfile(path), "table not written next to the FBX: " + path

    fbx_doors = parse_csv(os.path.join(fbx_dir, props.bake_name + "_doors.csv"))
    assert len(fbx_doors) == len(baseline), \
        "door rows %d in the FBX dir vs %d from plain Bake" % (len(fbx_doors), len(baseline))
    assert {r["Socket"] for r in fbx_doors} == {r["Socket"] for r in baseline}, \
        "the FBX dir's doors table does not match plain Bake"

    # --- and Bake itself is untouched ---------------------------------------
    assert bpy.ops.kitchen.bake_export() == {'FINISHED'}, "bake after export"
    after = parse_csv(blend_doors)
    assert len(after) == len(baseline), \
        "Bake changed: %d rows now vs %d before" % (len(after), len(baseline))

    print("  fbx %d bytes | sockets %d/%d | meshes %d/%d | doors %d"
          % (size, len(sockets) - len(lost_sockets), len(sockets),
             len(meshes) - len(lost_meshes), len(meshes), len(fbx_doors)))
    print("  tables:", sorted(os.listdir(fbx_dir)))
    print("  PASS")


os.makedirs(OUT, exist_ok=True)
print("Blender", bpy.app.version_string)
check_exporter_surface()
for scene_key in SCENES:
    check_export(scene_key)
print("\nALL FBX EXPORT TESTS PASSED")
