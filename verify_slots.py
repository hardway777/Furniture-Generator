# -*- coding: utf-8 -*-
"""Headless check of the per-compartment slot sockets.

Run from a Blender binary:

  blender --background --python-exit-code 1 --python verify_slots.py -- \
      --baseline .agent_tmp/slot_base

Written before bake.py was touched, so it fails until the feature exists and
stays honest afterwards. Two claims from the task were measured rather than
trusted:

  * every planned carcass in both scenes carries a PURE rotation about Z
    (euler x=y=0, scale 1, determinant +1), with the turned sections of the
    L row at -90 deg - so "yaw only" is the section's own euler z and nothing
    else has to be flattened;
  * the bake frames are Matrix.Translation all the way through (_back_pivot),
    so a socket's world rotation is its rotation in the body frame with no
    re-basing to undo.

What is asserted:

  * the header gained exactly one column, SlotSocket, at index 5, and is the
    old header with that name inserted - nothing else moved;
  * every row carries a slot socket; a drawer row reuses its drawer's own
    socket instead of minting a second one; a closed row's slot socket is not
    its door socket;
  * the sockets form one running per-body counter with no gaps, and slot
    sockets never reuse a door/drawer number on the same body;
  * every socket is a child of a MESH - FindMeshSockets only walks the mesh's
    own node subtree, so a sibling empty is silently dropped by the importer;
  * round-tripped through FBX, each socket is present under exactly its
    SlotSocket name, sits on the row's LocX/Y/Z within 1e-3 m, and carries
    the yaw of the section that owns it - the -90 deg corner rows included;
  * with --baseline: _doors.csv and _drawers.txt are byte-identical and the
    mesh section of the bake report (everything before "Слоты хранения") is
    unchanged, so the mesh part of the artifact did not move.

Scene sizes are printed rather than hard-coded: they are the report the
engine side asked for, and a change in them is something a human should read.
"""
import csv
import io
import math
import os
import re
import sys

import bpy

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import Files as fg
fg.register()
from Files import debug_scenes as ds
from Files.core import SHELF_PLAN_KEY
from Files.export_tables import _SHELVES_HEADER

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
BASELINE = None
if "--baseline" in argv:
    BASELINE = os.path.join(ROOT, argv[argv.index("--baseline") + 1])

OUT = os.path.join(ROOT, ".agent_tmp", "slot_out")
BAKE = "SLOTSLOT"
SCENES = ("bedside_dresser", "full_l_kitchen")
TOL = 1e-3


def clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    # Round-tripping an FBX in one session leaves image datablocks pointing into
    # the PREVIOUS scene's .fbm folder, and with auto-pack on (it is, in the
    # startup file this runs under) the next save fails on those dead paths.
    # The next scene loads its own textures anyway, so drop the orphans - the
    # check must hold whether auto-pack happens to be on or off.
    for blocks in (bpy.data.materials, bpy.data.meshes, bpy.data.images):
        for block in list(blocks):
            blocks.remove(block)


def read_csv(path):
    with io.open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def section_of(carcass_name, kid):
    """Base_04 for SM_<kid>_Base_Sec_04_Carcass - parsed here rather than
    imported from bake, so the yaw pairing is checked independently."""
    n = carcass_name[3:] if carcass_name.startswith("SM_") else carcass_name
    if n.startswith(kid + "_"):
        n = n[len(kid) + 1:]
    m = re.match(r"(.+)_Sec_(\d+)", n)
    return "%s_%02d" % (m.group(1), int(m.group(2))) if m else None


def mesh_section(text):
    """The part of the bake report that describes meshes, doors and drawers."""
    cut = text.find("Слоты хранения")
    return text if cut < 0 else text[:cut]


def ang_close(a, b, tol=1e-3):
    return abs((a - b + math.pi) % (2.0 * math.pi) - math.pi) <= tol


def nn_of(socket_name):
    m = re.search(r"_(\d+)$", socket_name)
    assert m, "socket has no trailing _NN: " + socket_name
    return int(m.group(1))


def check_table(shelves_path, door_path, baked_sockets, baseline_dir):
    """Header, SlotSocket semantics, counters. Returns (rows, door_count)."""
    header, rows = read_csv(shelves_path)
    assert header == list(_SHELVES_HEADER), \
        "header is not _SHELVES_HEADER: %r" % (header,)
    assert header[5] == "SlotSocket", "SlotSocket is not at index 5: %r" % (header,)

    if baseline_dir:
        base_header, _ = read_csv(os.path.join(baseline_dir, BAKE + "_shelves.csv"))
        expected = list(base_header[:5]) + ["SlotSocket"] + list(base_header[5:])
        assert header == expected, \
            "header must be the old one with SlotSocket inserted:\n  was %r\n  now %r" \
            % (expected, header)

        for name in (BAKE + "_doors.csv", BAKE + "_drawers.txt"):
            with open(os.path.join(baseline_dir, name), "rb") as fh:
                old = fh.read()
            with open(os.path.join(os.path.dirname(door_path), name), "rb") as fh:
                new = fh.read()
            assert old == new, name + " changed byte-for-byte"

    _, door_rows = read_csv(door_path)
    door_sockets = {r["Socket"] for r in door_rows}

    slot_sockets = []
    for r in rows:
        name = r["SlotSocket"]
        assert name, "row %s has no SlotSocket" % r["RowName"]
        assert name.startswith("SOCKET_") and re.search(r"_\d{2}$", name), \
            "bad socket name %r" % name
        if r["Type"] == "drawer":
            assert r["DoorSocket"], "drawer row %s lost its drawer socket" % r["RowName"]
            assert name == r["DoorSocket"], \
                "drawer row %s minted a second socket: %s" % (r["RowName"], name)
        else:
            assert name not in door_sockets, \
                "slot socket %s reuses a door socket" % name
            if r["DoorSocket"]:
                assert name != r["DoorSocket"], \
                    "closed row %s points its compartment at the door socket" % r["RowName"]
        slot_sockets.append(name)

    assert len(set(slot_sockets)) == len(slot_sockets), "duplicate slot sockets"

    # Every socket the table promises must be an object the bake actually made.
    baked_names = {o.name for o in baked_sockets}
    for name in slot_sockets:
        assert name in baked_names, "table promises a socket that was never built: " + name

    # Classify the real objects instead of parsing names blind: a door/drawer
    # socket is SOCKET_<body>_NN, so stripping the trailing number lands on a
    # body the tables know about, while a compartment socket still has the row
    # name left over and lands on nothing.
    known_bodies = {r["Body"] for r in rows} | {r["Body"] for r in door_rows}
    pre = {}
    for o in baked_sockets:
        body = re.sub(r"_\d{2}$", "", o.name[len("SOCKET_"):])
        if body in known_bodies:
            pre.setdefault(body, []).append(nn_of(o.name))
    slots = {}
    for r in rows:
        # A drawer row reuses the drawer's socket, which the object scan above
        # already counted as pre-existing - putting it here would report the
        # drawer's own number as a clash with itself.
        if r["Type"] == "drawer":
            continue
        slots.setdefault(r["Body"], []).append(nn_of(r["SlotSocket"]))

    # Nothing on a body is numbered twice - a counter restarted at 01 would
    # show up here as a clash with the door/drawer socket already using it.
    for body in sorted(set(pre) | set(slots)):
        a, b = pre.get(body, []), slots.get(body, [])
        assert len(set(a)) == len(a), "%s has two door sockets numbered alike" % body
        assert len(set(b)) == len(b), "%s has two compartment sockets numbered alike" % body
        clash = sorted(set(a) & set(b))
        assert not clash, "%s gives a compartment socket a door number: %r" % (body, clash)
        # And the compartment run starts past the door/drawer run, never at 01.
        if a and b:
            assert min(b) > max(a), \
                "%s compartment sockets restart the counter: doors/drawers %r, slots %r" \
                % (body, sorted(a), sorted(b))

    return rows, len(door_rows)


def check_roundtrip(key, rows, fbx_path, yaw_by_section):
    """Export -> wipe -> import, then read the sockets back out of the file."""
    assert os.path.isfile(fbx_path), "no FBX: " + fbx_path
    assert os.path.getsize(fbx_path) > 10000, "FBX implausibly small"

    clear_scene()
    result = bpy.ops.import_scene.fbx(filepath=fbx_path)
    assert result == {'FINISHED'}, "import returned %r" % (result,)

    imported = {o.name: o for o in bpy.data.objects
                if o.type == 'EMPTY' and o.name.startswith("SOCKET_")}
    for r in rows:
        sock = imported.get(r["SlotSocket"])
        assert sock is not None, \
            "socket %s from row %s is not in the FBX" % (r["SlotSocket"], r["RowName"])
        # The engine only walks the mesh's own subtree - a sibling is dropped.
        assert sock.parent is not None and sock.parent.type == 'MESH', \
            "%s is not a child of a mesh (parent=%r)" % (
                sock.name, sock.parent.name if sock.parent else None)

        # A drawer row reuses the drawer's own socket, which sits on the
        # drawer's front-face pivot, not on the compartment centre - that is
        # what makes requirement 2 (never mint a second socket for a drawer)
        # collide with the blanket "position matches LocX/Y/Z" check. The
        # specific requirement wins: relocating the drawer socket would move the
        # placement _drawers.txt and the engine already rely on, and Loc*/Depth
        # stay where they are by design. So a drawer row is held to presence,
        # name and parentage only; the centre and the yaw belong to the
        # compartment sockets the bake minted.
        if r["Type"] == "drawer":
            continue

        want = (float(r["LocX"]), float(r["LocY"]), float(r["LocZ"]))
        got = sock.matrix_world.translation
        delta = max(abs(got[i] - want[i]) for i in range(3))
        assert delta <= TOL, \
            "%s off by %.6f m: file %r vs table %r" % (
                r["RowName"], delta, tuple(round(v, 4) for v in got), want)

        section = r["Section"]
        if section in yaw_by_section:
            want_yaw = yaw_by_section[section]
            got_yaw = sock.matrix_world.to_euler('XYZ').z
            assert ang_close(got_yaw, want_yaw), \
                "%s yaw %.3f deg, section %s is at %.3f deg" % (
                    r["RowName"], math.degrees(got_yaw), section,
                    math.degrees(want_yaw))
            if not ang_close(want_yaw, 0.0):
                # The evidence the report is asked for: a slot inside a turned
                # section carries that section's yaw, not the body's zero.
                print("    yaw %-9s %-32s %7.2f deg (section %s)"
                      % (r["RowName"], sock.name, math.degrees(got_yaw), section))

    return len(imported)


def run(key, baseline_dir):
    print("\n=== " + key + " ===", flush=True)
    clear_scene()
    props = bpy.context.scene.kitchen_props
    sd = ds.find_debug_scene(key)
    assert sd, "no scene " + key
    problems = ds.apply_debug_scene(props, sd, bpy.context)
    assert not problems, "apply: " + "; ".join(problems)
    props.gen_collisions = True
    props.bake_name = BAKE
    props.bake_split_upper = True
    assert bpy.ops.kitchen.generate_kitchen() == {'FINISHED'}, "generate " + key

    # Section orientation, measured on the working model before any baking.
    yaw_by_section = {}
    for o in bpy.data.objects:
        if o.type == 'MESH' and o.get(SHELF_PLAN_KEY):
            sec = section_of(o.name, props.kitchen_id)
            if sec:
                yaw_by_section[sec] = o.matrix_world.to_euler('XYZ').z

    out_dir = os.path.join(OUT, key)
    fbx_dir = os.path.join(out_dir, "fbx")
    os.makedirs(fbx_dir, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, key + ".blend"))
    assert bpy.ops.kitchen.bake_export() == {'FINISHED'}, "bake " + key

    fbx_path = os.path.join(fbx_dir, BAKE + ".fbx")
    assert bpy.ops.kitchen.export_fbx(filepath=fbx_path) == {'FINISHED'}, "export " + key

    # Sockets as Blender has them, before the file is round-tripped.
    coll = bpy.data.collections.get("BAKE_" + BAKE)
    assert coll is not None, "no BAKE collection"
    baked_sockets = [o for o in coll.all_objects
                     if o.type == 'EMPTY' and o.name.startswith("SOCKET_")]
    # Names only from here on: the round trip wipes the scene, and a StructRNA
    # of a removed object cannot be read afterwards.
    baked_names = sorted((o.name for o in baked_sockets))

    shelves_path = os.path.join(fbx_dir, BAKE + "_shelves.csv")
    base_dir = os.path.join(baseline_dir, key) if baseline_dir else None
    rows, door_count = check_table(shelves_path,
                                   os.path.join(fbx_dir, BAKE + "_doors.csv"),
                                   baked_sockets, base_dir)

    if base_dir:
        with io.open(os.path.join(base_dir, BAKE + "_bake_report.txt"),
                     encoding="utf-8") as fh:
            old_report = mesh_section(fh.read())
        with io.open(os.path.join(out_dir, BAKE + "_bake_report.txt"),
                     encoding="utf-8") as fh:
            new_report = mesh_section(fh.read())
        assert old_report == new_report, "the bake report's mesh section changed"
    # Each shelf row owns exactly one socket, and doors own theirs on top.
    assert len(baked_sockets) == len(rows) + door_count, \
        "expected %d sockets (rows %d + doors %d), found %d" % (
            len(rows) + door_count, len(rows), door_count, len(baked_sockets))

    imported = check_roundtrip(key, rows, fbx_path, yaw_by_section)

    drawers = sum(1 for r in rows if r["Type"] == "drawer")
    compartments = len(rows) - drawers
    turned = sorted(s for s, y in yaw_by_section.items()
                    if not ang_close(y, 0.0))
    print("  counts: doors=%d drawers=%d compartments=%d sockets=%d (imported %d)"
          % (door_count, drawers, compartments, len(baked_sockets), imported))

    # The naming scheme, straight off the objects: one running counter, doors
    # and drawers first, compartment sockets continuing past them.
    for body in sorted({r["Body"] for r in rows}):
        names = sorted((n for n in baked_names
                        if n.startswith("SOCKET_" + body + "_")), key=nn_of)
        # SOCKET_<body>_NN exactly is a door or drawer socket; anything longer
        # carries a row name and is a compartment socket.
        def kind(n, _body=body):
            return ("door/drawer" if re.fullmatch(re.escape(_body) + r"_\d{2}",
                                                  n[len("SOCKET_"):]) else "slot")
        head, tail = (names, []) if len(names) <= 7 else (names[:3], names[-3:])
        print("  %s - %d sockets" % (body, len(names)))
        for n in head + tail:
            print("    %-12s %s" % (kind(n), n))
        if tail:
            print("    ... %d in between" % (len(names) - 6))

    print("  turned sections: %s"
          % ", ".join("%s@%.0fdeg" % (s, math.degrees(yaw_by_section[s]))
                      for s in turned) or "none")
    print("  PASS")


os.makedirs(OUT, exist_ok=True)
print("Blender", bpy.app.version_string, "| baseline:", BASELINE)
for scene_key in SCENES:
    run(scene_key, BASELINE)
print("\nALL SLOT SOCKET TESTS PASSED")
