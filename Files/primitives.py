"""primitives - Mesh construction: boxes, panels, countertop slabs, handles, rods.

Moved verbatim from the single-module addon; no body was edited during the move.
"""
import bpy
import bmesh
from mathutils import Vector, Matrix
from math import radians, cos, sin, atan2, pi
from .core import warn
from .mesh_ops import (
    add_and_apply_smooth,
    apply_bevel_to_object,
    apply_box_uvs,
    apply_edge_bevel_weights,
    create_ubx_box_primitive,
    create_ubx_from_bbox,
    ensure_material,
    mark_mesh_facade_bevel_weights,
    _select_only,
    _restore_selection,
)

# [ANCHOR: FACADE_ASSEMBLY]
# ============================================================
def create_hinge_empty(socket_name, collection, parent, matrix_world, display_type=None):
    """Door pivot empty that becomes a socket in UE. Every hinged door pivots on one of these."""
    hinge = bpy.data.objects.new(socket_name, None)
    collection.objects.link(hinge)
    hinge.empty_display_size = 0.010
    if display_type:
        hinge.empty_display_type = display_type
    hinge.parent = parent
    hinge.matrix_world = matrix_world
    return hinge


def build_facade_object(name, mesh, collection, parent, mat, matrix_world=None,
                        face="front", use_bevel=True, bevel_w=0.002, bevel_segs=2,
                        gen_collisions=True, ubx=True):
    """Shared tail for every facade element: doors, drawer fronts, island back panels.

    The order mirrors the inline copies this replaced and matters: bevel weights must reach
    the mesh before the modifier exists, the world transform has to be set before the bevel
    modifier is applied and before the box UVs are baked from the bounding box, and the UBX
    collider is finally taken from the resulting bound_box.

    face is passed to mark_mesh_facade_bevel_weights: 'front' when the visible side is local
    -Y, 'back' for the mirrored ones (island back panel, corner door 2).
    """
    if use_bevel:
        mark_mesh_facade_bevel_weights(mesh, face=face)
    obj = new_object(name, mesh, collection, parent, mat["name"])
    if matrix_world is not None:
        obj.matrix_world = matrix_world
    if use_bevel:
        apply_bevel_to_object(obj, bevel_w, bevel_segs)
    apply_box_uvs(obj, mat["u"], mat["v"], mat["rot"])
    if gen_collisions and ubx:
        create_ubx_from_bbox(obj, 1, collection)
    return obj


# ============================================================
# [ANCHOR: MESH_PRIMITIVES]
# ============================================================
def new_object(name, mesh, collection, parent=None, material_name=None):
    if name in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    if parent:
        obj.parent = parent
    if material_name:
        mat = ensure_material(material_name)
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
    return obj


def create_box_from_verts(verts, faces):
    mesh = bpy.data.meshes.new("tmp")
    mesh.from_pydata([v[:] for v in verts], [], faces)
    mesh.update()

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def add_box(verts, faces, x0, y0, z0, sx, sy, sz):
    base = len(verts)
    verts.extend([
        Vector((x0, y0, z0)),
        Vector((x0 + sx, y0, z0)),
        Vector((x0 + sx, y0 + sy, z0)),
        Vector((x0, y0 + sy, z0)),
        Vector((x0, y0, z0 + sz)),
        Vector((x0 + sx, y0, z0 + sz)),
        Vector((x0 + sx, y0 + sy, z0 + sz)),
        Vector((x0, y0 + sy, z0 + sz)),
    ])
    faces.extend([
        (base + 0, base + 3, base + 2, base + 1),
        (base + 4, base + 5, base + 6, base + 7),
        (base + 0, base + 1, base + 5, base + 4),
        (base + 2, base + 3, base + 7, base + 6),
        (base + 0, base + 4, base + 7, base + 3),
        (base + 1, base + 2, base + 6, base + 5),
    ])


def create_panel_mesh(name, width, height, thickness, x_offset=0.0, y_offset=0.0):
    """A flat box used for every door and facade panel.

    The panel is built centred on X/Z and then slid into place, which is what all the
    previous inline copies did in one of two equivalent spellings: scale-then-shift
    (v.co.x *= w; v.co.x += shift) or offset-then-scale (v.co.x = (v.co.x + 0.5) * w).
    Both land on x=[x_offset-w/2, x_offset+w/2], y=[y_offset-t/2, y_offset+t/2],
    z=[-h/2, h/2], so a door is fully described by two offsets:

        door hinged at its left edge, face outward   -> ( w/2, +t/2)
        door hinged at its right edge                -> (-w/2, +t/2)
        corner door 2, mirrored across the mitre     -> ( w/2, -t/2)

    The y_offset sign is what decides which local face is the visible one, so it must stay
    in sync with the face= argument given to build_facade_object.
    """
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(
        bm, size=1.0,
        matrix=Matrix.Translation(Vector((x_offset, y_offset, 0.0)))
               @ Matrix.Diagonal(Vector((width, thickness, height, 1.0)))
    )
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def add_drawer_boxes(verts, faces, front_w, front_h, t, box_x0, box_x1, lift, wall_h, box_depth):
    """Append one drawer (front plate + bottom + two sides + back) to verts/faces.

    Returns nothing: the mesh boxes and their colliders are separate concerns now, see
    drawer_collider_boxes for the collider side of the same drawer.
    """
    box_w = max(2 * t, box_x1 - box_x0)
    add_box(verts, faces, 0, -t, 0, front_w, t, front_h)
    add_box(verts, faces, box_x0, 0, lift, box_w, box_depth, t)
    add_box(verts, faces, box_x0, 0, lift + t, t, box_depth, wall_h)
    add_box(verts, faces, box_x0 + box_w - t, 0, lift + t, t, box_depth, wall_h)
    add_box(verts, faces, box_x0 + t, box_depth - t, lift + t, box_w - 2 * t, t, wall_h)


def drawer_collider_boxes(front_w, front_h, t, box_x0, box_x1, lift, wall_h, box_depth):
    """The four collider boxes of one drawer, in the drawer's own local space.

    A drawer is hollow by design: the mesh add_drawer_boxes builds is a front plate plus
    bottom, two sides and a back, and the volume they enclose is where the stored items
    go. One bound_box collider around that mesh fills the cavity, so the game engine
    sees a solid block and nothing can be put inside. The replacement is one collider per
    wall: bottom, left, right, back. The front plate is the fifth collider, added by
    add_drawer_colliders, and the handle already has its own - so the moving part ends up
    with 4 tray boxes + 1 front + 1 handle while the interior stays empty and can hold items.

    The top is deliberately left open. A lid over the opening reads as a solid floor at the
    top of the cavity, so items cannot be put into the drawer at all.
    """
    box_w = max(2 * t, box_x1 - box_x0)
    return [
        (box_x0, 0, lift, box_w, box_depth, t),
        (box_x0, 0, lift + t, t, box_depth, wall_h),
        (box_x0 + box_w - t, 0, lift + t, t, box_depth, wall_h),
        (box_x0 + t, box_depth - t, lift + t, box_w - 2 * t, t, wall_h),
    ]


def add_drawer_colliders(drawer_obj, front_w, front_h, t, boxes, collection, matrix):
    """Emit the drawer's collider set: the hollow tray walls plus the front plate.

    `boxes` is the four-piece list from drawer_collider_boxes (bottom, left, right, back),
    emitted as UBX 01..04. The front plate is emitted as UBX 05: it is a thin box exactly
    the size of the visible face, so the tray stays closed towards the user without filling
    the cavity. The drawer must be built with ubx=False - the single
    bound_box collider would cover front and box at once and read as a solid block.

    Uses the same factory as the countertop cutout colliders, so the pieces are explicit
    box primitives rather than a bound_box snapshot. They are unparented and linked into
    the generation's `_Colliders` collection: a collider that is a child of its mesh would
    sit in the outliner between the drawer and its handle instead of in the flat collider
    list, and `sync_bbox_colliders` re-reads the world matrix of every UBX whose parent is a
    MESH, which would collapse five offset pieces onto the drawer origin (see
    AGENT_NOTES.md [NOTE_16546]); box primitives are not followed by that pass and keep the
    transform given here. `matrix` is the drawer's own world matrix, so the box coordinates
    are the drawer-local ones add_drawer_boxes used for the mesh.
    """
    for i, (x0, y0, z0, sx, sy, sz) in enumerate(boxes):
        create_ubx_box_primitive(drawer_obj, i + 1, x0, y0, z0, sx, sy, sz, collection, matrix)
    create_ubx_box_primitive(drawer_obj, len(boxes) + 1,
                             0, -t, 0, front_w, t, front_h, collection, matrix)


def create_countertop_with_sink_cutout(x0, y0, z0, w, d, h, hx0, hy0, hw, hd):
    """
    Constructs a manifold countertop prism with an orthogonal 3x3 quad grid around the cutout.
    Eliminates diagonal corner edges, preventing normal pinching and shading artifacts on bevels.
    """
    x1, x2, x3, x4 = x0, hx0, hx0 + hw, x0 + w
    y1, y2, y3, y4 = y0, hy0, hy0 + hd, y0 + d
    z_bot, z_top = z0, z0 + h

    # 16 top vertices (grid 4x4)
    top_grid = [
        Vector((x, y, z_top))
        for y in (y1, y2, y3, y4)
        for x in (x1, x2, x3, x4)
    ]
    # 16 bottom vertices (grid 4x4)
    bot_grid = [
        Vector((x, y, z_bot))
        for y in (y1, y2, y3, y4)
        for x in (x1, x2, x3, x4)
    ]
    verts = top_grid + bot_grid

    # 8 quads surrounding the center hole (cell [1,1] is skipped)
    # Grid indexing: row * 4 + col
    top_faces = [
        (0, 1, 5, 4),     # Front-Left
        (1, 2, 6, 5),     # Front-Mid
        (2, 3, 7, 6),     # Front-Right
        (4, 5, 9, 8),     # Mid-Left
        (6, 7, 11, 10),   # Mid-Right
        (8, 9, 13, 12),   # Back-Left
        (9, 10, 14, 13),  # Back-Mid
        (10, 11, 15, 14), # Back-Right
    ]

    # Mirror for bottom faces (reversed winding for correct normals)
    bot_faces = [(f[0] + 16, f[3] + 16, f[2] + 16, f[1] + 16) for f in top_faces]

    # Outer vertical walls
    outer_walls = [
        # Front wall (y = y1)
        (0, 16, 17, 1), (1, 17, 18, 2), (2, 18, 19, 3),
        # Right wall (x = x4)
        (3, 19, 23, 7), (7, 23, 27, 11), (11, 27, 31, 15),
        # Back wall (y = y4)
        (15, 31, 30, 14), (14, 30, 29, 13), (13, 29, 28, 12),
        # Left wall (x = x1)
        (12, 28, 24, 8), (8, 24, 20, 4), (4, 20, 16, 0)
    ]

    # Inner cutout walls (around the hole)
    inner_walls = [
        (5, 6, 22, 21),   # Inner Front
        (6, 10, 26, 22),  # Inner Right
        (10, 9, 25, 26),  # Inner Back
        (9, 5, 21, 25)    # Inner Left
    ]

    faces = top_faces + bot_faces + outer_walls + inner_walls
    return create_box_from_verts(verts, faces)


def solve_sink_cutout(slab_x, slab_y, slab_w, slab_d, ref_x, ref_w,
                      sink_w, sink_d, margin_f, margin_b, margin_l, margin_r, collar=0.035):
    """Rectangular cutout rect: user margins position it, collars and back/right margins keep
    it inside the slab. ref_x/ref_w is the owning section frame (a whole slab for straight
    countertops, one section for a shared island slab)."""
    raw_hw = min(sink_w, ref_w - collar * 2)
    raw_hd = min(sink_d, slab_d - collar * 2)

    raw_hx0 = ref_x + margin_l if margin_l > 0.01 else ref_x + (ref_w - raw_hw) / 2.0
    raw_hy0 = slab_y + margin_f

    x_hi = min(slab_x + slab_w - collar - raw_hw, slab_x + slab_w - margin_r - raw_hw)
    y_hi = min(slab_y + slab_d - collar - raw_hd, slab_y + slab_d - margin_b - raw_hd)

    hx0 = max(slab_x + collar, min(x_hi, raw_hx0))
    hy0 = max(slab_y + collar, min(y_hi, raw_hy0))
    hw = max(0.10, min(slab_w - collar * 2, raw_hw))
    hd = max(0.10, min(slab_d - collar * 2, raw_hd))

    achieved_l = hx0 - slab_x
    achieved_r = (slab_x + slab_w) - (hx0 + hw)
    achieved_f = hy0 - slab_y
    achieved_b = (slab_y + slab_d) - (hy0 + hd)
    for side, wanted, got in (("left", margin_l, achieved_l), ("right", margin_r, achieved_r),
                              ("front", margin_f, achieved_f), ("back", margin_b, achieved_b)):
        if wanted - got > 0.001:
            warn(f"Sink cutout: {side} margin {wanted:.3f} m does not fit, got {got:.3f} m "
                 f"(collar {collar:.3f} m and slab {slab_w:.3f} x {slab_d:.3f} m take precedence)")
    return hx0, hy0, hw, hd


def create_island_countertop_mesh(ct_x, ct_y, ct_z, ct_w, ct_d, ct_h, corner_radius, sink_data=None):
    """
    Constructs a monolithic island countertop slab with rounded outer corners (BMesh bevel)
    and optional rectangular sink cutout, plus prepares outer perimeter bevel weights.
    """
    if sink_data is not None:
        hx0, hy0, hw, hd = sink_data
        base_mesh = create_countertop_with_sink_cutout(ct_x, ct_y, ct_z, ct_w, ct_d, ct_h, hx0, hy0, hw, hd)
        bm = bmesh.new()
        bm.from_mesh(base_mesh)
        bpy.data.meshes.remove(base_mesh)

        outer_corners_x = (ct_x, ct_x + ct_w)
        outer_corners_y = (ct_y, ct_y + ct_d)
        vert_edges = []
        for e in bm.edges:
            v0, v1 = e.verts[0].co, e.verts[1].co
            if abs(v0.x - v1.x) < 1e-4 and abs(v0.y - v1.y) < 1e-4 and abs(v0.z - v1.z) > 1e-4:
                is_outer_x = any(abs(v0.x - ox) < 1e-4 for ox in outer_corners_x)
                is_outer_y = any(abs(v0.y - oy) < 1e-4 for oy in outer_corners_y)
                if is_outer_x and is_outer_y:
                    vert_edges.append(e)

        max_r = min(ct_w / 2.0 - 0.005, ct_d / 2.0 - 0.005)
        dist_to_sink_x = min(abs(hx0 - ct_x), abs((ct_x + ct_w) - (hx0 + hw)))
        dist_to_sink_y = min(abs(hy0 - ct_y), abs((ct_y + ct_d) - (hy0 + hd)))
        max_r = max(0.001, min(max_r, dist_to_sink_x - 0.015, dist_to_sink_y - 0.015))
        r = min(corner_radius, max_r)

        if r > 0.002 and len(vert_edges) == 4:
            # Dynamic segments based on curvature radius, minimum 2
            corner_segs = max(2, int(2 + r * 160))
            bmesh.ops.bevel(
                bm, geom=vert_edges, offset=r, offset_type='OFFSET',
                segments=corner_segs, profile=0.5, affect='EDGES', clamp_overlap=True
            )

        mesh = bpy.data.meshes.new("tmp_island_ct")
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()

    else:
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        for v in bm.verts:
            v.co.x = ct_x + (v.co.x + 0.5) * ct_w
            v.co.y = ct_y + (v.co.y + 0.5) * ct_d
            v.co.z = ct_z + (v.co.z + 0.5) * ct_h

        vert_edges = [
            e for e in bm.edges
            if abs(e.verts[0].co.x - e.verts[1].co.x) < 1e-4
               and abs(e.verts[0].co.y - e.verts[1].co.y) < 1e-4
               and abs(e.verts[0].co.z - e.verts[1].co.z) > 1e-4
        ]

        max_r = min(ct_w / 2.0 - 0.005, ct_d / 2.0 - 0.005)
        r = min(corner_radius, max(0.001, max_r))

        if r > 0.002 and len(vert_edges) == 4:
            # Dynamic segments based on curvature radius, minimum 2
            corner_segs = max(2, int(2 + r * 160))
            bmesh.ops.bevel(
                bm, geom=vert_edges, offset=r, offset_type='OFFSET',
                segments=corner_segs, profile=0.5, affect='EDGES', clamp_overlap=True
            )

        mesh = bpy.data.meshes.new("tmp_island_ct")
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()

    # Mark all perimeter edges on the top surface for the micro-bevel
    top_z = ct_z + ct_h
    edge_map = {tuple(sorted(e.vertices)): e.index for e in mesh.edges}
    side_edge_indices = set()
    for poly in mesh.polygons:
        if abs(poly.normal.z) < 0.2:
            p_verts = poly.vertices
            n_v = len(p_verts)
            for i in range(n_v):
                ek = tuple(sorted((p_verts[i], p_verts[(i + 1) % n_v])))
                if ek in edge_map:
                    side_edge_indices.add(edge_map[ek])

    target_top_edges = []
    for e in mesh.edges:
        v1 = mesh.vertices[e.vertices[0]].co
        v2 = mesh.vertices[e.vertices[1]].co
        if abs(v1.z - top_z) < 1e-4 and abs(v2.z - top_z) < 1e-4:
            if e.index in side_edge_indices:
                target_top_edges.append(e.index)

    apply_edge_bevel_weights(mesh, target_top_edges, 1.0)
    return mesh


# ============================================================
# [ANCHOR: SINK_BOWL]
# ============================================================
def sink_bowl_grid(x0, y0, w, d, margin_f, margin_b, margin_l, margin_r, sq=None):
    """Six grid lines per axis of the sink bowl, plus the recess rect and corner side.

    Shared by the mesh builder and the bevel-group classifier so both agree on where the
    recess boundary is - the margin clamp is not duplicated between them.
    """
    # Clamp every margin so the recess keeps a positive size whatever the user asks for:
    # each side can take at most half the smaller footprint side, which keeps the grid
    # lines monotonic (bx0 < bx1, by0 < by1) even when two opposite margins are huge.
    lim = max(0.001, min(w, d) / 2.0 - 0.001)
    m_l = max(0.0, min(margin_l, lim))
    m_r = max(0.0, min(margin_r, lim))
    m_f = max(0.0, min(margin_f, lim))
    m_b = max(0.0, min(margin_b, lim))
    bx0, bx1 = x0 + m_l, x0 + w - m_r
    by0, by1 = y0 + m_f, y0 + d - m_b
    # The corner-cell side `sq` is chosen so that all four corner cells are 1:1 squares.
    if sq is None:
        sq = max(0.0005, min(m_l, m_r, m_f, m_b,
                             (bx1 - bx0) / 2.0, (by1 - by0) / 2.0))
    else:
        sq = max(0.0005, min(sq, (bx1 - bx0) / 2.0, (by1 - by0) / 2.0))
    xs = [x0, bx0, bx0 + sq, bx1 - sq, bx1, x0 + w]
    ys = [y0, by0, by0 + sq, by1 - sq, by1, y0 + d]
    return xs, ys, (bx0, bx1, by0, by1), sq


def create_sink_bowl_mesh(x0, y0, w, d, z_top, z_bot,
                          margin_f, margin_b, margin_l, margin_r,
                          sq=None, rim_extrude=0.0):
    """First sink primitive: a rim flange plus a rectangular bowl extruded down.

    The slab footprint (x0, y0, w, d) is the whole area that fits into the countertop
    cutout, and it lies flat at z_top.  The bowl is inset by four independent margins
    from the four sides of the footprint; its walls drop to z_bot and its bottom closes
    the cup.

    Grid layout, matching the two reference sketches:
      top rim    5x5 cells with the middle 3x3 removed  -> 16 quads
      walls      3 segments per wall                    -> 12 quads
      bottom     3x3 cells                              ->  9 quads
    Four corner cells of the 3x3 (labelled 1-4) are always kept square (1:1);
    their side `sq` is derived from the margins and clamped to keep the middle cell
    positive.  The remaining cells are arbitrary rectangles.
    See AGENT_NOTES.md [NOTE_16560].

    `rim_extrude` (> 0) drops the outer perimeter of the footprint straight down by that
    much, giving the sink a visible wall thickness inside the cutout; the shell then closes
    around the top. See AGENT_NOTES.md [NOTE_16575].
    """
    xs, ys, _rect, _sq = sink_bowl_grid(x0, y0, w, d, margin_f, margin_b, margin_l, margin_r, sq)

    verts, index = [], {}

    def vid(i, j, bottom):
        key = (i, j, bottom)
        if key not in index:
            index[key] = len(verts)
            verts.append(Vector((xs[i], ys[j], z_bot if bottom else z_top)))
        return index[key]

    faces = []

    # Rim: the 5x5 cell grid of the footprint minus the 3x3 bowl opening.
    for j in range(5):
        for i in range(5):
            if 1 <= i <= 3 and 1 <= j <= 3:
                continue
            faces.append((vid(i, j, False), vid(i + 1, j, False),
                          vid(i + 1, j + 1, False), vid(i, j + 1, False)))

    # Front (-Y) and back (+Y) walls, three segments each, wound so the visible
    # inner surface faces the cavity.
    for i in range(1, 4):
        faces.append((vid(i, 1, False), vid(i + 1, 1, False),
                      vid(i + 1, 1, True), vid(i, 1, True)))
        faces.append((vid(i + 1, 4, False), vid(i, 4, False),
                      vid(i, 4, True), vid(i + 1, 4, True)))

    # Right (+X) and left (-X) walls, three segments each, wound into the cavity.
    for j in range(1, 4):
        faces.append((vid(4, j, False), vid(4, j + 1, False),
                      vid(4, j + 1, True), vid(4, j, True)))
        faces.append((vid(1, j + 1, False), vid(1, j, False),
                      vid(1, j, True), vid(1, j + 1, True)))

    # Bowl bottom, 3x3 cells facing up, into the bowl.
    for j in range(1, 4):
        for i in range(1, 4):
            faces.append((vid(i + 1, j, True), vid(i + 1, j + 1, True),
                          vid(i, j + 1, True), vid(i, j, True)))

    # Outer rim skirt: walk the footprint perimeter of the 6x6 grid in order and drop one
    # quad per segment, straight down by `rim_extrude`. Wound so the skirt faces outward
    # (away from the bowl), matching the rim's up face at the shared edge.
    if rim_extrude > 0.0:
        z_skirt = z_top - rim_extrude
        loop = ([(i, 0) for i in range(5)]
                + [(5, j) for j in range(5)]
                + [(i, 5) for i in range(5, 0, -1)]
                + [(0, j) for j in range(5, 0, -1)])
        skirt_index = {}

        def skirt_vid(i, j):
            key = (i, j)
            if key not in skirt_index:
                skirt_index[key] = len(verts)
                verts.append(Vector((xs[i], ys[j], z_skirt)))
            return skirt_index[key]

        for k, (i, j) in enumerate(loop):
            ni, nj = loop[(k + 1) % len(loop)]
            faces.append((vid(i, j, False), skirt_vid(i, j),
                          skirt_vid(ni, nj), vid(ni, nj, False)))

    # Winding is authored so every visible surface faces the viewer: the rim up, the
    # recess walls and floor into the cavity. It must NOT be recalculated - the shell is
    # open along its outer perimeter, and recalc_face_normals on an open surface is
    # unreliable. See AGENT_NOTES.md [NOTE_16570].
    mesh = bpy.data.meshes.new("tmp_sink_bowl")
    mesh.from_pydata([v[:] for v in verts], [], faces)
    mesh.update()
    return mesh


# The collider plate thickness of the sink bowl: the same 10 mm the rim skirt of the mesh
# drops inside the cutout (SINK_RIM_EXTRUDE in sections.py), so the collision shell and the
# visible wall of the sink read as one thickness.
SINK_COLLIDER_PLATE = 0.010


def sink_bowl_collider_boxes(x0, y0, w, d, z_top, z_bot,
                             margin_f, margin_b, margin_l, margin_r,
                             plate=SINK_COLLIDER_PLATE):
    """The nine collider boxes of one sink bowl, in the frame the bowl mesh is authored in.

    A bowl is a hollow cup, so a single bound_box collider over it fills the cavity and the
    engine sees a solid block nothing can be dropped into. The replacement covers the three
    surfaces a player actually touches, in the order they are emitted:

      1-4  rim    - the flat flange between the footprint and the recess rect, cut into four
                    strips. Its top face is the countertop top, so a cup slid across the
                    counter crosses the sink without catching on a lip.
      5-8  walls  - one plate per inner wall, standing on the recess rect from the floor to
                    the rim. Each plate is laid OUTSIDE the cavity, so its inner face is
                    exactly the visible wall and the usable air box of the bowl is unchanged.
      9    floor  - a plate whose top face is the bowl floor, so items come to rest on the
                    sink bottom instead of falling through it into the carcass.

    Every box is read off `sink_bowl_grid`, the same grid the mesh is built from, so the
    clamped recess margins are shared with the mesh rather than recomputed here. A side whose
    margin clamps away gets no box at all - there is no wall there to collide with, and a
    zero-size piece would still be exported as a degenerate collision body.
    """
    _xs, _ys, (bx0, bx1, by0, by1), _sq = sink_bowl_grid(
        x0, y0, w, d, margin_f, margin_b, margin_l, margin_r)
    depth = max(0.0, z_top - z_bot)
    # The four recess margins, re-read from the clamped grid: each one is the thickness of
    # the ring the rim strips are cut from, and the most the matching wall plate can take
    # without sticking past the footprint into the countertop.
    m_l, m_r = bx0 - x0, (x0 + w) - bx1
    m_f, m_b = by0 - y0, (y0 + d) - by1
    cav_w, cav_d = bx1 - bx0, by1 - by0

    boxes = []

    def push(bx, by, bz, sx, sy, sz):
        if sx > 1e-6 and sy > 1e-6 and sz > 1e-6:
            boxes.append((bx, by, bz, sx, sy, sz))

    plate = min(plate, depth)
    # 1-4 Rim.
    z_rim = z_top - plate
    push(x0, y0, z_rim, w, m_f, plate)
    push(x0, by1, z_rim, w, m_b, plate)
    push(x0, by0, z_rim, m_l, cav_d, plate)
    push(bx1, by0, z_rim, m_r, cav_d, plate)
    # 5-8 Inner walls.
    t_f, t_b = min(plate, m_f), min(plate, m_b)
    t_l, t_r = min(plate, m_l), min(plate, m_r)
    push(bx0, by0 - t_f, z_bot, cav_w, t_f, depth)
    push(bx0, by1, z_bot, cav_w, t_b, depth)
    push(bx0 - t_l, by0, z_bot, t_l, cav_d, depth)
    push(bx1, by0, z_bot, t_r, cav_d, depth)
    # 9 Floor.
    push(bx0, by0, z_bot - plate, cav_w, cav_d, plate)
    return boxes


SINK_BEVEL_GROUPS = ("floor", "vert", "top")


def classify_sink_bowl_edges(mesh, x0, y0, w, d, z_top, z_bot,
                             margin_f, margin_b, margin_l, margin_r, sq=None):
    """Split the bowl's crease edges into the three bevel groups.

    Matching the reference sketch:
      floor - the perimeter loop where the walls meet the 3x3 bottom (12 edges, z_bot)
      vert  - the four vertical corner posts where two walls meet (4 edges)
      top   - the mouth loop where the walls meet the top rim (12 edges, z_top)

    Only real creases are returned: the intermediate vertical edges between coplanar wall
    segments, and the interior grid edges of the floor and the rim, are left out.
    See AGENT_NOTES.md [NOTE_16565].
    """
    xs, ys, (bx0, bx1, by0, by1), _sq = sink_bowl_grid(
        x0, y0, w, d, margin_f, margin_b, margin_l, margin_r, sq)
    tol = 1e-6

    def on_loop(a, b, z):
        if abs(a.z - z) > tol or abs(b.z - z) > tol:
            return False
        in_rect = (all(bx0 - tol <= v <= bx1 + tol for v in (a.x, b.x))
                   and all(by0 - tol <= v <= by1 + tol for v in (a.y, b.y)))
        if not in_rect:
            return False
        return ((abs(a.x - bx0) < tol and abs(b.x - bx0) < tol)
                or (abs(a.x - bx1) < tol and abs(b.x - bx1) < tol)
                or (abs(a.y - by0) < tol and abs(b.y - by0) < tol)
                or (abs(a.y - by1) < tol and abs(b.y - by1) < tol))

    groups = {name: [] for name in SINK_BEVEL_GROUPS}
    for e in mesh.edges:
        a = mesh.vertices[e.vertices[0]].co
        b = mesh.vertices[e.vertices[1]].co
        if on_loop(a, b, z_bot):
            groups["floor"].append(e.index)
        elif on_loop(a, b, z_top):
            groups["top"].append(e.index)
        elif abs(a.x - b.x) < tol and abs(a.y - b.y) < tol:
            on_x = abs(a.x - bx0) < tol or abs(a.x - bx1) < tol
            on_y = abs(a.y - by0) < tol or abs(a.y - by1) < tol
            # The corner post spans the full bowl depth; the z guard keeps the rim
            # skirt's short verticals (which sit on the footprint, not the recess) out.
            spans = ((abs(a.z - z_bot) < tol and abs(b.z - z_top) < tol)
                     or (abs(a.z - z_top) < tol and abs(b.z - z_bot) < tol))
            if on_x and on_y and spans:
                groups["vert"].append(e.index)
    return groups


# ============================================================
# [ANCHOR: SINK_DRAIN]
# ============================================================
SINK_DRAIN_GROUPS = ("drain_top", "drain_mid", "drain_low")
SINK_DRAIN_SEGMENTS = 32
SINK_DRAIN_MIN_R = 0.02
# Fraction of the central cell's inscribed radius the opening keeps: the outer circle is
# pulled back from the cell rectangle so the transition has a real flat flange around it.
SINK_DRAIN_CELL_CLEAR = 0.88


def create_cylinder_mesh(radius, depth, segments=SINK_DRAIN_SEGMENTS, name="tmp_cylinder"):
    """Closed cylinder used as the Boolean operand that cuts the drain opening.

    A closed cap is mandatory: Boolean DIFFERENCE needs a solid with a defined inside. An
    open tube has no reliable winding number, so the cut is undefined. See [NOTE_16580].
    """
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                          radius1=radius, radius2=radius, depth=depth)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _edges_among(bm, verts):
    """Edges of `bm` whose two endpoints are both in `verts` - the ring a fresh loop makes."""
    vs = set(verts)
    return [e for e in bm.edges if e.verts[0] in vs and e.verts[1] in vs]


def _apply_object_modifier(obj, name):
    """Apply one modifier by name, selecting only its object (bpy.ops needs an active)."""
    selection_state = _select_only(obj)
    try:
        bpy.ops.object.modifier_apply(modifier=name)
    except Exception as exc:
        warn(f"Could not apply '{name}' on '{obj.name}', it stays live: {exc}")
    _restore_selection(selection_state)


def _scale_ring(verts, cx, cy, factor, z_keep):
    """Inset a loop toward its axis (x/y scaled about cx,cy) and pin it to a z plane."""
    for v in verts:
        v.co.x = cx + (v.co.x - cx) * factor
        v.co.y = cy + (v.co.y - cy) * factor
        v.co.z = z_keep


def _ordered_loop(edges):
    """Walk an unordered closed edge set into a single ordered vertex loop."""
    adj = {}
    for e in edges:
        for v in e.verts:
            adj.setdefault(v, []).append(e)
    start_v = edges[0].verts[0]
    loop, prev_e, cur_v = [], None, start_v
    for _ in range(len(edges) + 2):
        nxt = [e for e in adj[cur_v] if e is not prev_e]
        if not nxt:
            break
        e = nxt[0]
        loop.append(e)
        prev_e, cur_v = e, e.other_vert(cur_v)
        if cur_v is start_v:
            break
    return loop


# Debris strainer: a thin perforated disc resting in the second drain step. Two rings of
# rectangular slots, laid out radially. Row 1: count, radius factor, length/width factors
# of the disc radius. See AGENT_NOTES.md [NOTE_16585].
SINK_STRAINER_ROWS = ((16, 0.62, 0.24, 0.12), (8, 0.34, 0.18, 0.12))
SINK_STRAINER_SEGMENTS = 32
# The disc radius is the step-2 floor radius minus this clearance, so it drops in freely.
SINK_STRAINER_CLEARANCE = 0.001


def create_sink_strainer_mesh(radius, thickness, name="tmp_strainer"):
    """Perforated disc: a closed cylinder with two rings of rectangular slots cut out.

    One Boolean DIFFERENCE against a single cutter object that carries every slot as a
    separate closed box, so the whole strainer is one clean manifold. Measured: the result
    volume equals pi r^2 t minus the summed slot volumes to 8e-9 m^3.
    """
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=SINK_STRAINER_SEGMENTS,
                          radius1=radius, radius2=radius, depth=thickness)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def build_sink_strainer_mesh(bowl, cx, cy, z_floor, radius, thickness, gap):
    """Perforated strainer disc in the bowl's local frame; returns (mesh, local_matrix).

    `z_floor` is the step-2 floor plane; `gap` lifts the disc off it (0 = resting on it,
    negative = sunk into it). The slots are cut by one Boolean DIFFERENCE against a single
    cutter object that carries every slot as its own closed box, so the result is one clean
    manifold. Measured: the result volume equals pi r^2 t minus the summed slot volumes to
    8e-9 m^3. The caller owns the returned mesh and places it with the returned matrix.
    """
    local = Matrix.Translation((cx, cy, z_floor + gap + thickness / 2.0))
    mesh = create_sink_strainer_mesh(radius, thickness)
    obj = bpy.data.objects.new("tmp_strainer_obj", mesh)
    bowl.users_collection[0].objects.link(obj)
    obj.matrix_world = bowl.matrix_world @ local

    # One cutter object holding every slot as a closed box: the boxes overlap the disc's
    # top and bottom faces generously so the Boolean sees clean through-cuts.
    cut_mesh = bpy.data.meshes.new("tmp_strainer_cut")
    cut_bm = bmesh.new()
    for count, ring_f, len_f, wid_f in SINK_STRAINER_ROWS:
        ring_r = radius * ring_f
        slot_len = radius * len_f
        slot_wid = radius * wid_f
        for i in range(count):
            ang = 2.0 * pi * i / count
            mat = (Matrix.Translation((cos(ang) * ring_r, sin(ang) * ring_r, 0.0))
                   @ Matrix.Rotation(ang, 4, 'Z')
                   @ Matrix.Diagonal((slot_len, slot_wid, thickness * 6.0, 1.0)))
            bmesh.ops.create_cube(cut_bm, size=1.0, matrix=mat)
    cut_bm.to_mesh(cut_mesh)
    cut_bm.free()
    cutter = bpy.data.objects.new("tmp_strainer_cut_obj", cut_mesh)
    bowl.users_collection[0].objects.link(cutter)
    cutter.matrix_world = obj.matrix_world

    mod = obj.modifiers.new("StrainerCut", 'BOOLEAN')
    mod.operation = 'DIFFERENCE'
    mod.solver = 'EXACT'
    mod.object = cutter
    _apply_object_modifier(obj, "StrainerCut")
    cut_name = cut_mesh.name
    bpy.data.objects.remove(cutter, do_unlink=True)
    if bpy.data.meshes.get(cut_name):
        bpy.data.meshes.remove(bpy.data.meshes[cut_name])
    bpy.data.objects.remove(obj, do_unlink=True)
    return mesh, local


def merge_mesh_into_object(target, mesh, matrix):
    """Append a standalone mesh into target.data, transformed by matrix (target's local frame).

    Used to join the strainer into the bowl: the bowl keeps one mesh datablock, so the
    strainer's faces inherit its single chrome material slot (index 0). bmesh.from_mesh
    appends, so the new geometry is exactly the verts past the pre-append count.
    """
    bm = bmesh.new()
    bm.from_mesh(target.data)
    first = len(bm.verts)
    bm.from_mesh(mesh)
    for v in list(bm.verts)[first:]:
        v.co = matrix @ v.co
    bm.to_mesh(target.data)
    bm.free()
    target.data.update()


def stamp_sink_drain(bowl, x0, y0, w, d, z_bot,
                     margin_f, margin_b, margin_l, margin_r,
                     radius_b, radius_c, depth_1, depth_2,
                     sq=None, segments=SINK_DRAIN_SEGMENTS):
    """Stamp the 2-step drain into the bowl floor; returns its bevel edge groups.

    Circle A (the flange opening) is cut with a Boolean DIFFERENCE of a closed cylinder,
    inscribed in the central floor cell. From the resulting boundary loop the two steps are
    built with bmesh, matching the user's operations:
      A --flat inset--> B --down d1--> B' --flat inset--> C --down d2--> cap
    Winding of the new faces follows the bowl: flange/floors up, step walls into the cup.
    See AGENT_NOTES.md [NOTE_16580].
    """
    xs, ys, (bx0, bx1, by0, by1), _sq = sink_bowl_grid(x0, y0, w, d, margin_f, margin_b, margin_l, margin_r, sq)
    cx, cy = (xs[2] + xs[3]) / 2.0, (ys[2] + ys[3]) / 2.0
    # Circle A is inscribed in the central floor cell by the smaller side (the user's rule),
    # pulled back by SINK_DRAIN_CELL_CLEAR so the transition triangles have a real flange to
    # fan across instead of meeting the cell edge tangentially.
    cell_r = min(xs[3] - xs[2], ys[3] - ys[2]) / 2.0
    if cell_r < SINK_DRAIN_MIN_R:
        # The cell can collapse when the recess margins reach half the recess - the panel's
        # own defaults do exactly that - so fall back to the largest circle the recess can
        # hold, centred on the recess instead of the collapsed cell.
        cx, cy = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
        cell_r = min(bx1 - bx0, by1 - by0) / 2.0 * 0.9
    radius_a = cell_r * SINK_DRAIN_CELL_CLEAR
    # Whatever the centre, the opening must not reach the recess walls, or the Boolean
    # would notch the bowl's own wall.
    radius_a = min(radius_a, (cx - bx0) * 0.95, (bx1 - cx) * 0.95,
                   (cy - by0) * 0.95, (by1 - cy) * 0.95)
    if radius_a < SINK_DRAIN_MIN_R:
        warn("Sink drain skipped: the floor is too small for a drain "
             "(widen the sink or reduce the recess margins)")
        return None
    if depth_1 <= 0.0 or depth_2 <= 0.0:
        return None
    # Keep a visible flange and step ring even when the user asks for oversized diameters.
    if radius_b > radius_a * 0.8:
        radius_b = radius_a * 0.8
    if radius_c > radius_b * 0.8:
        radius_c = radius_b * 0.8

    # 1. Boolean-cut the opening. The cylinder spans the floor plane generously so the cut
    #    is clean; it is placed in world space to match the bowl's own transform.
    cyl_mesh = create_cylinder_mesh(radius_a, depth_1 + depth_2 + 0.06, segments)
    cyl = bpy.data.objects.new("tmp_drain_cyl", cyl_mesh)
    bowl.users_collection[0].objects.link(cyl)
    cyl.matrix_world = bowl.matrix_world @ Matrix.Translation((cx, cy, z_bot))

    mod = bowl.modifiers.new("DrainCut", 'BOOLEAN')
    mod.operation = 'DIFFERENCE'
    mod.solver = 'EXACT'
    mod.use_hole_tolerant = True
    mod.object = cyl
    _apply_object_modifier(bowl, "DrainCut")
    cyl_mesh_name = cyl_mesh.name
    bpy.data.objects.remove(cyl, do_unlink=True)
    if bpy.data.meshes.get(cyl_mesh_name):
        bpy.data.meshes.remove(bpy.data.meshes[cyl_mesh_name])

    # 2. Build the steps from the hole boundary.
    bm = bmesh.new()
    bm.from_mesh(bowl.data)
    # The Boolean leaves the floor cut with n-gons where the circle meets the cell
    # rectangle; the reference sketch shows triangles fanning from the square to the
    # circle, so triangulate those n-gons before the stamp adds the rings.
    ngons = [f for f in bm.faces if len(f.verts) > 4]
    if ngons:
        bmesh.ops.triangulate(bm, faces=ngons)
    tol = 1e-5
    hole = [e for e in bm.edges if e.is_boundary
            and abs(e.verts[0].co.z - z_bot) < tol and abs(e.verts[1].co.z - z_bot) < tol]
    if not hole:
        bm.free()
        return None
    ring_a = _ordered_loop(hole)

    ret = bmesh.ops.extrude_edge_only(bm, edges=ring_a)
    ring_b_verts = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]
    _scale_ring(ring_b_verts, cx, cy, radius_b / radius_a, z_bot)
    ring_b = _edges_among(bm, ring_b_verts)

    ret = bmesh.ops.extrude_edge_only(bm, edges=ring_b)
    ring_b2_verts = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]
    for v in ring_b2_verts:
        v.co.z = z_bot - depth_1
    ring_b2 = _edges_among(bm, ring_b2_verts)

    ret = bmesh.ops.extrude_edge_only(bm, edges=ring_b2)
    ring_c_verts = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]
    _scale_ring(ring_c_verts, cx, cy, radius_c / radius_b, z_bot - depth_1)
    ring_c = _edges_among(bm, ring_c_verts)

    ret = bmesh.ops.extrude_edge_only(bm, edges=ring_c)
    ring_c2_verts = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]
    for v in ring_c2_verts:
        v.co.z = z_bot - depth_1 - depth_2
    ring_c2 = _edges_among(bm, ring_c2_verts)

    # Cap: extrude the last ring once more and collapse it to the axis centre.
    ret = bmesh.ops.extrude_edge_only(bm, edges=ring_c2)
    cap_verts = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]
    for v in cap_verts:
        v.co.z = z_bot - depth_1 - depth_2
    bmesh.ops.pointmerge(bm, verts=cap_verts,
                         merge_co=Vector((cx, cy, z_bot - depth_1 - depth_2)))

    bm.normal_update()
    bm.verts.index_update()
    bm.edges.index_update()
    groups = {
        "drain_top": [e.index for e in ring_b],
        "drain_mid": [e.index for e in ring_b2],
        "drain_low": [e.index for e in ring_c],
    }
    bm.to_mesh(bowl.data)
    bm.free()
    bowl.data.update()
    # The strainer needs the step-2 floor: its plane and the circle it was cut from.
    return groups, {"cx": cx, "cy": cy, "z_floor": z_bot - depth_1 - depth_2, "radius_c": radius_c}


# ============================================================
# [ANCHOR: HARDWARE_HANDLES_RODS]
# ============================================================
def create_handle_mesh(name, radius, bar_len, mount_r, mount_len, mount_span, vertical):
    """Bar plus two standoff mounts baked into a single mesh.

    Replaces the old create-3-objects + bpy.ops.object.join + transform_apply path:
    identical geometry, no selection/active-object dependency and no temp objects.
    """
    bm = bmesh.new()
    bar_matrix = Matrix.Identity(4) if vertical else Matrix.Rotation(radians(90), 4, 'Y')
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=12,
                          radius1=radius, radius2=radius, depth=bar_len, matrix=bar_matrix)

    y = mount_len / 2 - radius * 0.25
    for sign in (-1.0, 1.0):
        if vertical:
            offset = Vector((0.0, y, sign * mount_span / 2.0))
        else:
            offset = Vector((sign * mount_span / 2.0, y, 0.0))
        mount_matrix = Matrix.Translation(offset) @ Matrix.Rotation(radians(90), 4, 'X')
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=12,
                              radius1=mount_r, radius2=mount_r, depth=mount_len, matrix=mount_matrix)

    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def create_handle(name, length=0.128, overhang=0.01, radius=0.007, mount_len=0.018,
                  vertical=False, mat_name="MI_MetalBrownPainted_01", gen_coll=True,
                  tile_u=1.0, tile_v=1.0, rot_uv=False, collection=None):
    if collection is None:
        collection = bpy.context.collection
    mount_r = radius * 0.7
    bar_len = max(0.02, length + overhang * 2)
    mount_span = max(0.01, length - overhang)

    mesh = create_handle_mesh(name, radius, bar_len, mount_r, mount_len, mount_span, vertical)
    joined = new_object(name, mesh, collection, None, mat_name)
    add_and_apply_smooth(joined)
    apply_box_uvs(joined, tile_u=tile_u, tile_v=tile_v, rotate_90=rot_uv)

    if gen_coll:
        create_ubx_from_bbox(joined, col_idx=1, collection=collection)

    return joined


def create_clothes_rod_mesh(span_width, radius=0.0125):
    """Creates a hanging tube with mounting flanges strictly from X=0 to X=span_width"""
    bm = bmesh.new()
    mat_rot = Matrix.Rotation(radians(90), 4, 'Y')
    flange_r = radius * 1.8
    flange_t = 0.006

    mat_tube = Matrix.Translation(Vector((span_width / 2, 0, 0))) @ mat_rot
    bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=radius, radius2=radius, depth=span_width,
                          matrix=mat_tube)

    mat_fl = Matrix.Translation(Vector((flange_t / 2, 0, 0))) @ mat_rot
    bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=flange_r, radius2=flange_r, depth=flange_t,
                          matrix=mat_fl)

    mat_fr = Matrix.Translation(Vector((span_width - flange_t / 2, 0, 0))) @ mat_rot
    bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=flange_r, radius2=flange_r, depth=flange_t,
                          matrix=mat_fr)

    mesh = bpy.data.meshes.new("tmp_rod")
    bm.to_mesh(mesh)
    bm.free()
    return mesh


# ============================================================
