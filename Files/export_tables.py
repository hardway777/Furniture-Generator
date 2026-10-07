"""export_tables - Engine-facing tables for the moving parts of a bake.

Four files are written next to the bake report, all keyed by the bake name:

  <bake>_doors.csv    one row per door instance: the socket it hangs on, the
                      unique mesh that socket serves, the panel dimensions and
                      the socket transform rebased into its body - ready for a
                      UE DataTable import (RowName = the socket name, unique
                      per row);
  <bake>_drawers.csv  the same record for a drawer, without the hinge and with
                      the travel instead: one row per drawer INSTANCE, so three
                      rows may name one Mesh. That is the point of it - a
                      shelves row already carries the mount socket and still
                      cannot say what to put there, and the TXT below is prose
                      nobody should have to parse to learn which asset it is;
  <bake>_drawers.txt  a readable list of how far every drawer can travel;
  <bake>_shelves.csv  one row per storage SLOT: one invisible box per
                      functional compartment - the whole niche behind its
                      doors, one single drawer, the surface of a countertop,
                      the air under a hanging rod, an entire open rack - where
                      it is, how big it is, and which opening reaches it.

CSV numbers are metres with a dot decimal separator, the format the UE
DataTable importer expects. Dimensions are read off the source facade mesh in
its own pivot frame, which is the frame the baked mesh is authored in, so the
table describes the part exactly as the engine receives it.

Drawer travel is a geometric limit, not a slide catalogue: the box travels
forward until its rear wall reaches the front plane of the carcass. The drawer
mesh spans y = -t (facade face) .. box_depth, so the local max-y of the mesh
IS the travel; the same value the colliders were laid out from, and the Depth
column of a drawer row copies it verbatim so the two files cannot disagree.

The shelves table is the one table that is NOT measured off a mesh: a carcass
bakes into a single static mesh whose bounds are the whole body, so the boxes
come from the plan the generator left on the carcass object
(core.SHELF_PLAN_KEY), captured where the compartment was laid out.

A slot is a SLOT, not a shelf. Shelves, middle posts and bay dividers inside a
compartment are obstacles an item collides with; they never cut the box in
two, because the engine's "is the item inside" test is built from these boxes
and one compartment is one test. What does cut a box is a different OPENING: a
drawer gets its own row ("the keys are in the second drawer"), a niche with two
doors gets one, and a rack of fifty boards gets one.
"""
import csv
import os
from math import degrees

from .core import warn


def _local_bbox(obj):
    """(lo, hi) of the object's own mesh, in its pivot frame."""
    xs = [c[0] for c in obj.bound_box]
    ys = [c[1] for c in obj.bound_box]
    zs = [c[2] for c in obj.bound_box]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def door_entry(source, socket_name, mesh_name, body_name, socket_matrix):
    """One CSV record for a hinged door, measured in the hinge frame.

    A left-hinged panel occupies x > 0 around its pivot, a right-hinged one
    x < 0 (create_panel_mesh slides the slab by +/- the same offset), so the
    sign of the x span is the hinge side without touching any generator state.
    """
    lo, hi = _local_bbox(source)
    yaw = degrees(socket_matrix.to_euler().z)
    return {
        "row_name": socket_name,
        "source": source.name,
        "body": body_name,
        "socket": socket_name,
        "mesh": mesh_name,
        # The engine's DataTable importer matches native enum values by NAME
        # only (UEnum::GetIndexByNameString checks authored names for Blueprint
        # enums alone), so spell the enumerators out: "L"/"R" would fail import
        # and every right-hinged door would silently become left-hinged.
        "hinge": "Right" if hi[0] <= 0.0 else "Left",
        "width": hi[0] - lo[0],
        "height": hi[2] - lo[2],
        "thickness": hi[1] - lo[1],
        "x": socket_matrix.translation.x,
        "y": socket_matrix.translation.y,
        "z": socket_matrix.translation.z,
        "yaw": yaw,
    }


def drawer_entry(source, socket_name, mesh_name, body_name):
    """One record for a drawer, measured in the drawer's own frame.

    The mesh is front plate + tray, so its x/z spans are the facade and its
    max-y is the tray depth the travel stops at (see module docstring).

    One entry per drawer INSTANCE, not per unique mesh: the bake already
    deduplicates identical drawers into a single Mesh, and this record is
    what lets the engine tell those instances apart - the socket is theirs,
    the mesh is shared. RowName is the socket, mirroring the doors table.
    """
    lo, hi = _local_bbox(source)
    travel = max(0.0, hi[1])
    return {
        "row_name": socket_name,
        "source": source.name,
        "socket": socket_name,
        "mesh": mesh_name,
        "body": body_name,
        "front_w": hi[0] - lo[0],
        "front_h": hi[2] - lo[2],
        "box_depth": hi[1],
        "travel": travel,
    }


_CSV_HEADER = ("RowName", "Source", "Body", "Socket", "Mesh", "Hinge",
               "Width", "Height", "Thickness",
               "SocketX", "SocketY", "SocketZ", "SocketYawDeg")

# One row per drawer INSTANCE - three of them may name the same Mesh, which is
# the whole reason this file exists: the shelves table's drawer row has the
# mount socket and no asset to build from, and _drawers.txt is prose.
#
# The first five columns are the doors table's first five, in the same order,
# so both can be read as "moving part" tables and joined the same way -
# _shelves.csv DoorSocket resolves into Socket in either of them. Width and
# Height are the facade; Depth is the travel, byte-identical to the Depth
# column of the shelves row that joins here (the two are written from one
# number so they cannot disagree).
_DRAWERS_HEADER = ("RowName", "Source", "Body", "Socket", "Mesh",
                   "Width", "Height", "Depth")

# Storage slots. Ext* is the whole compartment box; Clear* repeats it, because
# the engine builds its containment collider from these boxes and "which shelf
# inside is the item on" is not a question it asks. MaxVolume is that box in
# litres, MaxItems a coarse reference (1 for a rod, 0 everywhere else). Depth
# is filled only for Type=drawer, where it is the travel the drawer TXT reports.
# Type: closed | open | rod | counter | drawer
#
# DoorSocket and SlotSocket answer different questions. DoorSocket is which
# OPENING reaches the compartment - a join key copied from the doors table, and
# for a drawer the drawer's mount socket. SlotSocket is where an object placed
# INSIDE the compartment attaches: a socket minted per exported slot and
# parented to the slot's body mesh, so the engine's FindMeshSockets finds it
# inside that mesh's own node subtree. On a drawer row it is parented to the
# DRAWER mesh instead, at the centre of the drawer's own frame - the component
# it carries has to travel with the drawer, and the mount socket in DoorSocket
# stays on the body by design. An empty DoorSocket (open niche, countertop,
# rod) says nothing opens the slot; SlotSocket is never empty on an exported
# row.
_SHELVES_HEADER = ("RowName", "Section", "Body", "Type", "DoorSocket", "SlotSocket",
                   "LocX", "LocY", "LocZ",
                   "ExtX", "ExtY", "ExtZ",
                   "ClearX", "ClearY", "ClearZ",
                   "MaxVolume", "MaxItems", "Depth")


def _write_doors_csv(path, entries):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CSV_HEADER)
        for d in entries:
            writer.writerow([
                d["row_name"], d["source"], d["body"], d["socket"], d["mesh"],
                d["hinge"],
                f"{d['width']:.4f}", f"{d['height']:.4f}", f"{d['thickness']:.4f}",
                f"{d['x']:.4f}", f"{d['y']:.4f}", f"{d['z']:.4f}",
                f"{d['yaw']:.2f}",
            ])


def shelf_entry(row_name, section, body, slot_type, door_socket, slot_socket,
                loc, ext, clear, max_items, depth=None):
    """One CSV record for a storage slot, placed in its body's frame.

    `loc` is the centre of the box, `ext`/`clear` the full sizes; all are
    already rebased into the body pivot by the bake, the same convention the
    doors table uses, so both tables can be joined on Body and share one space.

    `door_socket` is copied verbatim from the Socket column of the doors CSV for
    a closed/open slot, and for Type=drawer the drawer's own mount socket - an
    engine join key, not a derived name, which is why an unresolved one drops
    the row instead of exporting a guess. None means nothing opens this slot
    (an open niche, a countertop, a rack with no door).

    `slot_socket` is the socket an object INSIDE the compartment hangs on: one
    minted for this row, so the engine's FindMeshSockets finds it inside the
    mesh's own node subtree. That mesh is the row's body - except for a drawer,
    where it is the drawer mesh, because the compartment component has to leave
    the carcass with the drawer while the mount socket stays behind on the body.
    None only when the drawer mesh or its mount is missing from the bake, which
    the bake warns about and the row then drops.

    `depth` is None except for Type=drawer, where it is the travel extent in
    metres - the same number `_drawers.txt` prints for that drawer.
    """
    volume = ext[0] * ext[1] * ext[2] * 1000.0
    return {
        "row_name": row_name,
        "section": section,
        "body": body,
        "type": slot_type,
        "door_socket": door_socket,
        "slot_socket": slot_socket,
        "loc": loc,
        "ext": ext,
        "clear": clear,
        "volume": volume,
        "max_items": max_items,
        "depth": depth,
    }


def _write_drawers_csv(path, entries):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_DRAWERS_HEADER)
        for d in entries:
            writer.writerow([
                d["row_name"], d["source"], d["body"], d["socket"], d["mesh"],
                f"{d['front_w']:.4f}", f"{d['front_h']:.4f}",
                f"{d['travel']:.4f}",
            ])


def _write_shelves_csv(path, entries):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_SHELVES_HEADER)
        for s in entries:
            loc, ext, clear = s["loc"], s["ext"], s["clear"]
            writer.writerow([
                s["row_name"], s["section"], s["body"], s["type"],
                s["door_socket"] if s["door_socket"] else "",
                s["slot_socket"] if s["slot_socket"] else "",
                f"{loc[0]:.4f}", f"{loc[1]:.4f}", f"{loc[2]:.4f}",
                f"{ext[0]:.4f}", f"{ext[1]:.4f}", f"{ext[2]:.4f}",
                f"{clear[0]:.4f}", f"{clear[1]:.4f}", f"{clear[2]:.4f}",
                f"{s['volume']:.3f}", s["max_items"],
                "" if s["depth"] is None else f"{s['depth']:.4f}",
            ])


def _drawers_text(bake, entries):
    lines = [f"Предельное выдвижение ящиков: {bake}", ""]
    lines.append("Выдвижение ограничено коробом: ящик выезжает до тех пор, пока его")
    lines.append("задняя стенка не дойдёт до переднего среза корпуса, поэтому выезд")
    lines.append("равен глубине короба (глубина секции минус стенка и 10 мм зазора).")
    lines.append("")
    lines.append(f"Ящиков: {len(entries)}")
    for d in entries:
        lines.append(f"  {d['source']}  (сокет {d['socket']}, меш {d['mesh']},"
                     f" корпус {d['body']})")
        lines.append(f"      фасад {d['front_w'] * 1000:.0f} x {d['front_h'] * 1000:.0f} мм, "
                     f"короб глубиной {d['box_depth'] * 1000:.0f} мм")
        lines.append(f"      максимальное выдвижение: {d['travel']:.3f} м "
                     f"({d['travel'] * 1000:.0f} мм)")
    return "\n".join(lines) + "\n"


def _unlink(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _write_batch(targets):
    """Write every table beside its target, then swap all of them in.

    One batch, because the engine imports the tables together with the FBX
    and joins them on Socket: a set written half way - fresh doors next to
    shelves left over from the previous bake - would diverge there with no
    error anywhere. Two ways to fail, and both say "none of them":

    * the WRITE fails (disk full, permission, path) - nothing is swapped,
      so whatever was on disk stays on disk, whole;
    * a SWAP fails (a destination locked by whoever is importing) - every
      file already swapped is put back byte for byte from a snapshot taken
      before the first one moved. The file that refused is the one that
      never moved, so the restore never has to touch it.

    Returns the target path of each table holding the new content, None for
    the ones that do not - so a caller can still name what was lost.
    """
    staged = []
    try:
        for final, write in targets:
            tmp = final + ".tmp"
            write(tmp)
            staged.append((tmp, final))
    except OSError as exc:
        warn(f"bake: table batch stopped while writing, nothing replaced: {exc}")
        for tmp, _ in staged:
            _unlink(tmp)
        return [None] * len(targets)

    # What is on disk right now. These are three small CSVs, read once,
    # before anything moves - cheaper than a .old copy per file and it does
    # not leave a half-renamed directory behind if the process dies.
    before = []
    for _, final in staged:
        try:
            with open(final, "rb") as fh:
                before.append(fh.read())
        except OSError:
            before.append(None)

    for i, (tmp, final) in enumerate(staged):
        try:
            os.replace(tmp, final)
        except OSError as exc:
            warn(f"bake: table batch could not swap "
                 f"{os.path.basename(final)} in, previous set restored: {exc}")
            # Only the ones already swapped moved; the rest never did.
            for (_, done_path), old in zip(staged[:i], before[:i]):
                if old is None:
                    _unlink(done_path)
                    continue
                try:
                    with open(done_path, "wb") as fh:
                        fh.write(old)
                except OSError as restore_exc:
                    warn(f"bake: could not restore "
                         f"{os.path.basename(done_path)}: {restore_exc}")
            for tmp2, _ in staged[i:]:
                _unlink(tmp2)
            return [None] * len(targets)
    return [final for _, final in staged]


def write_tables(directory, bake, door_entries, drawer_entries, shelf_entries=None):
    """Write the four tables into `directory`; returns
    (doors_csv, drawers_csv, drawers_txt, shelves_csv).

    The three CSVs are written as ONE batch (see _write_batch): all of them,
    or none of them. The TXT is prose and goes on its own - a report that
    cannot be written must not take the machine tables with it.

    A failure is still a warning, not a failed bake: the meshes and sockets
    are already complete, and the same rule the bake report follows (never
    raise over the text files) applies here.

    A model with no storage slot at all still gets a shelves CSV with just its
    header: the engine side reads the file unconditionally, and "no slots" is a
    different answer from "no file". The drawers CSV is header-only for the
    same reason - a model with no drawer says so by having no row, not by
    having no file.
    """
    targets = (
        (os.path.join(directory, f"{bake}_doors.csv"),
         lambda p: _write_doors_csv(p, door_entries)),
        (os.path.join(directory, f"{bake}_drawers.csv"),
         lambda p: _write_drawers_csv(p, drawer_entries)),
        (os.path.join(directory, f"{bake}_shelves.csv"),
         lambda p: _write_shelves_csv(p, shelf_entries or [])),
    )
    txt_path = os.path.join(directory, f"{bake}_drawers.txt")
    doors_csv_path, drawers_csv_path, shelves_path = _write_batch(targets)

    try:
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write(_drawers_text(bake, drawer_entries))
    except OSError as exc:
        warn(f"bake: could not write the drawers TXT: {exc}")
        txt_path = None
    return doors_csv_path, drawers_csv_path, txt_path, shelves_path
