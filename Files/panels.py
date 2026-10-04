"""panels - The UI panels.

Moved verbatim from the single-module addon; no body was edited during the move.
"""
import os
import re

from bpy.types import PropertyGroup, Operator, Panel
from .core import (
    SEC_APPLIANCE,
    SEC_CORNER,
    SEC_HOOD_GAP,
    SEC_NORMAL,
    SEC_SINK,
    SEC_WARDROBE,
)
from .debug_scenes import DEBUG_GROUPS, DEBUG_SCENES
from .operators import request_live_rebuild
from .properties import request_collections_ready
from .strings import STR

# [ANCHOR: UI_PANELS]
# ============================================================
_ADDON_VERSION = None


def addon_version():
    """Version string from blender_manifest.toml, read once and cached.

    The extension format keeps the version only in the manifest, so that is where the
    label reads it. The panel shows it because Blender installs an extension by copying
    it into its own addons folder, and a stale copy keeps generating old geometry after
    the project moves on - the label exposes that without digging (see AGENT_NOTES.md).
    """
    global _ADDON_VERSION
    if _ADDON_VERSION is None:
        path = os.path.join(os.path.dirname(__file__), "blender_manifest.toml")
        try:
            with open(path, encoding="utf-8") as handle:
                match = re.search(r'^version\s*=\s*"([^"]+)"', handle.read(), re.MULTILINE)
            _ADDON_VERSION = match.group(1) if match else "unknown"
        except OSError:
            _ADDON_VERSION = "unknown"
    return _ADDON_VERSION


def section_summary(sec):
    """One-line text for a collapsed section header, so a closed list stays readable."""
    try:
        type_label = sec.bl_rna.properties["sec_type"].enum_items[sec.sec_type].label
    except Exception:
        type_label = str(sec.sec_type)
    # Corner planar extents are derived from neighbour depths, so no fixed width in the summary.
    if sec.sec_type == SEC_CORNER:
        bits = [type_label]
    else:
        bits = [f"{sec.width * 1000:.0f} mm", type_label]
    if sec.override_depth and sec.sec_type != SEC_CORNER:
        bits.append(f"D {sec.custom_depth * 1000:.0f} mm")
    if sec.override_height:
        bits.append(f"H {sec.custom_height * 1000:.0f} mm")
    if getattr(sec, "is_island", False):
        bits.append("Island")
    return "  ·  ".join(bits)


def draw_section_vertical_anchor(box, sec):
    """Where a section shorter than its row is placed, and by how much it is shifted.

    Only drawn together with Custom Height: without a height difference the anchor has
    nothing to choose between, and the offset alone is enough to hang a full-height
    section on the wall.
    """
    if not sec.override_height:
        return
    row = box.row(align=True)
    row.prop(sec, "z_anchor", text=STR["prop_z_anchor"])
    row.prop(sec, "z_offset", text=STR["prop_z_offset"])


def draw_section_header(box, sec, title, icon='OBJECT_DATA'):
    """Collapsible header row for one section. Returns True when the block should draw its body."""
    hdr = box.row(align=True)
    arrow = 'DOWNARROW_HLT' if sec.is_expanded else 'RIGHTARROW'
    hdr.prop(sec, "is_expanded", text="", icon=arrow, emboss=False)
    if sec.is_expanded:
        hdr.label(text=title, icon=icon)
    else:
        hdr.label(text=f"{title}: {section_summary(sec)}", icon=icon)
    return sec.is_expanded


def draw_list_tools(layout, count, upper=False):
    """Expand/Collapse-all row above a section list; useless with a single section."""
    if count < 2:
        return
    row = layout.row(align=True)
    op_open = row.operator("kitchen.set_sections_expanded", text=STR["ui_expand_all"], icon='TRIA_DOWN')
    op_open.expanded = True
    op_open.upper = upper
    op_close = row.operator("kitchen.set_sections_expanded", text=STR["ui_collapse_all"], icon='TRIA_RIGHT')
    op_close.expanded = False
    op_close.upper = upper


class KITCHEN_PT_MainPanel(Panel):
    bl_label = STR["panel_main_title"]
    bl_idname = "KITCHEN_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = STR["panel_category"]

    def draw(self, context):
        layout = self.layout
        props = context.scene.kitchen_props

        # Fresh scene: the count defaults do not fire their update callbacks, so the
        # sections collections start empty and every section panel below draws dead.
        # Request the deferred sync (same timer mechanism the nested grids use) - the
        # panel must not add ID data itself during a redraw.
        if (len(props.sections) != props.section_count
                or len(props.upper_sections) != props.upper_section_count):
            request_collections_ready(context.scene)

        box_p = layout.box()
        box_p.label(text=STR["ui_presets_manager"], icon='PRESET')
        row_sel = box_p.row(align=True)
        row_sel.prop(props, "preset_enum", text="")
        row_sel.operator("kitchen.load_preset", icon='IMPORT', text=STR["ui_load"])
        row_sel.operator("kitchen.delete_preset", icon='TRASH', text="")
        row_save = box_p.row(align=True)
        row_save.prop(props, "preset_name_input", text="")
        row_save.operator("kitchen.save_preset", icon='EXPORT', text=STR["ui_save"])

        layout.separator()
        layout.prop(props, "kitchen_id")
        layout.operator("kitchen.generate_kitchen", icon='MOD_BUILD', text=STR["ui_generate_btn"])

        # Which copy is running matters: Blender installs an extension by copying it into
        # its own addons folder, so a stale copy keeps generating old geometry after the
        # project moves on. The label exposes it without digging through the addon list.
        layout.label(text=STR["ui_version"].format(v=addon_version()))

        # Live preview (T-41). This is the change notification: every panel of the sidebar
        # region redraws when a property inside it changes, and the root panel is drawn on
        # every one of those redraws, so comparing the build signature here catches edits
        # made in panels below. Called unconditionally: the off-branch is what forgets the
        # seed, so that switching the feature back on does not rebuild an unchanged scene.
        request_live_rebuild(context.scene)


class KITCHEN_PT_BevelPanel(Panel):
    bl_label = STR["panel_bevel_title"]
    bl_parent_id = "KITCHEN_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = STR["panel_category"]

    def draw(self, context):
        layout = self.layout
        props = context.scene.kitchen_props
        layout.prop(props, "use_bevel")
        if props.use_bevel:
            col = layout.column(align=True)
            col.prop(props, "bevel_width")
            col.prop(props, "bevel_segments")


class KITCHEN_PT_BakePanel(Panel):
    bl_label = STR["panel_bake_title"]
    bl_parent_id = "KITCHEN_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = STR["panel_category"]
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.kitchen_props
        col = layout.column(align=True)
        col.prop(props, "bake_name")
        col.prop(props, "bake_split_upper")
        col.operator("kitchen.bake_export", icon='EXPORT', text=STR["ui_bake_btn"])
        # Directly under Bake: both finish the same BAKE collection, they only
        # differ in what leaves the machine. The icon is EXPORT rather than the
        # spec's `opengl_trace` - that name is not among the 1033 icons the
        # UILayout enum offers.
        col.operator("kitchen.export_fbx", icon='EXPORT', text=STR["ui_export_fbx_btn"])


class KITCHEN_PT_GeneralPanel(Panel):
    bl_label = STR["panel_general_title"]
    bl_parent_id = "KITCHEN_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = STR["panel_category"]
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.kitchen_props
        col = layout.column(align=True)
        col.prop(props, "wall_thickness")
        col.prop(props, "gap")
        col.separator()
        col.prop(props, "gen_collisions")
        # The note is drawn whether the switch is on or off: its whole point is to be read
        # before the box is ticked, so a first-time user does not turn colliders on and then
        # wonder why every rebuild got 2-3x slower (measured: 514 -> 1223 ms on the L-kitchen).
        # Colliders are only consumed by Bake, so the switch is meant to live on for the
        # export, not for the editing session.
        layout.label(text=STR["ui_gen_collisions_note"], icon='INFO')
        col.prop(props, "live_preview")
        if props.live_preview:
            layout.label(text=STR["ui_live_note"], icon='INFO')


class KITCHEN_PT_LowerGlobal(Panel):
    bl_label = STR["panel_carcass_title"]
    bl_parent_id = "KITCHEN_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = STR["panel_category"]

    def draw(self, context):
        layout = self.layout
        props = context.scene.kitchen_props
        col = layout.column(align=True)
        col.prop(props, "section_count")
        col.prop(props, "depth")
        col.prop(props, "height")
        # Legs and plinth are mutually exclusive supports: legs lift the body to
        # leg_height, so a plinth height set alongside would describe geometry that
        # is never built. Show the one that is active.
        col.prop(props, "use_legs")
        if props.use_legs:
            col.prop(props, "leg_height")
        else:
            col.prop(props, "plinth_height")
            col.prop(props, "plinth_recess")


class KITCHEN_PT_LowerSections(Panel):
    bl_label = STR["panel_sections_title"]
    bl_parent_id = "KITCHEN_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = STR["panel_category"]
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.kitchen_props
        draw_list_tools(layout, len(props.sections))
        for i, sec in enumerate(props.sections):
            box = layout.box()
            if not draw_section_header(box, sec, STR["ui_section_prefix"].format(num=i + 1)):
                continue
            # Corner planar extents come from neighbour depths - no user width/depth.
            # See AGENT_NOTES.md [NOTE_16550].
            if sec.sec_type != SEC_CORNER:
                box.prop(sec, "width")
            box.prop(sec, "sec_type")

            row_flags = box.row(align=True)
            row_flags.prop(sec, "is_island")
            if not sec.is_island:
                row_flags.prop(sec, "has_upstand")

            row_d = box.row(align=True)
            if sec.sec_type != SEC_CORNER:
                row_d.prop(sec, "override_depth")
                if sec.override_depth:
                    row_d.prop(sec, "custom_depth")

            row_h = box.row(align=True)
            row_h.prop(sec, "override_height")
            if sec.override_height:
                row_h.prop(sec, "custom_height")
            draw_section_vertical_anchor(box, sec)

            st = sec.sec_type

            if st == SEC_WARDROBE:
                if len(sec.columns) == 0:
                    request_collections_ready(context.scene)

                w_box = box.box()
                w_hdr = w_box.row(align=True)
                w_arrow = 'DOWNARROW_HLT' if sec.zones_expanded else 'RIGHTARROW'
                w_hdr.prop(sec, "zones_expanded", text="", icon=w_arrow, emboss=False)
                w_hdr.label(text=STR["ui_col_vertical_zones"], icon='ALIGN_JUSTIFY')
                row_c = w_box.row(align=True)
                row_c.prop(sec, "column_count")
                if sec.column_count > 1:
                    op = row_c.operator("kitchen.copy_col1_to_all", text=STR["ui_copy_col1_all"], icon='DUPLICATE')
                    op.sec_index = i

                # Column count stays editable while the grid itself is folded away.
                for c_idx, col in enumerate(sec.columns if sec.zones_expanded else []):
                    if len(col.zones) == 0:
                        request_collections_ready(context.scene)

                    col_box = w_box.box()
                    row_col_hdr = col_box.row(align=True)
                    icon_col = 'DOWNARROW_HLT' if col.is_expanded else 'RIGHTARROW'
                    row_col_hdr.prop(col, "is_expanded", text="", icon=icon_col, emboss=False)
                    row_col_hdr.label(text=STR["ui_column_prefix"].format(num=c_idx + 1), icon='SNAP_GRID')
                    row_col_hdr.prop(col, "zone_count")

                    if col.is_expanded:
                        for z_idx in reversed(range(len(col.zones))):
                            zone = col.zones[z_idx]
                            z_sub = col_box.box()

                            z_hdr = z_sub.row(align=True)
                            icon_z = 'DOWNARROW_HLT' if zone.is_expanded else 'RIGHTARROW'
                            z_hdr.prop(zone, "is_expanded", text="", icon=icon_z, emboss=False)
                            z_hdr.prop(zone, "zone_type", text="")
                            z_hdr.prop(zone, "height_mode", text="")
                            if zone.height_mode == 'METERS':
                                z_hdr.prop(zone, "height", text="")
                            elif zone.height_mode == 'PERCENT':
                                z_hdr.prop(zone, "height_pct", text="")

                            if zone.is_expanded:
                                if zone.zone_type == 'DOOR':
                                    d_row = z_sub.row(align=True)
                                    d_row.prop(zone, "door_swing", text=STR["ui_hinge"])
                                    d_row.prop(zone, "interior_type", text=STR["ui_inside"])

                                    h_row = z_sub.row(align=True)
                                    h_row.prop(zone, "handle_pos", text=STR["ui_handle"])
                                    if zone.handle_pos == 'CENTER':
                                        h_row.prop(zone, "handle_z_offset", text=STR["ui_shift"])
                                    else:
                                        h_row.prop(zone, "handle_z_offset", text=STR["ui_edge_dist"])

                                    len_row = z_sub.row(align=True)
                                    len_row.prop(zone, "handle_len_mode", text=STR["ui_length"])
                                    if zone.handle_len_mode == 'PERCENT':
                                        len_row.prop(zone, "handle_pct", text="%")
                                    elif zone.handle_len_mode == 'EXPLICIT':
                                        len_row.prop(zone, "handle_custom_len", text=STR["ui_size"])

                                elif zone.zone_type == 'OPEN':
                                    o_row = z_sub.row(align=True)
                                    o_row.prop(zone, "interior_type", text=STR["ui_inside"])

                                if zone.zone_type in ('DOOR', 'OPEN'):
                                    if zone.interior_type == 'SHELVES':
                                        sh_row = z_sub.row(align=True)
                                        sh_row.prop(zone, "shelf_mode", text=STR["ui_step"])
                                        if zone.shelf_mode == 'EVEN':
                                            sh_row.prop(zone, "shelves_count")
                                        else:
                                            sh_row.prop(zone, "bay_count")
                                            if len(zone.bays) != zone.bay_count:
                                                request_collections_ready(context.scene)
                                            bay_box = z_sub.box()
                                            b_hdr = bay_box.row(align=True)
                                            b_arrow = 'DOWNARROW_HLT' if zone.bays_expanded else 'RIGHTARROW'
                                            b_hdr.prop(zone, "bays_expanded", text="", icon=b_arrow, emboss=False)
                                            b_hdr.label(text=STR["ui_compartment_heights"], icon='LINENUMBERS_ON')
                                            for b_idx in reversed(range(len(zone.bays) if zone.bays_expanded else 0)):
                                                bay = zone.bays[b_idx]
                                                b_row = bay_box.row(align=True)
                                                b_row.label(text=STR["ui_bay_prefix"].format(num=b_idx + 1))
                                                b_row.prop(bay, "height_mode", text="")
                                                if bay.height_mode == 'METERS':
                                                    b_row.prop(bay, "height", text="")
                                                elif bay.height_mode == 'PERCENT':
                                                    b_row.prop(bay, "height_pct", text="")
                                    elif zone.interior_type == 'ROD':
                                        z_sub.prop(zone, "rod_drop")

            elif st == SEC_NORMAL:
                col_ui = box.column(align=True)
                row = col_ui.row(align=True)
                row.prop(sec, "doors")
                row.prop(sec, "shelves")
                col_ui.prop(sec, "has_mid_divider")
                col_ui.prop(sec, "drawer_count")
                col_ui.prop(sec, "drawer_height")
                col_ui.prop(sec, "has_back_panel")
            elif st == SEC_CORNER:
                # See AGENT_NOTES.md [NOTE_16552]: corner_style is upper-row-only.
                box.prop(sec, "shelves")
            elif st == SEC_APPLIANCE:
                row = box.row(align=True)
                row.prop(sec, "has_bottom")
                row.prop(sec, "has_top")
                box.prop(sec, "shelf_rows")
                row_bi = box.row(align=True)
                row_bi.prop(sec, "no_side_walls")
                row_bi.prop(sec, "shelves_span_walls")
                for k, tier in enumerate(sec.tiers):
                    box.prop(tier, "dividers", text=STR["ui_tier_dividers"].format(num=k + 1))
            elif st == SEC_SINK:
                col_ui = box.column(align=True)
                col_ui.prop(sec, "doors")
                # The carcass honours has_back_panel for every section type, so the sink
                # module gets the same switch a Normal section shows - a sink run often
                # carries a boiler niche or siphon access that has to stay open behind.
                col_ui.prop(sec, "has_back_panel")
                row_dim = col_ui.row(align=True)
                row_dim.prop(sec, "sink_w")
                row_dim.prop(sec, "sink_d")
                row_mf = col_ui.row(align=True)
                row_mf.prop(sec, "sink_margin_f")
                row_mf.prop(sec, "sink_margin_l")
                row_mb = col_ui.row(align=True)
                row_mb.prop(sec, "sink_margin_b")
                row_mb.prop(sec, "sink_margin_r")
                col_ui.separator()
                col_ui.prop(sec, "sink_recess_depth")
                row_r1 = col_ui.row(align=True)
                row_r1.prop(sec, "sink_recess_margin_f")
                row_r1.prop(sec, "sink_recess_margin_l")
                row_r2 = col_ui.row(align=True)
                row_r2.prop(sec, "sink_recess_margin_b")
                row_r2.prop(sec, "sink_recess_margin_r")
                col_ui.separator()
                row_bf = col_ui.row(align=True)
                row_bf.prop(sec, "sink_bevel_floor_w")
                row_bv = col_ui.row(align=True)
                row_bv.prop(sec, "sink_bevel_vert_w")
                row_bt = col_ui.row(align=True)
                row_bt.prop(sec, "sink_bevel_top_w")
                row_bm = col_ui.row(align=True)
                row_bm.prop(sec, "sink_bevel_segments")
                row_bm.prop(sec, "sink_bevel_miter", text="")
                col_ui.separator()
                col_ui.prop(sec, "sink_drain_on")
                if sec.sink_drain_on:
                    row_d1 = col_ui.row(align=True)
                    row_d1.prop(sec, "sink_drain_d1")
                    row_d1.prop(sec, "sink_drain_d2")
                    row_d2 = col_ui.row(align=True)
                    row_d2.prop(sec, "sink_drain_dia1")
                    row_d2.prop(sec, "sink_drain_dia2")
                    row_db = col_ui.row(align=True)
                    row_db.prop(sec, "sink_drain_bevel_top")
                    row_db.prop(sec, "sink_drain_bevel_mid")
                    row_db2 = col_ui.row(align=True)
                    row_db2.prop(sec, "sink_drain_bevel_low")
                    row_db2.prop(sec, "sink_drain_bevel_segments")
                    col_ui.separator()
                    col_ui.prop(sec, "sink_strainer_on")
                    if sec.sink_strainer_on:
                        row_st = col_ui.row(align=True)
                        row_st.prop(sec, "sink_strainer_thickness")
                        row_st.prop(sec, "sink_strainer_gap")

            box.prop(sec, "override_mat")
            if sec.override_mat:
                col_m = box.column(align=True)
                col_m.prop(sec, "custom_mat_facade", text=STR["ui_facade_mat"])
                col_m.prop(sec, "custom_mat_carcass", text=STR["ui_carcass_mat"])


class KITCHEN_PT_UpperGlobal(Panel):
    bl_label = STR["panel_upper_global_title"]
    bl_parent_id = "KITCHEN_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = STR["panel_category"]
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.kitchen_props
        layout.prop(props, "gen_upper")
        if props.gen_upper:
            col = layout.column(align=True)
            col.prop(props, "upper_depth")
            col.prop(props, "upper_height")
            col.prop(props, "backsplash_height")
            layout.prop(props, "sync_upper_with_lower")
            if not props.sync_upper_with_lower:
                layout.prop(props, "upper_section_count")
                layout.operator("kitchen.copy_lower_to_upper", icon='DUPLICATE')


class KITCHEN_PT_UpperSections(Panel):
    bl_label = STR["panel_upper_sections_title"]
    bl_parent_id = "KITCHEN_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = STR["panel_category"]
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        props = context.scene.kitchen_props
        return props.gen_upper and (not props.sync_upper_with_lower)

    def draw(self, context):
        layout = self.layout
        props = context.scene.kitchen_props
        draw_list_tools(layout, len(props.upper_sections), upper=True)
        for i, sec in enumerate(props.upper_sections):
            box = layout.box()
            if not draw_section_header(box, sec, STR["ui_upper_section_prefix"].format(num=i + 1), icon='MESH_PLANE'):
                continue
            # Corner planar extents come from neighbour depths - no user width/depth.
            # See AGENT_NOTES.md [NOTE_16550].
            if sec.sec_type != SEC_CORNER:
                box.prop(sec, "width")
            box.prop(sec, "sec_type")

            row_h = box.row(align=True)
            row_h.prop(sec, "override_height")
            if sec.override_height:
                row_h.prop(sec, "custom_height")
            draw_section_vertical_anchor(box, sec)

            row_d = box.row(align=True)
            if sec.sec_type != SEC_CORNER:
                row_d.prop(sec, "override_depth")
                if sec.override_depth:
                    row_d.prop(sec, "custom_depth")

            st = sec.sec_type
            if st == SEC_NORMAL:
                col = box.column(align=True)
                row = col.row(align=True)
                row.prop(sec, "doors")
                row.prop(sec, "shelves")
                col.prop(sec, "handle_orient")
                row_hz = col.row(align=True)
                row_hz.prop(sec, "override_handle_z")
                if sec.override_handle_z:
                    row_hz.prop(sec, "custom_handle_z")
                col.prop(sec, "has_mid_divider")
                col.prop(sec, "has_back_panel")
            elif st == SEC_APPLIANCE:
                row = box.row(align=True)
                row.prop(sec, "has_bottom")
                row.prop(sec, "has_top")
                box.prop(sec, "shelf_rows")
                row_bi = box.row(align=True)
                row_bi.prop(sec, "no_side_walls")
                row_bi.prop(sec, "shelves_span_walls")
                for k, tier in enumerate(sec.tiers):
                    box.prop(tier, "dividers", text=STR["ui_tier_dividers"].format(num=k + 1))
            elif st == SEC_CORNER:
                box.prop(sec, "corner_style")
                box.prop(sec, "shelves")
            elif st == SEC_HOOD_GAP:
                box.label(text=STR["ui_hood_gap_label"])

            box.prop(sec, "override_mat")
            if sec.override_mat:
                col_m = box.column(align=True)
                col_m.prop(sec, "custom_mat_facade", text=STR["ui_facade_mat"])
                col_m.prop(sec, "custom_mat_carcass", text=STR["ui_carcass_mat"])


class KITCHEN_PT_Countertop(Panel):
    bl_label = STR["panel_countertop_title"]
    bl_parent_id = "KITCHEN_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = STR["panel_category"]
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.kitchen_props

        box_ct = layout.box()
        box_ct.label(text="Countertop Dimensions & Overhangs", icon='SNAP_FACE')
        col = box_ct.column(align=True)
        col.prop(props, "countertop_thickness")
        col.prop(props, "countertop_overhang_front")
        col.prop(props, "countertop_overhang_back")
        col.prop(props, "countertop_overhang_side")
        col.prop(props, "island_corner_radius")

        box_up = layout.box()
        box_up.label(text="Wall Upstand (Rim)", icon='SNAP_EDGE')
        box_up.prop(props, "has_upstand")
        if props.has_upstand:
            col_up = box_up.column(align=True)
            col_up.prop(props, "upstand_height")
            col_up.prop(props, "upstand_thickness")


class KITCHEN_PT_Handles(Panel):
    bl_label = STR["panel_handles_title"]
    bl_parent_id = "KITCHEN_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = STR["panel_category"]
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.kitchen_props
        col = layout.column(align=True)
        col.prop(props, "handle_vertical")
        col.prop(props, "handle_length")
        col.prop(props, "handle_bar_overhang")
        col.prop(props, "handle_bar_radius")
        col.prop(props, "handle_mount_length")
        col.separator()
        col.prop(props, "handle_side_margin")
        col.prop(props, "lower_handle_top_margin")
        col.prop(props, "upper_handle_bottom_margin")
        col.prop(props, "handle_z_offset")
        col.separator()
        col.prop(props, "drawer_handle_scale")


class KITCHEN_PT_Materials(Panel):
    bl_label = STR["panel_materials_title"]
    bl_parent_id = "KITCHEN_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = STR["panel_category"]
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.kitchen_props

        layout.prop(props, "ui_show_uv_details", icon='UV')

        def draw_slot(box_label, prop_mat, prop_u, prop_v, prop_rot):
            bx = layout.box()
            row_mat = bx.row(align=True)
            row_mat.label(text=box_label, icon='MATERIAL')
            row_mat.prop(props, prop_mat, text="")
            if props.ui_show_uv_details:
                row_uv = bx.row(align=True)
                row_uv.prop(props, prop_u, text=STR["prop_tile_u"])
                row_uv.prop(props, prop_v, text=STR["prop_tile_v"])
                bx.prop(props, prop_rot)

        draw_slot(STR["ui_mat_lower_facades"], "mat_facade_lower", "uv_facade_lower_u", "uv_facade_lower_v",
                  "rot_facade_lower")
        draw_slot(STR["ui_mat_upper_facades"], "mat_facade_upper", "uv_facade_upper_u", "uv_facade_upper_v",
                  "rot_facade_upper")
        draw_slot(STR["ui_mat_carcass_shelves"], "mat_carcass", "uv_carcass_u", "uv_carcass_v", "rot_carcass")
        draw_slot(STR["ui_mat_countertop"], "mat_countertop", "uv_countertop_u", "uv_countertop_v", "rot_countertop")
        draw_slot(STR["ui_mat_plinth"], "mat_plinth", "uv_plinth_u", "uv_plinth_v", "rot_plinth")
        draw_slot(STR["ui_mat_handles"], "mat_handle", "uv_handle_u", "uv_handle_v", "rot_handle")


class KITCHEN_PT_DebugPanel(Panel):
    bl_label = STR["panel_debug_title"]
    bl_parent_id = "KITCHEN_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = STR["panel_category"]
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.kitchen_props

        col = layout.column()
        col.prop(props, "debug_auto_generate")
        note = col.row()
        note.active = False
        note.label(text=STR["ui_debug_note"], icon='INFO')

        last = layout.row()
        last.alert = not props.debug_last_scene
        if props.debug_last_scene:
            last.label(text=STR["ui_debug_last"].format(name=props.debug_last_scene), icon='CONSOLE')
        else:
            last.label(text=STR["ui_debug_never"], icon='CONSOLE')

        for group_key, group_label, group_icon in DEBUG_GROUPS:
            box = layout.box()
            box.label(text=group_label, icon=group_icon)
            col_buttons = box.column(align=True)
            for scene_def in DEBUG_SCENES:
                if scene_def["group"] != group_key:
                    continue
                debug_op = col_buttons.operator("kitchen.debug_scene", text=scene_def["label"],
                                                icon=scene_def["icon"])
                debug_op.scene_key = scene_def["key"]


# ============================================================
