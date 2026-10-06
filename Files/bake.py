"""bake - Prepare the generated kitchen for engine export (UE FBX naming rules).

Everything the bake creates lives in one collection and starts with the
user-chosen bake prefix, so a bake never collides with the working model and
re-running it replaces the previous bake of the same name. The colliders are
the exception on layout, not on naming: they go to a `BAKE_<prefix>_Colliders`
sub-collection as a flat unparented list, the same layout the working model
uses for its `FURNITURE_<id>_Colliders`.

Outputs (naming per the Epic FBX Static Mesh Pipeline rules):

  SM_<prefix>_Body        one static mesh of everything that never moves
                          (carcasses, plinths, legs, countertops, upstands);
                          geometry rebased so the pivot sits at the BOTTOM of
                          the wall-facing back wall - the wall corner for a row
                          that turns, the second turn's back wall for a U row
  SM_<prefix>_UpperBody   optional second body for the upper row; geometry is
                          rebased by the same rule - UE surface snapping (align
                          by normal) can then place either body directly
  SM_<prefix>_Door_NN     one mesh per UNIQUE door (door + handle joined),
                          geometry rebased into the hinge frame, transform
                          reset to zero - in UE the door hangs on its socket
                          and rotates around the pivot
  SM_<prefix>_Drawer_NN   one mesh per unique drawer (front + box + handle),
                          pivot at the front face centre
  SOCKET_<BodyName>_NN    one socket per source door/drawer, CHILDREN of the
                          mesh that owns them: FbxStaticMeshImport walks the
                          mesh's own node subtree only, so a sibling empty is
                          dropped without a word
  SOCKET_<BodyName>_<RowName>_NN
                          one socket per exported storage compartment, centred
                          on its box and turned to its section's yaw, so an
                          object dropped on it with a zero transform sits in
                          the slot facing the right way. NN continues the same
                          per-body run the door and drawer sockets started, so
                          the two kinds can never share a number. A drawer row
                          gets none: it reuses the drawer's own socket
  UBX_<MeshName>_NN       colliders cloned and renamed after their new owner;
                          body colliders keep their world transform, door and
                          drawer colliders are rebased into the owner's frame
                          so they still line up with the moved geometry

Identical doors/drawers (same local geometry incl. handle, same materials)
are baked once; a hash of the geometry is stored on the object (bake_hash)
and the report file lists which sockets each unique mesh serves.

Alongside the report, three engine-facing tables are written (see export_tables):

  <bake>_doors.csv    one row per door: socket, mesh, panel size, socket
                      transform - a UE DataTable straight from the file
  <bake>_drawers.txt  how far each drawer can travel out of its carcass
  <bake>_shelves.csv  one row per storage slot: an invisible box around one
                      functional compartment, the join key to the opening that
                      reaches it (DoorSocket) and the socket an object placed
                      INSIDE it hangs on (SlotSocket)
"""
import bpy
import bmesh
import hashlib
import json
import math
import os
import re
from bpy.types import Operator
from mathutils import Vector, Matrix

from .core import COLLIDER_COLL_SUFFIX, KITCHEN_COLL_PREFIX, SHELF_PLAN_KEY, warn
from .export_tables import door_entry, drawer_entry, shelf_entry, write_tables
from .mesh_ops import apply_collider_flags, collider_collection, ensure_material
from .strings import STR

# Name marks, tested in this order: a handle merges into its door/drawer,
# everything else with a Door/Drawer mark is a moving part, the rest is static.
# "_DrawerHandle_" contains "_Drawer", so handles must be classified first.
_HANDLE_MARKS = ("Handle", "_DH_", "_DrH_")
_MOVING_MARKS = ("Door", "Drawer")
_UPPER_MARK = "_Upper_"


def _is_handle_name(name):
    return any(m in name for m in _HANDLE_MARKS)


def _is_moving_name(name):
    return (not _is_handle_name(name)) and any(m in name for m in _MOVING_MARKS)


def _sanitize_bake_name(raw):
    # Export names must survive FBX and UE asset naming, so anything but
    # word characters becomes an underscore.
    name = re.sub(r"[^A-Za-z0-9_]", "_", (raw or "").strip())
    return name or "EXP"


def _purge_previous(bake, scene):
    """A re-bake replaces the previous bake of the same name, nothing else."""
    prefixes = (f"SM_{bake}_", f"UBX_SM_{bake}_", f"SOCKET_SM_{bake}_")
    victims = [o for o in list(bpy.data.objects) if o.name.startswith(prefixes)]
    meshes = [o.data for o in victims if o.data is not None]
    for o in victims:
        bpy.data.objects.remove(o, do_unlink=True)
    for me in meshes:
        try:
            if me.users == 0:
                bpy.data.meshes.remove(me)
        except ReferenceError:
            pass
    coll = bpy.data.collections.get(f"BAKE_{bake}")
    if coll is not None:
        try:
            bpy.data.collections.remove(coll)
        except RuntimeError:
            pass
    # The colliders live in a child collection, which survives the parent's removal as an
    # orphan datablock if it is not removed by name - and an orphan named like this bake
    # would be picked up by the next re-bake.
    colliders = bpy.data.collections.get(f"BAKE_{bake}{COLLIDER_COLL_SUFFIX}")
    if colliders is not None:
        try:
            bpy.data.collections.remove(colliders)
        except RuntimeError:
            pass


def _join_sources(sources, inv_pivot, mesh_name, depsgraph):
    """One mesh out of many objects, geometry rebased into the pivot frame.

    Evaluated meshes are used so live modifiers still reach the bake (the
    bevel fallback path leaves the modifier on the object). The join is done
    by hand: bpy.ops.object.join needs a context override and drops the
    non-active objects' modifiers.
    """
    bm = bmesh.new()
    slot_names = []
    for obj in sources:
        try:
            ev = obj.evaluated_get(depsgraph)
            me = ev.to_mesh()
        except Exception as exc:
            warn(f"bake: could not evaluate '{obj.name}': {exc}")
            continue
        mapping = []
        for slot in me.materials:
            mname = slot.name if slot is not None else ""
            if mname not in slot_names:
                slot_names.append(mname)
            mapping.append(slot_names.index(mname))
        first_vert = len(bm.verts)
        first_face = len(bm.faces)
        bm.from_mesh(me)
        mat = inv_pivot @ obj.matrix_world
        for v in list(bm.verts)[first_vert:]:
            v.co = mat @ v.co
        for f in list(bm.faces)[first_face:]:
            if f.material_index < len(mapping):
                f.material_index = mapping[f.material_index]
        ev.to_mesh_clear()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(mesh_name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh, slot_names


def _new_baked_object(name, mesh, coll, slot_names):
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    for mname in slot_names:
        mesh.materials.append(bpy.data.materials.get(mname) if mname else None)
    return obj


def _mesh_signature(mesh, slot_names):
    """Identity of a baked moving part: geometry + material slots.

    Rounded to 5 decimals so float noise never splits identical doors; the
    handle is already part of the geometry, so its size and position are
    covered without a separate parameter list.
    """
    h = hashlib.sha256()
    h.update("|".join(slot_names).encode())
    for v in mesh.vertices:
        h.update(f"{v.co.x:.5f},{v.co.y:.5f},{v.co.z:.5f};".encode())
    for p in mesh.polygons:
        h.update(",".join(str(i) for i in p.vertices).encode() + b";")
    return h.hexdigest()[:16]


def _section_key(name):
    """('Base', 3) for SM_K01_Base_Sec_03_DoorL_01, or None."""
    parts = name.split("_")
    if "Sec" not in parts:
        return None
    i = parts.index("Sec")
    if i + 1 >= len(parts) or i < 1:
        return None
    try:
        idx = int(parts[i + 1])
    except ValueError:
        return None
    return (parts[i - 1], idx)


def _facade_back_plane(facades, sec_lo, sec_hi):
    """(axis, sign, coord) of the wall a section leans on, or (None, 0, 0.0).

    A door or drawer front is a thin slab, so the axis in which the facade bbox is
    thinner is the axis the section faces; which end of the SECTION the slab sits
    at gives the sign. Nothing about the generator's internal rotation is assumed,
    which is what makes a turned row come out right.

    The slab is compared against the section box, never against itself: a thin
    slab's own centre is equidistant from its own two faces, so that comparison
    would be decided by float noise.

    The thin span must be a real slab (< 60 mm) and clearly elongated (>= 4x its
    thickness): two perpendicular leaves give a square bbox and must not invent a
    wall. The rule is a deliberate copy of the renderer's - the addon must not
    import from the Render folder - so if it changes there, change it here too.

    sign -1: the facade sits at the minimum, the section faces the negative
    direction, its back is the max-side plane. sign +1: the reverse.
    """
    if not facades:
        return (None, 0, 0.0)
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for o in facades:
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            lo = Vector((min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)))
            hi = Vector((max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)))
    span_x, span_y = hi.x - lo.x, hi.y - lo.y
    thin, along = min(span_x, span_y), max(span_x, span_y)
    if thin > 0.06 or along < 4.0 * max(thin, 1e-6):
        return (None, 0, 0.0)
    if span_x < span_y:
        centre = (lo.x + hi.x) / 2.0
        if abs(centre - sec_lo.x) < abs(sec_hi.x - centre):
            return ("X", -1, sec_hi.x)   # faces -X, back is the max-X plane
        return ("X", 1, sec_lo.x)
    centre = (lo.y + hi.y) / 2.0
    if abs(centre - sec_lo.y) < abs(sec_hi.y - centre):
        return ("Y", -1, sec_hi.y)       # faces -Y, back is the max-Y plane
    return ("Y", 1, sec_lo.y)


_FACADE_MARKS = ("_Door", "_Drawer", "_Facade", "_DH_", "_DrH_")


def _measure_back_planes(parts):
    """[(section index, axis, sign, coord, group bbox)] in build order.

    The row is split into its sections, each section's facing is measured from its
    own facade slabs, and the sections that share a wall are collected. A section
    with no facade (a corner, an appliance) contributes nothing - the walls are
    read off the sections that do have fronts, which is enough to place every wall
    of a straight, L or U row.
    """
    groups = {}
    for o in parts:
        key = _section_key(o.name)
        if key is None:
            continue
        groups.setdefault(key, []).append(o)

    out = []
    for key in sorted(groups, key=lambda k: (k[0], k[1])):
        objs = groups[key]
        lo = Vector((1e9, 1e9, 1e9))
        hi = Vector((-1e9, -1e9, -1e9))
        for o in objs:
            for c in o.bound_box:
                w = o.matrix_world @ Vector(c)
                lo = Vector((min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)))
                hi = Vector((max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)))
        facades = [o for o in objs if any(m in o.name for m in _FACADE_MARKS)]
        axis, sign, coord = _facade_back_plane(facades, lo, hi)
        if axis is None:
            continue
        out.append((key[1], axis, sign, coord, (lo, hi)))
    return out


def _back_pivot(parts, measure_parts=None):
    """Pivot for a body: bottom of the middle of the wall-facing back wall.

    # See AGENT_NOTES.md [NOTE_16557]

    UE snaps a placed mesh to a surface and aligns it by the normal, so a pivot
    on the wall-facing face lets either body be dropped straight onto the kitchen
    wall. The pivot sits at the BOTTOM of the geometry, not its middle: a body is
    placed from the floor up.

    Which wall is "the" back wall depends on the row, and it is measured, never
    assumed (see _measure_back_planes):

    * straight row - the one back plane, centred along it;
    * L row (one turn) - the corner where the two back planes cross, i.e. the turn
      point at the wall;
    * U row (two turns) - the bottom centre of the back wall of the SECOND turn,
      which is the wall the last leg leans on.

    `parts` is the body itself; `measure_parts` is the whole row when they differ.
    They do differ: a body holds carcasses, plinths and worktops, and every facade
    is a separate door/drawer object, so the body alone has no slab to measure a
    facing from and the walls must be read off the full row.
    """
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for o in parts:
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            lo = Vector((min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)))
            hi = Vector((max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)))
    bottom_z = lo.z

    measured = _measure_back_planes(measure_parts if measure_parts is not None else parts)
    walls = {}
    for idx, axis, sign, coord, box in measured:
        key = (axis, sign)
        entry = walls.setdefault(key, {"coords": [], "boxes": [], "last_idx": idx})
        entry["coords"].append(coord)
        entry["boxes"].append(box)
        entry["last_idx"] = max(entry["last_idx"], idx)

    if not walls:
        return Matrix.Translation(Vector(((lo.x + hi.x) / 2.0, hi.y, bottom_z)))

    if len(walls) == 1:
        (axis, sign), entry = next(iter(walls.items()))
        coord = max(entry["coords"]) if sign < 0 else min(entry["coords"])
        if axis == "Y":
            return Matrix.Translation(Vector(((lo.x + hi.x) / 2.0, coord, bottom_z)))
        return Matrix.Translation(Vector((coord, (lo.y + hi.y) / 2.0, bottom_z)))

    if len(walls) == 2 and len({k[0] for k in walls}) == 2:
        # L row: the two back planes are perpendicular, so where they cross is the
        # wall corner the row wraps around. Two walls on the SAME axis are not a
        # corner (that is a free-standing row with fronts on both sides), so they
        # fall through to the last-wall rule below.
        xs = [max(v["coords"]) if k[1] < 0 else min(v["coords"])
              for k, v in walls.items() if k[0] == "X"]
        ys = [max(v["coords"]) if k[1] < 0 else min(v["coords"])
              for k, v in walls.items() if k[0] == "Y"]
        corner_x = xs[0] if xs else (lo.x + hi.x) / 2.0
        corner_y = ys[0] if ys else (lo.y + hi.y) / 2.0
        return Matrix.Translation(Vector((corner_x, corner_y, bottom_z)))

    # U row (three walls) and anything else with more than one wall: the wall added
    # by the LAST turn - the one whose sections come last in build order - is the
    # anchor, and the pivot sits at the middle of that wall's span, at the bottom.
    last_key = max(walls, key=lambda k: walls[k]["last_idx"])
    entry = walls[last_key]
    axis, sign = last_key
    coord = max(entry["coords"]) if sign < 0 else min(entry["coords"])
    boxes = entry["boxes"]
    # The wall runs ALONG the other axis: a wall facing +-Y is measured along X,
    # a wall facing +-X along Y. Centring on the facing axis instead put the U
    # row's pivot at the far end of the leg (measured: x=0.600 for a leg spanning
    # x 0.586..1.221, i.e. on the corner rather than mid-wall).
    along = 0 if axis == "Y" else 1
    span_lo = min(b[0][along] for b in boxes)
    span_hi = max(b[1][along] for b in boxes)
    mid = (span_lo + span_hi) / 2.0
    if axis == "Y":
        return Matrix.Translation(Vector((mid, coord, bottom_z)))
    return Matrix.Translation(Vector((coord, mid, bottom_z)))


def _front_pivot(obj):
    """Pivot for a moving part without a hinge socket (drawers): front face
    centre in the object's own frame, rotation kept so the socket axes stay
    aligned with the body."""
    lo = Vector((min(c[0] for c in obj.bound_box), min(c[1] for c in obj.bound_box),
                 min(c[2] for c in obj.bound_box)))
    hi = Vector((max(c[0] for c in obj.bound_box), max(c[1] for c in obj.bound_box),
                 max(c[2] for c in obj.bound_box)))
    local = Vector(((lo.x + hi.x) / 2.0, lo.y, (lo.z + hi.z) / 2.0))
    loc, rot, _scl = obj.matrix_world.decompose()
    return Matrix.LocRotScale(obj.matrix_world @ local, rot, Vector((1.0, 1.0, 1.0)))


def _clone_ubx(source, new_name, new_matrix, coll):
    """Collider copy in the bake; the working model keeps its own.

    Linked into the bake's `_Colliders` sub-collection next to every other collider of
    this bake, unparented - the same flat layout the working model uses, so the FBX
    hierarchy stays a list of meshes and helpers with nothing nested under anything.
    """
    mesh = source.data.copy()
    mesh.name = new_name
    obj = bpy.data.objects.new(new_name, mesh)
    collider_collection(coll).objects.link(obj)
    obj.matrix_world = new_matrix
    apply_collider_flags(obj)
    return obj


def _fmt_pivot(point):
    x, y, z = point
    return f"({x:.3f}, {y:.3f}, {z:.3f})"


def _report_text(bake, coll_name, body, upper, doors, drawers, ubx_counts,
                 shelves=None):
    lines = []
    lines.append(f"Запекание для экспорта: {bake}")
    lines.append(f"Коллекция: {coll_name}")
    lines.append("")
    lines.append("Пивоты в системе координат сцены; геометрия каждого меша пересчитана "
                 "в его собственный пивот (трансформ объекта = единица).")
    lines.append(f"Корпус: {body['name']} — деталей: {body['parts']}, "
                 f"вершин: {body['verts']}, коллайдеров: {ubx_counts.get(body['name'], 0)}, "
                 f"пивот низ задней стенки: {_fmt_pivot(body['pivot'])}")
    if upper:
        lines.append(f"Верхний корпус: {upper['name']} — деталей: {upper['parts']}, "
                     f"вершин: {upper['verts']}, коллайдеров: {ubx_counts.get(upper['name'], 0)}, "
                     f"пивот низ задней стенки: {_fmt_pivot(upper['pivot'])}")
    lines.append("")
    total_src_doors = sum(len(d["sockets"]) for d in doors)
    lines.append(f"Двери (уникальных: {len(doors)} из {total_src_doors}):")
    for d in doors:
        lines.append(f"  {d['name']} — сокеты: {', '.join(d['sockets'])}")
    lines.append("")
    total_src_drawers = sum(len(d["sockets"]) for d in drawers)
    lines.append(f"Ящики (уникальных: {len(drawers)} из {total_src_drawers}):")
    for d in drawers:
        lines.append(f"  {d['name']} — сокеты: {', '.join(d['sockets'])}")
    lines.append("")
    lines.append(f"Слоты хранения: {len(shelves or [])}")
    for s in shelves or []:
        if s["door_socket"]:
            via = "ящик" if s["type"] == "drawer" else "дверь"
            closing = f", {via} {s['door_socket']}"
        elif s["type"] == "counter":
            closing = ", поверхность"
        else:
            closing = ", открытая"
        lines.append(f"  {s['row_name']} — {s['type']}, корпус {s['body']}, "
                     f"секция {s['section']}, габарит "
                     f"{s['ext'][0] * 1000:.0f}×{s['ext'][1] * 1000:.0f}×"
                     f"{s['ext'][2] * 1000:.0f} мм{closing}")
    return "\n".join(lines) + "\n"


def bake_kitchen(props, scene):
    """Bake the current generation into an export-ready collection.

    Returns a report dict, or None when there is nothing to bake. The working
    model is never modified: every output is a new object, sources are only
    read.
    """
    kid = props.kitchen_id
    bake = _sanitize_bake_name(props.bake_name)
    if bake == kid:
        warn("bake: the bake name must differ from the kitchen id")
        return None

    sm_prefix = f"SM_{kid}_"
    sources = [o for o in bpy.data.objects
               if o.type == 'MESH' and o.name.startswith(sm_prefix)]
    if not sources:
        return None

    _purge_previous(bake, scene)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    coll = bpy.data.collections.new(f"BAKE_{bake}")
    scene.collection.children.link(coll)

    # ---- classification -------------------------------------------------
    body_parts = [o for o in sources
                  if not _is_moving_name(o.name) and not _is_handle_name(o.name)]
    upper_parts = [o for o in body_parts if _UPPER_MARK in o.name]
    base_parts = [o for o in body_parts if _UPPER_MARK not in o.name]

    moving_roots = sorted((o for o in sources if _is_moving_name(o.name)),
                          key=lambda o: o.name)
    parts_of = {}
    orphan_handles = []
    for h in (o for o in sources if _is_handle_name(o.name)):
        root = None
        p = h.parent
        while p is not None:
            if p.type == 'MESH' and _is_moving_name(p.name):
                root = p
                break
            p = p.parent
        if root is not None:
            parts_of.setdefault(root, [root]).append(h)
        else:
            orphan_handles.append(h)
    if orphan_handles:
        warn(f"bake: handles without a door/drawer parent go to the body: "
             f"{[o.name for o in orphan_handles]}")
        body_parts.extend(orphan_handles)
        upper_parts = [o for o in body_parts if _UPPER_MARK in o.name]
        base_parts = [o for o in body_parts if _UPPER_MARK not in o.name]

    split_upper = bool(props.bake_split_upper) and bool(upper_parts)
    body_name = f"SM_{bake}_Body"
    upper_name = f"SM_{bake}_UpperBody"

    # ---- bodies ----------------------------------------------------------
    base_join = base_parts if split_upper else (base_parts + upper_parts)
    # Both bodies stand on their own origin: the geometry is rebased into a
    # pivot placed at the bottom of the back wall, so UE can drop either of
    # them against the wall without a manual origin move. The walls are measured
    # off the WHOLE row, facades included: a body has no facades of its own
    # (every facade is a separate door/drawer object), and the facades are what
    # say which way each section faces.
    if split_upper:
        base_sources = [o for o in sources if _UPPER_MARK not in o.name]
        upper_sources = [o for o in sources if _UPPER_MARK in o.name]
    else:
        base_sources = sources
        upper_sources = []
    body_pivot = _back_pivot(base_join, measure_parts=base_sources)
    upper_pivot = (_back_pivot(upper_parts, measure_parts=upper_sources)
                   if split_upper else None)
    body_frame = body_pivot.inverted()

    body_mesh, body_slots = _join_sources(base_join, body_frame, body_name, depsgraph)
    body_obj = _new_baked_object(body_name, body_mesh, coll, body_slots)
    body_info = {"name": body_name, "parts": len(base_join),
                 "verts": len(body_mesh.vertices), "pivot": body_pivot.translation}

    upper_info = None
    if split_upper:
        upper_mesh, upper_slots = _join_sources(
            upper_parts, upper_pivot.inverted(), upper_name, depsgraph)
        _new_baked_object(upper_name, upper_mesh, coll, upper_slots)
        upper_info = {"name": upper_name, "parts": len(upper_parts),
                      "verts": len(upper_mesh.vertices),
                      "pivot": upper_pivot.translation}

    # ---- moving parts ----------------------------------------------------
    doors = []
    drawers = []
    door_rows = []
    drawer_rows = []
    sig_map = {}
    root_to_record = {}
    socket_counters = {body_name: 0}
    if split_upper:
        socket_counters[upper_name] = 0

    for root in moving_roots:
        is_upper_part = _UPPER_MARK in root.name
        owner = upper_name if (split_upper and is_upper_part) else body_name
        # Doors hang on a hinge socket already; that transform is the pivot.
        # Drawers have no socket in the working model - one is created here.
        if root.parent is not None and root.parent.type == 'EMPTY' \
                and root.parent.name.startswith("SOCKET_"):
            pivot = root.parent.matrix_world.copy()
        else:
            pivot = _front_pivot(root)

        mesh, slots = _join_sources(parts_of.get(root, [root]), pivot.inverted(),
                                    f"tmp_{root.name}", depsgraph)
        sig = _mesh_signature(mesh, slots)
        record = sig_map.get(sig)
        if record is None:
            kind = "Drawer" if "Drawer" in root.name else "Door"
            bucket = drawers if kind == "Drawer" else doors
            name = f"SM_{bake}_{kind}_{len(bucket) + 1:02d}"
            obj = _new_baked_object(name, mesh, coll, slots)
            obj["bake_hash"] = sig
            record = {"name": name, "sockets": [], "sources": []}
            bucket.append(record)
            sig_map[sig] = record
        else:
            bpy.data.meshes.remove(mesh)

        socket_counters[owner] += 1
        sock_name = f"SOCKET_{owner}_{socket_counters[owner]:02d}"
        sock = bpy.data.objects.new(sock_name, None)
        coll.objects.link(sock)
        sock.empty_display_type = 'PLAIN_AXES'
        sock.empty_display_size = 0.010
        # Sockets are CHILDREN of their owner mesh. The engine attaches a
        # socket to a static mesh only from inside that mesh's own node
        # subtree (FbxStaticMeshImport: FindMeshSockets runs over the mesh
        # node array), so a sibling empty never reaches it - UE silently
        # dropped every socket and the doors lived on their CSV fallback.
        # The name after SOCKET_ is free-form: it lands on whatever mesh
        # parents it (verified in 5.8), it still spells the owner for
        # debugging. Baked bodies sit at identity, so the keep-world recipe
        # below leaves the socket's local transform equal to the body-frame
        # numbers the doors CSV stores.
        frame = upper_pivot.inverted() if (split_upper and is_upper_part) else body_frame
        sock.matrix_world = frame @ pivot
        owner_obj = bpy.data.objects.get(owner)
        if owner_obj is not None:
            sock.parent = owner_obj
            sock.matrix_parent_inverse = owner_obj.matrix_world.inverted()

        record["sockets"].append(sock_name)
        record["sources"].append(root.name)
        root_to_record[root] = record

        # Engine tables collect one row per SOURCE part, not per unique mesh:
        # every socket needs its own placement even when several sockets share
        # one mesh. sock.matrix_world is already rebased into the owner body.
        if "Drawer" in root.name:
            drawer_rows.append(drawer_entry(root, sock_name, record["name"], owner))
        else:
            door_rows.append(door_entry(root, sock_name, record["name"], owner,
                                        sock.matrix_world))

    # ---- storage slots ----------------------------------------------------
    # Built after the moving parts on purpose: a slot joins its opening by the
    # socket name that table assigned - a door's for a niche, the drawer's own
    # for a drawer row - so the sockets must exist first.
    shelf_rows = _shelf_rows(sources, door_rows, drawer_rows, split_upper, body_name,
                             upper_name, body_frame, upper_pivot, kid, coll,
                             socket_counters)

    # ---- colliders --------------------------------------------------------
    ubx_prefix = f"UBX_SM_{kid}_"
    by_name = {o.name: o for o in bpy.data.objects}
    ubx_counts = {}
    body_ubx_counters = {body_name: 0}
    if split_upper:
        body_ubx_counters[upper_name] = 0
    for u in sorted((o for o in bpy.data.objects if o.name.startswith(ubx_prefix)),
                    key=lambda o: o.name):
        target_name = u.name[len("UBX_"):].rsplit("_", 1)[0]
        target = by_name.get(target_name)
        if target is None or target.type != 'MESH':
            warn(f"bake: collider '{u.name}' has no mesh target, skipped")
            continue

        # Walk up to the moving root (handles own colliders too).
        node = target
        root = node if _is_moving_name(node.name) else None
        while root is None and node.parent is not None:
            node = node.parent
            if node.type == 'MESH' and _is_moving_name(node.name):
                root = node
        if root is not None and root in root_to_record:
            record = root_to_record[root]
            # Rebased into the owner frame: the door moved to its pivot, the
            # collider must follow or the FBX pair no longer lines up.
            pivot = _record_pivot(root)
            new_matrix = pivot.inverted() @ u.matrix_world
            idx = ubx_counts.get(record["name"], 0) + 1
            new_name = f"UBX_{record['name']}_{idx:02d}"
            _clone_ubx(u, new_name, new_matrix, coll)
            ubx_counts[record["name"]] = idx
        else:
            is_upper_ubx = _UPPER_MARK in target_name
            owner = upper_name if (split_upper and is_upper_ubx) else body_name
            frame = (upper_pivot.inverted() if (split_upper and is_upper_ubx)
                     else body_frame)
            body_ubx_counters[owner] += 1
            new_name = f"UBX_{owner}_{body_ubx_counters[owner]:02d}"
            # Body colliders are rebased into the body frame: in UE the pair
            # (mesh, collider) must share one origin.
            _clone_ubx(u, new_name, frame @ u.matrix_world, coll)
            ubx_counts[owner] = body_ubx_counters[owner]

    # ---- report -----------------------------------------------------------
    text = _report_text(bake, coll.name, body_info, upper_info, doors, drawers,
                        ubx_counts, shelf_rows)
    text += f"\nКоллекция '{coll.name}' скрыта в вьюпорте - глаз в аутлайнере вернёт её."
    report_path = None
    doors_csv_path = None
    drawers_txt_path = None
    shelves_csv_path = None
    blend = bpy.data.filepath
    if blend:
        # The engine tables live next to the report, so one bake drops every
        # text output of this name in one place.
        doors_csv_path, drawers_txt_path, shelves_csv_path = write_tables(
            os.path.dirname(blend), bake, door_rows, drawer_rows, shelf_rows)
        if doors_csv_path:
            text += f"\nДвери (CSV): {os.path.basename(doors_csv_path)}\n"
        if drawers_txt_path:
            text += f"Ящики (TXT): {os.path.basename(drawers_txt_path)}\n"
        if shelves_csv_path:
            text += f"Слоты хранения (CSV): {os.path.basename(shelves_csv_path)}\n"
        report_path = os.path.join(os.path.dirname(blend), f"{bake}_bake_report.txt")
        try:
            with open(report_path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            warn(f"bake: could not write the report file: {exc}")
            report_path = None

    # Visibility after the bake - the two checkboxes in the panel. The result
    # and the model it came from occupy the same place, so either can bury the
    # other; each collection hides only on its own checkbox. The outliner eye
    # brings a collection back; the FBX operator unhides the BAKE side for its
    # own pass, so the engine export never depends on this state.
    coll.hide_viewport = bool(props.bake_hide_bake)
    if props.bake_hide_generated:
        for generated in bpy.data.collections:
            if generated.name.startswith(KITCHEN_COLL_PREFIX):
                generated.hide_viewport = True

    return {
        "bake": bake,
        "collection": coll.name,
        "body": body_info,
        "upper_body": upper_info,
        "doors": doors,
        "drawers": drawers,
        "doors_csv": doors_csv_path,
        "drawers_txt": drawers_txt_path,
        "shelves_csv": shelves_csv_path,
        # The raw rows, not only the paths they were written to. The FBX
        # operator writes the very same tables next to the FBX, in a directory
        # this bake never touches, and re-deriving them would mean a second bake
        # with a second chance to disagree with the numbers already on disk.
        "door_rows": door_rows,
        "drawer_rows": drawer_rows,
        "shelf_rows": shelf_rows,
        "ubx_counts": ubx_counts,
        "report_path": report_path,
    }


def _record_pivot(root):
    """Pivot matrix of a moving root, same rule the bake loop used."""
    if root.parent is not None and root.parent.type == 'EMPTY' \
            and root.parent.name.startswith("SOCKET_"):
        return root.parent.matrix_world.copy()
    return _front_pivot(root)


# Object name marks of the carcasses that carry a storage plan. A plan is only
# ever written by the three section builders that lay out compartments, so
# listing them keeps a stray property on some other object from reaching the
# table.
_CARCASS_MARKS = ("_Carcass", "_WardrobeCarcass", "_CornerCabinet")


def _shelf_slot_type(row):
    """The Type column for one plan row, straight from how it was built.

    `niche` is the only kind that has to look at the front: `closed` behind a
    door, `open` when nothing hangs in front of it. rod / counter / drawer are
    types of their own, because the engine treats a drawer as an addressable
    container and a countertop as a surface - neither is "a niche with a door".
    """
    kind = row.get("kind") or "niche"
    if kind == "niche":
        return "closed" if row.get("front") else "open"
    return kind


def _shelf_rows(sources, door_rows, drawer_rows, split_upper, body_name, upper_name,
                body_frame, upper_pivot, kitchen_id, coll, socket_counters):
    """Storage slots of every carcass, placed in the frame of their own body.

    The boxes come off the plan the generator left on the carcass (see
    core.SHELF_PLAN_KEY), never off the baked mesh: the whole body is one mesh
    by now, so its bounds say nothing about a single compartment.

    A slot that names an opening nobody exported is dropped with a warning. The
    DoorSocket column is a join key copied from the doors table - or, for a
    drawer row, the drawer's own socket - so exporting a row that cannot be
    joined would hand the engine a door it has no mesh or socket for: a silently
    wrong wardrobe is worse than one slot fewer in the report.

    Every row that survives also gets a SlotSocket: an EMPTY minted here and
    parented to the row's body mesh, at the centre of the compartment box, so an
    object attached to it with a zero transform sits in the slot facing the way
    its section faces. `socket_counters` is the SAME dict the door and drawer
    loop already incremented, passed in rather than restarted, because the
    engine rejects a second socket on a number the body is already wearing.

    Ext and Clear are the same box on purpose. These boxes are the engine's
    "is the item inside" colliders, and a shelf board in the middle of a niche
    does not make two of those.
    """
    source_to_door = {d["source"]: (d["socket"], d["body"]) for d in door_rows}
    source_to_drawer = {d["source"]: d for d in drawer_rows}

    rows = []
    seen = set()
    for obj in sorted(sources, key=lambda o: o.name):
        raw = obj.get(SHELF_PLAN_KEY)
        if not raw or not any(m in obj.name for m in _CARCASS_MARKS):
            continue
        try:
            plan = json.loads(raw)
        except (ValueError, TypeError) as exc:
            warn(f"bake: shelf plan of '{obj.name}' is unreadable: {exc}")
            continue

        is_upper_part = _UPPER_MARK in obj.name
        owner = upper_name if (split_upper and is_upper_part) else body_name
        frame = upper_pivot.inverted() if (split_upper and is_upper_part) else body_frame
        # Measured, not assumed: the planned carcasses of both test scenes are
        # pure rotations about Z, the turned sections of the L row at -90 deg.
        yaw = _section_yaw(obj.matrix_world)

        key = _section_key(obj.name)
        section = f"{key[0]}_{key[1]:02d}" if key else obj.name
        # RowName keeps the carcass name minus the SM_<kitchen id> the working
        # model already carries, plus the slot index: stable across re-bakes (it
        # never mentions the bake prefix) and unique within the table.
        tail = obj.name[len("SM_"):] if obj.name.startswith("SM_") else obj.name
        if tail.startswith(f"{kitchen_id}_"):
            tail = tail[len(kitchen_id) + 1:]
        base = tail

        for i, plan_row in enumerate(plan, start=1):
            box = plan_row.get("box")
            if not box or len(box) != 6:
                continue
            slot_type = _shelf_slot_type(plan_row)
            front_src = plan_row.get("front")
            socket_name = None
            depth = None
            if slot_type == "drawer":
                # A drawer row without a drawer to point at is unaddressable -
                # "the keys are in the second ... what?" - so it goes.
                if not front_src:
                    warn(f"bake: slot {i} of '{obj.name}' is a drawer with no "
                         f"source to key on - the row is skipped")
                    continue
                d_row = source_to_drawer.get(front_src)
                if d_row is None:
                    warn(f"bake: slot {i} of '{obj.name}' belongs to the drawer "
                         f"'{front_src}', which has no drawer row - the row is skipped")
                    continue
                socket_name = d_row["socket"]
                # Depth is the travel the TXT reports for this same drawer, not
                # a second measurement of it: one drawer, one number.
                depth = d_row["travel"]
            elif front_src:
                resolved = source_to_door.get(front_src)
                if resolved is None:
                    warn(f"bake: slot {i} of '{obj.name}' is closed by "
                         f"'{front_src}', which has no door row - the row is skipped")
                    continue
                socket_name = resolved[0]

            # The centre of the box, not of anything smaller: this is where an
            # item is considered placed when it enters the slot.
            cx = box[0] + box[3] / 2.0
            cy = box[1] + box[4] / 2.0
            cz = box[2] + box[5] / 2.0
            loc = frame @ (obj.matrix_world @ Vector((cx, cy, cz)))
            # Sizes need the rotation, too: a corner section is turned, so its
            # local axes are not the body's. The two opposite corners of each box
            # give the world axis-aligned span of the slot.
            ext_lo, ext_hi = _world_span(obj.matrix_world, frame, box)
            size = (ext_hi[0] - ext_lo[0], ext_hi[1] - ext_lo[1], ext_hi[2] - ext_lo[2])

            row_name = f"{base}_Z{i:02d}"
            if row_name in seen:
                row_name = f"{base}_{section}_Z{i:02d}"
            seen.add(row_name)

            # A drawer already has the socket its row was keyed on above, and a
            # second one on the same box would leave the engine choosing between
            # two placements nobody specified.
            if slot_type == "drawer":
                slot_socket = socket_name
            else:
                slot_socket = _mint_slot_socket(
                    coll, socket_counters, bpy.data.objects.get(owner),
                    row_name, loc, yaw)
                if slot_socket is None:
                    warn(f"bake: slot {i} of '{obj.name}' has no body '{owner}' "
                         f"to hang its socket on - the row is skipped")
                    continue

            rows.append(shelf_entry(
                row_name, section, owner, slot_type, socket_name, slot_socket,
                (loc.x, loc.y, loc.z),
                size, size,
                1 if slot_type == "rod" else 0,
                depth,
            ))
    return rows


def _section_yaw(matrix):
    """Yaw of a section, flattened to the horizontal plane.

    Measured on both test scenes: every planned carcass is a PURE rotation
    about Z - euler x=y=0, scale 1, determinant +1 - and the turned sections of
    the L row sit at -90 deg, so this is the section's own euler z. The axis is
    projected rather than the euler read because "yaw only" means pitch and roll
    are dropped, not carried into a frame the engine treats as flat.
    """
    x = Vector((matrix[0][0], matrix[1][0], 0.0))
    if x.length < 1e-9:
        return 0.0
    x.normalize()
    return math.atan2(x.y, x.x)


def _mint_slot_socket(coll, counters, owner_obj, row_name, loc, yaw):
    """One EMPTY per exported compartment, parented to its body mesh.

    Returns None when `owner_obj` is missing, and the caller drops the row: a
    shelves row promising a socket the engine cannot find is exactly the failure
    this column exists to prevent, so it is not exported with an empty cell.

    FindMeshSockets (FbxStaticMeshImport.cpp) walks the MESH's own node subtree,
    so a sibling empty is dropped without a word - hence a child of the owner,
    with the same keep-world recipe the door sockets use. Baked bodies sit at
    identity, so that recipe leaves the socket's local transform equal to the
    body-frame numbers the shelves table prints next to it.

    The name is SOCKET_<owner>_<row name>_<NN>. NN continues the per-body counter
    the door and drawer sockets already advanced, so a compartment can never be
    handed a number that body is wearing, and the row name makes the socket
    readable against its CSV line. The `SOCKET_<owner>_` prefix is also what
    _purge_previous matches: without the body in front, a re-bake would leave the
    previous run's slot sockets behind and Blender would rename the new ones.
    """
    if owner_obj is None:
        return None
    owner = owner_obj.name
    counters[owner] = counters.get(owner, 0) + 1
    name = f"SOCKET_{owner}_{row_name}_{counters[owner]:02d}"
    sock = bpy.data.objects.new(name, None)
    coll.objects.link(sock)
    sock.empty_display_type = 'PLAIN_AXES'
    sock.empty_display_size = 0.010
    sock.matrix_world = Matrix.Translation(loc) @ Matrix.Rotation(yaw, 4, 'Z')
    sock.parent = owner_obj
    sock.matrix_parent_inverse = owner_obj.matrix_world.inverted()
    return name


def _world_span(obj_matrix, frame, box):
    """Axis-aligned (lo, hi) of a section-local box, in the body frame.

    Only rotation can turn a local box, and the bake's frames are translations of
    the world frame, so measuring the eight corners is enough and a turned corner
    section still gets a box the engine can collide against.
    """
    m = frame @ obj_matrix
    x0, y0, z0, sx, sy, sz = box
    lo = [1e9, 1e9, 1e9]
    hi = [-1e9, -1e9, -1e9]
    for c in ((x0, y0, z0), (x0 + sx, y0, z0), (x0, y0 + sy, z0), (x0 + sx, y0 + sy, z0),
              (x0, y0, z0 + sz), (x0 + sx, y0, z0 + sz), (x0, y0 + sy, z0 + sz),
              (x0 + sx, y0 + sy, z0 + sz)):
        p = m @ Vector(c)
        for a in range(3):
            v = (p.x, p.y, p.z)[a]
            lo[a] = min(lo[a], v)
            hi[a] = max(hi[a], v)
    return lo, hi


class KITCHEN_OT_Bake(Operator):
    bl_idname = "kitchen.bake_export"
    bl_label = STR["op_bake_label"]
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return getattr(context.scene, "kitchen_props", None) is not None

    def execute(self, context):
        props = context.scene.kitchen_props
        if _sanitize_bake_name(props.bake_name) == props.kitchen_id:
            self.report({'WARNING'}, STR["op_bake_name_bad"])
            return {'CANCELLED'}
        result = bake_kitchen(props, context.scene)
        if result is None:
            self.report({'WARNING'}, STR["op_bake_no_source"])
            return {'CANCELLED'}
        self.report({'INFO'}, STR["op_bake_done"])
        return {'FINISHED'}
