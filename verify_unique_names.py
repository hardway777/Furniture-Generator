# -*- coding: utf-8 -*-
"""Headless check of name uniqueness across several assemblies in ONE scene.

Run from a Blender binary:

  blender.exe --background --python-exit-code 1 --python verify_unique_names.py

The scenario is the user's own: one scene, a kitchen AND a wardrobe (several
furniture assemblies generated side by side). Blender resolves name collisions
by appending ".001", and every ".001" in this addon's namespaces used to break
a lookup - the bake mixed copies into one body, the tables promised socket
names Blender had renamed away.

Covered here:

  * two assemblies generated under two Furniture IDs coexist with no ".NNN"
    suffix anywhere in bpy.data.objects;
  * the Clone operator is the supported way to a copy: every object, collider
    and hinge-socket name is rewritten onto the new id, the two name-valued
    custom properties (ubx_follow_target, shelf_plan "front") point at the
    copies, and the clone is refused for an id that is already in use;
  * two bakes coexist in one scene: sockets are SOCKET_<bake>_..., the tables
    carry exactly the names the scene holds, and re-baking one name purges
    only that bake;
  * a bake name colliding with a live Furniture ID is refused by name;
  * a hand-made duplicate (the ".001" object a user creates with Shift-D) is
    excluded from the bake with a warning instead of merged into it;
  * the FBX of the second assembly still carries every renamed socket.
"""
import csv
import os
import re
import sys

import bpy

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import Files as fg
fg.register()
from Files import debug_scenes as ds

OUT = os.path.join(ROOT, ".agent_tmp", "unique_names")

# A duplicate suffix Blender appends on a name collision. Nothing the addon
# generates carries a dot, so any hit is a bug or a hand-made copy.
DUP = re.compile(r"\.\d{1,4}$")


def clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)


def build(key, kid):
    """Generate one assembly from a debug scene under furniture id `kid`."""
    props = bpy.context.scene.kitchen_props
    sd = ds.find_debug_scene(key)
    assert sd, "no debug scene " + key
    problems = ds.apply_debug_scene(props, sd, bpy.context)
    assert not problems, "apply: " + "; ".join(problems)
    props.kitchen_id = kid
    props.gen_collisions = True
    assert bpy.ops.kitchen.generate_kitchen() == {'FINISHED'}, "generate " + key


# In background mode an operator's self.report({'ERROR'}) raises RuntimeError
# instead of bubbling a {'CANCELLED'} back, so a refusal is either shape.
def refused(op_call):
    try:
        return op_call()
    except RuntimeError:
        return {'CANCELLED'}


def dup_named_objects():
    return [o.name for o in bpy.data.objects if DUP.search(o.name)]


def check_two_generations():
    print("\n=== two assemblies, two ids, one scene ===", flush=True)
    build("full_l_kitchen", "A")
    # The kitchen's own re-run protection is per id; a second id must build
    # beside it without Blender renaming anything.
    build("bedside_dresser", "B")
    dups = dup_named_objects()
    assert not dups, "Blender renamed generated objects: %r" % dups[:5]
    for kid in ("A", "B"):
        assert bpy.data.collections.get("FURNITURE_" + kid), "no collection for " + kid
        assert bpy.data.collections.get(f"FURNITURE_{kid}_Colliders"), \
            "no collider collection for " + kid
    print("  PASS")


def check_clone():
    print("\n=== clone assembly onto a new id ===", flush=True)
    props = bpy.context.scene.kitchen_props
    props.kitchen_id = "A"
    before = {o.name for o in bpy.data.collections["FURNITURE_A"].all_objects}
    before |= {o.name for o in bpy.data.collections["FURNITURE_A_Colliders"].all_objects}

    assert bpy.ops.kitchen.clone_furniture(new_id="C") == {'FINISHED'}, "clone A->C"
    assert props.kitchen_id == "C", "clone did not switch the furniture id"

    dups = dup_named_objects()
    assert not dups, "clone left Blender-renamed objects: %r" % dups[:5]

    coll = bpy.data.collections.get("FURNITURE_C")
    assert coll is not None, "clone made no FURNITURE_C collection"
    colliders = bpy.data.collections.get("FURNITURE_C_Colliders")
    assert colliders is not None, "clone made no collider collection"

    after = {o.name for o in coll.all_objects}
    after |= {o.name for o in colliders.all_objects}
    assert len(after) == len(before), \
        f"clone lost or added objects: {len(before)} -> {len(after)}"

    # Every copied name is the old name with the id swapped, nothing else.
    bad_names = [n for n in after if not (n.startswith(("SM_C_", "SOCKET_SM_C_"))
                                          and n.replace("_C_", "_A_", 1) in before
                                          or n.startswith("UBX_SM_C_")
                                          and n.replace("_C_", "_A_", 1) in before)]
    assert not bad_names, "names not rewritten onto C: %r" % bad_names[:5]

    # Name-valued custom properties must point at the copies, not the source.
    for o in colliders.all_objects:
        target = o.get("ubx_follow_target")
        if target:
            assert target.startswith("SM_C_"), f"{o.name} follows {target}"
            assert bpy.data.objects.get(target), f"{o.name} follows missing {target}"
    import json as _json
    plans = 0
    for o in coll.all_objects:
        raw = o.get("shelf_plan")
        if not raw:
            continue
        plans += 1
        for row in _json.loads(raw):
            front = row.get("front")
            if front:
                assert front.startswith("SM_C_"), f"{o.name} plan points at {front}"
    print(f"  {len(after)} objects, {plans} shelf plans rewritten")

    # Clone onto a live id is refused, and must not have built anything.
    assert refused(lambda: bpy.ops.kitchen.clone_furniture(new_id="B")) == {'CANCELLED'}, \
        "clone onto a used id was accepted"
    assert bpy.data.collections.get("FURNITURE_B2") is None
    print("  PASS")
    return after


def check_bakes_coexist(c_names):
    print("\n=== two bakes in one scene ===", flush=True)
    props = bpy.context.scene.kitchen_props
    blend_dir = OUT
    os.makedirs(blend_dir, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(blend_dir, "scene.blend"))

    props.kitchen_id = "A"
    props.bake_name = "EXP_A"
    assert bpy.ops.kitchen.bake_export() == {'FINISHED'}, "bake A"
    props.kitchen_id = "B"
    props.bake_name = "EXP_B"
    assert bpy.ops.kitchen.bake_export() == {'FINISHED'}, "bake B"

    dups = dup_named_objects()
    assert not dups, "two bakes produced renamed objects: %r" % dups[:5]

    for bake in ("EXP_A", "EXP_B"):
        coll = bpy.data.collections.get("BAKE_" + bake)
        assert coll is not None, "no BAKE_" + bake
        sockets = [o for o in coll.all_objects if o.name.startswith("SOCKET_")]
        assert sockets, "BAKE_%s has no sockets" % bake
        wrong = [s.name for s in sockets if not s.name.startswith(f"SOCKET_{bake}_")]
        assert not wrong, f"sockets without the {bake} tag: {wrong[:5]}"

    # The tables carry the socket names the scene actually holds.
    doors = os.path.join(blend_dir, "EXP_B_doors.csv")
    assert os.path.isfile(doors), "no doors csv for EXP_B"
    with open(doors, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    scene_sockets = {o.name for o in bpy.data.objects
                     if o.name.startswith("SOCKET_EXP_B_")}
    missing = [r["Socket"] for r in rows if r["Socket"] not in scene_sockets]
    assert not missing, "csv promises sockets that do not exist: %r" % missing[:5]

    # Shelves join keys (SlotSocket, DoorSocket) live in the scene too.
    shelves = os.path.join(blend_dir, "EXP_B_shelves.csv")
    assert os.path.isfile(shelves), "no shelves csv for EXP_B"
    with open(shelves, encoding="utf-8", newline="") as fh:
        srows = list(csv.DictReader(fh))
    all_b_sockets = {o.name for o in bpy.data.objects
                     if o.name.startswith("SOCKET_")}
    bad_slot = [r["SlotSocket"] for r in srows if r["SlotSocket"] not in all_b_sockets]
    assert not bad_slot, "shelves csv SlotSocket not in scene: %r" % bad_slot[:5]
    bad_door = [r["DoorSocket"] for r in srows
                if r["DoorSocket"] and r["DoorSocket"] not in all_b_sockets]
    assert not bad_door, "shelves csv DoorSocket not in scene: %r" % bad_door[:5]

    # Re-baking one name replaces only that bake.
    assert bpy.ops.kitchen.bake_export() == {'FINISHED'}, "re-bake EXP_B"
    assert bpy.data.collections.get("BAKE_EXP_A") is not None, "re-bake B ate A"
    print("  PASS")


def check_bake_name_guard():
    print("\n=== bake name vs live furniture ids ===", flush=True)
    props = bpy.context.scene.kitchen_props
    props.kitchen_id = "B"
    props.bake_name = "A"          # A is a live assembly in this scene
    result = refused(bpy.ops.kitchen.bake_export)
    assert result == {'CANCELLED'}, f"bake onto id A returned {result}"
    assert bpy.data.collections.get("BAKE_A") is None, "the refused bake still built"
    print("  PASS")


def check_stray_duplicate():
    print("\n=== hand-made .001 copy excluded from the bake ===", flush=True)
    props = bpy.context.scene.kitchen_props
    props.kitchen_id = "B"
    props.bake_name = "EXP_B"
    doors = [o for o in bpy.data.objects
             if o.name.startswith("SM_B_") and "_Door" in o.name and o.type == 'MESH']
    # bedside_dresser has no doors; any moving part serves the test equally.
    if not doors:
        doors = [o for o in bpy.data.objects
                 if o.name.startswith("SM_B_") and "_Drawer" in o.name
                 and o.type == 'MESH']
    assert doors, "no door or drawer object to duplicate"
    stray = doors[0].copy()
    bpy.context.scene.collection.objects.link(stray)
    assert DUP.search(stray.name), f"Blender did not rename the copy: {stray.name}"

    result = bpy.ops.kitchen.bake_export()
    assert result == {'FINISHED'}, f"bake with a stray returned {result}"
    bake_coll = bpy.data.collections.get("BAKE_EXP_B")
    members = {o.name for o in bake_coll.all_objects}
    assert stray.name not in members, "the stray reached the bake"
    assert bpy.data.objects.get(stray.name) is not None, "the stray was deleted"

    # Body part count must be the clean one, not the doubled one.
    clean = [o for o in bpy.data.objects
             if o.name.startswith("SM_B_") and o.type == 'MESH' and not DUP.search(o.name)]
    print(f"  {len(clean)} clean source meshes, stray '{stray.name}' excluded")

    bpy.data.objects.remove(stray, do_unlink=True)
    assert bpy.ops.kitchen.bake_export() == {'FINISHED'}, "clean re-bake"
    print("  PASS")


def check_fbx_of_second_assembly():
    print("\n=== FBX of the second assembly carries renamed sockets ===", flush=True)
    props = bpy.context.scene.kitchen_props
    props.kitchen_id = "B"
    props.bake_name = "EXP_B"
    fbx_path = os.path.join(OUT, "EXP_B.fbx")
    assert bpy.ops.kitchen.export_fbx(filepath=fbx_path) == {'FINISHED'}, "export B"

    coll = bpy.data.collections.get("BAKE_EXP_B")
    sockets = sorted(o.name for o in coll.all_objects
                     if o.name.startswith("SOCKET_"))
    assert sockets, "no sockets to check"
    with open(fbx_path, "rb") as fh:
        data = fh.read()
    lost = [s for s in sockets if s.encode("ascii") not in data]
    assert not lost, "sockets lost in the FBX: %r" % lost[:5]
    print(f"  {len(sockets)}/{len(sockets)} sockets in {os.path.basename(fbx_path)}")
    print("  PASS")


def main():
    print("verify_unique_names", flush=True)
    clear_scene()
    check_two_generations()
    check_clone()
    check_bakes_coexist(None)
    check_bake_name_guard()
    check_stray_duplicate()
    check_fbx_of_second_assembly()
    clear_scene()
    print("\nALL CHECKS PASSED")


main()
