"""core - Enums, asset paths, the warning list and the timing log.

Moved verbatim from the single-module addon; no body was edited during the move.
"""
from mathutils import Vector, Matrix

# [ANCHOR: CONSTANTS]
# ============================================================
SEC_NORMAL = 'NORMAL'
SEC_CORNER = 'CORNER'
SEC_APPLIANCE = 'APPLIANCE'
SEC_HOOD_GAP = 'HOOD_GAP'
SEC_SINK = 'SINK'
SEC_WARDROBE = 'WARDROBE'

CORN_DIAGONAL = 'DIAGONAL'
CORN_DOORS = 'DOORS'
CORN_BLIND = 'BLIND'
CORN_OPEN = 'OPEN'

# Every generation writes into its own collection, named with this prefix plus the
# kitchen id. The generator used to write into whatever collection happened to be
# active, so two runs mixed and a whole run could not be switched off at once.
KITCHEN_COLL_PREFIX = "FURNITURE_"

# Every UBX collider of one generation is linked into a sub-collection named after the
# generation's collection plus this suffix, and holds no parenting at all: the outliner
# shows a flat list of colliders that can be hidden, selected or deleted as one unit,
# instead of colliders scattered between the furniture objects they belong to.
COLLIDER_COLL_SUFFIX = "_Colliders"

# Custom property that records which object a bbox collider was authored from. The
# collider is no longer its child (see COLLIDER_COLL_SUFFIX), so this is how
# sync_bbox_colliders finds the target whose final world transform to copy.
UBX_FOLLOW_KEY = "ubx_follow_target"

# Custom property holding the JSON shelf plan of one carcass: every shelf board, tier
# gap and hanging rod the generator built inside it, as boxes in the section's own frame,
# plus the source door name that closes each one. Captured at generation time, where the
# exact box is known, so the export never has to re-measure it off the merged mesh.
SHELF_PLAN_KEY = "shelf_plan"

# Custom property holding the box centre in the target's local frame. A collider's mesh is
# authored around its own origin - the pivot IS the box centre, which is what the engine
# reads as the collision body's centre - so the offset that used to live in the mesh has to
# be applied to the object transform instead, and re-applied after the target moves.
UBX_LOCAL_CENTER_KEY = "ubx_local_center"

# Geometry-nodes "Smooth by Angle" asset shipped with Blender >= 4.4 (Essentials asset library).
# Socket identifiers are internal names of the bundled node group and may move between
# Blender releases, so they are kept here together with tolerant fallbacks.
GN_SMOOTH_BY_ANGLE_ASSET = "nodes/geometry_nodes_essentials.blend/NodeTree/Smooth by Angle"
GN_SMOOTH_ANGLE_SOCKETS = ("Input_1", "input_1", "Angle")
GN_SMOOTH_ENABLED_SOCKETS = ("Socket_1", "socket_1", "Keep Sharp")

# Collected during a single generation run and surfaced to the user by KITCHEN_OT_Generate.
GEN_WARNINGS = []


def warn(message):
    """Collect a non-fatal issue for the current generation run (deduplicated)."""
    if message and message not in GEN_WARNINGS:
        GEN_WARNINGS.append(message)


def clear_warnings():
    del GEN_WARNINGS[:]


# Console verbosity for per-section timing. Warnings are always printed, this only gates timing.
DEBUG_LOG = True


def log(message):
    if DEBUG_LOG:
        print(message)


def add_extruded_polygon(bm, poly2d, z_bottom, thickness):
    bottom_verts = [bm.verts.new(Vector((p[0], p[1], z_bottom))) for p in poly2d]
    top_verts = [bm.verts.new(Vector((p[0], p[1], z_bottom + thickness))) for p in poly2d]
    n = len(poly2d)
    bm.faces.new(bottom_verts[::-1])
    bm.faces.new(top_verts)
    for i in range(n):
        nxt = (i + 1) % n
        bm.faces.new([bottom_verts[i], bottom_verts[nxt], top_verts[nxt], top_verts[i]])


# ============================================================
