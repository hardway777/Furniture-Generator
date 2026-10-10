"""debug_scenes - The DEBUG_SCENES table and the code that applies one.

Moved verbatim from the single-module addon; nobody was edited during the move.
"""
import bpy
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
    SEC_APPLIANCE,
    SEC_CORNER,
    SEC_HOOD_GAP,
    SEC_NORMAL,
    SEC_SINK,
    SEC_WARDROBE,
)
from .properties import update_section_columns
from .strings import STR

# [ANCHOR: DEBUG_SCENES]
# ============================================================
# One-click scenarios for visual inspection: press a button, the parameters are set and
# the model is rebuilt, so a scenario can be looked at directly instead of assembled by
# hand through the panels first.
#
# A scenario is data rather than code, so adding one does not touch the generator. Two
# rules keep the results trustworthy:
#   * every scenario lists the global properties it depends on, so it is self-contained
#     and cannot inherit an upper row or an upstand from whatever was pressed last;
#   * kitchen_id is the same for all of them, because the generator purges by the
#     SM_{kitchen_id}_ prefix - a per-scenario id would leave every previous debug build
#     in the scene, stacked on top of the new one.
#
# Property names are resolved against the RNA when a scenario is applied (see
# apply_debug_values), so a typo here aborts with a report instead of quietly building a
# different kitchen - which is precisely what looks like a geometry bug.

DEBUG_GROUPS = (
    ("rows", STR["ui_debug_group_rows"], 'MESH_CUBE'),
    ("corners", STR["ui_debug_group_corners"], 'MOD_BEVEL'),
    ("specials", STR["ui_debug_group_specials"], 'OBJECT_DATA'),
)

DEBUG_ID = "DEBUG"

# See AGENT_NOTES.md [NOTE_16549]
DEBUG_SCENES = (
    {
        "key": "base_row", "label": "Base Row x4", "group": "rows", "icon": 'MESH_CUBE',
        "props": {
            "kitchen_id": DEBUG_ID, "use_legs": False, "section_count": 4, "depth": 0.60, "height": 0.72,
            "plinth_height": 0.10, "plinth_recess": 0.02,
            "gen_upper": False, "sync_upper_with_lower": True,
            "has_upstand": False, "gen_collisions": True,
        },
        # Side overhangs must appear on the first and the last section only.
        "sections": (
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2},
            {"width": 0.45, "sec_type": SEC_NORMAL, "doors": 1, "shelves": 2},
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2, "has_mid_divider": True},
            {"width": 0.80, "sec_type": SEC_NORMAL, "doors": 0, "drawer_count": 3,
             "drawer_height": 0.16},
        ),
    },
    {
        "key": "upper_synced", "label": "Upper Synced to Base", "group": "rows", "icon": 'MESH_PLANE',
        "props": {
            "kitchen_id": DEBUG_ID, "use_legs": False, "section_count": 3, "depth": 0.60, "height": 0.72,
            "plinth_height": 0.10, "plinth_recess": 0.02,
            "gen_upper": True, "sync_upper_with_lower": True,
            "upper_depth": 0.35, "upper_height": 0.72, "backsplash_height": 0.60,
            "has_upstand": False, "gen_collisions": True,
        },
        # The mirrored list is built from the lower sections by the generate operator.
        "sections": (
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2},
            {"width": 0.45, "sec_type": SEC_NORMAL, "doors": 1},
            {"width": 0.80, "sec_type": SEC_NORMAL, "doors": 2, "shelves": 2},
        ),
    },
    {
        "key": "upper_independent", "label": "Upper Independent List", "group": "rows", "icon": 'OUTLINER',
        "props": {
            "kitchen_id": DEBUG_ID, "use_legs": False, "section_count": 2, "depth": 0.60, "height": 0.72,
            "plinth_height": 0.10, "plinth_recess": 0.02,
            "gen_upper": True, "sync_upper_with_lower": False, "upper_section_count": 3,
            "upper_depth": 0.35, "upper_height": 0.90, "backsplash_height": 0.55,
            "has_upstand": False, "gen_collisions": True,
        },
        "sections": (
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2},
            {"width": 0.80, "sec_type": SEC_NORMAL, "doors": 0, "drawer_count": 3},
        ),
        # Different widths on purpose: a mismatch between the two rows is then visible
        # immediately instead of hiding behind identical geometry.
        "upper": (
            {"width": 0.45, "sec_type": SEC_NORMAL, "doors": 1, "shelves": 1},
            {"width": 0.90, "sec_type": SEC_NORMAL, "doors": 2, "shelves": 2},
            {"width": 0.35, "sec_type": SEC_NORMAL, "doors": 1},
        ),
    },
    {
        "key": "full_l_kitchen", "label": "Full L-Kitchen", "group": "rows", "icon": 'MOD_BUILD',
        "props": {
            "kitchen_id": DEBUG_ID, "use_legs": False, "section_count": 6, "depth": 0.60, "height": 0.72,
            "plinth_height": 0.10, "plinth_recess": 0.02,
            "gen_upper": True, "sync_upper_with_lower": True,
            "upper_depth": 0.35, "upper_height": 0.72, "backsplash_height": 0.60,
            "has_upstand": True, "upstand_height": 0.060, "upstand_thickness": 0.018,
            "gen_collisions": True,
        },
        "sections": (
            {"width": 0.80, "sec_type": SEC_NORMAL, "doors": 0, "drawer_count": 3, "drawer_height": 0.18},
            {"width": 0.60, "sec_type": SEC_SINK, "doors": 2, "sink_w": 0.50, "sink_d": 0.40,
             "sink_margin_f": 0.07, "sink_margin_b": 0.07},
            {"sec_type": SEC_CORNER, "corner_style": CORN_DIAGONAL},
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2, "shelves": 2},
            {"width": 0.60, "sec_type": SEC_APPLIANCE, "doors": 0},
            {"width": 0.45, "sec_type": SEC_HOOD_GAP, "doors": 0},
        ),
    },
    {
        "key": "corner_45", "label": "Corner 45 Beveled", "group": "corners", "icon": 'MOD_BEVEL',
        "props": {
            "kitchen_id": DEBUG_ID, "use_legs": False, "section_count": 3, "depth": 0.60, "height": 0.72,
            "plinth_height": 0.10, "plinth_recess": 0.02,
            "gen_upper": True, "sync_upper_with_lower": True,
            "upper_depth": 0.35, "upper_height": 0.72, "backsplash_height": 0.60,
            "has_upstand": True, "gen_collisions": True,
        },
        "sections": (
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2},
            # Corner planar extents are derived from neighbour depths - no width key.
            {"sec_type": SEC_CORNER, "corner_style": CORN_DIAGONAL},
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2},
        ),
    },
    {
        "key": "corner_doors", "label": "Corner L-Doors", "group": "corners", "icon": 'MOD_BEVEL',
        "props": {
            "kitchen_id": DEBUG_ID, "use_legs": False, "section_count": 3, "depth": 0.60, "height": 0.72,
            "plinth_height": 0.10, "plinth_recess": 0.02,
            "gen_upper": True, "sync_upper_with_lower": True,
            "upper_depth": 0.35, "upper_height": 0.72, "backsplash_height": 0.60,
            "has_upstand": True, "gen_collisions": True,
        },
        "sections": (
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2},
            {"sec_type": SEC_CORNER, "corner_style": CORN_DOORS},
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2},
        ),
    },
    {
        "key": "corner_blind", "label": "Corner Blind Panels", "group": "corners", "icon": 'MOD_BEVEL',
        "props": {
            "kitchen_id": DEBUG_ID, "use_legs": False, "section_count": 3, "depth": 0.60, "height": 0.72,
            "plinth_height": 0.10, "plinth_recess": 0.02,
            "gen_upper": True, "sync_upper_with_lower": True,
            "upper_depth": 0.35, "upper_height": 0.72, "backsplash_height": 0.60,
            "has_upstand": True, "gen_collisions": True,
        },
        "sections": (
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2},
            {"sec_type": SEC_CORNER, "corner_style": CORN_BLIND},
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2},
        ),
    },
    {
        "key": "corner_open", "label": "Corner Open Shelves", "group": "corners", "icon": 'MOD_BEVEL',
        "props": {
            "kitchen_id": DEBUG_ID, "use_legs": False, "section_count": 3, "depth": 0.60, "height": 0.72,
            "plinth_height": 0.10, "plinth_recess": 0.02,
            "gen_upper": True, "sync_upper_with_lower": True,
            "upper_depth": 0.35, "upper_height": 0.72, "backsplash_height": 0.60,
            "has_upstand": True, "gen_collisions": True,
        },
        "sections": (
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2},
            {"sec_type": SEC_CORNER, "corner_style": CORN_OPEN, "shelves": 2},
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2},
        ),
    },
    {
        "key": "island_rounded", "label": "Island, Rounded Slab", "group": "specials", "icon": 'MESH_UVSPHERE',
        "props": {
            "kitchen_id": DEBUG_ID, "use_legs": False, "section_count": 3, "depth": 0.60, "height": 0.72,
            "plinth_height": 0.10, "plinth_recess": 0.02,
            "gen_upper": False, "has_upstand": True, "upstand_height": 0.060,
            "upstand_thickness": 0.018, "island_corner_radius": 0.040,
            "countertop_overhang_front": 0.050, "countertop_overhang_back": 0.050,
            "countertop_overhang_side": 0.020, "gen_collisions": True,
        },
        # A contiguous island run gets one monolithic slab instead of per-section slabs.
        # The wall overhang default of 250 mm would make that slab 25 cm deeper than the
        # carcass on one side, so both overhangs are set equal here.
        #
        # has_upstand stays True on purpose: build_upstand deliberately skips islands, so
        # this scenario is also the place where that silently-ignored checkbox is visible.
        "sections": (
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2, "is_island": True, "has_upstand": True},
            {"width": 0.80, "sec_type": SEC_NORMAL, "doors": 0, "drawer_count": 3, "is_island": True,
             "has_upstand": True},
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2, "is_island": True, "has_upstand": True},
        ),
    },
    {
        "key": "island_with_sink", "label": "Island with Sink", "group": "specials", "icon": 'MESH_UVSPHERE',
        "props": {
            "kitchen_id": DEBUG_ID, "use_legs": False, "section_count": 3, "depth": 0.60, "height": 0.72,
            "plinth_height": 0.10, "plinth_recess": 0.02,
            "gen_upper": False, "has_upstand": False, "island_corner_radius": 0.040,
            "countertop_overhang_front": 0.050, "countertop_overhang_back": 0.050,
            "countertop_overhang_side": 0.020, "gen_collisions": True,
        },
        # The cutout of an island is solved against the whole slab, not against one section,
        # which is a different code path from the per-section sink. The sink sits in the
        # middle section so the cutout cannot fall on a slab edge by accident.
        "sections": (
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2, "is_island": True},
            {"width": 0.80, "sec_type": SEC_SINK, "doors": 2, "is_island": True, "sink_w": 0.50,
             "sink_d": 0.40, "sink_margin_f": 0.09, "sink_margin_b": 0.09},
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2, "is_island": True},
        ),
    },
    {
        "key": "sink_cutout", "label": "Sink + Countertop Cutout", "group": "specials", "icon": 'MESH_CONE',
        "props": {
            "kitchen_id": DEBUG_ID, "use_legs": False, "section_count": 3, "depth": 0.60, "height": 0.72,
            "plinth_height": 0.10, "plinth_recess": 0.02,
            "gen_upper": False, "has_upstand": True, "upstand_height": 0.060,
            "upstand_thickness": 0.018, "gen_collisions": True,
        },
        # Uneven side margins: a cutout that ignores them stays centred and looks fine
        # until measured.
        "sections": (
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2},
            {"width": 0.80, "sec_type": SEC_SINK, "doors": 2, "sink_w": 0.50, "sink_d": 0.40,
             "sink_margin_f": 0.09, "sink_margin_b": 0.05, "sink_margin_l": 0.15, "sink_margin_r": 0.05},
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2},
        ),
    },
    {
        "key": "wardrobe_column", "label": "Wardrobe Column", "group": "specials", "icon": 'MESH_CUBE',
        "props": {
            "kitchen_id": DEBUG_ID, "use_legs": False, "section_count": 2, "depth": 0.60, "height": 0.72,
            "plinth_height": 0.10, "plinth_recess": 0.02,
            "gen_upper": False, "has_upstand": False, "gen_collisions": True,
        },
        # The wardrobe is the only type that reaches its full custom height and the only
        # one that uses the column/zone solver.
        "sections": (
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2},
            {"width": 0.80, "sec_type": SEC_WARDROBE, "override_height": True, "custom_height": 2.20,
             "column_count": 2, "shelves": 3},
        ),
    },
    {
        "key": "appliance_hoodgap", "label": "Appliance + Hood Gap", "group": "specials", "icon": 'LIGHT',
        "props": {
            "kitchen_id": DEBUG_ID, "use_legs": False, "section_count": 4, "depth": 0.60, "height": 0.72,
            "plinth_height": 0.10, "plinth_recess": 0.02,
            "gen_upper": True, "sync_upper_with_lower": True,
            "upper_depth": 0.35, "upper_height": 0.72, "backsplash_height": 0.60,
            "has_upstand": False, "gen_collisions": True,
        },
        # Neither type gets a plinth or a top cover, and the generate operator maps
        # appliance sections to hood gaps in the upper row.
        "sections": (
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2},
            {"width": 0.60, "sec_type": SEC_APPLIANCE, "doors": 0},
            {"width": 0.60, "sec_type": SEC_HOOD_GAP, "doors": 0},
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2},
        ),
    },
    {
        "key": "plinth_degenerate", "label": "Plinth Height Zero", "group": "specials", "icon": 'ERROR',
        "props": {
            "kitchen_id": DEBUG_ID, "use_legs": False, "section_count": 2, "depth": 0.60, "height": 0.72,
            "plinth_height": 0.0, "plinth_recess": 0.0,
            "gen_upper": False, "has_upstand": False, "gen_collisions": True,
        },
        # Degenerate input: no plinth band and no recess. Faces of zero height here show
        # up as stray geometry or flipped normals rather than as an error.
        "sections": (
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 2},
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 0, "drawer_count": 2},
        ),
    },
    {
        "key": "tv_console", "label": "TV Console (Open Niches)", "group": "specials", "icon": 'MESH_GRID',
        "props": {
            "kitchen_id": DEBUG_ID, "use_legs": False, "section_count": 3, "depth": 0.40, "height": 0.40,
            "plinth_height": 0.05, "plinth_recess": 0.02,
            "gen_upper": False, "has_upstand": False, "gen_collisions": True,
        },
        # Low long console under a TV: open niches for equipment - no doors, no back
        # panel (has_back_panel off), shelves carry the A/V stack. The rest is the
        # ordinary section functionality.
        "sections": (
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 0, "shelves": 2, "has_back_panel": False},
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 0, "shelves": 1, "has_back_panel": False},
            {"width": 0.60, "sec_type": SEC_NORMAL, "doors": 0, "shelves": 2, "has_back_panel": False},
        ),
    },
    {
        "key": "bedside_dresser", "label": "Bedside Dresser on Legs", "group": "specials", "icon": 'MOD_SIMPLEDEFORM',
        "props": {
            "kitchen_id": DEBUG_ID, "section_count": 1, "depth": 0.50, "height": 0.55,
            "plinth_height": 0.10, "plinth_recess": 0.02,
            "use_legs": True, "leg_height": 0.15,
            "gen_upper": False, "has_upstand": False, "gen_collisions": True,
        },
        # Wide low bedside dresser: the body the generator already builds, carried by
        # four legs instead of a plinth. leg_height is adjustable; the plinth values in
        # the preset prove they are ignored while legs are on.
        "sections": (
            {"width": 1.00, "sec_type": SEC_NORMAL, "doors": 0, "drawer_count": 2, "drawer_height": 0.20},
        ),
    },
)


def find_debug_scene(key):
    return next((scene_def for scene_def in DEBUG_SCENES if scene_def["key"] == key), None)


def reset_property_group(group):
    """Restore every scalar property of a property group to its declared default.

    Scenarios overlap: a sink width, an island flag or a custom height surviving from the
    previous button produces geometry that reads like a generator bug but is really stale
    UI state. Collections are left alone on purpose - their size is driven by the matching
    count property, which is reset through the count property's own update callback.
    """
    for prop in group.bl_rna.properties:
        if prop.is_readonly or prop.type in ('COLLECTION', 'POINTER'):
            continue
        setattr(group, prop.identifier, prop.default)


def apply_debug_values(group, values, owner):
    """Assign a preset mapping onto a property group; returns problems, empty when all applied.

    Unknown names are reported instead of skipped. A silently dropped entry would build a
    model that does not match the button that was pressed.
    """
    problems = []
    rna = group.bl_rna.properties
    for key, value in values.items():
        if key not in rna:
            problems.append(f"{owner}: no property '{key}'")
            continue
        try:
            setattr(group, key, value)
        except Exception as exc:
            problems.append(f"{owner}.{key}={value!r}: {exc}")
    return problems


def apply_debug_row(props, specs, count_attr, row_attr, label, context):
    """Size one section list from the preset and fill it, resetting every row first."""
    problems = []
    wanted = len(specs)
    if getattr(props, count_attr) != wanted:
        setattr(props, count_attr, wanted)
    row = getattr(props, row_attr)
    if len(row) != wanted:
        # The count property is clamped to its min/max, so a preset can ask for more
        # sections than the UI allows.
        return [f"{label}: asked for {wanted} sections, list holds {len(row)}"]
    for index, spec in enumerate(specs):
        section = row[index]
        reset_property_group(section)
        problems += apply_debug_values(section, spec, f"{label} section {index + 1}")
        # Mirrors update_lower_sections: nested collections are not created by assigning
        # the scalar properties above.
        if len(section.tiers) == 0:
            section.tiers.add()
        if len(section.columns) == 0:
            update_section_columns(section, context)
    return problems


def apply_debug_scene(props, scene_def, context):
    """Apply one scenario: globals first, then the lower row, then the upper row."""
    problems = apply_debug_values(props, scene_def.get("props", {}), "scene")
    problems += apply_debug_row(props, scene_def["sections"], "section_count", "sections",
                                "Lower", context)
    if "upper" in scene_def:
        problems += apply_debug_row(props, scene_def["upper"], "upper_section_count",
                                    "upper_sections", "Upper", context)
    return problems


class KITCHEN_OT_DebugScene(Operator):
    """Set one scenario's parameters and rebuild, for looking at a case without assembling it by hand."""

    bl_idname = "kitchen.debug_scene"
    bl_label = STR["op_debug_scene_label"]
    bl_description = STR["op_debug_scene_desc"]
    bl_options = {'REGISTER', 'UNDO'}

    scene_key: StringProperty(name="scene_key", default="")

    @classmethod
    def poll(cls, context):
        return getattr(context.scene, "kitchen_props", None) is not None

    def execute(self, context):
        props = context.scene.kitchen_props
        scene_def = find_debug_scene(self.scene_key)
        if scene_def is None:
            self.report({'ERROR'}, STR["op_debug_scene_err_unknown"].format(key=self.scene_key))
            return {'CANCELLED'}

        problems = apply_debug_scene(props, scene_def, context)
        if problems:
            # Building anyway would show a model that does not match the button pressed.
            for problem in problems:
                print(f"  !! debug scene: {problem}")
            self.report({'ERROR'}, STR["op_debug_scene_err_apply"].format(
                name=scene_def["label"], err=problems[0]))
            return {'CANCELLED'}

        props.debug_last_scene = scene_def["label"]
        if not props.debug_auto_generate:
            self.report({'INFO'}, STR["op_debug_scene_params_only"].format(name=scene_def["label"]))
            return {'FINISHED'}

        result = bpy.ops.kitchen.generate_kitchen()
        if result == {'FINISHED'}:
            self.report({'INFO'}, STR["op_debug_scene_done"].format(name=scene_def["label"]))
        return result


# ============================================================
