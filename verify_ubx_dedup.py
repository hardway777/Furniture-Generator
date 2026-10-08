# -*- coding: utf-8 -*-
"""Headless check: Bake must not multiply UBX colliders on deduplicated meshes.

Run from a Blender binary:

  blender.exe --background --python-exit-code 1 --python verify_ubx_dedup.py

The bake joins identical doors/drawers into one unique mesh, but every SOURCE
instance in the working model carries its own collider set. The collider pass
used to clone each instance's set under the shared mesh name, so three
identical drawers (5 colliders each) handed UE one mesh with 15 boxes - three
overlapping copies of the same collision. UE reads every UBX_<Mesh>_NN into
the static mesh's collision, so nothing on the engine side hides the stack.

The assertion pinned here is the one the FBX pair actually needs: a unique
mesh wears exactly ONE collider set - the canonical source's - whatever the
number of instances sharing it. Which instances share which mesh is read from
the bake's own tables (_doors.csv / _drawers.csv, Source -> Mesh), never
recomputed here: the tables are the contract.
"""
import csv
import os
import shutil
import sys

import bpy

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import Files as fg
fg.register()
from Files import debug_scenes as ds
from Files.bake import _is_moving_name

OUT = os.path.join(ROOT, ".agent_tmp", "ubx_out")
SCENES = ("full_l_kitchen", "bedside_dresser")

# Same epsilon class the generator's own placements use; two colliders closer
# than this in every number are the same box written twice, not two boxes.
EPS = 1e-6


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
    props.bake_name = "UBXFIX_" + key
    props.bake_split_upper = True
    assert bpy.ops.kitchen.generate_kitchen() == {'FINISHED'}, "generate " + key


def moving_root_of(target):
    """The door/drawer root a collider's target hangs under, bake's own walk."""
    node = target
    root = node if _is_moving_name(node.name) else None
    while root is None and node.parent is not None:
        node = node.parent
        if node.type == 'MESH' and _is_moving_name(node.name):
            root = node
    return root


def working_colliders(kid):
    """Working-model colliders split into per-root sets and the body remainder."""
    prefix = f"UBX_SM_{kid}_"
    by_name = {o.name: o for o in bpy.data.objects}
    per_root, body = {}, []
    for u in sorted((o for o in bpy.data.objects if o.name.startswith(prefix)),
                    key=lambda o: o.name):
        target = by_name.get(u.name[len("UBX_"):].rsplit("_", 1)[0])
        assert target is not None and target.type == 'MESH', \
            "working collider without a mesh target: " + u.name
        root = moving_root_of(target)
        if root is None:
            body.append(u.name)
        else:
            per_root.setdefault(root.name, []).append(u.name)
    return per_root, body


def baked_colliders(bake):
    """Baked colliders grouped by the unique mesh name they belong to."""
    groups = {}
    prefix = f"UBX_SM_{bake}_"
    for o in bpy.data.objects:
        if not o.name.startswith(prefix):
            continue
        owner = o.name[len("UBX_"):].rsplit("_", 1)[0]
        groups.setdefault(owner, []).append(o)
    return groups


def box_key(obj):
    loc, rot, scl = obj.matrix_world.decompose()
    dims = tuple(sorted((obj.dimensions.x, obj.dimensions.y, obj.dimensions.z)))
    return (tuple(round(v, 5) for v in loc),
            tuple(round(q, 5) for q in rot),
            tuple(round(v, 5) for v in scl),
            tuple(round(v, 4) for v in dims))


def check_scene(key):
    print("\n=== " + key + " ===", flush=True)
    clear_scene()
    props = bpy.context.scene.kitchen_props
    build(key, props)
    kid = props.kitchen_id
    bake = props.bake_name

    # Tables land next to the .blend, and headless has none until saved.
    blend_dir = os.path.join(OUT, key)
    os.makedirs(blend_dir, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(blend_dir, key + ".blend"))

    assert bpy.ops.kitchen.bake_export() == {'FINISHED'}, "bake " + key

    per_root, body_ubx = working_colliders(kid)

    # Source -> Mesh straight from the bake's own tables.
    src_to_mesh = {}
    for suffix in ("_doors.csv", "_drawers.csv"):
        for row in parse_csv(os.path.join(blend_dir, bake + suffix)):
            src_to_mesh[row["Source"]] = row["Mesh"]
    assert src_to_mesh, "no moving-part rows in the tables for " + key

    instances = {}
    for src, mesh in src_to_mesh.items():
        instances.setdefault(mesh, []).append(src)

    groups = baked_colliders(bake)
    dedup_seen = 0
    for mesh, sources in sorted(instances.items()):
        counts = [len(per_root.get(s, [])) for s in sources]
        assert len(set(counts)) == 1, \
            f"{mesh}: instances disagree on collider counts {counts}"
        baked = groups.get(mesh, [])
        assert len(baked) == counts[0], \
            f"{mesh}: {len(baked)} baked colliders for {counts[0]} per instance " \
            f"({len(sources)} instances) - duplicates are back"
        keys = [box_key(o) for o in baked]
        assert len(set(keys)) == len(keys), \
            f"{mesh}: two baked colliders occupy the same box"
        if len(sources) > 1 and counts[0] > 0:
            dedup_seen += 1
            print(f"  {mesh}: {len(sources)} instances x {counts[0]} colliders "
                  f"-> {len(baked)} baked (one set)")
        # The FBX naming rule needs one running counter with no gaps: NN is
        # minted in clone order, so a gap would mean a collider was cloned and
        # then lost, not merely skipped.
        nums = sorted(int(o.name.rsplit("_", 1)[1]) for o in baked)
        assert nums == list(range(1, len(baked) + 1)), \
            f"{mesh}: collider numbers are not 1..N: {nums}"

    # The body keeps every collider it owns: deduplication only ever applies to
    # moving parts, whose instances share one mesh.
    split_upper = bool(props.bake_split_upper)
    body_name, upper_name = f"SM_{bake}_Body", f"SM_{bake}_UpperBody"
    expected_body = [n for n in body_ubx if "_Upper_" not in n]
    expected_upper = [n for n in body_ubx if "_Upper_" in n]
    assert len(groups.get(body_name, [])) == len(expected_body), \
        f"body colliders {len(groups.get(body_name, []))} != {len(expected_body)} working"
    if split_upper:
        assert len(groups.get(upper_name, [])) == len(expected_upper), \
            f"upper colliders {len(groups.get(upper_name, []))} != {len(expected_upper)} working"

    # A re-bake must replace, not accumulate: the purge path is what stands
    # between two exports and doubled colliders on the second one.
    assert bpy.ops.kitchen.bake_export() == {'FINISHED'}, "re-bake " + key
    again = baked_colliders(bake)
    for mesh in instances:
        assert len(again.get(mesh, [])) == len(groups.get(mesh, [])), \
            f"{mesh}: re-bake changed its collider count"
    assert len(again.get(body_name, [])) == len(expected_body), \
        "re-bake changed the body collider count"

    print(f"  body colliders: {len(expected_body)}, upper: {len(expected_upper)}")
    print("  PASS")
    return dedup_seen


shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT, exist_ok=True)
print("Blender", bpy.app.version_string)
dedup_cases = 0
for scene_key in SCENES:
    dedup_cases += check_scene(scene_key)
# The whole check is about shared meshes: if no scene in the run deduplicated
# anything with colliders on it, the assertions above proved nothing.
assert dedup_cases > 0, \
    "no scene in the run had a shared moving mesh with colliders"
print("\nALL UBX DEDUP TESTS PASSED")
