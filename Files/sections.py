"""sections - One section's geometry, from carcass to facade, and the dispatcher.

Moved verbatim from the single-module addon; no body was edited during the move.
"""
import bpy
import bmesh
from mathutils import Vector, Matrix
from math import radians, cos, sin, atan2
from .core import (
    CORN_BLIND,
    CORN_DIAGONAL,
    CORN_DOORS,
    SEC_APPLIANCE,
    SEC_CORNER,
    SEC_HOOD_GAP,
    SEC_NORMAL,
    SEC_SINK,
    SEC_WARDROBE,
    add_extruded_polygon,
    warn,
)
from .mesh_ops import (
    add_and_apply_smooth,
    add_chamfered_corner_box,
    apply_bevel_to_object,
    apply_box_uvs,
    apply_edge_bevel_weights,
    apply_sink_bowl_bevel,
    create_ubx_box_primitive,
    create_ubx_from_bbox,
    mark_mesh_countertop_bevel_weights,
)
from .primitives import (
    add_box,
    add_drawer_boxes,
    add_drawer_colliders,
    build_facade_object,
    build_sink_strainer_mesh,
    classify_sink_bowl_edges,
    create_box_from_verts,
    create_clothes_rod_mesh,
    create_countertop_with_sink_cutout,
    create_handle,
    create_hinge_empty,
    create_panel_mesh,
    create_sink_bowl_mesh,
    drawer_collider_boxes,
    merge_mesh_into_object,
    new_object,
    solve_sink_cutout,
    stamp_sink_drain,
    SINK_STRAINER_CLEARANCE,
)
from .solver import solve_element_heights


def drawer_box_inset(front_x, front_w, interior_x0, interior_x1):
    """Symmetric x inset of a drawer box inside its own front, in front-local metres.

    A drawer box has to stay inside the carcass interior, while its front is an overlay
    that reaches to the edge of the row: on the outer side of an end drawer the front
    hangs over the carcass wall, so the box has to keep at least that much off the front
    edge. Taking the larger of the two overhangs and applying it to BOTH sides is what
    centres the box under its front. Clamping each side to whatever limits it instead -
    the previous behaviour - pressed the box against one wall: measured on a 3-drawer
    bank in 0.80 m, the end drawers had 18.5 mm of dead air on one side and 0 on the
    other, and their cavity sat 9.2 mm off the handle.

    Derived from the user's wall thickness and facade gap, so it follows the settings: for
    a front that spans the row it comes out exactly wall_thickness - gap.
    """
    return max(0.0, interior_x0 - front_x, (front_x + front_w) - interior_x1)


# [ANCHOR: SECTION_BUILDER]
# ============================================================
def build_wardrobe_section(
        name_prefix, width, plinth_recess, shelf_t,
        gap, handle_door, handle_drawer,
        has_plinth, use_legs, leg_height, columns_data, gen_collisions, use_bevel,
        bevel_w, bevel_segs, collection, parent,
        matrix, h, ph, t,
        d, m_carcass, m_plinth, m_facade,
        m_handle
):
    """Tall wardrobe column section: carcass, per-column zones, doors and drawers."""
    # The wardrobe returns from generate_section before the shared support pass, so it has
    # to make the same legs/plinth choice itself. Reading has_plinth alone was enough while
    # legs were on: row.py drops the plinth flag then, so a legged wardrobe got neither.
    if use_legs and leg_height > 0.0:
        build_legs(
            name_prefix=name_prefix, width=width, d=d, leg_h=leg_height,
            gen_collisions=gen_collisions, collection=collection, parent=parent,
            matrix=matrix, m_plinth=m_plinth
        )
    elif has_plinth and ph > 0:
        rec = plinth_recess
        verts, faces = [], []
        add_box(verts, faces, 0, rec, 0, width, d - rec, ph)
        mesh = create_box_from_verts(verts, faces)
        plinth = new_object(f"{name_prefix}_Plinth", mesh, collection, parent, m_plinth["name"])
        plinth.matrix_world = matrix
        apply_box_uvs(plinth, m_plinth["u"], m_plinth["v"], m_plinth["rot"])
        if gen_collisions:
            create_ubx_box_primitive(plinth, 1, 0, rec, 0, width, d - rec, ph, collection, matrix)

    num_cols = max(1, len(columns_data))
    w_inner = width - 2 * t
    w_bays = w_inner - (num_cols - 1) * t
    col_w = max(0.05, w_bays / num_cols)
    col_front_w = (width - gap * (num_cols + 1)) / num_cols
    usable_h = h - 2 * t

    verts, faces = [], []
    boxes_data = []

    def rec_box(x0, y0, z0, sx, sy, sz):
        add_box(verts, faces, x0, y0, z0, sx, sy, sz)
        boxes_data.append((x0, y0, z0, sx, sy, sz))

    rec_box(0, 0, ph, t, d, h)
    rec_box(width - t, 0, ph, t, d, h)
    rec_box(t, d - t, ph, width - 2 * t, t, h)
    rec_box(t, 0, ph, width - 2 * t, d - t, t)
    rec_box(t, 0, ph + h - t, width - 2 * t, d - t, t)

    for c in range(1, num_cols):
        div_x = t + c * col_w + (c - 1) * t
        rec_box(div_x, 0, ph + t, t, d - t, usable_h)

    for c_idx, col in enumerate(columns_data):
        col_x = t + c_idx * (col_w + t)
        col_facade_x = gap + c_idx * (col_front_w + gap)
        zones = col.zones
        num_zones = len(zones)
        if num_zones == 0:
            continue

        zone_heights = solve_element_heights(
            zones, h, min_val=0.08, label=f"{name_prefix} column {c_idx + 1}")
        alloc_accum_z = ph

        for z_idx, zone in enumerate(zones):
            zh = zone_heights[z_idx]
            zt = zone.zone_type
            z_bottom_alloc = alloc_accum_z
            z_top_alloc = z_bottom_alloc + zh

            facade_z_min = (ph + gap) if z_idx == 0 else (z_bottom_alloc + gap / 2.0)
            facade_z_max = (ph + h - gap) if z_idx == num_zones - 1 else (z_top_alloc - gap / 2.0)
            facade_h = max(0.02, facade_z_max - facade_z_min)
            facade_z_center = (facade_z_min + facade_z_max) / 2.0

            z_interior_min = (ph + t) if z_idx == 0 else (z_bottom_alloc + shelf_t / 2.0)
            z_interior_max = (ph + h - t) if z_idx == num_zones - 1 else (z_top_alloc - shelf_t / 2.0)
            interior_h = max(0.02, z_interior_max - z_interior_min)

            if z_idx < num_zones - 1:
                rec_box(col_x, 0, z_top_alloc - shelf_t / 2.0, col_w, d - t, shelf_t)

            if zt == 'DRAWER':
                dr_h = facade_h
                dr_z = facade_z_min

                dr_lift_rel = max(0.008, (z_interior_min + 0.010) - facade_z_min)
                dr_top_rel = max(0.012, facade_z_max - (z_interior_max - 0.020))
                box_total_h = max(t * 2, facade_h - dr_lift_rel - dr_top_rel)
                wall_h = box_total_h - t
                # Interior depth: from the front plane to the back panel (thickness t).
                box_depth = d - t - 0.01
                # Box x span: centred inside the column front. The front is an overlay
                # wider than the column bay between the walls/dividers (all thickness t),
                # so the box keeps off whichever side overhangs further - the same rule the
                # drawer bank of a regular section uses (drawer_box_inset).
                col_inset = drawer_box_inset(col_facade_x, col_front_w, col_x, col_x + col_w)
                col_inset = min(col_inset, max(0.0, (col_front_w - 2 * t) / 2.0))
                box_x0 = col_inset
                box_x1 = col_front_w - col_inset

                d_verts, d_faces = [], []
                add_drawer_boxes(d_verts, d_faces, col_front_w, dr_h, t, box_x0, box_x1,
                                 dr_lift_rel, wall_h, box_depth)

                drawer_world = matrix @ Matrix.Translation(Vector((col_facade_x, 0.0, dr_z)))
                drawer_obj = build_facade_object(
                    f"{name_prefix}_C{c_idx + 1}_Drawer_{z_idx + 1}",
                    create_box_from_verts(d_verts, d_faces), collection, parent, m_facade,
                    matrix_world=drawer_world,
                    use_bevel=use_bevel, bevel_w=bevel_w, bevel_segs=bevel_segs,
                    gen_collisions=gen_collisions, ubx=False)
                # Hollow set instead of the whole-mesh bound_box: items must fit inside.
                if gen_collisions:
                    add_drawer_colliders(
                        drawer_obj, col_front_w, dr_h, t,
                        drawer_collider_boxes(col_front_w, dr_h, t, box_x0, box_x1,
                                              dr_lift_rel, wall_h, box_depth),
                        collection, drawer_world)

                h_obj = create_handle(
                    f"{name_prefix}_C{c_idx + 1}_DrH_{z_idx + 1}",
                    length=handle_drawer["length"], overhang=handle_drawer["overhang"],
                    radius=handle_drawer["radius"], mount_len=handle_drawer["mount_len"],
                    vertical=False, mat_name=m_handle["name"], gen_coll=gen_collisions,
                    tile_u=m_handle["u"], tile_v=m_handle["v"], rot_uv=m_handle["rot"], collection=collection
                )
                h_obj.parent = drawer_obj
                h_obj.location = (col_front_w / 2, -t - handle_drawer["mount_len"] / 2, dr_h / 2)

            elif zt == 'DOOR':
                door_h = facade_h
                if zone.handle_len_mode == 'PERCENT':
                    calc_h_len = (door_h - 0.04) * (zone.handle_pct / 100.0)
                elif zone.handle_len_mode == 'EXPLICIT':
                    calc_h_len = zone.handle_custom_len
                else:
                    calc_h_len = handle_door["length"]

                max_safe_len = max(0.02, door_h - 0.03)
                eff_handle_len = min(calc_h_len, max_safe_len)

                def make_wardrobe_door(side, dw, offset_x, didx):
                    door_name = f"{name_prefix}_C{c_idx + 1}_Door_{z_idx + 1}_{didx}"
                    socket_name = f"SOCKET_{door_name}"
                    p_x = col_facade_x + offset_x if side == "L" else col_facade_x + offset_x + dw
                    hinge = create_hinge_empty(
                        socket_name, collection, parent,
                        matrix @ Matrix.Translation(Vector((p_x, -t, facade_z_center))))

                    dm = create_panel_mesh(door_name, dw, door_h, t,
                                           x_offset=dw / 2.0 if side == "L" else -dw / 2.0,
                                           y_offset=t / 2.0)
                    d_obj = build_facade_object(door_name, dm, collection, hinge, m_facade,
                                                use_bevel=use_bevel, bevel_w=bevel_w,
                                                bevel_segs=bevel_segs, gen_collisions=gen_collisions)

                    sm = handle_door["side_margin"]
                    hx = (dw - sm) if side == "L" else (-dw + sm)
                    is_h_vert = handle_door["vertical"]
                    total_bar_len = eff_handle_len + handle_door["overhang"] * 2
                    bar_half_z = (total_bar_len / 2.0) if is_h_vert else handle_door["radius"]

                    max_edge_dist = max(0.0, door_h - bar_half_z * 2)
                    edge_dist = min(max(0.0, zone.handle_z_offset), max_edge_dist)

                    if zone.handle_pos == 'TOP':
                        final_h_z = (door_h / 2.0) - bar_half_z - edge_dist
                    elif zone.handle_pos == 'BOTTOM':
                        final_h_z = (-door_h / 2.0) + bar_half_z + edge_dist
                    else:
                        shift = zone.handle_z_offset
                        final_h_z = max(-door_h / 2.0 + bar_half_z, min(door_h / 2.0 - bar_half_z, shift))

                    h_obj = create_handle(
                        f"{name_prefix}_C{c_idx + 1}_DH_{z_idx + 1}_{didx}",
                        length=eff_handle_len, overhang=handle_door["overhang"],
                        radius=handle_door["radius"], mount_len=handle_door["mount_len"],
                        vertical=is_h_vert, mat_name=m_handle["name"], gen_coll=gen_collisions,
                        tile_u=m_handle["u"], tile_v=m_handle["v"], rot_uv=m_handle["rot"], collection=collection
                    )
                    h_obj.parent = d_obj
                    h_obj.location = (hx, -handle_door["mount_len"] / 2, final_h_z)

                if zone.door_swing == 'PAIR':
                    dw = (col_front_w - gap) / 2.0
                    make_wardrobe_door("L", dw, 0.0, 1)
                    make_wardrobe_door("R", dw, dw + gap, 2)
                elif zone.door_swing == 'RIGHT':
                    make_wardrobe_door("R", col_front_w, 0.0, 1)
                else:
                    make_wardrobe_door("L", col_front_w, 0.0, 1)

            if zt in ('DOOR', 'OPEN'):
                if zone.interior_type == 'SHELVES':
                    if zone.shelf_mode == 'EVEN' and zone.shelves_count > 0:
                        step_z = interior_h / (zone.shelves_count + 1)
                        for s in range(zone.shelves_count):
                            sz = z_interior_min + step_z * (s + 1) - shelf_t / 2.0
                            rec_box(col_x, 0, sz, col_w, d - t, shelf_t)
                    elif zone.shelf_mode == 'CUSTOM' and len(zone.bays) > 1:
                        num_bays = len(zone.bays)
                        net_air = interior_h - (num_bays - 1) * shelf_t
                        bay_heights = solve_element_heights(
                            zone.bays, net_air, min_val=0.04,
                            label=f"{name_prefix} column {c_idx + 1} zone {z_idx + 1}")
                        accum_z = z_interior_min
                        for b_i in range(num_bays - 1):
                            accum_z += bay_heights[b_i]
                            rec_box(col_x, 0, accum_z, col_w, d - t, shelf_t)
                            accum_z += shelf_t

                elif zone.interior_type == 'ROD':
                    rod_z = z_interior_max - zone.rod_drop
                    r_mesh = create_clothes_rod_mesh(col_w, radius=0.0125)
                    rod = new_object(f"{name_prefix}_C{c_idx + 1}_Rod_{z_idx + 1}", r_mesh, collection, parent,
                                     m_handle["name"])
                    rod.matrix_world = matrix @ Matrix.Translation(Vector((col_x, (d - t) / 2, rod_z)))
                    add_and_apply_smooth(rod)
                    if gen_collisions:
                        create_ubx_from_bbox(rod, 1, collection)

            alloc_accum_z += zh

    mesh = create_box_from_verts(verts, faces)
    carcass = new_object(f"{name_prefix}_WardrobeCarcass", mesh, collection, parent, m_carcass["name"])
    carcass.matrix_world = matrix
    apply_box_uvs(carcass, m_carcass["u"], m_carcass["v"], m_carcass["rot"])
    if gen_collisions:
        for idx, bx in enumerate(boxes_data):
            create_ubx_box_primitive(carcass, idx + 1, *bx, collection, matrix)
    return


def build_corner_upper_section(
        name_prefix, width, corner_style, shelves, shelf_t,
        gap, handle_door, lower_depth, prev_d,
        prev_has_doors, next_d, next_has_doors, gen_collisions,
        use_bevel, bevel_w, bevel_segs, collection,
        parent, matrix, d, ph,
        t, h, m_carcass, m_facade,
        m_handle
):
    """Upper corner section: two walls, top plate, diagonal or two-door facade."""
    # Planar extents are adaptive (see AGENT_NOTES.md [NOTE_16550]):
    #   cw  = corrected wall-1 extent = props.depth (+ wall_t+gap upstream), so both
    #         rows turn on the same line
    #   the 45 deg / L cut joins the left upper neighbour's front plane (prev_d) to the
    #   right one's (next_d); cd still spans to the lower front line so the upper
    #   covers the lower L footprint.
    cw = width
    cd = lower_depth + t + gap
    x_front = lower_depth - next_d + t + gap
    y_front = lower_depth - prev_d
    y_back = cd - t * 2 - gap

    bm = bmesh.new()

    if corner_style == CORN_DIAGONAL:
        plate_poly = [
            (0.0, y_front),
            (x_front, -t - gap),
            (cw, -t - gap),
            (cw, cd - t - gap),
            (0.0, cd - t - gap)
        ]
    else:
        plate_poly = [
            (0.0, y_front),
            (x_front, y_front),
            (x_front, -t - gap),
            (cw, -t - gap),
            (cw, cd - t - gap),
            (0.0, cd - t - gap)
        ]

    add_extruded_polygon(bm, plate_poly, ph, t)
    add_extruded_polygon(bm, plate_poly, ph + h - t, t)

    wall_z = ph + t
    wall_h = h - 2 * t

    bw1_len = cw - t
    bmesh.ops.create_cube(
        bm, size=1.0,
        matrix=Matrix.Translation(Vector((bw1_len / 2, y_back + t / 2, wall_z + wall_h / 2)))
               @ Matrix.Scale(bw1_len, 4, Vector((1, 0, 0)))
               @ Matrix.Scale(t, 4, Vector((0, 1, 0)))
               @ Matrix.Scale(wall_h, 4, Vector((0, 0, 1)))
    )

    y_start_bw2 = -t - gap
    bw2_len = (y_back + t) - y_start_bw2
    bmesh.ops.create_cube(
        bm, size=1.0,
        matrix=Matrix.Translation(Vector((cw - t / 2, y_start_bw2 + bw2_len / 2, wall_z + wall_h / 2)))
               @ Matrix.Scale(t, 4, Vector((1, 0, 0)))
               @ Matrix.Scale(bw2_len, 4, Vector((0, 1, 0)))
               @ Matrix.Scale(wall_h, 4, Vector((0, 0, 1)))
    )

    sw1_len = y_back - y_front
    bmesh.ops.create_cube(
        bm, size=1.0,
        matrix=Matrix.Translation(Vector((t / 2, y_front + sw1_len / 2, wall_z + wall_h / 2)))
               @ Matrix.Scale(t, 4, Vector((1, 0, 0)))
               @ Matrix.Scale(sw1_len, 4, Vector((0, 1, 0)))
               @ Matrix.Scale(wall_h, 4, Vector((0, 0, 1)))
    )

    sw2_len = (cw - t) - x_front
    bmesh.ops.create_cube(
        bm, size=1.0,
        matrix=Matrix.Translation(Vector((x_front + sw2_len / 2, -t - gap + t / 2, wall_z + wall_h / 2)))
               @ Matrix.Scale(sw2_len, 4, Vector((1, 0, 0)))
               @ Matrix.Scale(t, 4, Vector((0, 1, 0)))
               @ Matrix.Scale(wall_h, 4, Vector((0, 0, 1)))
    )

    if corner_style == CORN_DOORS:
        post_x = x_front - t
        post_y = y_front - t
        bmesh.ops.create_cube(
            bm, size=1.0,
            matrix=Matrix.Translation(Vector((post_x + t / 2, post_y + t / 2, ph + h / 2)))
                   @ Matrix.Scale(t, 4, Vector((1, 0, 0)))
                   @ Matrix.Scale(t, 4, Vector((0, 1, 0)))
                   @ Matrix.Scale(h, 4, Vector((0, 0, 1)))
        )

    if corner_style == CORN_BLIND:
        bmesh.ops.create_cube(
            bm, size=1.0,
            matrix=Matrix.Translation(Vector((x_front / 2.0, y_front - t / 2, ph + h / 2.0)))
                   @ Matrix.Scale(x_front, 4, Vector((1, 0, 0)))
                   @ Matrix.Scale(t, 4, Vector((0, 1, 0)))
                   @ Matrix.Scale(h, 4, Vector((0, 0, 1)))
        )
        bmesh.ops.create_cube(
            bm, size=1.0,
            matrix=Matrix.Translation(Vector((x_front - t / 2.0, (-t - gap + y_front - t) / 2, ph + h / 2.0)))
                   @ Matrix.Scale(t, 4, Vector((1, 0, 0)))
                   @ Matrix.Scale(y_front - t - (-t - gap), 4, Vector((0, 1, 0)))
                   @ Matrix.Scale(h, 4, Vector((0, 0, 1)))
        )

    if corner_style != CORN_BLIND and shelves > 0 and wall_h > 0.15:
        c = 0.001
        s_setback = 0.020
        y_right_wall = -t - gap + t + c

        if corner_style == CORN_DIAGONAL:
            c1 = Vector((0.0, y_front))
            c2 = Vector((x_front, -t - gap))
            d_vec = c2 - c1
            d_len = d_vec.length
            u = d_vec / d_len
            n = Vector((-u.y, u.x))

            s_L = (t + c - s_setback * n.x) / u.x
            pt_L = c1 + s_L * u + s_setback * n

            s_R = (y_right_wall - c1.y - s_setback * n.y) / u.y
            pt_R = c1 + s_R * u + s_setback * n

            shelf_poly = [
                (pt_L.x, pt_L.y),
                (pt_R.x, pt_R.y),
                (cw - t - c, y_right_wall),
                (cw - t - c, y_back - c),
                (t + c, y_back - c)
            ]
        else:
            shelf_poly = [
                (t + c, y_front + s_setback),
                (x_front + s_setback, y_front + s_setback),
                (x_front + s_setback, y_right_wall),
                (cw - t - c, y_right_wall),
                (cw - t - c, y_back - c),
                (t + c, y_back - c)
            ]

        step = (wall_h - t) / (shelves + 1)
        for s in range(shelves):
            sz = wall_z + step * (s + 1)
            add_extruded_polygon(bm, shelf_poly, sz, shelf_t)

    mesh = bpy.data.meshes.new(f"{name_prefix}_CornerCabinet")
    bm.to_mesh(mesh)
    bm.free()
    carcass = new_object(f"{name_prefix}_CornerCabinet", mesh, collection, parent, m_carcass["name"])
    carcass.matrix_world = matrix
    apply_box_uvs(carcass, m_carcass["u"], m_carcass["v"], m_carcass["rot"])

    if gen_collisions:
        create_ubx_box_primitive(carcass, 1, 0, y_back, wall_z, bw1_len, t, wall_h, collection, matrix)
        create_ubx_box_primitive(carcass, 2, cw - t, y_start_bw2, wall_z, t, bw2_len, wall_h, collection,
                                 matrix)
        create_ubx_box_primitive(carcass, 3, 0, y_front, wall_z, t, sw1_len, wall_h, collection, matrix)
        create_ubx_box_primitive(carcass, 4, x_front, -t - gap, wall_z, sw2_len, t, wall_h, collection, matrix)

    door_h = h - gap * 2
    door_z = ph + gap + door_h / 2

    bar_half = handle_door["length"] / 2 + handle_door["overhang"]
    base_corner_hz = -door_h / 2 + handle_door["bottom_margin"] + bar_half
    corner_hz = base_corner_hz + handle_door["z_offset"]
    corner_hz = max(-door_h / 2 + bar_half, min(door_h / 2 - bar_half, corner_hz))

    if corner_style == CORN_DIAGONAL:
        p1 = Vector((0.0, y_front, door_z))
        p2 = Vector((x_front, -t - gap, door_z))
        diag_vec = p2 - p1
        total_len = diag_vec.length
        angle = atan2(diag_vec.y, diag_vec.x)
        u_dir = diag_vec.normalized()
        n_in = Vector((-u_dir.y, u_dir.x))

        needs_inset_start = (prev_d >= d - 0.005) and prev_has_doors
        needs_inset_end = (next_d >= d - 0.005) and next_has_doors

        inset_start = (t * 0.42 + gap * 1.5) if needs_inset_start else gap
        inset_end = (t * 0.42 + gap * 1.5) if needs_inset_end else gap

        diag_w = max(0.05, total_len - inset_start - inset_end)

        p_base = p1 + u_dir * inset_start
        p_hinge_outer = Vector((p_base.x - n_in.x * t, p_base.y - n_in.y * t, door_z))

        door_name = f"{name_prefix}_DiagDoor"
        socket_name = f"SOCKET_{door_name}_01"
        if socket_name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[socket_name], do_unlink=True)
        hinge = create_hinge_empty(
            socket_name, collection, parent,
            matrix @ Matrix.Translation(p_hinge_outer) @ Matrix.Rotation(angle, 4, 'Z'),
            display_type='SPHERE')

        d_mesh = create_panel_mesh(door_name, diag_w, door_h, t,
                                   x_offset=diag_w / 2.0, y_offset=t / 2.0)
        door = build_facade_object(door_name, d_mesh, collection, hinge, m_facade,
                                   use_bevel=use_bevel, bevel_w=bevel_w, bevel_segs=bevel_segs,
                                   gen_collisions=gen_collisions)

        handle = create_handle(
            f"{name_prefix}_DiagHandle",
            length=handle_door["length"], overhang=handle_door["overhang"],
            radius=handle_door["radius"], mount_len=handle_door["mount_len"],
            vertical=handle_door["vertical"], mat_name=m_handle["name"],
            gen_coll=gen_collisions, tile_u=m_handle["u"], tile_v=m_handle["v"],
            rot_uv=m_handle["rot"], collection=collection
        )
        handle.parent = door
        sm = handle_door["side_margin"]
        handle.location = (diag_w - sm, -handle_door["mount_len"] / 2, corner_hz)

    elif corner_style == CORN_DOORS:
        dw1 = x_front - t - gap * 2
        hinge1_pos = Vector((gap, y_front - t, door_z))

        door1_name = f"{name_prefix}_DoorL_01"
        socket1_name = f"SOCKET_{door1_name}_01"
        hinge1 = create_hinge_empty(socket1_name, collection, parent,
                                    matrix @ Matrix.Translation(hinge1_pos))

        d1_mesh = create_panel_mesh(door1_name, dw1, door_h, t,
                                    x_offset=dw1 / 2.0, y_offset=t / 2.0)
        d1 = build_facade_object(door1_name, d1_mesh, collection, hinge1, m_facade,
                                 use_bevel=use_bevel, bevel_w=bevel_w, bevel_segs=bevel_segs,
                                 gen_collisions=gen_collisions)

        h1 = create_handle(
            f"{name_prefix}_HandleL_01", length=handle_door["length"], overhang=handle_door["overhang"],
            radius=handle_door["radius"], mount_len=handle_door["mount_len"], vertical=handle_door["vertical"],
            mat_name=m_handle["name"], gen_coll=gen_collisions, tile_u=m_handle["u"], tile_v=m_handle["v"],
            rot_uv=m_handle["rot"], collection=collection
        )
        h1.parent = d1
        sm = handle_door["side_margin"]
        h1.location = (dw1 - sm, -handle_door["mount_len"] / 2, corner_hz)

        dw2 = (y_front - (-t - gap)) - t - gap * 2
        hinge2_pos = Vector((x_front - t, -t - gap + gap, door_z))

        door2_name = f"{name_prefix}_DoorL_02"
        socket2_name = f"SOCKET_{door2_name}_01"
        hinge2 = create_hinge_empty(
            socket2_name, collection, parent,
            matrix @ Matrix.Translation(hinge2_pos) @ Matrix.Rotation(radians(90), 4, 'Z'))

        # Door 2 is mirrored relative to door 1: y_offset=-t/2 runs the panel from y=-t to y=0,
        # so its visible face is local y=0 = max_y, not min_y. The +90 deg hinge turns that face
        # onto the second wall, and the handle confirms the side (positive mount_len/2 plus a
        # 180 deg rotation, unique in this file). Marking it as a regular 'front' facade bevels
        # the inner side of the door instead of the front.
        d2_mesh = create_panel_mesh(door2_name, dw2, door_h, t,
                                    x_offset=dw2 / 2.0, y_offset=-t / 2.0)
        d2 = build_facade_object(door2_name, d2_mesh, collection, hinge2, m_facade, face="back",
                                 use_bevel=use_bevel, bevel_w=bevel_w, bevel_segs=bevel_segs,
                                 gen_collisions=gen_collisions)

        h2 = create_handle(
            f"{name_prefix}_HandleL_02", length=handle_door["length"], overhang=handle_door["overhang"],
            radius=handle_door["radius"], mount_len=handle_door["mount_len"], vertical=handle_door["vertical"],
            mat_name=m_handle["name"], gen_coll=gen_collisions, tile_u=m_handle["u"], tile_v=m_handle["v"],
            rot_uv=m_handle["rot"], collection=collection
        )
        h2.parent = d2
        h2.rotation_euler = (0, 0, radians(180))
        h2.location = (dw2 - sm, handle_door["mount_len"] / 2, corner_hz)

    return


def build_plinth(
        name_prefix, width, wall_t, plinth_recess,
        gap, is_island, has_plinth, is_first_sec,
        is_last_sec, gen_collisions, collection, parent,
        matrix, is_corner_sec, ph, m_plinth,
        d
):
    """Plinth (toe kick) under a regular section, with corner and run-end recessing."""
    if has_plinth and ph > 0:
        recess = plinth_recess
        verts, faces = [], []
        pfix = recess + wall_t

        if is_corner_sec:  # работает
            plinth_w = width - (wall_t + gap) + recess
            y_start = recess - pfix - gap
            y_depth = d - recess + pfix + gap
            px_start = 0.0
        elif is_island:
            # 4-сторонний теневой цоколь для островных секций
            px_start = recess if is_first_sec else 0.0
            side_sub = (recess if is_first_sec else 0.0) + (recess if is_last_sec else 0.0)
            plinth_w = max(0.02, width - side_sub)
            y_start = recess
            y_depth = max(0.02, d - 2 * recess) + wall_t + gap * 2
        else:
            plinth_w = width
            pfix = 0.0
            y_start = recess - pfix
            # The rear edge lands on the carcass rear plane (d) - the plane the back panel
            # closes, or the one the side walls reach when the panel is switched off - so
            # the plinth never sticks out behind the body and never leaves a ledge at the
            # wall. Its ends are the section's own edges, which are the side walls' outer
            # planes, so the band reads as one piece with the carcass.
            y_depth = d - y_start
            px_start = 0.0

        add_box(verts, faces, px_start, y_start, 0, plinth_w, y_depth, ph)
        mesh = create_box_from_verts(verts, faces)
        plinth = new_object(f"{name_prefix}_Plinth", mesh, collection, parent, m_plinth["name"])
        plinth.matrix_world = matrix
        apply_box_uvs(plinth, m_plinth["u"], m_plinth["v"], m_plinth["rot"])

        if gen_collisions:
            create_ubx_box_primitive(plinth, 1, px_start, y_start, 0, plinth_w, y_depth, ph, collection, matrix)


def build_legs(
        name_prefix, width, d, leg_h,
        gen_collisions, collection, parent, matrix, m_plinth
):
    """Four legs under a section body, replacing the plinth (bedside dresser style).

    The body above sits at z=leg_h exactly as it sits on a plinth, so the caller only
    swaps this in for build_plinth; every z computation above the body is untouched.
    Legs use the plinth material slot - for legged furniture they are the visible base.
    """
    inset = 0.05
    leg_s = 0.05
    xs = (inset, width - inset - leg_s)
    ys = (inset, d - inset - leg_s)
    idx = 0
    for lx in xs:
        for ly in ys:
            idx += 1
            verts, faces = [], []
            add_box(verts, faces, lx, ly, 0.0, leg_s, leg_s, leg_h)
            mesh = create_box_from_verts(verts, faces)
            leg = new_object(f"{name_prefix}_Leg_{idx:02d}", mesh, collection, parent, m_plinth["name"])
            leg.matrix_world = matrix
            apply_box_uvs(leg, m_plinth["u"], m_plinth["v"], m_plinth["rot"])
            if gen_collisions:
                create_ubx_box_primitive(leg, 1, lx, ly, 0.0, leg_s, leg_s, leg_h, collection, matrix)


def build_carcass(
        name_prefix, width, sec_type, shelves,
        has_mid_div, shelf_t, gap, is_island,
        is_upper, has_bottom, has_top, has_back_panel, shelf_rows,
        tier_dividers, gen_collisions, use_bevel, bevel_w,
        bevel_segs, collection, parent, matrix,
        use_drawers, is_corner_sec, ph, t,
        h, m_facade, d, lower_h,
        m_carcass,
        has_side_walls=True, shelf_span_l=0.0, shelf_span_r=0.0
):
    """Carcass of a regular section: sides, bottom, top, dividers, shelves, appliance tiers.

    has_side_walls=False and the two shelf spans are the built-in carcass of an appliance
    section that shares its neighbours' walls instead of owning its own.
    """
    verts, faces = [], []
    boxes_data = []

    def record_box(x0, y0, z0, sx, sy, sz):
        add_box(verts, faces, x0, y0, z0, sx, sy, sz)
        boxes_data.append((x0, y0, z0, sx, sy, sz))

    # Carcass Frame
    if is_island:
        # Island mode: Separate decorative facade panel facing backwards
        back_verts, back_faces = [], []
        add_box(back_verts, back_faces, 0, d - t, ph, width, t, h)
        # The visible side of an island back panel faces +Y (rear countertop overhang).
        # ubx=False: this panel keeps its exact-size collider instead of a bound_box one.
        back_panel = build_facade_object(
            f"{name_prefix}_IslandBack", create_box_from_verts(back_verts, back_faces),
            collection, parent, m_facade, matrix_world=matrix, face="back",
            use_bevel=use_bevel, bevel_w=bevel_w, bevel_segs=bevel_segs,
            gen_collisions=gen_collisions, ubx=False)
        if gen_collisions:
            create_ubx_box_primitive(back_panel, 1, 0, d - t, ph, width, t, h, collection, matrix)
    else:
        # Off for open-niche furniture (TV console): the niche stays open at the back,
        # so equipment depth and cables are not blocked by a panel nobody sees.
        if has_back_panel:
            record_box(0, d - t, ph, width, t, h)

    y_front = -gap if is_corner_sec else 0.0
    # Rear plane the plates stop at. A back panel closes the run itself, so the plates butt
    # against its front face at d - t. With the panel switched off (open-niche furniture)
    # nothing closes the run any more, so the side walls carry the full depth instead: they
    # reach the wall line and butt into the countertop above, rather than leaving a
    # panel-thick ledge under its back edge.
    y_rear = d if (not has_back_panel and not is_island) else (d - t)
    y_depth_adj = y_rear - y_front

    # A built-in shares the walls of its neighbours: both side plates are simply not
    # built, and then the horizontal plates run the full width instead of stopping
    # short at t (there is no wall left for them to land on).
    if has_side_walls:
        record_box(0, y_front, ph, t, y_depth_adj, h)
        record_box(width - t, y_front, ph, t, y_depth_adj, h)
    frame_x = t if has_side_walls else 0.0
    frame_w = (width - 2 * t) if has_side_walls else width

    if (sec_type != SEC_APPLIANCE) or has_bottom:
        record_box(frame_x, y_front, ph, frame_w, y_depth_adj, t)

    # Top plates / Stretchers
    if sec_type == SEC_SINK:
        # American/Modern Sink stretcher ribs (front and back bars)
        stretcher_w = 0.070
        record_box(frame_x, 0, ph + h - t, frame_w, stretcher_w, t)
        # The rear bar stops at the same rear plane as the side walls, so a run without a
        # back panel carries the rib to the wall line instead of leaving a panel-thick ledge.
        record_box(frame_x, y_rear - stretcher_w, ph + h - t, frame_w, stretcher_w, t)
    elif (sec_type != SEC_APPLIANCE) or has_top:
        if is_upper:
            record_box(frame_x, 0, ph + h - t, frame_w, d - t, t)
        elif is_corner_sec:
            # Накладная стенка по внешнему контуру от ph до h без пересечения боковин
            record_box(0, -t - gap, ph, width, t, h)
        else:
            record_box(frame_x, 0, ph + h - t, frame_w, t * 2, t)

    if use_drawers and lower_h > t:
        div_z = ph + lower_h
        record_box(t, 0, div_z - t, width - 2 * t, d - t, t)

    if sec_type == SEC_NORMAL and has_mid_div and lower_h > 0.05:
        record_box(width / 2 - t / 2, 0, ph + t, t, d - t, lower_h - 2 * t)

    if sec_type == SEC_NORMAL and shelves > 0 and lower_h > 0.1:
        usable = lower_h - 2 * t
        step = usable / (shelves + 1)
        for s in range(shelves):
            z = ph + t + step * (s + 1) - shelf_t / 2
            if z + shelf_t < ph + lower_h - t:
                record_box(t, 0, z, width - 2 * t, d - t, shelf_t)

    # Appliance / Open Rack Shelves & Vertical Tier Dividers
    if sec_type == SEC_APPLIANCE and (shelf_rows > 0 or any(div > 0 for div in tier_dividers)):
        z_start = (ph + t) if has_bottom else ph
        z_end = (ph + h - t) if has_top else (ph + h)
        total_interior_h = max(0.01, z_end - z_start)
        num_tiers = shelf_rows + 1
        net_tier_h = total_interior_h - (shelf_rows * shelf_t)

        if net_tier_h > 0.02:
            tier_h = net_tier_h / num_tiers

            # Horizontal shelves. "Shelves to walls" lets the board run past the
            # section's own edges up to the inner face of the nearest side wall on each
            # side; a side with no wall in reach (row end, corner) keeps the default
            # inset, so nothing sticks out of the furniture.
            sh_x0 = -shelf_span_l if shelf_span_l > 0.0 else t
            sh_x1 = (width + shelf_span_r) if shelf_span_r > 0.0 else (width - t)
            for s in range(shelf_rows):
                sz = z_start + (s + 1) * tier_h + s * shelf_t
                record_box(sh_x0, 0, sz, sh_x1 - sh_x0, d - t, shelf_t)

            # Vertical dividers per tier (Tier 1 is Top)
            inner_w = width - 2 * t
            for k in range(num_tiers):
                num_divs = tier_dividers[k] if k < len(tier_dividers) else 0
                if num_divs > 0:
                    tier_z_bot = z_start + (num_tiers - 1 - k) * (tier_h + shelf_t)
                    div_space_w = inner_w - (num_divs * t)
                    if div_space_w > 0.02:
                        bay_w = div_space_w / (num_divs + 1)
                        for d_i in range(num_divs):
                            dx = t + (d_i + 1) * bay_w + d_i * t
                            record_box(dx, 0, tier_z_bot, t, d - t, tier_h)

    mesh = create_box_from_verts(verts, faces)
    carcass = new_object(f"{name_prefix}_Carcass", mesh, collection, parent, m_carcass["name"])
    carcass.matrix_world = matrix
    apply_box_uvs(carcass, m_carcass["u"], m_carcass["v"], m_carcass["rot"])

    if gen_collisions:
        for idx, bx in enumerate(boxes_data):
            create_ubx_box_primitive(carcass, idx + 1, *bx, collection, matrix)


def build_section_facades(
        name_prefix, width, sec_type, doors,
        drawer_count, drawer_zone_h, gap,
        handle_door, handle_drawer, is_upper, gen_collisions,
        use_bevel, bevel_w, bevel_segs, collection,
        parent, matrix, use_drawers, lower_h,
        t, ph, m_facade, d,
        m_handle
):
    """Doors and drawer fronts of a regular section, with their handles."""
    if sec_type != SEC_APPLIANCE and doors > 0 and lower_h > 0.1:
        door_h = lower_h - gap * 2
        door_z = ph + gap + door_h / 2
        bar_half = handle_door["length"] / 2 + handle_door["overhang"]
        base_hz = (-door_h / 2 + handle_door["bottom_margin"] + bar_half) if is_upper else (
                door_h / 2 - handle_door["top_margin"] - bar_half)
        hz = max(-door_h / 2 + bar_half, min(door_h / 2 - bar_half, base_hz + handle_door["z_offset"]))

        def make_door(side, dw, idx):
            door_name = f"{name_prefix}_Door{side}_{idx:02d}"
            socket_name = f"SOCKET_{door_name}_01"
            pivot_x = 0.0 if side == "L" else width
            hinge = create_hinge_empty(socket_name, collection, parent,
                                       matrix @ Matrix.Translation(Vector((pivot_x, -t, door_z))))

            shift = dw / 2 + gap
            dm = create_panel_mesh(door_name, dw, door_h, t,
                                   x_offset=shift if side == "L" else -shift, y_offset=t / 2)
            door = build_facade_object(door_name, dm, collection, hinge, m_facade,
                                       use_bevel=use_bevel, bevel_w=bevel_w, bevel_segs=bevel_segs,
                                       gen_collisions=gen_collisions)

            handle = create_handle(
                f"{name_prefix}_Handle{side}_{idx:02d}",
                length=handle_door["length"], overhang=handle_door["overhang"],
                radius=handle_door["radius"], mount_len=handle_door["mount_len"],
                vertical=handle_door["vertical"], mat_name=m_handle["name"],
                gen_coll=gen_collisions, tile_u=m_handle["u"], tile_v=m_handle["v"], rot_uv=m_handle["rot"],
                collection=collection
            )
            handle.parent = door
            sm = handle_door["side_margin"]
            hx = (dw - sm) if side == "L" else (-dw + sm)
            handle.location = (hx, -handle_door["mount_len"] / 2, hz)

        if doors == 1:
            make_door("L", width - gap * 2, 1)
        else:
            dw = (width - gap * 3) / 2
            make_door("L", dw, 1)
            make_door("R", dw, 2)

    # Standard Drawers
    if use_drawers and drawer_zone_h > 0.05:
        drawer_h = drawer_zone_h - gap * 2
        drawer_z = ph + lower_h + gap
        front_w = (width - gap * (drawer_count + 1)) / drawer_count

        dr_lift = 0.012
        dr_top_margin = 0.035
        box_total_h = max(t * 2, drawer_h - dr_lift - dr_top_margin)
        wall_h = box_total_h - t
        # Interior depth: front plane to the back panel (thickness t).
        box_depth = d - t - 0.01
        # Box x span: centred inside every front of the bank. The facade bays (gap-based)
        # and the carcass interior (wall-thickness-based) are different partitions, and an
        # end front overhangs the carcass wall, so that overhang has to be kept off both
        # sides. One inset for the whole bank - every box of a bank is then the same box,
        # which is also what lets the bake dedup them into one mesh.
        box_inset = max(drawer_box_inset(gap + di * (front_w + gap), front_w, t, width - t)
                        for di in range(drawer_count))
        # A front narrower than two walls plus the inset cannot hold a centred box; keep
        # the symmetry and let the inset shrink instead of growing the box past the front.
        box_inset = min(box_inset, max(0.0, (front_w - 2 * t) / 2.0))
        box_x0 = box_inset
        box_x1 = front_w - box_inset

        for di in range(drawer_count):
            front_x = gap + di * (front_w + gap)
            verts, faces = [], []
            add_drawer_boxes(verts, faces, front_w, drawer_h, t, box_x0, box_x1,
                             dr_lift, wall_h, box_depth)

            drawer_world = matrix @ Matrix.Translation(Vector((front_x, 0.0, drawer_z)))
            drawer = build_facade_object(
                f"{name_prefix}_Drawer_{di + 1:02d}", create_box_from_verts(verts, faces),
                collection, parent, m_facade,
                matrix_world=drawer_world,
                use_bevel=use_bevel, bevel_w=bevel_w, bevel_segs=bevel_segs,
                gen_collisions=gen_collisions, ubx=False)
            # Hollow set instead of the whole-mesh bound_box: items must fit inside.
            if gen_collisions:
                add_drawer_colliders(
                    drawer, front_w, drawer_h, t,
                    drawer_collider_boxes(front_w, drawer_h, t, box_x0, box_x1,
                                          dr_lift, wall_h, box_depth),
                    collection, drawer_world)

            handle = create_handle(
                f"{name_prefix}_DrawerHandle_{di + 1:02d}",
                length=handle_drawer["length"], overhang=handle_drawer["overhang"],
                radius=handle_drawer["radius"], mount_len=handle_drawer["mount_len"],
                vertical=False, mat_name=m_handle["name"], gen_coll=gen_collisions,
                tile_u=m_handle["u"], tile_v=m_handle["v"], rot_uv=m_handle["rot"], collection=collection
            )
            handle.parent = drawer
            handle.location = (front_w / 2, -t - handle_drawer["mount_len"] / 2, drawer_h / 2)


# Sink presentation: the bowl is its own part, so it takes the chrome material instead of
# the countertop's, and its outer perimeter drops 1 cm so the sink shows a real wall
# thickness inside the cutout rather than an open edge. See AGENT_NOTES.md [NOTE_16575].
SINK_MATERIAL_NAME = "MI_MetalChrome_01"
SINK_RIM_EXTRUDE = 0.01


def build_sink_bowl(
        name_prefix, hx0, hy0, hw, hd, z_top, depth,
        margin_f, margin_b, margin_l, margin_r,
        collection, parent, matrix, mat, bevels=None, drain=None
):
    """Sink bowl object: the 5x5 rim + 3x3 recess primitive dropped into the cutout.

    Built in the countertop's own frame, so the footprint (hx0, hy0, hw, hd) is the
    cutout rect and z_top is the countertop's top face. The bowl uses the sink material
    (not the countertop's) and its outer perimeter is extruded 1 cm down. `bevels` is a
    dict with the three per-group widths (floor / vert / top) plus the shared `segments`
    and `miter`; the bevel is applied before the UVs so the new bevel faces are projected
    too. `drain` carries the 2-step stamp parameters (see primitives.stamp_sink_drain) and
    the drain bevel widths/segments. No collider: a bbox over an open bowl would fill the
    cavity, and the export-side collision for a sink is a separate decision.
    See AGENT_NOTES.md [NOTE_16560], [NOTE_16565], [NOTE_16575], [NOTE_16580].
    """
    z_bot = z_top - depth
    mesh = create_sink_bowl_mesh(hx0, hy0, hw, hd, z_top, z_bot,
                                 margin_f, margin_b, margin_l, margin_r,
                                 rim_extrude=SINK_RIM_EXTRUDE)
    bowl = new_object(f"{name_prefix}_SinkBowl", mesh, collection, parent, SINK_MATERIAL_NAME)
    bowl.matrix_world = matrix
    drain_groups = None
    drain_widths = None
    drain_segments = 2
    drain_floor = None
    if drain and drain.get("on"):
        # The two steps descend below the bowl floor; clamp their sum so the stamp can
        # never punch through the bottom of the recess.
        d1, d2 = drain["d1"], drain["d2"]
        budget = depth * 0.8
        if d1 + d2 > budget:
            scale = budget / (d1 + d2)
            d1, d2 = d1 * scale, d2 * scale
        stamp = stamp_sink_drain(
            bowl, hx0, hy0, hw, hd, z_bot,
            margin_f, margin_b, margin_l, margin_r,
            radius_b=drain["dia1"] / 2.0, radius_c=drain["dia2"] / 2.0,
            depth_1=d1, depth_2=d2)
        if stamp:
            drain_groups, drain_floor = stamp
        drain_widths = {"drain_top": drain["bevel_top"],
                        "drain_mid": drain["bevel_mid"],
                        "drain_low": drain["bevel_low"]}
        drain_segments = drain["segments"]
    if bevels:
        groups = classify_sink_bowl_edges(mesh, hx0, hy0, hw, hd, z_top, z_bot,
                                          margin_f, margin_b, margin_l, margin_r)
        apply_sink_bowl_bevel(bowl, groups,
                              widths={"floor": bevels["floor_w"],
                                      "vert": bevels["vert_w"],
                                      "top": bevels["top_w"]},
                              segments=bevels["segments"], miter=bevels["miter"],
                              drain_groups=drain_groups, drain_widths=drain_widths,
                              drain_segments=drain_segments)
    if drain and drain.get("strainer_on") and drain_floor is not None:
        # Sizing comes straight from the UI's Drain Diameter 2: the radius is 1 mm inside
        # the step-2 floor so the disc drops into the second step. radius_c is that same
        # diameter already clamped to the floor, so an over-large setting still fits.
        strainer_radius = min(drain["dia2"] / 2.0,
                              drain_floor["radius_c"]) - SINK_STRAINER_CLEARANCE
        if strainer_radius > 0.002:
            # The strainer is merged INTO the bowl: one object, one material, and the
            # export bake sees the sink as a single part. It is built in the bowl's local
            # frame, so its matrix is the local offset itself. Merged before the UVs so
            # the disc's faces are projected with the bowl.
            smesh, smatrix = build_sink_strainer_mesh(
                bowl, drain_floor["cx"], drain_floor["cy"], drain_floor["z_floor"],
                radius=strainer_radius,
                thickness=drain["strainer_thickness"],
                gap=drain["strainer_gap"])
            merge_mesh_into_object(bowl, smesh, smatrix)
            bpy.data.meshes.remove(smesh)
    apply_box_uvs(bowl, mat["u"], mat["v"], mat["rot"])
    return bowl


def build_countertop(
        name_prefix, width, wall_t, sec_type,
        next_is_corner, prev_is_corner, gap, counter_thickness,
        over_front, over_back, over_left, over_right,
        is_island, sink_cutout, sink_w, sink_d,
        sink_margin_f, sink_margin_b, sink_margin_l, sink_margin_r,
        sink_recess_depth, sink_recess_margin_f, sink_recess_margin_b,
        sink_recess_margin_l, sink_recess_margin_r,
        is_first_sec, is_last_sec, gen_collisions, use_bevel,
        bevel_w, bevel_segs, collection, parent,
        matrix, ph, h, d,
        m_counter, sink_bevels=None, sink_drain=None
):
    """Countertop slab for a section, mitred at corner joints, with the sink cutout. Returns the slab box so the upstand can sit on it."""
    corner_inset = max(0.0, over_front - wall_t - gap)

    if prev_is_corner:
        ct_x = corner_inset
        ct_w = width - corner_inset + over_right - (corner_inset if next_is_corner else 0.0)
    else:
        ct_x = -over_left
        ct_w = width + over_left + over_right - (corner_inset if next_is_corner else 0.0)

    ct_y = -over_front
    eff_over_back = over_back if is_island else 0.0
    ct_d = d + over_front + eff_over_back
    ct_z = ph + h

    # Для самого угла: добираем нахлест влево к предыдущей секции
    # (справа width уже увеличен на старте функции, поэтому правый край остается на зеленой линии)
    if sec_type == SEC_CORNER:
        ct_x -= corner_inset
        ct_w += corner_inset

    ct_top_z = ct_z + counter_thickness
    back_edge_y = (ct_y + ct_d) if is_island else None
    left_edge_x = ct_x if is_first_sec else None
    right_edge_x = (ct_x + ct_w) if is_last_sec else None

    if sink_cutout and sec_type == SEC_SINK:
        hx0, hy0, hw, hd = solve_sink_cutout(
            ct_x, ct_y, ct_w, ct_d, ct_x, ct_w,
            sink_w, sink_d, sink_margin_f, sink_margin_b, sink_margin_l, sink_margin_r)

        mesh = create_countertop_with_sink_cutout(ct_x, ct_y, ct_z, ct_w, ct_d, counter_thickness, hx0, hy0, hw, hd)
        if use_bevel:
            mark_mesh_countertop_bevel_weights(
                mesh, front_y=ct_y, top_z=ct_top_z,
                back_y=back_edge_y, left_x=left_edge_x, right_x=right_edge_x
            )
        ct = new_object(f"{name_prefix}_Countertop", mesh, collection, parent, m_counter["name"])
        ct.matrix_world = matrix
        if use_bevel:
            apply_bevel_to_object(ct, bevel_w, bevel_segs)
        apply_box_uvs(ct, m_counter["u"], m_counter["v"], m_counter["rot"])

        if gen_collisions:
            create_ubx_box_primitive(ct, 1, ct_x, ct_y, ct_z, ct_w, hy0 - ct_y, counter_thickness, collection, matrix)
            create_ubx_box_primitive(ct, 2, ct_x, hy0 + hd, ct_z, ct_w, (ct_y + ct_d) - (hy0 + hd), counter_thickness,
                                     collection, matrix)
            create_ubx_box_primitive(ct, 3, ct_x, hy0, ct_z, hx0 - ct_x, hd, counter_thickness, collection, matrix)
            create_ubx_box_primitive(ct, 4, hx0 + hw, hy0, ct_z, (ct_x + ct_w) - (hx0 + hw), hd, counter_thickness,
                                     collection, matrix)

        build_sink_bowl(
            name_prefix=name_prefix, hx0=hx0, hy0=hy0, hw=hw, hd=hd, z_top=ct_top_z,
            depth=sink_recess_depth,
            margin_f=sink_recess_margin_f, margin_b=sink_recess_margin_b,
            margin_l=sink_recess_margin_l, margin_r=sink_recess_margin_r,
            collection=collection, parent=parent, matrix=matrix, mat=m_counter,
            bevels=sink_bevels, drain=sink_drain)
    else:
        verts, faces = [], []
        if sec_type == SEC_CORNER and use_bevel:
            # See AGENT_NOTES.md [NOTE_16551]. The quad chamfer replaces the bmesh
            # vertex bevel that triangulated into a fan.
            add_chamfered_corner_box(verts, faces, ct_x, ct_y, ct_z, ct_w, ct_d, counter_thickness, bevel_w)
        else:
            add_box(verts, faces, ct_x, ct_y, ct_z, ct_w, ct_d, counter_thickness)
        mesh = create_box_from_verts(verts, faces)

        # FIX: Corner butt-joint edge must not have a bevel
        if use_bevel:
            if sec_type == SEC_CORNER:
                # Keep filter: corner section receives no edge bevels
                front_edges = []
                for e in mesh.edges:
                    v1 = mesh.vertices[e.vertices[0]].co
                    v2 = mesh.vertices[e.vertices[1]].co
                    is_front = (abs(v1.y - ct_y) < 1e-4 and abs(v2.y - ct_y) < 1e-4)
                    is_top = (abs(v1.z - ct_top_z) < 1e-4 and abs(v2.z - ct_top_z) < 1e-4)
                    is_not_joint = max(v1.x, v2.x) < (ct_x + ct_w - 0.05)
                    if is_front and is_top and is_not_joint:
                        front_edges.append(e.index)
                apply_edge_bevel_weights(mesh, front_edges, 1.0)
            else:
                mark_mesh_countertop_bevel_weights(
                    mesh, front_y=ct_y, top_z=ct_top_z,
                    back_y=back_edge_y, left_x=left_edge_x, right_x=right_edge_x
                )

        ct = new_object(f"{name_prefix}_Countertop", mesh, collection, parent, m_counter["name"])
        ct.matrix_world = matrix
        if use_bevel:
            apply_bevel_to_object(ct, bevel_w, bevel_segs)
        apply_box_uvs(ct, m_counter["u"], m_counter["v"], m_counter["rot"])
        if gen_collisions:
            create_ubx_box_primitive(ct, 1, ct_x, ct_y, ct_z, ct_w, ct_d, counter_thickness, collection, matrix)
    return ct_x, ct_y, ct_w, ct_d, ct_z


def build_upstand(
        name_prefix, sec_type, counter_thickness, has_upstand,
        upstand_h, upstand_t, is_island, gen_collisions,
        use_bevel, bevel_w, bevel_segs, collection,
        parent, matrix, d, m_counter,
        ct_x, ct_y, ct_w, ct_z
):
    """Upstand (backsplash) strip behind the countertop of a non-island section."""
    # See AGENT_NOTES.md [NOTE_16547]
    if has_upstand and (not is_island):
        up_z = ct_z + counter_thickness
        u_verts, u_faces = [], []
        u_boxes_data = []

        # 1. Задний бортик вдоль первой стены (по оси X)
        up_x = ct_x
        up_w = ct_w
        up_y = d - upstand_t
        add_box(u_verts, u_faces, up_x, up_y, up_z, up_w, upstand_t, upstand_h)
        u_boxes_data.append((up_x, up_y, up_z, up_w, upstand_t, upstand_h))

        # 2. Второй бортик для угла вдоль ВТОРОЙ стены (по правому ребру X = ct_x + ct_w)
        if sec_type == SEC_CORNER:
            side_up_x = ct_x + ct_w - upstand_t
            side_up_w = upstand_t
            side_up_y = ct_y
            side_up_d = (d - upstand_t) - ct_y
            if side_up_d > 0.01:
                add_box(u_verts, u_faces, side_up_x, side_up_y, up_z, side_up_w, side_up_d, upstand_h)
                u_boxes_data.append((side_up_x, side_up_y, up_z, side_up_w, side_up_d, upstand_h))

        u_mesh = create_box_from_verts(u_verts, u_faces)
        if use_bevel:
            # Снимаем фаску с внутренних лицевых кромок обоих бортиков
            target_edges = []
            top_z = up_z + upstand_h
            side_x_match = ct_x + ct_w - upstand_t
            for e in u_mesh.edges:
                v1 = u_mesh.vertices[e.vertices[0]].co
                v2 = u_mesh.vertices[e.vertices[1]].co
                is_top = (abs(v1.z - top_z) < 1e-4 and abs(v2.z - top_z) < 1e-4)
                if not is_top:
                    continue
                is_back_front = (abs(v1.y - up_y) < 1e-4 and abs(v2.y - up_y) < 1e-4)
                is_side_front = (sec_type == SEC_CORNER and abs(v1.x - side_x_match) < 1e-4 and abs(
                    v2.x - side_x_match) < 1e-4)
                if is_back_front or is_side_front:
                    target_edges.append(e.index)
            apply_edge_bevel_weights(u_mesh, target_edges, 1.0)

        upstand_obj = new_object(f"{name_prefix}_Upstand", u_mesh, collection, parent, m_counter["name"])
        upstand_obj.matrix_world = matrix
        if use_bevel:
            apply_bevel_to_object(upstand_obj, bevel_w, bevel_segs)
        apply_box_uvs(upstand_obj, m_counter["u"], m_counter["v"], m_counter["rot"])

        if gen_collisions:
            for b_idx, bx in enumerate(u_boxes_data):
                create_ubx_box_primitive(upstand_obj, b_idx + 1, *bx, collection, matrix)


def generate_section(
        name_prefix,
        width, depth, height, wall_t,
        plinth_h, plinth_recess,
        sec_type, corner_style, next_is_corner, prev_is_corner,
        doors, shelves, has_mid_div, shelf_t,
        drawer_count, drawer_zone_h,
        gap,
        handle_door, handle_drawer,
        mat_roles,
        counter_thickness, over_front, over_back, over_left, over_right,
        has_upstand, upstand_h, upstand_t, is_island,
        has_plinth, use_legs, leg_height, has_top_cover, is_upper, lower_depth, allow_drawers,
        sink_cutout, sink_w, sink_d, sink_margin_f, sink_margin_b, sink_margin_l, sink_margin_r,
        sink_recess_depth, sink_recess_margin_f, sink_recess_margin_b,
        sink_recess_margin_l, sink_recess_margin_r,
        has_bottom, has_top, has_back_panel, shelf_rows, tier_dividers,
        columns_data,
        prev_d, prev_has_doors, next_d, next_has_doors,
        is_first_sec, is_last_sec,
        gen_collisions, use_bevel, bevel_w, bevel_segs,
        collection, parent, matrix,
        has_side_walls=True, shelf_span_l=0.0, shelf_span_r=0.0,
        sink_bevels=None, sink_drain=None
):
    t = wall_t
    d = depth
    # Legs lift the body exactly like a plinth does, so every existing z computation
    # keeps working; only the support under the body changes shape.
    ph = leg_height if (use_legs and leg_height > 0.0) else (plinth_h if has_plinth else 0.0)
    h = height

    if sec_type == SEC_HOOD_GAP:
        return

    m_facade = mat_roles["facade"]
    m_carcass = mat_roles["carcass"]
    m_counter = mat_roles["countertop"]
    m_plinth = mat_roles["plinth"]
    m_handle = mat_roles["handle"]

    # --------------------------------------------------------
    # WARDROBE BRANCH
    # --------------------------------------------------------
    if sec_type == SEC_WARDROBE:
        build_wardrobe_section(
            name_prefix=name_prefix, width=width, plinth_recess=plinth_recess,
            shelf_t=shelf_t, gap=gap,
            handle_door=handle_door, handle_drawer=handle_drawer, has_plinth=has_plinth,
            use_legs=use_legs, leg_height=leg_height,
            columns_data=columns_data, gen_collisions=gen_collisions, use_bevel=use_bevel,
            bevel_w=bevel_w, bevel_segs=bevel_segs, collection=collection,
            parent=parent, matrix=matrix, h=h,
            ph=ph, t=t, d=d,
            m_carcass=m_carcass, m_plinth=m_plinth, m_facade=m_facade,
            m_handle=m_handle
        )
        return

    # ============================================================
    # [ANCHOR: KITCHEN_CARCASS]
    # ============================================================
    is_corner_sec = (sec_type == SEC_CORNER)
    if is_corner_sec:
        # See AGENT_NOTES.md [NOTE_16550]
        width += (wall_t + gap)

    # ============================================================
    # [ANCHOR: UPPER_CORNER]
    # ============================================================
    if is_corner_sec and is_upper:
        build_corner_upper_section(
            name_prefix=name_prefix, width=width, corner_style=corner_style, shelves=shelves,
            shelf_t=shelf_t, gap=gap, handle_door=handle_door,
            lower_depth=lower_depth, prev_d=prev_d, prev_has_doors=prev_has_doors,
            next_d=next_d, next_has_doors=next_has_doors, gen_collisions=gen_collisions,
            use_bevel=use_bevel, bevel_w=bevel_w, bevel_segs=bevel_segs,
            collection=collection, parent=parent, matrix=matrix,
            d=d, ph=ph, t=t,
            h=h, m_carcass=m_carcass, m_facade=m_facade,
            m_handle=m_handle
        )
        return

    if use_legs and leg_height > 0.0:
        build_legs(
            name_prefix=name_prefix, width=width, d=d, leg_h=leg_height,
            gen_collisions=gen_collisions, collection=collection, parent=parent,
            matrix=matrix, m_plinth=m_plinth
        )
    else:
        build_plinth(
            name_prefix=name_prefix, width=width, wall_t=wall_t,
            plinth_recess=plinth_recess, gap=gap, is_island=is_island,
            has_plinth=has_plinth, is_first_sec=is_first_sec, is_last_sec=is_last_sec,
            gen_collisions=gen_collisions, collection=collection, parent=parent,
            matrix=matrix, is_corner_sec=is_corner_sec, ph=ph,
            m_plinth=m_plinth, d=d
        )

    use_drawers = allow_drawers and drawer_count > 0 and sec_type == SEC_NORMAL
    if use_drawers and drawer_zone_h > h - t:
        # The band sits on top of the compartment below it, so anything taller than the
        # body minus one wall leaves no place for the divider plate - it would land under
        # the floor. Clamped here rather than in the property, because the limit belongs to
        # the body and two sections of one row can have different heights.
        warn(f"{name_prefix}: drawer zone {drawer_zone_h:.3f} m does not fit the "
             f"{h:.3f} m body, clamped to {h - t:.3f} m")
        drawer_zone_h = h - t
    lower_h = h - (drawer_zone_h if use_drawers else 0.0)
    if use_drawers and doors > 0 and lower_h <= 0.1:
        # The door band is dropped by build_section_facades below this height, so say so
        # instead of letting the section build without doors in silence.
        warn(f"{name_prefix}: drawer zone {drawer_zone_h:.3f} m leaves a "
             f"{lower_h:.3f} m band below, too small for the doors - they are not built")

    build_carcass(
        name_prefix=name_prefix, width=width, sec_type=sec_type,
        shelves=shelves, has_mid_div=has_mid_div, shelf_t=shelf_t,
        gap=gap, is_island=is_island, is_upper=is_upper,
        has_bottom=has_bottom, has_top=has_top, has_back_panel=has_back_panel, shelf_rows=shelf_rows,
        tier_dividers=tier_dividers, gen_collisions=gen_collisions, use_bevel=use_bevel,
        bevel_w=bevel_w, bevel_segs=bevel_segs, collection=collection,
        parent=parent, matrix=matrix, use_drawers=use_drawers,
        is_corner_sec=is_corner_sec, ph=ph, t=t,
        h=h, m_facade=m_facade, d=d,
        lower_h=lower_h, m_carcass=m_carcass,
        has_side_walls=has_side_walls, shelf_span_l=shelf_span_l, shelf_span_r=shelf_span_r
    )

    # Standard Doors
    build_section_facades(
        name_prefix=name_prefix, width=width, sec_type=sec_type,
        doors=doors, drawer_count=drawer_count, drawer_zone_h=drawer_zone_h,
        gap=gap, handle_door=handle_door,
        handle_drawer=handle_drawer, is_upper=is_upper, gen_collisions=gen_collisions,
        use_bevel=use_bevel, bevel_w=bevel_w, bevel_segs=bevel_segs,
        collection=collection, parent=parent, matrix=matrix,
        use_drawers=use_drawers, lower_h=lower_h, t=t,
        ph=ph, m_facade=m_facade, d=d,
        m_handle=m_handle
    )

    if not has_top_cover or is_upper:
        return

    # ============================================================
    # [ANCHOR: COUNTERTOP_GEOMETRY]
    # ============================================================
    ct_x, ct_y, ct_w, ct_d, ct_z = build_countertop(
        name_prefix=name_prefix, width=width, wall_t=wall_t,
        sec_type=sec_type, next_is_corner=next_is_corner, prev_is_corner=prev_is_corner,
        gap=gap, counter_thickness=counter_thickness, over_front=over_front,
        over_back=over_back, over_left=over_left, over_right=over_right,
        is_island=is_island, sink_cutout=sink_cutout, sink_w=sink_w,
        sink_d=sink_d, sink_margin_f=sink_margin_f, sink_margin_b=sink_margin_b,
        sink_margin_l=sink_margin_l, sink_margin_r=sink_margin_r,
        sink_recess_depth=sink_recess_depth,
        sink_recess_margin_f=sink_recess_margin_f, sink_recess_margin_b=sink_recess_margin_b,
        sink_recess_margin_l=sink_recess_margin_l, sink_recess_margin_r=sink_recess_margin_r,
        is_first_sec=is_first_sec,
        is_last_sec=is_last_sec, gen_collisions=gen_collisions, use_bevel=use_bevel,
        bevel_w=bevel_w, bevel_segs=bevel_segs, collection=collection,
        parent=parent, matrix=matrix, ph=ph,
        h=h, d=d, m_counter=m_counter, sink_bevels=sink_bevels, sink_drain=sink_drain
    )

    # ============================================================
    # [ANCHOR: UPSTAND_RIM]
    # ============================================================
    build_upstand(
        name_prefix=name_prefix, sec_type=sec_type, counter_thickness=counter_thickness,
        has_upstand=has_upstand, upstand_h=upstand_h, upstand_t=upstand_t,
        is_island=is_island, gen_collisions=gen_collisions, use_bevel=use_bevel,
        bevel_w=bevel_w, bevel_segs=bevel_segs, collection=collection,
        parent=parent, matrix=matrix, d=d,
        m_counter=m_counter, ct_x=ct_x, ct_y=ct_y,
        ct_w=ct_w, ct_z=ct_z
    )


# ============================================================
