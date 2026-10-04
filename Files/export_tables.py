"""export_tables - Engine-facing tables for the moving parts of a bake.

Two files are written next to the bake report, both keyed by the bake name:

  <bake>_doors.csv    one row per door instance: the socket it hangs on, the
                      unique mesh that socket serves, the panel dimensions and
                      the socket transform rebased into its body - ready for a
                      UE DataTable import (RowName = the socket name, unique
                      per row);
  <bake>_drawers.txt  a readable list of how far every drawer can travel.

CSV numbers are metres with a dot decimal separator, the format the UE
DataTable importer expects. Dimensions are read off the source facade mesh in
its own pivot frame, which is the frame the baked mesh is authored in, so the
table describes the part exactly as the engine receives it.

Drawer travel is a geometric limit, not a slide catalogue: the box travels
forward until its rear wall reaches the front plane of the carcass. The drawer
mesh spans y = -t (facade face) .. box_depth, so the local max-y of the mesh
IS the travel; the same value the colliders were laid out from.
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
        "hinge": "R" if hi[0] <= 0.0 else "L",
        "width": hi[0] - lo[0],
        "height": hi[2] - lo[2],
        "thickness": hi[1] - lo[1],
        "x": socket_matrix.translation.x,
        "y": socket_matrix.translation.y,
        "z": socket_matrix.translation.z,
        "yaw": yaw,
    }


def drawer_entry(source, socket_name, mesh_name, body_name):
    """One TXT record for a drawer, measured in the drawer's own frame.

    The mesh is front plate + tray, so its x/z spans are the facade and its
    max-y is the tray depth the travel stops at (see module docstring).
    """
    lo, hi = _local_bbox(source)
    travel = max(0.0, hi[1])
    return {
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


def write_tables(directory, bake, door_entries, drawer_entries):
    """Write both tables into `directory`; returns (csv_path, txt_path).

    A failure of either write is a warning, not a failed bake: the meshes and
    sockets are already complete, and the same rule the bake report follows
    (never raise over the text files) applies here.
    """
    csv_path = os.path.join(directory, f"{bake}_doors.csv")
    txt_path = os.path.join(directory, f"{bake}_drawers.txt")
    try:
        _write_doors_csv(csv_path, door_entries)
    except OSError as exc:
        warn(f"bake: could not write the doors CSV: {exc}")
        csv_path = None
    try:
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write(_drawers_text(bake, drawer_entries))
    except OSError as exc:
        warn(f"bake: could not write the drawers TXT: {exc}")
        txt_path = None
    return csv_path, txt_path
