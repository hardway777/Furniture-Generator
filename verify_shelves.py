# -*- coding: utf-8 -*-
"""Headless check of the <bake>_shelves.csv table produced by Bake.

Run from a Blender binary:

  blender.exe --background --python-exit-code 1 --python verify_shelves.py

`--python-exit-code 1` is not decoration: without it Blender prints the
traceback of a failed assertion and still exits 0, so a red run reads green
to anything that only checks the exit status.

The table lists storage SLOTS, not shelves: one invisible box per functional
compartment - the whole niche behind its doors, one single drawer, the surface
of a countertop, the air under a hanging rod, an entire open rack. A board or a
middle post INSIDE a compartment never splits its box; only a different opening
does, because the box is what the engine turns into its "is the item inside"
collider.

Two different things are asserted and they are deliberately separate:

  fidelity - every planned slot is exported, joins its opening through a socket
             that really exists (doors CSV for a niche, the drawers TXT for a
             drawer) and carries its own numbers. The expected count is read
             back off the plan (core.SHELF_PLAN_KEY), so this asks "did the
             export write what the generator planned";
  concept  - one box per compartment, pinned on the bedside dresser, which is
             the spec's own example. This is the part a regression would
             silently undo by re-splitting a compartment along its boards, so it
             is asserted explicitly rather than inferred from a count.
"""
import csv
import json
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
from Files.export_tables import _DRAWERS_HEADER, _SHELVES_HEADER, write_tables
from Files.sections import COUNTERTOP_SLOT_H

SCENES = ("full_l_kitchen", "wardrobe_column", "corner_45")
CARCASS_MARKS = ("_Carcass", "_WardrobeCarcass", "_CornerCabinet")
OUT = os.path.join(ROOT, ".agent_tmp", "shelves_out")
TYPES = ("closed", "open", "rod", "counter", "drawer")


def parse_csv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def drawers_txt(path):
    """[(source, socket), ...] listed by the drawers TXT - the drawer join keys."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    return re.findall(r"^\s+(\S+)\s+\(сокет (SOCKET_[^,]+),", text, re.M)


def clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def build(key, props):
    sd = ds.find_debug_scene(key)
    assert sd, "no scene " + key
    problems = ds.apply_debug_scene(props, sd, bpy.context)
    assert not problems, "apply: " + "; ".join(problems)
    props.gen_collisions = True
    props.bake_name = "SHL_" + key
    props.bake_split_upper = True
    assert bpy.ops.kitchen.generate_kitchen() == {'FINISHED'}, "generate " + key


def planned_rows():
    """[(carcass object, plan row)] straight off the generated model."""
    out = []
    for o in sorted(bpy.data.objects, key=lambda x: x.name):
        raw = o.get(SHELF_PLAN_KEY)
        if raw and any(m in o.name for m in CARCASS_MARKS):
            for row in json.loads(raw):
                out.append((o, row))
    return out


def check_scene(scene_key):
    print("\n=== " + scene_key + " ===", flush=True)
    clear_scene()
    props = bpy.context.scene.kitchen_props
    build(scene_key, props)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, scene_key + ".blend"))

    plan = planned_rows()
    assert bpy.ops.kitchen.bake_export() == {'FINISHED'}, "bake " + scene_key

    door_rows = parse_csv(os.path.join(OUT, props.bake_name + "_doors.csv"))
    door_sources = {r["Source"] for r in door_rows}
    door_sockets = {r["Socket"] for r in door_rows}
    drawers = drawers_txt(os.path.join(OUT, props.bake_name + "_drawers.txt"))
    drawer_sources = {s for s, _k in drawers}
    drawer_sockets = {k for _s, k in drawers}

    # A slot that names an opening nobody exported must be dropped, so the
    # expected row count is the plan minus exactly those.
    def droppable(row):
        front = row.get("front")
        if not front:
            return False
        pool = drawer_sources if row.get("kind") == "drawer" else door_sources
        return front not in pool

    dropped = [row for _o, row in plan if droppable(row)]
    expected = len(plan) - len(dropped)
    print("  planned slots:", len(plan), "droppable:", len(dropped))

    path = os.path.join(OUT, props.bake_name + "_shelves.csv")
    assert os.path.isfile(path), "no shelves csv " + path
    rows = parse_csv(path)
    mix = {t: sum(1 for r in rows if r["Type"] == t) for t in TYPES}
    print("  exported slots:", len(rows), mix)
    assert len(rows) == expected, "rows %d != plan %d" % (len(rows), expected)

    names = [r["RowName"] for r in rows]
    assert len(set(names)) == len(names), "duplicate RowName"
    assert all(n.strip() for n in names), "empty RowName"

    for r in rows:
        assert r["Body"] in ("SM_%s_Body" % props.bake_name,
                             "SM_%s_UpperBody" % props.bake_name), \
            "unknown body " + r["Body"]
        assert r["Section"], "empty Section " + r["RowName"]
        assert r["Type"] in TYPES, "bad type " + r["RowName"]

        if r["Type"] == "drawer":
            # A drawer is addressed by its OWN socket, which lives in the
            # drawers TXT - it must never be mistaken for a door key.
            assert r["DoorSocket"] in drawer_sockets, \
                "not a drawer socket: " + r["RowName"]
            assert r["DoorSocket"] not in door_sockets, \
                "drawer row keyed on a door: " + r["RowName"]
            assert float(r["Depth"]) > 0.0, "drawer without travel " + r["RowName"]
        else:
            assert r["Depth"] == "", "Depth only belongs to a drawer: " + r["RowName"]
            if r["Type"] == "counter":
                assert not r["DoorSocket"], "countertop with an opening " + r["RowName"]
            elif r["DoorSocket"]:
                assert r["DoorSocket"] in door_sockets, \
                    "socket not in doors csv: " + r["DoorSocket"]
            if r["Type"] == "closed":
                assert r["DoorSocket"], "closed slot without a door " + r["RowName"]
            elif r["Type"] == "open":
                assert not r["DoorSocket"], "open slot with a door " + r["RowName"]

        ext = [float(r["ExtX"]), float(r["ExtY"]), float(r["ExtZ"])]
        clear = [float(r["ClearX"]), float(r["ClearY"]), float(r["ClearZ"])]
        assert all(v > 0.0 for v in ext), "zero extent " + r["RowName"]
        # The engine builds its containment collider from these boxes, so Clear
        # repeats Ext: which board the item rests on is not its business.
        for a in range(3):
            assert abs(clear[a] - ext[a]) < 1e-6, \
                "Clear != Ext on axis %d: %s" % (a, r["RowName"])

        volume = float(r["MaxVolume"])
        want = ext[0] * ext[1] * ext[2] * 1000.0
        assert abs(volume - want) < 0.1, \
            "volume %.3f != %.3f %s" % (volume, want, r["RowName"])
        assert volume > 0.0, "zero volume " + r["RowName"]
        assert int(r["MaxItems"]) == (1 if r["Type"] == "rod" else 0), \
            "MaxItems " + r["RowName"]
        if r["Type"] == "counter":
            # A surface slot is the shallow band above the slab, not a cabinet.
            assert abs(ext[2] - COUNTERTOP_SLOT_H) < 1e-3, \
                "countertop box is not the surface band: " + r["RowName"]

    print("  bodies:", sorted({r["Body"] for r in rows}))
    print("  PASS")


def check_one_box_per_compartment():
    """A compartment is ONE box: its boards and its drawers do not split it.

    The bedside dresser preset is the spec's own example - a body carrying two
    drawers over a niche, two boards inside that niche, and a slab on top. The
    plan must come out as exactly four slots, and the niche slot must span the
    whole niche from the floor plate up to the drawer bank rather than one tier
    of it.
    """
    print("\n=== one box per compartment ===", flush=True)
    clear_scene()
    props = bpy.context.scene.kitchen_props
    build("bedside_dresser", props)
    sec = props.sections[0]
    assert sec.sec_type == "NORMAL" and sec.doors == 0 and sec.drawer_count == 2, \
        "preset no longer matches the spec example"

    plan = planned_rows()
    kinds = [row.get("kind") for _o, row in plan]
    print("  planned kinds:", kinds)
    assert kinds == ["niche", "drawer", "drawer", "counter"], \
        "expected niche + 2 drawers + countertop, got %r" % (kinds,)

    t = props.wall_thickness
    ph = props.leg_height if props.use_legs else props.plinth_height
    lower_h = props.height - sec.drawer_height
    box = plan[0][1]["box"]
    assert abs(box[2] - (ph + t)) < 1e-6, "niche does not start on the floor plate"
    assert abs(box[2] + box[5] - (ph + lower_h - t)) < 1e-6, \
        "niche stops at a board instead of the top of the compartment"

    assert bpy.ops.kitchen.bake_export() == {'FINISHED'}, "bake dresser"
    rows = parse_csv(os.path.join(OUT, props.bake_name + "_shelves.csv"))
    by_type = {}
    for r in rows:
        by_type.setdefault(r["Type"], []).append(r)
    print("  exported:", {k: len(v) for k, v in sorted(by_type.items())})
    assert sorted(by_type) == ["counter", "drawer", "open"], \
        "unexpected type mix: %r" % (sorted(by_type),)
    assert len(by_type["open"]) == 1, "the niche was split into tiers"
    assert len(by_type["drawer"]) == 2, "a drawer bank must give one slot per drawer"
    assert len(by_type["counter"]) == 1, "missing surface slot"

    # Two drawers must be two DIFFERENT boxes, or the player could not be told
    # "the keys are in the second drawer". They sit side by side in a carcass
    # and stacked in a wardrobe column, so the invariant is separation on some
    # axis rather than on one in particular.
    a, b = by_type["drawer"]
    sep = max(abs(float(a["Loc" + ax]) - float(b["Loc" + ax])) for ax in "XYZ")
    assert sep > 0.05, "the two drawers share one box"
    assert float(by_type["counter"][0]["LocZ"]) > float(by_type["open"][0]["LocZ"]), \
        "the surface slot sits below the niche it belongs on top of"
    print("  PASS")


def check_rod_zone():
    """A hanging zone exports one rod row with a single item slot."""
    print("\n=== hanging rod ===", flush=True)
    clear_scene()
    props = bpy.context.scene.kitchen_props
    build("wardrobe_column", props)
    sec = props.sections[1]
    assert sec.sec_type == "WARDROBE", "preset is not a wardrobe column"
    rods = 0
    for col in sec.columns:
        for zone in col.zones:
            if zone.zone_type == "DOOR":
                zone.interior_type = "ROD"
                rods += 1
    assert rods, "no door zone to turn into a hanging one"
    assert bpy.ops.kitchen.generate_kitchen() == {'FINISHED'}, "regenerate rod"
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "rod.blend"))

    plan = planned_rows()
    planned_rods = sum(1 for _o, row in plan if row.get("kind") == "rod")
    assert planned_rods == rods, "planned rods %d != zones %d" % (planned_rods, rods)
    assert bpy.ops.kitchen.bake_export() == {'FINISHED'}, "bake rod"
    rows = parse_csv(os.path.join(OUT, props.bake_name + "_shelves.csv"))
    rod_rows = [r for r in rows if r["Type"] == "rod"]
    print("  planned slots:", len(plan), "exported:", len(rows), "rod:", len(rod_rows))
    assert len(rod_rows) == rods, "rod rows %d != %d" % (len(rod_rows), rods)
    for r in rod_rows:
        assert int(r["MaxItems"]) == 1, "rod must hold one item: " + r["RowName"]
        # The air under the bar is the whole box: nothing floors it.
        for axis in "XYZ":
            assert abs(float(r["Ext" + axis]) - float(r["Clear" + axis])) < 1e-4, \
                "rod Ext != Clear on " + axis + ": " + r["RowName"]
        assert float(r["ClearZ"]) < 2.20, "rod zone taller than the column"
    print("  rod ClearZ:", [round(float(r["ClearZ"]), 3) for r in rod_rows])
    print("  PASS")


def check_unresolved_opening():
    """A slot naming an opening nobody exported must drop just that row."""
    print("\n=== unresolved opening ===", flush=True)
    clear_scene()
    props = bpy.context.scene.kitchen_props
    build("full_l_kitchen", props)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "drop.blend"))

    plan = planned_rows()
    assert plan, "nothing to corrupt"
    assert any(r.get("kind") == "drawer" for _o, r in plan), "no drawer to corrupt"
    assert any(r.get("kind") in ("niche", "rod") and r.get("front") for _o, r in plan), \
        "no door-fronted slot to corrupt"

    for wanted in ("niche", "drawer"):
        for o, row in plan:
            if row.get("kind") == wanted and row.get("front"):
                raw = json.loads(o[SHELF_PLAN_KEY])
                for entry in raw:
                    if entry.get("kind") == wanted and entry.get("front"):
                        entry["front"] = ("SM_No_Such_Door" if wanted == "niche"
                                          else "SM_No_Such_Drawer")
                        break
                o[SHELF_PLAN_KEY] = json.dumps(raw)
                break

    before = len(plan)
    assert bpy.ops.kitchen.bake_export() == {'FINISHED'}, "bake drop"
    rows = parse_csv(os.path.join(OUT, props.bake_name + "_shelves.csv"))
    print("  planned:", before, "-> exported:", len(rows))
    assert len(rows) == before - 2, "the two bad rows were not dropped"

    door_sockets = {r["Socket"] for r in
                    parse_csv(os.path.join(OUT, props.bake_name + "_doors.csv"))}
    drawer_sockets = {k for _s, k in
                      drawers_txt(os.path.join(OUT, props.bake_name + "_drawers.txt"))}
    for r in rows:
        if r["Type"] == "drawer":
            assert r["DoorSocket"] in drawer_sockets, "unjoinable drawer row exported"
        elif r["DoorSocket"]:
            assert r["DoorSocket"] in door_sockets, "unjoinable row exported"
    print("  PASS")


def check_island_surface():
    """The one slab an island run shares gets exactly one surface slot.

    Island sections skip their own slab, so a per-section counter row here
    would mean that skip stopped working, and no counter row at all would mean
    the monolithic slab found no carcass to attach to - `host is None` only
    warns, and a warning alone would leave this test green.
    """
    print("\n=== island surface ===", flush=True)
    clear_scene()
    props = bpy.context.scene.kitchen_props
    build("island_rounded", props)
    # The span is the whole run, so its slot belongs to the FIRST section: that
    # is the section whose matrix the slab - and therefore its box - is in.
    islands = [s for s in props.sections if getattr(s, "is_island", False)]
    assert islands, "preset is no longer an island"
    assert props.sections[0].is_island, "first section is not part of the span"

    assert bpy.ops.kitchen.bake_export() == {'FINISHED'}, "bake island"
    rows = parse_csv(os.path.join(OUT, props.bake_name + "_shelves.csv"))
    counters = [r for r in rows if r["Type"] == "counter"]
    print("  slots:", len(rows), "counters:", len(counters))
    assert len(counters) == 1, \
        "expected exactly the one monolithic slab, got %d counter rows" % len(counters)
    c = counters[0]
    assert c["Section"] == "Base_01", \
        "island slab slot landed on %s instead of the span's first section" % c["Section"]
    assert abs(float(c["ExtZ"]) - COUNTERTOP_SLOT_H) < 1e-3, "not a surface band"
    assert c["Depth"] == "" and not c["DoorSocket"], "a surface opens nothing"
    # The slab sits on top of every section of the run, never inside one.
    niche_z = max(float(r["LocZ"]) for r in rows if r["Type"] in ("closed", "open"))
    assert float(c["LocZ"]) > niche_z, "surface slot is below the cabinets it covers"
    print("  PASS")


def check_no_slots():
    """No storage at all is still a file: a header and nothing under it.

    Checked twice - at the writer, where the "never a missing file" rule
    actually lives, and through a full bake of a model whose carcasses carry no
    plan at all, which is the state a model with nothing to store reaches.
    """
    print("\n=== no slots ===", flush=True)
    empty_dir = os.path.join(OUT, "noslots")
    os.makedirs(empty_dir, exist_ok=True)
    _csv, drawers_csv, _txt, shelves_path = write_tables(
        empty_dir, "EMPTY", [], [], [])
    assert shelves_path and os.path.isfile(shelves_path), "empty list wrote no file"
    lines = open(shelves_path, encoding="utf-8").read().splitlines()
    assert lines == [",".join(_SHELVES_HEADER)], "expected header only, got %r" % (lines,)
    print("  writer: header only, file present")
    # The same rule for the drawers table: a model with no drawer says so by
    # having no row, not by having no file - otherwise "no drawers" and "the
    # write failed" read identically to the importer.
    assert drawers_csv and os.path.isfile(drawers_csv), "no drawers CSV written"
    dlines = open(drawers_csv, encoding="utf-8").read().splitlines()
    assert dlines == [",".join(_DRAWERS_HEADER)], \
        "expected drawers header only, got %r" % (dlines,)
    print("  writer: drawers header only, file present")

    clear_scene()
    props = bpy.context.scene.kitchen_props
    build("bedside_dresser", props)
    for o in bpy.data.objects:
        if SHELF_PLAN_KEY in o.keys():
            del o[SHELF_PLAN_KEY]
    assert not planned_rows(), "model still carries a plan"
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "no_slots.blend"))

    assert bpy.ops.kitchen.bake_export() == {'FINISHED'}, "bake no slots"
    path = os.path.join(OUT, props.bake_name + "_shelves.csv")
    assert os.path.isfile(path), "no-slot model wrote no file"
    rows = parse_csv(path)
    print("  bake rows:", len(rows))
    assert rows == [], "no-slot model exported rows"
    header = open(path, encoding="utf-8").readline().strip()
    assert header.startswith("RowName,Section,Body,Type,DoorSocket"), header
    print("  header:", header)
    print("  PASS")


os.makedirs(OUT, exist_ok=True)
print("Blender", bpy.app.version_string)
for scene_key in SCENES:
    check_scene(scene_key)
check_one_box_per_compartment()
check_rod_zone()
check_unresolved_opening()
check_island_surface()
check_no_slots()
print("\nALL SLOT TABLE TESTS PASSED")
