"""row - The row orchestrator - places sections along a wall and turns the corner.

Moved verbatim from the single-module addon; no body was edited during the move.
"""
import time
from mathutils import Vector, Matrix
from math import radians, cos, sin, atan2
from .core import (
    SEC_APPLIANCE,
    SEC_CORNER,
    SEC_HOOD_GAP,
    SEC_NORMAL,
    SEC_SINK,
    SEC_WARDROBE,
    log,
)
from .mesh_ops import apply_bevel_to_object, apply_box_uvs, create_ubx_box_primitive
from .primitives import create_island_countertop_mesh, new_object, solve_sink_cutout
from .sections import generate_section, build_sink_bowl

# [ANCHOR: ROW_ORCHESTRATOR]
# ============================================================
def shelf_wall_span(sections, index, step, wall_t):
    """How far past its own edge a shelf of section `index` runs to reach a side wall.

    Walks over the neighbours that dropped their own side walls, so a run of built-ins
    shares one pair of walls instead of leaving a shelf end in mid-air. A corner or a
    hood gap ends the walk (their carcasses are built elsewhere), and so does the row
    end - there is no wall to reach there.
    """
    span = 0.0
    j = index + step
    while 0 <= j < len(sections):
        s = sections[j]
        if getattr(s, "sec_type", None) in (SEC_CORNER, SEC_HOOD_GAP):
            return 0.0
        if not (getattr(s, "sec_type", None) == SEC_APPLIANCE and getattr(s, "no_side_walls", False)):
            return span + wall_t
        span += s.width
        j += step
    return 0.0


def build_cabinet_row(props, sections, row_name, depth, height, is_upper, base_z, root, collection,
                      gen_collisions=None):
    """Build one row of sections.

    gen_collisions overrides props.gen_collisions when given: the live-preview pass builds
    the same geometry without colliders (T-41), and the flag has to be threaded here because
    every collider call site below reads it - reading props instead would silently ignore
    the override, which is exactly what the first version of this did.
    """
    if gen_collisions is None:
        gen_collisions = props.gen_collisions
    base_handle_z = props.upper_handle_z_offset if is_upper else props.handle_z_offset
    pos = Vector((0.0, 0.0, base_z))
    rot = 0.0

    door_offset = props.wall_thickness + props.gap
    num_sec = len(sections)

    section_matrices = []

    for i, sec in enumerate(sections):
        st = sec.sec_type
        sec.is_corner = (st == SEC_CORNER)

        sec_h = sec.custom_height if (sec.override_height and sec.custom_height > 0.05) else height
        # A section shorter than its row needs an edge to be measured from. AUTO keeps
        # the historical placement (an upper section hangs from the row top, a lower one
        # stands on its plinth); the anchor makes it explicit and the offset is always
        # read away from that edge, so it lifts a bottom-anchored and drops a
        # top-anchored section.
        sec_anchor = getattr(sec, "z_anchor", 'AUTO')
        if sec_anchor == 'AUTO':
            sec_anchor = 'TOP' if is_upper else 'BOTTOM'
        z_off = getattr(sec, "z_offset", 0.0)
        if sec_anchor == 'TOP':
            z_lift = (height - sec_h) - z_off
        else:
            z_lift = z_off
        sec_d = sec.custom_depth if (sec.override_depth and sec.custom_depth > 0.05) else depth

        next_sec = sections[i + 1] if (i + 1 < num_sec) else None
        prev_sec = sections[i - 1] if i > 0 else None
        next_is_corner = (next_sec.sec_type == SEC_CORNER) if next_sec else False
        prev_is_corner = (prev_sec.sec_type == SEC_CORNER) if prev_sec else False

        prev_d = prev_sec.custom_depth if (
                prev_sec and prev_sec.override_depth and prev_sec.custom_depth > 0.05) else depth
        prev_has_doors = (prev_sec.sec_type not in (SEC_APPLIANCE,
                                                    SEC_HOOD_GAP) and prev_sec.doors > 0) if prev_sec else False
        next_d = next_sec.custom_depth if (
                next_sec and next_sec.override_depth and next_sec.custom_depth > 0.05) else depth
        next_has_doors = (next_sec.sec_type not in (SEC_APPLIANCE,
                                                    SEC_HOOD_GAP) and next_sec.doors > 0) if next_sec else False

        # Corner planar extents — see AGENT_NOTES.md [NOTE_16550].
        # Lower: rectangle next_d (along wall 1) x prev_d (from wall 1).
        # Upper: wall-1 extent = props.depth so both rows turn on the same line;
        #   only the diagonal cut adapts to upper prev_d/next_d inside the builder.
        if st == SEC_CORNER:
            if is_upper:
                corner_w1 = props.depth
                gen_width = corner_w1
                gen_depth = depth
            else:
                corner_w1 = next_d
                gen_width = corner_w1
                gen_depth = prev_d
        else:
            gen_width = sec.width
            gen_depth = sec_d

        sec_pos = Vector((pos.x, pos.y, pos.z + z_lift))
        base_mat = Matrix.Translation(sec_pos) @ Matrix.Rotation(radians(rot), 4, 'Z')
        # Keep the back on the wall line.
        # Lower corner: mesh depth is gen_depth (prev_d); shift like a shallower
        #   regular section so the back lands on the wall.
        # Upper corner: build_corner_upper_section already spans to lower_depth
        #   (cd = lower_depth + t + gap), so the mesh is full lower-depth in plan —
        #   applying props.depth - upper_depth would push it past the wall into
        #   the room. Use props.depth → shift 0.
        # Regular sections: unchanged (sec_d).
        if st == SEC_CORNER and is_upper:
            wall_align_d = props.depth
        elif st == SEC_CORNER:
            wall_align_d = gen_depth
        else:
            wall_align_d = sec_d
        sec_mat = base_mat @ Matrix.Translation(
            Vector((0.0, props.depth - wall_align_d, 0.0)))
        section_matrices.append(sec_mat)

        is_vert = props.handle_vertical
        if sec.handle_orient == 'HORIZ':
            is_vert = False
        elif sec.handle_orient == 'VERT':
            is_vert = True

        custom_z_off = sec.custom_handle_z if sec.override_handle_z else base_handle_z

        handle_door = {
            "length": props.handle_length, "overhang": props.handle_bar_overhang,
            "radius": props.handle_bar_radius, "mount_len": props.handle_mount_length,
            "vertical": is_vert, "side_margin": props.handle_side_margin,
            "top_margin": props.lower_handle_top_margin, "bottom_margin": props.upper_handle_bottom_margin,
            "z_offset": custom_z_off,
        }
        handle_drawer = {
            "length": props.handle_length * props.drawer_handle_scale,
            "overhang": props.handle_bar_overhang * props.drawer_handle_scale,
            "radius": props.handle_bar_radius * props.drawer_handle_scale,
            "mount_len": props.handle_mount_length * props.drawer_handle_scale,
            "vertical": False, "z_offset": 0.0,
        }

        def_facade_name = props.mat_facade_upper if is_upper else props.mat_facade_lower
        def_facade_u = props.uv_facade_upper_u if is_upper else props.uv_facade_lower_u
        def_facade_v = props.uv_facade_upper_v if is_upper else props.uv_facade_lower_v
        def_facade_rot = props.rot_facade_upper if is_upper else props.rot_facade_lower

        facade_name = sec.custom_mat_facade if (sec.override_mat and sec.custom_mat_facade) else def_facade_name
        carcass_name = sec.custom_mat_carcass if (sec.override_mat and sec.custom_mat_carcass) else props.mat_carcass

        mat_roles = {
            "facade": {"name": facade_name, "u": def_facade_u, "v": def_facade_v, "rot": def_facade_rot},
            "carcass": {"name": carcass_name, "u": props.uv_carcass_u, "v": props.uv_carcass_v,
                        "rot": props.rot_carcass},
            "countertop": {"name": props.mat_countertop, "u": props.uv_countertop_u, "v": props.uv_countertop_v,
                           "rot": props.rot_countertop},
            "plinth": {"name": props.mat_plinth, "u": props.uv_plinth_u, "v": props.uv_plinth_v,
                       "rot": props.rot_plinth},
            "handle": {"name": props.mat_handle, "u": props.uv_handle_u, "v": props.uv_handle_v,
                       "rot": props.rot_handle},
        }

        is_first = (i == 0 and not prev_is_corner)
        is_last = (i == num_sec - 1 and not next_is_corner)

        over_l = props.countertop_overhang_side if is_first else 0.0
        over_r = props.countertop_overhang_side if is_last else 0.0
        sec_is_island = getattr(sec, "is_island", False)
        sec_has_upstand = getattr(sec, "has_upstand", True) and props.has_upstand and (not is_upper)

        # Island base modules have a single monolithic slab across the island, skip per-section slab
        has_sec_top_cover = (st not in (SEC_HOOD_GAP, SEC_WARDROBE)) and not (sec_is_island and not is_upper)

        # Built-in carcass: an appliance section between two neighbours may drop its own
        # side walls and run its shelves into them. An end section cannot - it would
        # stand with both sides open and nothing to screw to.
        drop_side_walls = (st == SEC_APPLIANCE and getattr(sec, "no_side_walls", False)
                           and not is_first and not is_last)
        shelf_span_l = shelf_span_r = 0.0
        if st == SEC_APPLIANCE and getattr(sec, "shelves_span_walls", False):
            shelf_span_l = shelf_wall_span(sections, i, -1, props.wall_thickness)
            shelf_span_r = shelf_wall_span(sections, i, +1, props.wall_thickness)

        t_sec_start = time.perf_counter()
        generate_section(
            name_prefix=f"SM_{props.kitchen_id}_{row_name}_Sec_{i + 1:02d}",
            width=gen_width, depth=gen_depth, height=sec_h, wall_t=props.wall_thickness,
            plinth_h=props.plinth_height, plinth_recess=props.plinth_recess,
            sec_type=st, corner_style=sec.corner_style,
            next_is_corner=next_is_corner, prev_is_corner=prev_is_corner,
            doors=0 if st in (SEC_APPLIANCE, SEC_CORNER, SEC_WARDROBE) else sec.doors,
            shelves=sec.shelves if (st == SEC_NORMAL or (is_upper and st == SEC_CORNER)) else 0,
            has_mid_div=sec.has_mid_divider if st == SEC_NORMAL else False,
            shelf_t=sec.shelf_thickness,
            drawer_count=sec.drawer_count if (st == SEC_NORMAL and not is_upper) else 0,
            drawer_zone_h=sec.drawer_height, gap=props.gap,
            handle_door=handle_door, handle_drawer=handle_drawer, mat_roles=mat_roles,
            counter_thickness=props.countertop_thickness,
            over_front=props.countertop_overhang_front,
            over_back=props.countertop_overhang_back,
            over_left=over_l, over_right=over_r,
            has_upstand=sec_has_upstand,
            upstand_h=props.upstand_height,
            upstand_t=props.upstand_thickness,
            is_island=sec_is_island,
            has_plinth=(not is_upper) and (st not in (SEC_HOOD_GAP,)) and not props.use_legs,
            use_legs=props.use_legs and (not is_upper),
            leg_height=props.leg_height,
            has_top_cover=has_sec_top_cover,
            is_upper=is_upper, lower_depth=props.depth, allow_drawers=(not is_upper) and (st == SEC_NORMAL),
            sink_cutout=(st == SEC_SINK),
            sink_w=sec.sink_w, sink_d=sec.sink_d,
            sink_margin_f=sec.sink_margin_f, sink_margin_b=sec.sink_margin_b,
            sink_margin_l=sec.sink_margin_l, sink_margin_r=sec.sink_margin_r,
            sink_recess_depth=sec.sink_recess_depth,
            sink_recess_margin_f=sec.sink_recess_margin_f,
            sink_recess_margin_b=sec.sink_recess_margin_b,
            sink_recess_margin_l=sec.sink_recess_margin_l,
            sink_recess_margin_r=sec.sink_recess_margin_r,
            has_bottom=sec.has_bottom, has_top=sec.has_top, has_back_panel=sec.has_back_panel,
            shelf_rows=sec.shelf_rows,
            has_side_walls=not drop_side_walls,
            shelf_span_l=shelf_span_l, shelf_span_r=shelf_span_r,
            tier_dividers=[t.dividers for t in sec.tiers],
            columns_data=sec.columns if st == SEC_WARDROBE else [],
            prev_d=prev_d, prev_has_doors=prev_has_doors, next_d=next_d, next_has_doors=next_has_doors,
            is_first_sec=is_first, is_last_sec=is_last,
            gen_collisions=gen_collisions, use_bevel=props.use_bevel, bevel_w=props.bevel_width,
            bevel_segs=props.bevel_segments,
            collection=collection, parent=root, matrix=sec_mat,
            sink_bevels={
                "floor_w": sec.sink_bevel_floor_w,
                "vert_w": sec.sink_bevel_vert_w,
                "top_w": sec.sink_bevel_top_w,
                "segments": sec.sink_bevel_segments,
                "miter": sec.sink_bevel_miter,
            },
            sink_drain={
                "on": sec.sink_drain_on,
                "d1": sec.sink_drain_d1,
                "d2": sec.sink_drain_d2,
                "dia1": sec.sink_drain_dia1,
                "dia2": sec.sink_drain_dia2,
                "bevel_top": sec.sink_drain_bevel_top,
                "bevel_mid": sec.sink_drain_bevel_mid,
                "bevel_low": sec.sink_drain_bevel_low,
                "segments": sec.sink_drain_bevel_segments,
                "strainer_on": sec.sink_strainer_on,
                "strainer_thickness": sec.sink_strainer_thickness,
                "strainer_gap": sec.sink_strainer_gap,
            }
        )
        t_sec_ms = (time.perf_counter() - t_sec_start) * 1000.0
        log(f"  [{row_name}] Sec {i + 1:02d} ({st}): {t_sec_ms:.2f} ms")

        if st == SEC_CORNER:
            # See AGENT_NOTES.md [NOTE_16550]. corner_w1 is next_d on the lower row
            # and props.depth on the upper row (so both rows turn on the same line).
            # Wall corrections keep door-gap geometry consistent. After the turn the
            # next origin is placed one row-depth from wall 2 (shallower neighbours
            # then shift via props.depth - sec_d).
            #
            # The corner's sec_mat also applies a wall-align shift S = props.depth -
            # gen_depth in local Y. pos must absorb that same world offset, otherwise
            # every section after the corner stays on the un-shifted base line and a
            # gap opens between the corner and the rest of the L.
            corner_extent = corner_w1 + props.wall_thickness + props.gap
            pos += Vector((cos(radians(rot)), sin(radians(rot)), 0.0)) * corner_extent
            # Same shift that was applied to sec_mat — keep pos in sync so the
            # following sections do not reopen a gap. Upper corner shift is 0.
            s_align = props.depth - wall_align_d
            # local (0, s_align) under the corner's current rotation → world offset
            pos += Vector((
                -s_align * sin(radians(rot)),
                s_align * cos(radians(rot)),
                0.0,
            ))
            rot -= 90.0
            pos += Vector((sin(radians(rot)), -cos(radians(rot)), 0.0)) * props.depth
            pos += Vector((cos(radians(rot)), sin(radians(rot)), 0.0)) * door_offset
        else:
            pos += Vector((cos(radians(rot)), sin(radians(rot)), 0.0)) * sec.width

    # Monolithic Island Countertop generation for contiguous island runs
    if not is_upper:
        idx = 0
        while idx < num_sec:
            if getattr(sections[idx], "is_island", False):
                span_start = idx
                while idx < num_sec and getattr(sections[idx], "is_island", False):
                    idx += 1
                span_end = idx

                t_island_start = time.perf_counter()
                island_w = sum(sections[k].width for k in range(span_start, span_end))
                span_mat = section_matrices[span_start]

                max_sec_d = max(sections[k].custom_depth if (
                        sections[k].override_depth and sections[k].custom_depth > 0.05) else depth for k in
                                range(span_start, span_end))
                max_sec_h = max(sections[k].custom_height if (
                        sections[k].override_height and sections[k].custom_height > 0.05) else height for k in
                                range(span_start, span_end))

                ct_x = -props.countertop_overhang_side
                ct_w = island_w + props.countertop_overhang_side * 2
                ct_y = -props.countertop_overhang_front
                ct_d = max_sec_d + props.countertop_overhang_front + props.countertop_overhang_back
                # With legs the body is lifted to leg_height, not plinth_height, so the
                # island slab must sit on the same line as the section bodies.
                ct_z = (props.leg_height if props.use_legs else props.plinth_height) + max_sec_h
                ct_h = props.countertop_thickness

                sink_data = None
                sink_sec = None
                for k in range(span_start, span_end):
                    s_sec = sections[k]
                    if s_sec.sec_type == SEC_SINK:
                        x_off = sum(sections[m].width for m in range(span_start, k))
                        sink_data = solve_sink_cutout(
                            ct_x, ct_y, ct_w, ct_d, x_off, s_sec.width,
                            s_sec.sink_w, s_sec.sink_d,
                            s_sec.sink_margin_f, s_sec.sink_margin_b,
                            s_sec.sink_margin_l, s_sec.sink_margin_r)
                        sink_sec = s_sec
                        break

                mesh_ct = create_island_countertop_mesh(
                    ct_x, ct_y, ct_z, ct_w, ct_d, ct_h,
                    corner_radius=props.island_corner_radius,
                    sink_data=sink_data
                )
                island_ct_name = f"SM_{props.kitchen_id}_{row_name}_IslandCountertop_{span_start + 1:02d}"
                obj_ct = new_object(island_ct_name, mesh_ct, collection, root, props.mat_countertop)
                obj_ct.matrix_world = span_mat

                if props.use_bevel:
                    apply_bevel_to_object(obj_ct, props.bevel_width, props.bevel_segments)
                apply_box_uvs(obj_ct, props.uv_countertop_u, props.uv_countertop_v, props.rot_countertop)

                if gen_collisions:
                    if sink_data is None:
                        create_ubx_box_primitive(obj_ct, 1, ct_x, ct_y, ct_z, ct_w, ct_d, ct_h, collection, span_mat)
                    else:
                        shx0, shy0, shw, shd = sink_data
                        create_ubx_box_primitive(obj_ct, 1, ct_x, ct_y, ct_z, ct_w, shy0 - ct_y, ct_h, collection,
                                                 span_mat)
                        create_ubx_box_primitive(obj_ct, 2, ct_x, shy0 + shd, ct_z, ct_w, (ct_y + ct_d) - (shy0 + shd),
                                                 ct_h, collection, span_mat)
                        create_ubx_box_primitive(obj_ct, 3, ct_x, shy0, ct_z, shx0 - ct_x, shd, ct_h, collection,
                                                 span_mat)
                        create_ubx_box_primitive(obj_ct, 4, shx0 + shw, shy0, ct_z, (ct_x + ct_w) - (shx0 + shw), shd,
                                                 ct_h, collection, span_mat)
                if sink_data is not None and sink_sec is not None:
                    shx0, shy0, shw, shd = sink_data
                    build_sink_bowl(
                        name_prefix=f"SM_{props.kitchen_id}_{row_name}_Island_{span_start + 1:02d}",
                        hx0=shx0, hy0=shy0, hw=shw, hd=shd, z_top=ct_z + ct_h,
                        depth=sink_sec.sink_recess_depth,
                        margin_f=sink_sec.sink_recess_margin_f,
                        margin_b=sink_sec.sink_recess_margin_b,
                        margin_l=sink_sec.sink_recess_margin_l,
                        margin_r=sink_sec.sink_recess_margin_r,
                        collection=collection, parent=root, matrix=span_mat,
                        mat={"name": props.mat_countertop, "u": props.uv_countertop_u,
                             "v": props.uv_countertop_v, "rot": props.rot_countertop},
                        bevels={
                            "floor_w": sink_sec.sink_bevel_floor_w,
                            "vert_w": sink_sec.sink_bevel_vert_w,
                            "top_w": sink_sec.sink_bevel_top_w,
                            "segments": sink_sec.sink_bevel_segments,
                            "miter": sink_sec.sink_bevel_miter,
                        },
                        drain={
                            "on": sink_sec.sink_drain_on,
                            "d1": sink_sec.sink_drain_d1,
                            "d2": sink_sec.sink_drain_d2,
                            "dia1": sink_sec.sink_drain_dia1,
                            "dia2": sink_sec.sink_drain_dia2,
                            "bevel_top": sink_sec.sink_drain_bevel_top,
                            "bevel_mid": sink_sec.sink_drain_bevel_mid,
                            "bevel_low": sink_sec.sink_drain_bevel_low,
                            "segments": sink_sec.sink_drain_bevel_segments,
                            "strainer_on": sink_sec.sink_strainer_on,
                            "strainer_thickness": sink_sec.sink_strainer_thickness,
                            "strainer_gap": sink_sec.sink_strainer_gap,
                        })
                t_island_ms = (time.perf_counter() - t_island_start) * 1000.0
                log(f"  [{row_name}] Island Countertop: {t_island_ms:.2f} ms")
            else:
                idx += 1


# ============================================================
