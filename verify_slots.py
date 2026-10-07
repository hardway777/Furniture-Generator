# -*- coding: utf-8 -*-
"""Headless check of the per-compartment sockets and the drawer sockets.

Run from a Blender binary:

  blender --background --python-exit-code 1 --python verify_slots.py -- \
      --baseline .agent_tmp/slot_base

Written before bake.py was touched, so it fails until the feature exists and
stays honest afterwards.

Naming, as agreed - SOCKET_<for-whom>_<NN>:

  Door<NN>         for the unique door mesh SM_<bake>_Door_<NN>
  Drawer<NN>       for the unique drawer mesh SM_<bake>_Drawer_<NN>
  DrawerCol<NN>    for the collision component of that same drawer mesh
  <RowName>        for the compartment that row describes

<NN> is still one running counter per parent mesh - doors and drawers take it
first, compartment sockets continue past them, so a number is never worn
twice. Only the owner text changed: it says who the socket is FOR, not which
mesh it hangs off, because the scene hierarchy already answers whose it is.

Asserted:

  * every socket parses as SOCKET_<owner>_<NN> and its owner says what it is
    for; the owner of a collision socket carries the index of the drawer mesh
    it sits on, and a compartment socket's owner is a real RowName;
  * classification comes from the HIERARCHY, not from the name: a socket whose
    parent is a drawer mesh is a collision socket, a socket whose parent is a
    body is either a door/drawer mount or a compartment socket;
  * one running counter per body with no gaps or repeats, and compartment
    sockets never restart at 01 or wear a door number;
  * a drawer row's SlotSocket is the collision socket on the drawer mesh - a
    different socket from its mount (DoorSocket) - and with the drawer closed
    it lands on the row's LocX/Y/Z within 1e-3 m, which is what makes it a
    compartment centre rather than an arbitrary point;
  * round-tripped through FBX: the socket is present under exactly its
    SlotSocket name, parented to a MESH (FindMeshSockets only walks the mesh's
    own subtree, so a sibling is dropped without a word), and a compartment
    socket carries the yaw of the section that owns it - the -90 deg corner
    rows included;
  * baked twice over: the second run's socket names are the first run's, byte
    for byte, with no .001 anywhere - the purge reaches sockets through
    parenthood now that no name prefix carries the bake, and a purge that
    missed one would stay silent until a table promised a name the file does
    not have;
  * every concrete socket name written in NOTE_FOR_KODA.MD is one the bake
    actually makes - the note is what the engine side codes against, so an
    example that is not in the file is worse than no example;
  * a drawers.csv is written and every Type=drawer row of _shelves.csv
    resolves into it - the mesh a drawer component is built from has to be
    machine-readable, not a field of prose in _drawers.txt, and nothing may
    dangle in either direction (no row pointing at prose, no CSV row nobody
    wants, no disagreement with the human file about which drawers exist);
  * with --baseline: the tables and the bake report may differ ONLY in socket
    names - everything else (mesh list, dimensions, transforms, materials) is
    compared with socket names masked out, so a real change still fails.

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
from Files.export_tables import _DRAWERS_HEADER, _SHELVES_HEADER

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
BASELINE = None
if "--baseline" in argv:
    BASELINE = os.path.join(ROOT, argv[argv.index("--baseline") + 1])

OUT = os.path.join(ROOT, ".agent_tmp", "slot_out")
BAKE = "SLOTSLOT"
SCENES = ("bedside_dresser", "full_l_kitchen")
TOL = 1e-3

# SOCKET_<owner>_NN, where owner itself may contain underscores.
NAME_RE = re.compile(r"^SOCKET_(.+)_(\d{2})$")
MOUNT_OWNER_RE = re.compile(r"^(Door|Drawer)(\d{2})$")
COL_OWNER_RE = re.compile(r"^DrawerCol(\d{2})$")
DRAWER_MESH_RE = re.compile(r"^SM_%s_Drawer_(\d{2})$" % BAKE)
# Everything that is a socket name, for masking before a baseline diff.
SOCKET_TOKEN_RE = re.compile(r"SOCKET_\S+")


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


def split_socket(name):
    """(owner, NN) - owner is everything between SOCKET_ and the trailing _NN."""
    m = NAME_RE.match(name)
    assert m, "socket name is not SOCKET_<owner>_NN: " + name
    return m.group(1), int(m.group(2))


def nn_of(name):
    return split_socket(name)[1]


def mask(text):
    """Socket names redacted, so a baseline diff sees only what else moved."""
    return SOCKET_TOKEN_RE.sub("SOCKET_", text)


def assert_only_socket_names_changed(label, old_path, new_path, transform=mask):
    with open(old_path, "rb") as fh:
        old = fh.read()
    with open(new_path, "rb") as fh:
        new = fh.read()
    try:
        old_t = transform(old.decode("utf-8"))
        new_t = transform(new.decode("utf-8"))
    except UnicodeDecodeError:
        old_t, new_t = old, new
    assert old_t == new_t, label + " changed in more than its socket names"


def check_baseline(base_dir, fbx_dir, out_dir):
    """The artifact may move only where a socket name is written down."""
    for name in (BAKE + "_doors.csv", BAKE + "_drawers.txt"):
        assert_only_socket_names_changed(
            name, os.path.join(base_dir, name), os.path.join(fbx_dir, name))
    # _drawers.csv postdates this snapshot, so there is nothing to compare it
    # against yet - but the moment the baseline is refreshed it must come under
    # the same rule. Testing for the OLD file rather than remembering to edit
    # this list is what makes that happen: a missing file means "not covered",
    # an expired condition would have meant "silently skipped forever".
    name = BAKE + "_drawers.csv"
    if os.path.isfile(os.path.join(base_dir, name)):
        assert_only_socket_names_changed(
            name, os.path.join(base_dir, name), os.path.join(fbx_dir, name))
        print("  baseline: %s compared" % name)
    else:
        print("  baseline: %s predates this file, checked structurally instead"
              % name)
    assert_only_socket_names_changed(
        "the bake report's mesh section",
        os.path.join(base_dir, BAKE + "_bake_report.txt"),
        os.path.join(out_dir, BAKE + "_bake_report.txt"),
        transform=lambda t: mask(mesh_section(t)))


def check_note(known):
    """Every concrete socket name the contract shows must be a real one.

    NOTE_FOR_KODA.MD is what the engine side codes against, so an example that
    is not in the file is worse than no example - someone writes code to it.
    Only names that look finished are checked: SOCKET_<ForWhom>_NN is a
    pattern, not an example, and an elision is not worth chasing.
    """
    path = os.path.join(ROOT, "NOTE_FOR_KODA.MD")
    if not os.path.isfile(path):
        return
    text = io.open(path, encoding="utf-8").read()
    concrete = {n for n in set(re.findall(r"SOCKET_[A-Za-z0-9_]+", text))
                if re.search(r"_\d{2}$", n)}
    unknown = sorted(concrete - set(known))
    assert not unknown, \
        "NOTE_FOR_KODA.MD shows socket names the bake does not make: %r" % unknown
    print("  note: %d concrete socket names, all real" % len(concrete))


def check_table(shelves_path, door_path, baked, objects, baseline_dir):
    """Header, SlotSocket semantics, counters. Returns (rows, door_count, meshes).

    `baked` is every socket in the bake; `objects` is everything else in it as
    well, because whose a socket is turns on the hierarchy - and a drawer's
    collision socket is named after the drawer mesh it sits on, so that mesh has
    to be reachable to be named."""

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

    _, door_rows = read_csv(door_path)
    door_sockets = {r["Socket"] for r in door_rows}
    row_names = {r["RowName"] for r in rows}

    # Every name in the table is a name the bake actually made.
    by_name = {o.name: o for o in objects}
    for r in rows:
        assert r["SlotSocket"], "row %s has no SlotSocket" % r["RowName"]
        assert r["SlotSocket"] in by_name, \
            "table promises a socket that was never built: " + r["SlotSocket"]
        if r["DoorSocket"]:
            assert r["DoorSocket"] in by_name, \
                "table promises a door socket that was never built: " + r["DoorSocket"]

    slot_sockets = []
    for r in rows:
        name = r["SlotSocket"]
        owner, _ = split_socket(name)
        sock = by_name[name]
        parent = sock.parent.name if sock.parent else None
        assert parent, "%s has no parent" % name
        is_mesh = sock.parent.type == "MESH"
        assert is_mesh, "%s is not a child of a mesh (parent=%r)" % (name, parent)

        if r["Type"] == "drawer":
            # The compartment component lives on the drawer, so it must ride
            # the drawer mesh - not the mount socket, which stays on the body
            # and would not follow the drawer out.
            assert r["DoorSocket"], "drawer row %s lost its mount socket" % r["RowName"]
            assert name != r["DoorSocket"], \
                "drawer row %s still points its compartment at the mount socket" % r["RowName"]
            m = COL_OWNER_RE.match(owner)
            assert m, "drawer row %s SlotSocket owner is %r, want DrawerCol<NN>" % (
                r["RowName"], owner)
            dm = DRAWER_MESH_RE.match(parent)
            assert dm, "collision socket %s sits on %r, not a drawer mesh" % (name, parent)
        else:
            assert name not in door_sockets, \
                "slot socket %s reuses a door socket" % name
            assert owner in row_names, \
                "compartment socket %s names %r, which is no RowName" % (name, owner)
        slot_sockets.append(name)

    # A compartment socket is one per row - except drawers, which all hang on
    # the one shared drawer mesh and therefore share its collision socket.
    unique_slots = [n for n, r in zip(slot_sockets, rows) if r["Type"] != "drawer"]
    assert len(set(unique_slots)) == len(unique_slots), "duplicate compartment sockets"

    # Classification by hierarchy: whose socket it is is a scene fact, and the
    # name only has to agree with it. A socket either hangs on a body - a door or
    # drawer mount, or a compartment - or on a drawer mesh, which is where a
    # compartment component has to live if it is to travel with the drawer.
    bodies = {r["Body"] for r in rows} | {r["Body"] for r in door_rows}
    drawer_meshes = sorted(o.name for o in objects
                           if o.type == "MESH" and DRAWER_MESH_RE.match(o.name))
    parents = []
    for o in baked:
        parent = o.parent.name if o.parent else None
        assert parent, "%s is a root socket" % o.name
        if parent in drawer_meshes or parent in bodies:
            parents.append(parent)
        else:
            raise AssertionError("%s hangs on unexpected parent %r" % (o.name, parent))

    # Nothing on a mesh is numbered twice, and the compartment run starts past
    # the door/drawer run rather than restarting at 01.
    moving, slots = {}, {}
    for r in rows:
        if r["Type"] == "drawer":
            continue
        slots.setdefault(r["Body"], []).append(nn_of(r["SlotSocket"]))
    for o in baked:
        owner, nn = split_socket(o.name)
        if o.parent and o.parent.name in drawer_meshes:
            continue
        if MOUNT_OWNER_RE.match(owner) or o.name in door_sockets:
            moving.setdefault(o.parent.name, []).append(nn)

    for parent in sorted(set(parents) | set(slots)):
        a_all, b_all = moving.get(parent, []), slots.get(parent, [])
        a, b = sorted(set(a_all)), sorted(set(b_all))
        assert len(a) == len(a_all), "%s has two mount sockets numbered alike" % parent
        assert len(b) == len(b_all), \
            "%s has two compartment sockets numbered alike" % parent
        clash = sorted(set(a) & set(b))
        assert not clash, "%s gives a compartment socket a mount number: %r" % (parent, clash)
        if a and b:
            assert min(b) > max(a), \
                "%s compartment sockets restart the counter: mounts %r, slots %r" \
                % (parent, a, b)

    # Exactly one collision socket per drawer mesh, named for that mesh and
    # first on it - a second would be a placement the engine has to choose
    # between, which is the ambiguity this naming exists to remove.
    for mesh in drawer_meshes:
        idx = DRAWER_MESH_RE.match(mesh).group(1)
        on_mesh = sorted((o.name for o in baked
                          if o.parent is by_name.get(mesh)), key=nn_of)
        assert len(on_mesh) == 1, \
            "%s carries %r, want exactly one collision socket" % (mesh, on_mesh)
        owner, nn = split_socket(on_mesh[0])
        assert owner == "DrawerCol" + idx and nn == 1, \
            "%s carries %s, want SOCKET_DrawerCol%s_01" % (mesh, on_mesh[0], idx)

    # Every drawer row's compartment socket lands on its own Loc once the
    # drawer is closed - that is the whole claim about "the centre".
    for r in rows:
        if r["Type"] != "drawer":
            continue
        mount = by_name[r["DoorSocket"]]
        trig = by_name[r["SlotSocket"]]
        want = (float(r["LocX"]), float(r["LocY"]), float(r["LocZ"]))
        got = (mount.matrix_world @ trig.matrix_world).translation
        delta = max(abs(got[i] - want[i]) for i in range(3))
        assert delta <= TOL, \
            "%s trigger off by %.6f m once closed: %r vs %r" % (
                r["RowName"], delta, tuple(round(v, 4) for v in got), want)

    return rows, len(door_rows), drawer_meshes


def check_drawers_csv(path, txt_path, rows, objects):
    """A drawer row must be able to name its mesh without reading prose.

    The engine enumerates compartments from _shelves.csv, and a drawer row
    there carries the mount socket but not the asset the component is built
    from. Until now the only file that said which mesh was _drawers.txt - a
    human document whose wording is free to move, and which a machine reader
    would have to parse.

    The fix is a CSV twin of the doors table rather than a column on the
    shelves header, and both halves of that choice are measured, not
    assumed: the shelves table ALREADY reaches across files for its door
    (DoorSocket joins into doors.csv on five rows of full_l_kitchen), so a
    second join of exactly that shape leaves a drawer row no more
    self-contained than a closed one instead of making it a special case;
    and the shelves header is fixed by contract to have SlotSocket as its
    only added column, which a DrawerMesh column would break outright.

    What has to hold is that nothing dangles in either direction: every
    shelves drawer row resolves to a mesh, every drawers.csv row is wanted
    by one, and the human file agrees about which drawers exist at all.
    """
    assert os.path.isfile(path), "no drawers CSV (Q6 unanswered): " + path
    header, drows = read_csv(path)
    assert header == list(_DRAWERS_HEADER), \
        "drawers header is not _DRAWERS_HEADER: %r" % (header,)

    # The doors table's own invariant, mirrored: RowName is the socket, so a
    # row is a valid DataTable row and the join key appears twice on purpose.
    for d in drows:
        assert d["RowName"] == d["Socket"], \
            "drawers row %s breaks RowName == Socket" % d["RowName"]
    sockets = [d["Socket"] for d in drows]
    assert len(set(sockets)) == len(sockets), "duplicate sockets in drawers.csv"

    by_socket = {d["Socket"]: d for d in drows}
    meshes = {o.name for o in objects if o.type == "MESH"}
    wanted = set()
    for r in rows:
        if r["Type"] != "drawer":
            continue
        assert r["DoorSocket"], "drawer row %s lost its mount socket" % r["RowName"]
        d = by_socket.get(r["DoorSocket"])
        assert d is not None, \
            "drawer row %s points %s at nothing machine-readable - its mesh " \
            "exists only in prose" % (r["RowName"], r["DoorSocket"])
        assert d["Mesh"] in meshes, \
            "drawers.csv promises mesh %s, which was never baked" % d["Mesh"]
        assert d["Body"] == r["Body"], \
            "%s sits on %s in shelves.csv but %s in drawers.csv" % (
                r["RowName"], r["Body"], d["Body"])
        # Both files format Depth to four places from the same travel value,
        # so string equality is exact: a mismatch means they stopped being
        # computed the same way rather than rounded differently.
        assert d["Depth"] == r["Depth"], \
            "%s Depth %r in drawers.csv, %r in shelves.csv" % (
                r["RowName"], d["Depth"], r["Depth"])
        wanted.add(r["DoorSocket"])

    orphans = sorted(set(sockets) - wanted)
    assert not orphans, \
        "drawers.csv describes drawers no shelf row wants: %r" % orphans

    # The human file and the machine one are written in the same pass, so
    # they cannot drift by accident - only by someone rewording one of them.
    txt = io.open(txt_path, encoding="utf-8").read()
    unmentioned = sorted(s for s in sockets if s not in txt)
    assert not unmentioned, \
        "_drawers.txt no longer mentions %r" % unmentioned

    print("  drawers.csv: %d rows, %d resolved from shelves, all meshes real"
          % (len(drows), len(wanted)))


def check_roundtrip(key, rows, fbx_path, yaw_by_section, baked_names):
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

        # A drawer's compartment socket rides the drawer, so its position in
        # the file is relative to that mesh, not to the body: what has to hold
        # is that closing the drawer puts it back on the row's Loc.
        if r["Type"] == "drawer":
            mount = imported.get(r["DoorSocket"])
            assert mount is not None, "mount %s missing from the FBX" % r["DoorSocket"]
            assert mount.parent.name == r["Body"], \
                "mount %s hangs on %r, want %r" % (
                    r["DoorSocket"], mount.parent.name, r["Body"])
            want = (float(r["LocX"]), float(r["LocY"]), float(r["LocZ"]))
            got = (mount.matrix_world @ sock.matrix_world).translation
            delta = max(abs(got[i] - want[i]) for i in range(3))
            assert delta <= TOL, \
                "%s closed-drawer trigger off by %.6f m: %r vs %r" % (
                    r["RowName"], delta, tuple(round(v, 4) for v in got), want)
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

    missing = sorted(set(baked_names) - set(imported))
    assert not missing, "sockets lost in the round trip: %r" % missing
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

    # Bake twice. The purge can no longer reach a socket by name prefix, because
    # sockets are named for who they are FOR and not for the mesh they hang off;
    # it reaches them through parenthood instead. If that ever misses one, this
    # second run leaves the first run's sockets sitting there and Blender hands
    # the new ones .001 suffixes - a name no table would then promise. The whole
    # claim is that a re-bake is a no-op on names.
    once = sorted(o.name for o in bpy.data.collections["BAKE_" + BAKE].all_objects
                  if o.type == 'EMPTY' and o.name.startswith("SOCKET_"))
    assert bpy.ops.kitchen.bake_export() == {'FINISHED'}, "re-bake " + key
    twice = sorted(o.name for o in bpy.data.collections["BAKE_" + BAKE].all_objects
                   if o.type == 'EMPTY' and o.name.startswith("SOCKET_"))
    assert once == twice, \
        "a re-bake is not a no-op on names:\n  first  %r\n  second %r" \
        % (once, twice)
    renamed = [n for n in twice if "." in n.rsplit("_", 1)[-1]]
    assert not renamed, "Blender renamed the new sockets: %r" % renamed

    fbx_path = os.path.join(fbx_dir, BAKE + ".fbx")
    assert bpy.ops.kitchen.export_fbx(filepath=fbx_path) == {'FINISHED'}, "export " + key

    # Sockets as Blender has them, before the file is round-tripped. Everything
    # in the bake too: a collision socket is named after the drawer mesh it sits
    # on, so that mesh has to be there to be matched against.
    coll = bpy.data.collections.get("BAKE_" + BAKE)
    assert coll is not None, "no BAKE collection"
    objects = list(coll.all_objects)
    baked = [o for o in objects
             if o.type == 'EMPTY' and o.name.startswith("SOCKET_")]
    # Names only from here on: the round trip wipes the scene, and a StructRNA
    # of a removed object cannot be read afterwards - parentage included, which
    # is the half of the naming scheme that says whose the socket is.
    baked_names = sorted((o.name for o in baked))
    parent_of = {o.name: (o.parent.name if o.parent else None) for o in baked}

    shelves_path = os.path.join(fbx_dir, BAKE + "_shelves.csv")
    base_dir = os.path.join(baseline_dir, key) if baseline_dir else None
    rows, door_count, drawer_meshes = check_table(
        shelves_path, os.path.join(fbx_dir, BAKE + "_doors.csv"),
        baked, objects, base_dir)
    check_drawers_csv(
        os.path.join(fbx_dir, BAKE + "_drawers.csv"),
        os.path.join(fbx_dir, BAKE + "_drawers.txt"),
        rows, objects)

    if base_dir:
        check_baseline(base_dir, fbx_dir, out_dir)

    # The note's examples are full_l_kitchen's (it says so in 4.2), so check
    # them against that scene only - bedside_dresser has no doors to name.
    if key == "full_l_kitchen":
        check_note(baked_names)

    # Every shelf row owns one socket, doors own theirs on top, and each drawer
    # mesh owns one collision socket.
    expected = len(rows) + door_count + len(drawer_meshes)
    assert len(baked) == expected, \
        "expected %d sockets (rows %d + doors %d + drawers %d), found %d" % (
            expected, len(rows), door_count, len(drawer_meshes), len(baked))

    imported = check_roundtrip(key, rows, fbx_path, yaw_by_section, baked_names)

    drawers = sum(1 for r in rows if r["Type"] == "drawer")
    compartments = len(rows) - drawers
    turned = sorted(s for s, y in yaw_by_section.items()
                    if not ang_close(y, 0.0))
    print("  counts: doors=%d drawers=%d compartments=%d drawer-meshes=%d "
          "sockets=%d (imported %d)"
          % (door_count, drawers, compartments, len(drawer_meshes),
             len(baked), imported))

    # The naming scheme, grouped by the mesh that owns them - hierarchy first,
    # the name only has to agree with it.
    groups = {}
    for n in baked_names:
        groups.setdefault(parent_of[n], []).append(n)
    for parent in sorted(groups):
        names = sorted(groups[parent], key=nn_of)
        print("  %s - %d sockets" % (parent, len(names)))
        head, tail = (names, []) if len(names) <= 7 else (names[:3], names[-3:])
        for n in head + tail:
            owner, nn = split_socket(n)
            print("    %-14s NN=%02d  %s" % (owner, nn, n))
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
