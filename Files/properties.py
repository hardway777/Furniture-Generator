"""properties - Property groups, their update callbacks and preset serialization.

Moved verbatim from the single-module addon; no body was edited during the move.
"""
import bpy
import os
import re
import ntpath
from bpy.props import (
    FloatProperty, IntProperty, BoolProperty, EnumProperty,
    CollectionProperty, PointerProperty, StringProperty
)
from bpy.types import PropertyGroup, Operator, Panel
from .core import (
    CORN_BLIND,
    CORN_DIAGONAL,
    CORN_DOORS,
    CORN_OPEN,
    KITCHEN_COLL_PREFIX,
    SEC_APPLIANCE,
    SEC_CORNER,
    SEC_HOOD_GAP,
    SEC_NORMAL,
    SEC_SINK,
    SEC_WARDROBE,
)
from .strings import STR

# [ANCHOR: PRESET_SYSTEM]
# ============================================================
def get_preset_directory():
    base_dir = bpy.utils.user_resource('SCRIPTS')
    preset_dir = os.path.join(base_dir, "presets", "kitchen_generator")
    if not os.path.exists(preset_dir):
        os.makedirs(preset_dir, exist_ok=True)
    return preset_dir


PRESET_NAME_FORBIDDEN = re.compile(r"[^\w\-. ]+")


def safe_preset_name(name):
    """Reduce user input to a single file name that cannot escape the preset directory.

    ntpath is used on purpose: it treats the backslash as a separator on every host OS,
    so a Windows-style path typed on Linux/macOS is reduced to its file part as well.
    """
    base = ntpath.basename(os.path.basename(str(name).strip()))
    base = PRESET_NAME_FORBIDDEN.sub("_", base).strip(". ")
    return base[:64]


def resolve_preset_path(name):
    """Absolute path of a preset inside the preset directory, or None if the name is unusable."""
    fname = safe_preset_name(name)
    if not fname:
        return None
    preset_dir = os.path.abspath(get_preset_directory())
    path = os.path.abspath(os.path.join(preset_dir, fname + ".json"))
    if os.path.commonpath([preset_dir, path]) != preset_dir:
        return None
    return path


def get_preset_enum_items(self, context):
    pdir = get_preset_directory()
    items = []
    if os.path.exists(pdir):
        files = sorted([f for f in os.listdir(pdir) if f.endswith(".json")])
        for f in files:
            name = os.path.splitext(f)[0]
            items.append((name, name, STR["preset_file_desc"].format(file=f)))
    if not items:
        items.append(("NONE", STR["preset_none_title"], STR["preset_none_desc"]))
    return items


def serialize_kitchen(props):
    def serialize_section(sec):
        cols_data = []
        for col in sec.columns:
            zones_data = []
            for z in col.zones:
                bays_data = []
                for b in z.bays:
                    bays_data.append({
                        "height_mode": b.height_mode,
                        "height": b.height,
                        "height_pct": b.height_pct,
                    })

                zones_data.append({
                    "zone_type": z.zone_type,
                    "height_mode": z.height_mode,
                    "height": z.height,
                    "height_pct": z.height_pct,
                    "door_swing": z.door_swing,
                    "interior_type": z.interior_type,
                    "shelf_mode": z.shelf_mode,
                    "shelves_count": z.shelves_count,
                    "bay_count": z.bay_count,
                    "bays": bays_data,
                    "rod_drop": z.rod_drop,
                    "handle_pos": z.handle_pos,
                    "handle_z_offset": z.handle_z_offset,
                    "handle_len_mode": z.handle_len_mode,
                    "handle_pct": z.handle_pct,
                    "handle_custom_len": z.handle_custom_len,
                })
            cols_data.append({"zones": zones_data})

        return {
            "width": sec.width,
            "sec_type": sec.sec_type,
            "corner_style": sec.corner_style,
            "is_corner": sec.is_corner,
            "is_island": sec.is_island,
            "has_upstand": sec.has_upstand,
            "override_height": sec.override_height,
            "custom_height": sec.custom_height,
            "override_depth": sec.override_depth,
            "custom_depth": sec.custom_depth,
            "has_bottom": sec.has_bottom,
            "has_top": sec.has_top,
            "has_back_panel": sec.has_back_panel,
            "shelf_rows": sec.shelf_rows,
            "tiers": [t.dividers for t in sec.tiers],
            "no_side_walls": sec.no_side_walls,
            "shelves_span_walls": sec.shelves_span_walls,
            "z_anchor": sec.z_anchor,
            "z_offset": sec.z_offset,
            "doors": sec.doors,
            "handle_orient": sec.handle_orient,
            "override_handle_z": sec.override_handle_z,
            "custom_handle_z": sec.custom_handle_z,
            "shelves": sec.shelves,
            "has_mid_divider": sec.has_mid_divider,
            "shelf_thickness": sec.shelf_thickness,
            "drawer_count": sec.drawer_count,
            "drawer_height": sec.drawer_height,
            "sink_w": sec.sink_w,
            "sink_d": sec.sink_d,
            "sink_margin_f": sec.sink_margin_f,
            "sink_margin_b": sec.sink_margin_b,
            "sink_margin_l": sec.sink_margin_l,
            "sink_margin_r": sec.sink_margin_r,
            "sink_recess_depth": sec.sink_recess_depth,
            "sink_recess_margin_f": sec.sink_recess_margin_f,
            "sink_recess_margin_b": sec.sink_recess_margin_b,
            "sink_recess_margin_l": sec.sink_recess_margin_l,
            "sink_recess_margin_r": sec.sink_recess_margin_r,
            "sink_bevel_floor_w": sec.sink_bevel_floor_w,
            "sink_bevel_vert_w": sec.sink_bevel_vert_w,
            "sink_bevel_top_w": sec.sink_bevel_top_w,
            "sink_bevel_segments": sec.sink_bevel_segments,
            "sink_bevel_miter": sec.sink_bevel_miter,
            "sink_drain_on": sec.sink_drain_on,
            "sink_drain_d1": sec.sink_drain_d1,
            "sink_drain_d2": sec.sink_drain_d2,
            "sink_drain_dia1": sec.sink_drain_dia1,
            "sink_drain_dia2": sec.sink_drain_dia2,
            "sink_drain_bevel_top": sec.sink_drain_bevel_top,
            "sink_drain_bevel_mid": sec.sink_drain_bevel_mid,
            "sink_drain_bevel_low": sec.sink_drain_bevel_low,
            "sink_drain_bevel_segments": sec.sink_drain_bevel_segments,
            "sink_strainer_on": sec.sink_strainer_on,
            "sink_strainer_thickness": sec.sink_strainer_thickness,
            "sink_strainer_gap": sec.sink_strainer_gap,
            "override_mat": sec.override_mat,
            "custom_mat_facade": sec.custom_mat_facade,
            "custom_mat_carcass": sec.custom_mat_carcass,
            "column_count": sec.column_count,
            "columns": cols_data,
        }

    data = {
        "kitchen_id": props.kitchen_id,
        "wall_thickness": props.wall_thickness,
        "gap": props.gap,
        "gen_collisions": props.gen_collisions,
        "use_bevel": props.use_bevel,
        "bevel_width": props.bevel_width,
        "bevel_segments": props.bevel_segments,
        "section_count": props.section_count,
        "depth": props.depth,
        "height": props.height,
       "plinth_height": props.plinth_height,
       "plinth_recess": props.plinth_recess,
       "use_legs": props.use_legs,
       "leg_height": props.leg_height,

        "countertop_thickness": props.countertop_thickness,
        "countertop_overhang_front": props.countertop_overhang_front,
        "countertop_overhang_back": props.countertop_overhang_back,
        "countertop_overhang_side": props.countertop_overhang_side,
        "island_corner_radius": props.island_corner_radius,
        "has_upstand": props.has_upstand,
        "upstand_height": props.upstand_height,
        "upstand_thickness": props.upstand_thickness,
        "gen_upper": props.gen_upper,
        "sync_upper_with_lower": props.sync_upper_with_lower,
        "upper_section_count": props.upper_section_count,
        "upper_depth": props.upper_depth,
        "upper_height": props.upper_height,
        "backsplash_height": props.backsplash_height,
        "upper_handle_z_offset": props.upper_handle_z_offset,
        "handle_vertical": props.handle_vertical,
        "handle_length": props.handle_length,
        "handle_bar_overhang": props.handle_bar_overhang,
        "handle_bar_radius": props.handle_bar_radius,
        "handle_mount_length": props.handle_mount_length,
        "handle_side_margin": props.handle_side_margin,
        "lower_handle_top_margin": props.lower_handle_top_margin,
        "upper_handle_bottom_margin": props.upper_handle_bottom_margin,
        "handle_z_offset": props.handle_z_offset,
        "drawer_handle_scale": props.drawer_handle_scale,

        "mat_facade_lower": props.mat_facade_lower,
        "uv_facade_lower_u": props.uv_facade_lower_u,
        "uv_facade_lower_v": props.uv_facade_lower_v,
        "rot_facade_lower": props.rot_facade_lower,

        "mat_facade_upper": props.mat_facade_upper,
        "uv_facade_upper_u": props.uv_facade_upper_u,
        "uv_facade_upper_v": props.uv_facade_upper_v,
        "rot_facade_upper": props.rot_facade_upper,

        "mat_carcass": props.mat_carcass,
        "uv_carcass_u": props.uv_carcass_u,
        "uv_carcass_v": props.uv_carcass_v,
        "rot_carcass": props.rot_carcass,

        "mat_countertop": props.mat_countertop,
        "uv_countertop_u": props.uv_countertop_u,
        "uv_countertop_v": props.uv_countertop_v,
        "rot_countertop": props.rot_countertop,

        "mat_plinth": props.mat_plinth,
        "uv_plinth_u": props.uv_plinth_u,
        "uv_plinth_v": props.uv_plinth_v,
        "rot_plinth": props.rot_plinth,

        "mat_handle": props.mat_handle,
        "uv_handle_u": props.uv_handle_u,
        "uv_handle_v": props.uv_handle_v,
        "rot_handle": props.rot_handle,

        "sections": [serialize_section(s) for s in props.sections],
        "upper_sections": [serialize_section(s) for s in props.upper_sections],
    }
    return data


def deserialize_kitchen(props, data, context):
    scalar_keys = [
        "kitchen_id", "wall_thickness", "gap", "gen_collisions",
        "use_bevel", "bevel_width", "bevel_segments",
        "depth", "height", "plinth_height", "plinth_recess", "use_legs", "leg_height",
        "countertop_thickness", "countertop_overhang_front", "countertop_overhang_back", "countertop_overhang_side",
        "island_corner_radius", "has_upstand", "upstand_height", "upstand_thickness",
        "gen_upper", "sync_upper_with_lower", "upper_depth", "upper_height",
        "backsplash_height", "upper_handle_z_offset",
        "handle_vertical", "handle_length", "handle_bar_overhang", "handle_bar_radius",
        "handle_mount_length", "handle_side_margin", "lower_handle_top_margin",
        "upper_handle_bottom_margin", "handle_z_offset", "drawer_handle_scale",
        "mat_facade_lower", "uv_facade_lower_u", "uv_facade_lower_v", "rot_facade_lower",
        "mat_facade_upper", "uv_facade_upper_u", "uv_facade_upper_v", "rot_facade_upper",
        "mat_carcass", "uv_carcass_u", "uv_carcass_v", "rot_carcass",
        "mat_countertop", "uv_countertop_u", "uv_countertop_v", "rot_countertop",
        "mat_plinth", "uv_plinth_u", "uv_plinth_v", "rot_plinth",
        "mat_handle", "uv_handle_u", "uv_handle_v", "rot_handle"
    ]
    for key in scalar_keys:
        if key in data:
            setattr(props, key, data[key])

    def restore_section(sec, sec_data):
        for k, v in sec_data.items():
            if k == "tiers":
                sec.shelf_rows = len(v) - 1 if len(v) > 0 else 0
                update_section_tiers(sec, context)
                for idx, div_val in enumerate(v):
                    if idx < len(sec.tiers):
                        sec.tiers[idx].dividers = div_val
            elif k == "columns":
                sec.column_count = len(v)
                update_section_columns(sec, context)
                for c_idx, c_data in enumerate(v):
                    if c_idx < len(sec.columns):
                        col = sec.columns[c_idx]
                        z_list = c_data.get("zones", [])
                        col.zone_count = len(z_list)
                        update_column_zones(col, context)
                        for z_idx, z_data in enumerate(z_list):
                            if z_idx < len(col.zones):
                                z = col.zones[z_idx]
                                for zk, zv in z_data.items():
                                    if zk == "bays":
                                        z.bay_count = len(zv)
                                        update_zone_bays(z, context)
                                        for b_idx, b_data in enumerate(zv):
                                            if b_idx < len(z.bays):
                                                for bk, bv in b_data.items():
                                                    if hasattr(z.bays[b_idx], bk):
                                                        setattr(z.bays[b_idx], bk, bv)
                                    elif zk == "auto_height" and zv:
                                        z.height_mode = 'AUTO'
                                    elif hasattr(z, zk):
                                        setattr(z, zk, zv)
            elif hasattr(sec, k):
                setattr(sec, k, v)

    lower_data = data.get("sections", [])
    props.section_count = len(lower_data)
    update_lower_sections(props, context)
    for i, s_data in enumerate(lower_data):
        if i < len(props.sections):
            restore_section(props.sections[i], s_data)

    upper_data = data.get("upper_sections", [])
    props.upper_section_count = len(upper_data)
    update_upper_sections(props, context)
    for i, s_data in enumerate(upper_data):
        if i < len(props.upper_sections):
            restore_section(props.upper_sections[i], s_data)


# ============================================================
# [ANCHOR: DATA_PROPERTIES]
# ============================================================
class ShelfTier(PropertyGroup):
    dividers: IntProperty(name=STR["prop_dividers"], default=0, min=0, max=10)


def update_section_tiers(self, context):
    desired = self.shelf_rows + 1
    while len(self.tiers) < desired:
        self.tiers.add()
    while len(self.tiers) > desired:
        self.tiers.remove(len(self.tiers) - 1)


class ShelfBay(PropertyGroup):
    height_mode: EnumProperty(
        name=STR["prop_mode"],
        items=[
            ('PERCENT', STR["enum_bay_mode_pct"], STR["enum_bay_mode_pct_desc"]),
            ('METERS', STR["enum_bay_mode_m"], STR["enum_bay_mode_m_desc"]),
            ('AUTO', STR["enum_bay_mode_auto"], STR["enum_bay_mode_auto_desc"]),
        ],
        default='PERCENT'
    )
    height: FloatProperty(name=STR["prop_height"], default=0.25, min=0.04, max=2.5, unit='LENGTH', precision=3)
    height_pct: FloatProperty(name=STR["prop_share_pct"], default=33.3, min=1.0, max=100.0, subtype='PERCENTAGE')


def update_zone_bays(zone, context):
    while len(zone.bays) < zone.bay_count:
        b = zone.bays.add()
        b.height = 0.25
        b.height_pct = 100.0 / max(1, zone.bay_count)
    while len(zone.bays) > zone.bay_count:
        zone.bays.remove(len(zone.bays) - 1)


class CabinetZone(PropertyGroup):
    is_expanded: BoolProperty(name=STR["prop_expanded"], default=True)
    zone_type: EnumProperty(
        name=STR["prop_zone_type"],
        items=[
            ('DRAWER', STR["enum_zone_drawer"], STR["enum_zone_drawer_desc"]),
            ('DOOR', STR["enum_zone_door"], STR["enum_zone_door_desc"]),
            ('OPEN', STR["enum_zone_open"], STR["enum_zone_open_desc"]),
        ],
        default='DRAWER'
    )
    height_mode: EnumProperty(
        name=STR["prop_height_mode"],
        items=[
            ('METERS', STR["enum_zone_h_meters"], STR["enum_zone_h_meters_desc"]),
            ('PERCENT', STR["enum_zone_h_pct"], STR["enum_zone_h_pct_desc"]),
            ('AUTO', STR["enum_zone_h_auto"], STR["enum_zone_h_auto_desc"]),
        ],
        default='METERS'
    )
    height: FloatProperty(name=STR["prop_height"], default=0.22, min=0.08, max=3.0, unit='LENGTH', precision=3)
    height_pct: FloatProperty(name=STR["prop_height_pct"], default=30.0, min=1.0, max=100.0, subtype='PERCENTAGE')

    door_swing: EnumProperty(
        name=STR["prop_door_swing"],
        items=[
            ('LEFT', STR["enum_swing_left"], STR["enum_swing_left_desc"]),
            ('RIGHT', STR["enum_swing_right"], STR["enum_swing_right_desc"]),
            ('PAIR', STR["enum_swing_pair"], STR["enum_swing_pair_desc"]),
        ],
        default='LEFT'
    )
    handle_pos: EnumProperty(
        name=STR["prop_handle_pos"],
        items=[
            ('TOP', STR["enum_hpos_top"], STR["enum_hpos_top_desc"]),
            ('CENTER', STR["enum_hpos_center"], STR["enum_hpos_center_desc"]),
            ('BOTTOM', STR["enum_hpos_bottom"], STR["enum_hpos_bottom_desc"]),
        ],
        default='BOTTOM'
    )
    handle_z_offset: FloatProperty(name=STR["prop_edge_dist"], default=0.05, min=0.0, max=2.0, unit='LENGTH',
                                   precision=3, description=STR["prop_edge_dist_desc"])
    handle_len_mode: EnumProperty(
        name=STR["prop_handle_len_mode"],
        items=[
            ('DEFAULT', STR["enum_hlen_default"], STR["enum_hlen_default_desc"]),
            ('PERCENT', STR["enum_hlen_pct"], STR["enum_hlen_pct_desc"]),
            ('EXPLICIT', STR["enum_hlen_explicit"], STR["enum_hlen_explicit_desc"]),
        ],
        default='DEFAULT'
    )
    handle_pct: FloatProperty(name=STR["prop_handle_pct"], default=50.0, min=5.0, max=95.0, subtype='PERCENTAGE')
    handle_custom_len: FloatProperty(name=STR["prop_handle_custom_len"], default=0.30, min=0.03, max=2.5, unit='LENGTH',
                                     precision=3)

    interior_type: EnumProperty(
        name=STR["prop_interior"],
        items=[
            ('SHELVES', STR["enum_interior_shelves"], STR["enum_interior_shelves_desc"]),
            ('ROD', STR["enum_interior_rod"], STR["enum_interior_rod_desc"]),
            ('EMPTY', STR["enum_interior_empty"], STR["enum_interior_empty_desc"]),
        ],
        default='SHELVES'
    )
    shelf_mode: EnumProperty(
        name=STR["prop_shelf_spacing"],
        items=[
            ('EVEN', STR["enum_shelf_even"], STR["enum_shelf_even_desc"]),
            ('CUSTOM', STR["enum_shelf_custom"], STR["enum_shelf_custom_desc"]),
        ],
        default='EVEN'
    )
    shelves_count: IntProperty(name=STR["prop_shelves"], default=2, min=1, max=8)
    bay_count: IntProperty(name=STR["prop_bays"], default=3, min=2, max=8, update=lambda s, c: update_zone_bays(s, c))
    bays: CollectionProperty(type=ShelfBay)
    # UI-only: the per-compartment height list is collapsed by default.
    bays_expanded: BoolProperty(name=STR["prop_expanded"], default=False)

    rod_drop: FloatProperty(name=STR["prop_rod_drop"], default=0.08, min=0.04, max=0.35, unit='LENGTH', precision=3)


class CabinetColumn(PropertyGroup):
    is_expanded: BoolProperty(name=STR["prop_expanded"], default=True)
    zones: CollectionProperty(type=CabinetZone)
    zone_count: IntProperty(name=STR["prop_zones"], default=2, min=1, max=10,
                            update=lambda s, c: update_column_zones(s, c))


def update_column_zones(col, context):
    while len(col.zones) < col.zone_count:
        z = col.zones.add()
        z.height = 0.22
        if len(z.bays) == 0:
            update_zone_bays(z, context)
    while len(col.zones) > col.zone_count:
        col.zones.remove(len(col.zones) - 1)


def update_section_columns(sec, context):
    while len(sec.columns) < sec.column_count:
        col = sec.columns.add()
        if len(col.zones) == 0:
            z1 = col.zones.add()
            z1.zone_type = 'DRAWER'
            z1.height_mode = 'METERS'
            z1.height = 0.25
            update_zone_bays(z1, context)

            z2 = col.zones.add()
            z2.zone_type = 'DOOR'
            z2.height_mode = 'AUTO'
            update_zone_bays(z2, context)
            col.zone_count = 2
    while len(sec.columns) > sec.column_count:
        sec.columns.remove(len(sec.columns) - 1)


# See AGENT_NOTES.md [NOTE_16548]
def on_sec_type_update(sec, context):
    sec.is_corner = (sec.sec_type == SEC_CORNER)
    if sec.sec_type == SEC_CORNER and sec.is_island:
        sec.is_island = False
    if sec.sec_type == SEC_WARDROBE and len(sec.columns) == 0:
        update_section_columns(sec, context)


def on_is_island_update(sec, context):
    if sec.is_island and sec.sec_type == SEC_CORNER:
        sec.sec_type = SEC_NORMAL


class KitchenSection(PropertyGroup):
    # UI-only state: never written to presets, so a preset never carries the panel layout.
    is_expanded: BoolProperty(name=STR["prop_expanded"], default=True)
    zones_expanded: BoolProperty(name=STR["prop_expanded"], default=True)

    width: FloatProperty(name=STR["prop_width"], default=0.6, min=0.25, max=3.0, unit='LENGTH', precision=3)
    sec_type: EnumProperty(
        name=STR["prop_sec_type"],
        items=[
            (SEC_NORMAL, STR["enum_sec_normal"], STR["enum_sec_normal_desc"]),
            (SEC_WARDROBE, STR["enum_sec_wardrobe"], STR["enum_sec_wardrobe_desc"]),
            (SEC_CORNER, STR["enum_sec_corner"], STR["enum_sec_corner_desc"]),
            (SEC_APPLIANCE, STR["enum_sec_appliance"], STR["enum_sec_appliance_desc"]),
            (SEC_HOOD_GAP, STR["enum_sec_hood_gap"], STR["enum_sec_hood_gap_desc"]),
            (SEC_SINK, STR["enum_sec_sink"], STR["enum_sec_sink_desc"]),
        ],
        default=SEC_NORMAL,
        update=on_sec_type_update
    )
    corner_style: EnumProperty(
        name=STR["prop_corner_style"],
        items=[
            (CORN_DIAGONAL, STR["enum_corn_diag"], STR["enum_corn_diag_desc"]),
            (CORN_DOORS, STR["enum_corn_doors"], STR["enum_corn_doors_desc"]),
            (CORN_BLIND, STR["enum_corn_blind"], STR["enum_corn_blind_desc"]),
            (CORN_OPEN, STR["enum_corn_open"], STR["enum_corn_open_desc"]),
        ],
        default=CORN_DIAGONAL,
    )
    is_corner: BoolProperty(name=STR["prop_corner_sec"], default=False)
    is_island: BoolProperty(name=STR["prop_is_island"], default=False, update=on_is_island_update)
    has_upstand: BoolProperty(name=STR["prop_has_upstand"], default=True)

    override_height: BoolProperty(name=STR["prop_custom_height"], default=False)
    custom_height: FloatProperty(name=STR["prop_height"], default=2.20, min=0.15, max=3.5, unit='LENGTH', precision=3)
    override_depth: BoolProperty(name=STR["prop_custom_depth"], default=False)
    custom_depth: FloatProperty(name=STR["prop_depth"], default=0.58, min=0.15, max=1.2, unit='LENGTH', precision=3)

    column_count: IntProperty(name=STR["prop_columns"], default=2, min=1, max=4, update=update_section_columns)
    columns: CollectionProperty(type=CabinetColumn)

    has_bottom: BoolProperty(name=STR["prop_bottom_panel"], default=True)
    has_top: BoolProperty(name=STR["prop_top_panel"], default=True)
    # Off for open-niche furniture (a TV console): the niche is open at the back for
    # cables and equipment depth.
    has_back_panel: BoolProperty(name=STR["prop_has_back_panel"], default=True)
    shelf_rows: IntProperty(name=STR["prop_horiz_shelves"], default=0, min=0, max=8, update=update_section_tiers)
    tiers: CollectionProperty(type=ShelfTier)

    # Built-in carcass: the section gives up its own side walls and lets its shelves
    # run into the neighbours. Only ever meaningful between two other sections.
    no_side_walls: BoolProperty(name=STR["prop_no_side_walls"], default=False,
                                description=STR["prop_no_side_walls_tip"])
    shelves_span_walls: BoolProperty(name=STR["prop_shelves_span_walls"], default=False,
                                     description=STR["prop_shelves_span_walls_tip"])

    # Where a section shorter than its row sits inside the row band. AUTO keeps the
    # historical behaviour; the offset then works from the chosen edge in both rows.
    z_anchor: EnumProperty(
        name=STR["prop_z_anchor"],
        items=[
            ('AUTO', STR["enum_z_anchor_auto"], STR["enum_z_anchor_auto_desc"]),
            ('BOTTOM', STR["enum_z_anchor_bottom"], STR["enum_z_anchor_bottom_desc"]),
            ('TOP', STR["enum_z_anchor_top"], STR["enum_z_anchor_top_desc"]),
        ],
        default='AUTO',
    )
    z_offset: FloatProperty(name=STR["prop_z_offset"], default=0.0, min=-1.0, max=1.0,
                            soft_min=-0.2, soft_max=0.2, unit='LENGTH', precision=3,
                            description=STR["prop_z_offset_tip"])

    doors: IntProperty(name=STR["prop_doors"], default=1, min=0, max=2)
    handle_orient: EnumProperty(
        name=STR["prop_handle_orient"],
        items=[
            ('AUTO', STR["enum_horient_auto"], STR["enum_horient_auto_desc"]),
            ('HORIZ', STR["enum_horient_horiz"], STR["enum_horient_horiz_desc"]),
            ('VERT', STR["enum_horient_vert"], STR["enum_horient_vert_desc"]),
        ],
        default='AUTO',
    )
    override_handle_z: BoolProperty(name=STR["prop_custom_handle_h"], default=False)
    custom_handle_z: FloatProperty(name=STR["prop_offset"], default=0.0, min=-0.3, max=0.5, unit='LENGTH', precision=3)

    shelves: IntProperty(name=STR["prop_shelves"], default=2, min=0, max=4)
    has_mid_divider: BoolProperty(name=STR["prop_mid_divider"], default=False)
    shelf_thickness: FloatProperty(name=STR["prop_shelf_thickness"], default=0.018, min=0.012, max=0.03, unit='LENGTH',
                                   precision=3)
    drawer_count: IntProperty(name=STR["prop_drawer_count"], default=0, min=0, max=4)
    # The band is measured from the bottom edge of the body, so a tall drawer zone is only
    # limited by that body: the soft maximum keeps the slider in the range a base cabinet
    # normally uses, while a value typed above it still builds (generate_section clamps the
    # band to the body height and warns instead of letting the UI reject it).
    drawer_height: FloatProperty(name=STR["prop_drawer_h"], default=0.14, min=0.08, max=1.20,
                                 soft_max=0.72, unit='LENGTH', precision=3)

    sink_w: FloatProperty(name=STR["prop_sink_w"], default=0.50, min=0.20, max=1.5, unit='LENGTH', precision=3)
    sink_d: FloatProperty(name=STR["prop_sink_d"], default=0.40, min=0.20, max=1.0, unit='LENGTH', precision=3)
    sink_margin_f: FloatProperty(name=STR["prop_sink_margin_f"], default=0.07, min=0.02, max=0.3, unit='LENGTH',
                                 precision=3)
    sink_margin_b: FloatProperty(name=STR["prop_sink_margin_b"], default=0.07, min=0.02, max=0.3, unit='LENGTH',
                                 precision=3)
    sink_margin_l: FloatProperty(name=STR["prop_sink_margin_l"], default=0.00, min=0.00, max=0.5, unit='LENGTH',
                                 precision=3)
    sink_margin_r: FloatProperty(name=STR["prop_sink_margin_r"], default=0.00, min=0.00, max=0.5, unit='LENGTH',
                                  precision=3)
    # Defaults follow the pressed sink the user models against: a 150 mm deep bowl with a
    # 50 mm flat rim all round, so the recess keeps a real wall inside a 500x400 cutout.
    sink_recess_depth: FloatProperty(name=STR["prop_sink_recess_depth"], default=0.15, min=0.01, max=0.30,
                                      unit='LENGTH', precision=3)
    sink_recess_margin_f: FloatProperty(name=STR["prop_sink_recess_margin_f"], default=0.05, min=0.01, max=0.3,
                                         unit='LENGTH', precision=3)
    sink_recess_margin_b: FloatProperty(name=STR["prop_sink_recess_margin_b"], default=0.05, min=0.01, max=0.3,
                                         unit='LENGTH', precision=3)
    sink_recess_margin_l: FloatProperty(name=STR["prop_sink_recess_margin_l"], default=0.05, min=0.01, max=0.3,
                                         unit='LENGTH', precision=3)
    sink_recess_margin_r: FloatProperty(name=STR["prop_sink_recess_margin_r"], default=0.05, min=0.01, max=0.3,
                                         unit='LENGTH', precision=3)

    sink_bevel_floor_w: FloatProperty(name=STR["prop_sink_bevel_floor_w"], default=0.036, min=0.0, max=0.05,
                                      unit='LENGTH', precision=4)
    sink_bevel_vert_w: FloatProperty(name=STR["prop_sink_bevel_vert_w"], default=0.031, min=0.0, max=0.05,
                                     unit='LENGTH', precision=4)
    sink_bevel_top_w: FloatProperty(name=STR["prop_sink_bevel_top_w"], default=0.017, min=0.0, max=0.05,
                                    unit='LENGTH', precision=4)
    # One Bevel modifier covers the whole bowl, so segments and the miter type are shared
    # by the three edge groups; only the width differs per group, carried by edge weights.
    sink_bevel_segments: IntProperty(name=STR["prop_sink_bevel_segments"], default=8, min=1, max=16)
    sink_bevel_miter: EnumProperty(
        name=STR["prop_sink_bevel_miter"],
        items=[('SHARP', STR["enum_bevel_miter_sharp"], ""), ('ARC', STR["enum_bevel_miter_arc"], "")],
        default='ARC')

    # Stamped 2-step drain. Circle A is the flange opening, inscribed in the central floor
    # cell and not user-set; B and C are the two step rims, both radii user-set. See
    # AGENT_NOTES.md [NOTE_16580].
    sink_drain_on: BoolProperty(name=STR["prop_sink_drain_on"], default=True)
    sink_drain_d1: FloatProperty(name=STR["prop_sink_drain_d1"], default=0.012, min=0.005, max=0.04,
                                 unit='LENGTH', precision=3)
    sink_drain_d2: FloatProperty(name=STR["prop_sink_drain_d2"], default=0.024, min=0.005, max=0.04,
                                 unit='LENGTH', precision=3)
    sink_drain_dia1: FloatProperty(name=STR["prop_sink_drain_dia1"], default=0.050, min=0.03, max=0.30,
                                   unit='LENGTH', precision=3)
    sink_drain_dia2: FloatProperty(name=STR["prop_sink_drain_dia2"], default=0.032, min=0.02, max=0.30,
                                   unit='LENGTH', precision=3)
    sink_drain_bevel_top: FloatProperty(name=STR["prop_sink_drain_bevel_top"], default=0.004, min=0.0, max=0.02,
                                        unit='LENGTH', precision=4)
    sink_drain_bevel_mid: FloatProperty(name=STR["prop_sink_drain_bevel_mid"], default=0.001, min=0.0, max=0.02,
                                        unit='LENGTH', precision=4)
    sink_drain_bevel_low: FloatProperty(name=STR["prop_sink_drain_bevel_low"], default=0.002, min=0.0, max=0.02,
                                        unit='LENGTH', precision=4)
    # The drain gets its own Bevel modifier (fewer segments than the bowl, per the user).
    sink_drain_bevel_segments: IntProperty(name=STR["prop_sink_drain_bevel_segments"], default=3, min=1, max=16)

    # Debris strainer: a thin disc that sits in the second step, its radius 2 mm inside the
    # step-2 floor, perforated by two rings of rectangular slots. Height is relative to the
    # step-2 floor (0 = resting on it, positive = floating up toward the bowl floor).
    sink_strainer_on: BoolProperty(name=STR["prop_sink_strainer_on"], default=True)
    sink_strainer_thickness: FloatProperty(name=STR["prop_sink_strainer_thickness"], default=0.002,
                                           min=0.001, max=0.01, unit='LENGTH', precision=4)
    sink_strainer_gap: FloatProperty(name=STR["prop_sink_strainer_gap"], default=0.002,
                                     min=-0.02, max=0.02, unit='LENGTH', precision=4)

    override_mat: BoolProperty(name=STR["prop_override_mat"], default=False)
    custom_mat_facade: StringProperty(name=STR["prop_custom_facade"], default="")
    custom_mat_carcass: StringProperty(name=STR["prop_custom_carcass"], default="")


def update_lower_sections(self, context):
    while len(self.sections) < self.section_count:
        s = self.sections.add()
        if len(s.tiers) == 0:
            s.tiers.add()
        if len(s.columns) == 0:
            update_section_columns(s, context)
    while len(self.sections) > self.section_count:
        self.sections.remove(len(self.sections) - 1)


def update_upper_sections(self, context):
    while len(self.upper_sections) < self.upper_section_count:
        s = self.upper_sections.add()
        if len(s.tiers) == 0:
            s.tiers.add()
        if len(s.columns) == 0:
            update_section_columns(s, context)
    while len(self.upper_sections) > self.upper_section_count:
        self.upper_sections.remove(len(self.upper_sections) - 1)


# ============================================================
# [ANCHOR: DEFERRED_GRID_INIT]
# ============================================================
# Panel.draw() must not add/remove ID data: doing so during a UI redraw can crash
# Blender or leave stale undo steps. Panels only request the fix, a timer applies it
# on the next event loop iteration.
_GRID_FIX = {"scene": None, "registered": False}


def kitchen_collection_name(kitchen_id):
    """Name of the collection one generation writes into."""
    return f"{KITCHEN_COLL_PREFIX}{kitchen_id}"


def get_or_create_kitchen_collection(scene, kitchen_id):
    """The collection for this kitchen id, created and linked to the scene on demand.

    One collection per generation: the generator used to write into whichever
    collection was active in the outliner, so a second run landed inside the first
    one's collection and a single run could not be hidden or exported as a unit.
    """
    name = kitchen_collection_name(kitchen_id)
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        scene.collection.children.link(coll)
    return coll


def drop_empty_kitchen_collections(scene):
    """Remove collections this addon made that no longer hold anything.

    A collection is only dropped while it is empty, so nothing is ever deleted
    with objects still in it, and only names carrying the prefix are touched -
    the user's own collections are never candidates.
    """
    for coll in list(bpy.data.collections):
        if not coll.name.startswith(KITCHEN_COLL_PREFIX):
            continue
        if coll.objects or coll.children:
            continue
        try:
            bpy.data.collections.remove(coll)
        except (RuntimeError, ReferenceError):
            continue


def ensure_collections_ready(scene):
    """Rebuild the whole furniture config: sections first, then their nested grids.

    The top level comes first: update callbacks do not fire for property defaults on
    registration, so a fresh scene holds section_count=2 with an EMPTY sections
    collection - and everything downstream (generate, the panels) sees no sections at
    all. Syncing both rows the same way the UI spinners do is the primary
    initialization; without it a first Generate press built only the root empty.
    """
    props = getattr(scene, "kitchen_props", None)
    if props is None:
        return
    context = bpy.context
    if len(props.sections) != props.section_count:
        update_lower_sections(props, context)
    if len(props.upper_sections) != props.upper_section_count:
        update_upper_sections(props, context)
    for sec in list(props.sections) + list(props.upper_sections):
        if len(sec.tiers) != sec.shelf_rows + 1:
            update_section_tiers(sec, context)
        if len(sec.columns) == 0:
            update_section_columns(sec, context)
        for col in sec.columns:
            if len(col.zones) == 0:
                update_column_zones(col, context)
            for zone in col.zones:
                if len(zone.bays) != zone.bay_count:
                    update_zone_bays(zone, context)


def _grid_fix_job():
    _GRID_FIX["registered"] = False
    scene = _GRID_FIX["scene"]
    _GRID_FIX["scene"] = None
    if scene is not None:
        try:
            ensure_collections_ready(scene)
            for win in bpy.context.window_manager.windows:
                for area in win.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
        except ReferenceError:
            pass
    return None


def request_collections_ready(scene):
    """Schedule ensure_collections_ready() outside of the current draw pass."""
    _GRID_FIX["scene"] = scene
    if _GRID_FIX["registered"]:
        return
    _GRID_FIX["registered"] = True
    bpy.app.timers.register(_grid_fix_job, first_interval=0.05)


def unregister_grid_fix_timer():
    if bpy.app.timers.is_registered(_grid_fix_job):
        bpy.app.timers.unregister(_grid_fix_job)


class KitchenGeneratorProps(PropertyGroup):
    preset_name_input: StringProperty(name=STR["prop_preset_name"], default="Island_Modern_01")
    preset_enum: EnumProperty(name=STR["prop_preset_enum"], items=get_preset_enum_items)

    kitchen_id: StringProperty(name=STR["prop_kitchen_id"], default="K01")
    wall_thickness: FloatProperty(name=STR["prop_wall_thickness"], default=0.018, min=0.012, max=0.025, unit='LENGTH',
                                  precision=3)
    gap: FloatProperty(name=STR["prop_gap"], default=0.0025, min=0.001, max=0.008, unit='LENGTH', precision=4)

    use_bevel: BoolProperty(name=STR["prop_enable_bevel"], default=True)
    bevel_width: FloatProperty(name=STR["prop_bevel_width"], default=0.002, min=0.0005, max=0.020, unit='LENGTH',
                               precision=4)
    bevel_segments: IntProperty(name=STR["prop_bevel_segments"], default=2, min=2, max=4)
    gen_collisions: BoolProperty(name=STR["prop_gen_collisions"], default=False)

    section_count: IntProperty(name=STR["prop_sections"], default=2, min=1, max=12, update=update_lower_sections)
    depth: FloatProperty(name=STR["prop_depth"], default=0.60, min=0.30, max=1.2, unit='LENGTH', precision=3)
    height: FloatProperty(name=STR["prop_carcass_height"], default=0.72, min=0.2, max=3.5, unit='LENGTH', precision=3)
    plinth_height: FloatProperty(name=STR["prop_plinth_height"], default=0.10, min=0.0, max=0.2, unit='LENGTH',
                                 precision=3)
    plinth_recess: FloatProperty(name=STR["prop_plinth_recess"], default=0.02, min=0.0, max=0.08, unit='LENGTH',
                                 precision=3)
    # Legs replace the plinth for freestanding low furniture (bedside dresser): the body
    # sits at z=leg_height, same arithmetic as with a plinth, but four legs carry it.
    use_legs: BoolProperty(name=STR["prop_use_legs"], default=False)
    leg_height: FloatProperty(name=STR["prop_leg_height"], default=0.12, min=0.02, max=0.35, unit='LENGTH',
                              precision=3)
    sections: CollectionProperty(type=KitchenSection)

    # Countertop & 4-sided Overhangs
    countertop_thickness: FloatProperty(name=STR["prop_countertop_thickness"], default=0.038, min=0.01, max=0.1,
                                        unit='LENGTH', precision=3)
    countertop_overhang_front: FloatProperty(name=STR["prop_countertop_over_front"], default=0.025, min=0.0, max=0.06,
                                             unit='LENGTH', precision=3)
    countertop_overhang_back: FloatProperty(name=STR["prop_countertop_over_back"], default=0.250, min=0.0, max=0.80,
                                            unit='LENGTH', precision=3)
    countertop_overhang_side: FloatProperty(name=STR["prop_countertop_over_side"], default=0.020, min=0.0, max=0.10,
                                            unit='LENGTH', precision=3)
    island_corner_radius: FloatProperty(name=STR["prop_island_corner_radius"], default=0.040, min=0.005, max=0.200,
                                        unit='LENGTH', precision=3)

    # Upstand / Rim
    has_upstand: BoolProperty(name=STR["prop_has_upstand"], default=True)
    upstand_height: FloatProperty(name=STR["prop_upstand_height"], default=0.035, min=0.015, max=0.150, unit='LENGTH',
                                  precision=3)
    upstand_thickness: FloatProperty(name=STR["prop_upstand_thickness"], default=0.015, min=0.008, max=0.040,
                                     unit='LENGTH', precision=3)

    gen_upper: BoolProperty(name=STR["prop_gen_upper"], default=False)
    sync_upper_with_lower: BoolProperty(name=STR["prop_sync_upper"], default=True)
    upper_section_count: IntProperty(name=STR["prop_upper_sections"], default=1, min=1, max=12,
                                     update=update_upper_sections)
    upper_depth: FloatProperty(name=STR["prop_depth"], default=0.35, min=0.20, max=0.50, unit='LENGTH', precision=3)
    upper_height: FloatProperty(name=STR["prop_height"], default=0.72, min=0.40, max=1.20, unit='LENGTH', precision=3)
    backsplash_height: FloatProperty(name=STR["prop_backsplash_gap"], default=0.60, min=0.40, max=0.85, unit='LENGTH',
                                     precision=3)
    upper_handle_z_offset: FloatProperty(name=STR["prop_upper_handle_z"], default=0.0, min=-0.3, max=0.3, unit='LENGTH',
                                         precision=3)
    upper_sections: CollectionProperty(type=KitchenSection)

    handle_vertical: BoolProperty(name=STR["prop_vert_handles"], default=True)
    handle_length: FloatProperty(name=STR["prop_handle_length"], default=0.160, min=0.03, max=0.60, unit='LENGTH',
                                 precision=3)
    handle_bar_overhang: FloatProperty(name=STR["prop_handle_bar_overhang"], default=0.01, min=0.0, max=0.03,
                                       unit='LENGTH', precision=3)
    handle_bar_radius: FloatProperty(name=STR["prop_handle_bar_radius"], default=0.007, min=0.003, max=0.015,
                                     unit='LENGTH', precision=4)
    handle_mount_length: FloatProperty(name=STR["prop_handle_mount_len"], default=0.018, min=0.008, max=0.05,
                                       unit='LENGTH', precision=3)
    handle_side_margin: FloatProperty(name=STR["prop_handle_side_margin"], default=0.045, min=0.01, max=0.15,
                                      unit='LENGTH', precision=3)
    lower_handle_top_margin: FloatProperty(name=STR["prop_lower_handle_top_margin"], default=0.050, min=0.01, max=1.25,
                                           unit='LENGTH', precision=3)
    upper_handle_bottom_margin: FloatProperty(name=STR["prop_upper_handle_bottom_margin"], default=0.080, min=0.01,
                                              max=1.25, unit='LENGTH', precision=3)
    handle_z_offset: FloatProperty(name=STR["prop_handle_z_fine"], default=0.0, min=-0.2, max=1.5, unit='LENGTH',
                                   precision=3)
    drawer_handle_scale: FloatProperty(name=STR["prop_drawer_handle_scale"], default=0.8, min=0.3, max=1.2)

    # UI-only: keeps the six material slots short unless tiling is being tuned.
    ui_show_uv_details: BoolProperty(name=STR["ui_show_uv_details"], default=False,
                                     description=STR["ui_show_uv_details_desc"])

    # UI-only: debug panel state. Neither name appears in serialize_kitchen, so a preset
    # can never carry a debug scenario or the last-built label.
    debug_auto_generate: BoolProperty(name=STR["ui_debug_auto"], description=STR["ui_debug_auto_desc"],
                                      default=True)
    debug_last_scene: StringProperty(name=STR["op_debug_scene_label"], default="")

    # UI-only (T-41): a working-mode preference, not geometry. Deliberately absent from
    # serialize_kitchen - opening a preset must not decide whether the user's Blender
    # auto-rebuilds, and a preset saved with the switch on must not switch it on elsewhere.
    live_preview: BoolProperty(name=STR["prop_live_preview"], description=STR["prop_live_preview_desc"],
                               default=False)

    # Bake-for-export options (see bake.py). UI-only, never serialized into
    # presets: a preset must not pin an export prefix.
    bake_name: StringProperty(name=STR["prop_bake_name"], default="EXP")
    bake_split_upper: BoolProperty(name=STR["prop_bake_split_upper"], default=True)
    # What stays visible after the bake: the result and the model it came from
    # occupy the same place, so either can bury the other. Each collection hides
    # only on its own checkbox; the outliner eye brings it back.
    bake_hide_bake: BoolProperty(name=STR["prop_hide_bake_after_bake"], default=True)
    bake_hide_generated: BoolProperty(name=STR["prop_hide_generated_after_bake"], default=False)

    mat_facade_lower: StringProperty(name=STR["prop_mat_facade_lower"], default="MI_WoodDark_01")
    uv_facade_lower_u: FloatProperty(name=STR["prop_tile_u"], default=1.0, min=0.01, max=50.0)
    uv_facade_lower_v: FloatProperty(name=STR["prop_tile_v"], default=1.0, min=0.01, max=50.0)
    rot_facade_lower: BoolProperty(name=STR["prop_rotate_90"], default=False)

    mat_facade_upper: StringProperty(name=STR["prop_mat_facade_upper"], default="MI_WoodLight_01")
    uv_facade_upper_u: FloatProperty(name=STR["prop_tile_u"], default=1.0, min=0.01, max=50.0)
    uv_facade_upper_v: FloatProperty(name=STR["prop_tile_v"], default=1.0, min=0.01, max=50.0)
    rot_facade_upper: BoolProperty(name=STR["prop_rotate_90"], default=False)

    mat_carcass: StringProperty(name=STR["prop_mat_carcass"], default="MI_WoodLight_01")
    uv_carcass_u: FloatProperty(name=STR["prop_tile_u"], default=1.0, min=0.01, max=50.0)
    uv_carcass_v: FloatProperty(name=STR["prop_tile_v"], default=1.0, min=0.01, max=50.0)
    rot_carcass: BoolProperty(name=STR["prop_rotate_90"], default=False)

    mat_countertop: StringProperty(name=STR["prop_mat_countertop"], default="MI_StoneWhite_01")
    uv_countertop_u: FloatProperty(name=STR["prop_tile_u"], default=1.0, min=0.01, max=50.0)
    uv_countertop_v: FloatProperty(name=STR["prop_tile_v"], default=1.0, min=0.01, max=50.0)
    rot_countertop: BoolProperty(name=STR["prop_rotate_90"], default=False)

    mat_plinth: StringProperty(name=STR["prop_mat_plinth"], default="MI_WoodDark_01")
    uv_plinth_u: FloatProperty(name=STR["prop_tile_u"], default=1.0, min=0.01, max=50.0)
    uv_plinth_v: FloatProperty(name=STR["prop_tile_v"], default=1.0, min=0.01, max=50.0)
    rot_plinth: BoolProperty(name=STR["prop_rotate_90"], default=False)

    mat_handle: StringProperty(name=STR["prop_mat_handle"], default="MI_MetalBrownPainted_01")
    uv_handle_u: FloatProperty(name=STR["prop_tile_u"], default=1.0, min=0.01, max=50.0)
    uv_handle_v: FloatProperty(name=STR["prop_tile_v"], default=1.0, min=0.01, max=50.0)
    rot_handle: BoolProperty(name=STR["prop_rotate_90"], default=False)


# ============================================================
