"""operators - The operators: generate, presets, copy, and the debug scene applier.

Moved verbatim from the single-module addon; no body was edited during the move.
"""
import bpy
import os
import json
import time
from bpy.props import (
    FloatProperty, IntProperty, BoolProperty, EnumProperty,
    CollectionProperty, PointerProperty, StringProperty
)
from bpy.types import PropertyGroup, Operator, Panel
from .core import (
    GEN_WARNINGS,
    SEC_APPLIANCE,
    SEC_CORNER,
    SEC_HOOD_GAP,
    SEC_NORMAL,
    SEC_WARDROBE,
    clear_warnings,
    log,
    warn,
)
from .properties import (
    deserialize_kitchen,
    drop_empty_kitchen_collections,
    ensure_collections_ready,
    get_or_create_kitchen_collection,
    resolve_preset_path,
    serialize_kitchen,
    update_column_zones,
    update_section_tiers,
    update_zone_bays,
)
from .mesh_ops import sync_bbox_colliders
from .row import build_cabinet_row
from .strings import STR

# [ANCHOR: OPERATORS]
# ============================================================
class KITCHEN_OT_CopyCol1ToAll(Operator):
    bl_idname = "kitchen.copy_col1_to_all"
    bl_label = STR["op_copy_col_label"]
    bl_description = STR["op_copy_col_desc"]
    bl_options = {'REGISTER', 'UNDO'}

    sec_index: IntProperty(default=0)

    def execute(self, context):
        props = context.scene.kitchen_props
        if self.sec_index >= len(props.sections):
            return {'CANCELLED'}
        sec = props.sections[self.sec_index]
        if len(sec.columns) < 2:
            return {'FINISHED'}

        src_col = sec.columns[0]
        for c in range(1, len(sec.columns)):
            dst_col = sec.columns[c]
            dst_col.zone_count = src_col.zone_count
            update_column_zones(dst_col, context)
            for z_idx in range(len(src_col.zones)):
                sz = src_col.zones[z_idx]
                dz = dst_col.zones[z_idx]
                dz.zone_type = sz.zone_type
                dz.height_mode = sz.height_mode
                dz.height = sz.height
                dz.height_pct = sz.height_pct
                dz.interior_type = sz.interior_type
                dz.shelf_mode = sz.shelf_mode
                dz.shelves_count = sz.shelves_count
                dz.bay_count = sz.bay_count
                update_zone_bays(dz, context)
                for b_i in range(len(sz.bays)):
                    if b_i < len(dz.bays):
                        dz.bays[b_i].height_mode = sz.bays[b_i].height_mode
                        dz.bays[b_i].height = sz.bays[b_i].height
                        dz.bays[b_i].height_pct = sz.bays[b_i].height_pct

                dz.rod_drop = sz.rod_drop
                dz.handle_pos = sz.handle_pos
                dz.handle_z_offset = sz.handle_z_offset
                dz.handle_len_mode = sz.handle_len_mode
                dz.handle_pct = sz.handle_pct
                dz.handle_custom_len = sz.handle_custom_len
                dz.door_swing = 'RIGHT' if sz.door_swing == 'LEFT' else ('LEFT' if sz.door_swing == 'RIGHT' else 'PAIR')
        self.report({'INFO'}, STR["op_copy_col_done"])
        return {'FINISHED'}


class KITCHEN_OT_SetSectionsExpanded(Operator):
    """Open or close every section block at once. Deliberately not undoable: it is panel state."""

    bl_idname = "kitchen.set_sections_expanded"
    bl_label = STR["op_expand_secs_label"]
    bl_description = STR["op_expand_secs_desc"]

    expanded: BoolProperty(name=STR["prop_expanded"], default=True)
    upper: BoolProperty(name="Upper", default=False)

    def execute(self, context):
        props = context.scene.kitchen_props
        for sec in (props.upper_sections if self.upper else props.sections):
            sec.is_expanded = self.expanded
        return {'FINISHED'}


class KITCHEN_OT_SavePreset(Operator):
    bl_idname = "kitchen.save_preset"
    bl_label = STR["op_save_preset_label"]
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.kitchen_props
        name = props.preset_name_input.strip()
        if not name:
            self.report({'ERROR'}, STR["op_save_preset_err_empty"])
            return {'CANCELLED'}
        filepath = resolve_preset_path(name)
        if filepath is None:
            self.report({'ERROR'}, STR["op_preset_err_bad_name"].format(name=name))
            return {'CANCELLED'}
        data = serialize_kitchen(props)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            self.report({'INFO'}, STR["op_save_preset_done"].format(name=os.path.basename(filepath)))
        except Exception as e:
            self.report({'ERROR'}, STR["op_save_preset_err"].format(err=e))
            return {'CANCELLED'}
        return {'FINISHED'}


class KITCHEN_OT_LoadPreset(Operator):
    bl_idname = "kitchen.load_preset"
    bl_label = STR["op_load_preset_label"]
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.kitchen_props
        preset_name = props.preset_enum
        if preset_name == "NONE" or not preset_name:
            self.report({'WARNING'}, STR["op_load_preset_warn_none"])
            return {'CANCELLED'}
        filepath = resolve_preset_path(preset_name)
        if filepath is None:
            self.report({'ERROR'}, STR["op_preset_err_bad_name"].format(name=preset_name))
            return {'CANCELLED'}
        if not os.path.exists(filepath):
            self.report({'ERROR'}, STR["op_load_preset_err_not_found"].format(name=preset_name))
            return {'CANCELLED'}
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            deserialize_kitchen(props, data, context)
            props.preset_name_input = os.path.basename(filepath)[:-len(".json")]
            self.report({'INFO'}, STR["op_load_preset_done"].format(name=preset_name))
        except Exception as e:
            self.report({'ERROR'}, STR["op_load_preset_err"].format(err=e))
            return {'CANCELLED'}
        return {'FINISHED'}


class KITCHEN_OT_DeletePreset(Operator):
    bl_idname = "kitchen.delete_preset"
    bl_label = STR["op_del_preset_label"]
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.kitchen_props
        preset_name = props.preset_enum
        if preset_name == "NONE" or not preset_name:
            self.report({'WARNING'}, STR["op_del_preset_warn_none"])
            return {'CANCELLED'}
        filepath = resolve_preset_path(preset_name)
        if filepath is None:
            self.report({'ERROR'}, STR["op_preset_err_bad_name"].format(name=preset_name))
            return {'CANCELLED'}
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                self.report({'INFO'}, STR["op_del_preset_done"].format(name=preset_name))
            except Exception as e:
                self.report({'ERROR'}, STR["op_del_preset_err"].format(err=e))
                return {'CANCELLED'}
        return {'FINISHED'}


class KITCHEN_OT_CopyLowerToUpper(Operator):
    bl_idname = "kitchen.copy_lower_to_upper"
    bl_label = STR["op_copy_lower_label"]
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.kitchen_props
        props.upper_section_count = len(props.sections)
        for i, src in enumerate(props.sections):
            dst = props.upper_sections[i]
            dst.width = src.width
            dst.doors = src.doors
            dst.shelves = src.shelves
            dst.corner_style = src.corner_style
            dst.override_height = src.override_height
            dst.custom_height = src.custom_height
            dst.override_depth = src.override_depth
            dst.custom_depth = src.custom_depth
            dst.has_bottom = src.has_bottom
            dst.has_top = src.has_top
            dst.shelf_rows = src.shelf_rows
            dst.no_side_walls = src.no_side_walls
            dst.shelves_span_walls = src.shelves_span_walls
            dst.z_anchor = src.z_anchor
            dst.z_offset = src.z_offset
            dst.override_mat = src.override_mat
            dst.custom_mat_facade = src.custom_mat_facade
            dst.custom_mat_carcass = src.custom_mat_carcass
            update_section_tiers(dst, context)
            for k in range(min(len(src.tiers), len(dst.tiers))):
                dst.tiers[k].dividers = src.tiers[k].dividers

            if src.sec_type == SEC_CORNER:
                dst.sec_type = SEC_CORNER
            elif src.sec_type == SEC_APPLIANCE:
                dst.sec_type = SEC_HOOD_GAP
            elif src.sec_type == SEC_WARDROBE:
                dst.sec_type = SEC_NORMAL
            else:
                dst.sec_type = SEC_NORMAL
        self.report({'INFO'}, STR["op_copy_lower_done"])
        return {'FINISHED'}


class KITCHEN_OT_Generate(Operator):
    bl_idname = "kitchen.generate_kitchen"
    bl_label = STR["op_gen_label"]
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.kitchen_props
        t_total_ms = run_generation(props, context.scene, props.gen_collisions)

        if GEN_WARNINGS:
            self.report({'WARNING'}, f"{len(GEN_WARNINGS)} issue(s): {GEN_WARNINGS[0]}")

        self.report({'INFO'}, STR["op_gen_done"].format(id=props.kitchen_id) + f" [{t_total_ms:.1f} ms]")
        return {'FINISHED'}


# [ANCHOR: GENERATION_CORE]
# ============================================================
def run_generation(props, scene, gen_collisions=True):
    """Purge the previous run of this kitchen id, then build both rows. The full body
    that KITCHEN_OT_Generate.execute used to hold, extracted verbatim so the live-preview
    timer (T-41) can call the same code without going through an operator - an operator
    run from a timer would push an undo step per rebuild and explode the undo queue.
    gen_collisions is a parameter because the live pass deliberately builds without
    colliders; everything else still reads from props. Returns elapsed milliseconds.
    """
    t_gen_start = time.perf_counter()
    clear_warnings()

    # Every generation gets its own collection, named after the kitchen id, so a
    # run is a unit in the outliner and two ids cannot mix. The previous
    # collection of the SAME id is reused (its contents are purged below), an
    # empty leftover is dropped, and collections of other ids are left alone.
    drop_empty_kitchen_collections(scene)
    collection = get_or_create_kitchen_collection(scene, props.kitchen_id)

    # Nested collections (tiers/columns/zones/bays) used to be repaired from the panel draw
    # pass. Sections can now be folded away and the fix may still sit in the timer, so the
    # generator rebuilds them itself: a run must not depend on how the panel was drawn.
    try:
        ensure_collections_ready(scene)
    except Exception as exc:
        warn(f"Could not pre-fill wardrobe/shelf collections: {exc}")

    prefix = f"SM_{props.kitchen_id}_"
    prefix_ubx = f"UBX_SM_{props.kitchen_id}_"
    prefix_socket = f"SOCKET_SM_{props.kitchen_id}_"

    t_purge_start = time.perf_counter()
    # Two criteria, because either alone leaves litter: a renamed kitchen_id leaves
    # old-prefix objects in the old collection, and a leftover object in THIS
    # collection may carry a name the prefixes miss. Anything found by either test
    # goes, and only objects this addon made can match - the collection is ours by
    # construction and the prefixes are ours by naming rule.
    in_our_collection = set(collection.all_objects)
    to_remove = [o for o in list(bpy.data.objects) if
                 (o.name.startswith(prefix) or o.name.startswith(prefix_ubx)
                  or o.name.startswith(prefix_socket) or o in in_our_collection)]
    # do_unlink=True leaves the mesh datablocks behind, so they are dropped explicitly.
    # A global orphans_purge is deliberately avoided: it would also delete user data.
    own_meshes = [o.data for o in to_remove if o.data is not None]
    for o in to_remove:
        bpy.data.objects.remove(o, do_unlink=True)
    purged_meshes = 0
    for mesh in own_meshes:
        try:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
                purged_meshes += 1
        except ReferenceError:
            continue
    t_purge_ms = (time.perf_counter() - t_purge_start) * 1000.0

    # Removed objects keep stale slots in the view-layer object map until the depsgraph
    # is re-evaluated; refresh it before any operator touches the selection. The layer is
    # taken from the scene, not from bpy.context: a timer callback runs with a context
    # that has no view_layer, and the scene's own layer is the one being rebuilt.
    try:
        scene.view_layers[0].update()
    except Exception as exc:
        warn(f"view_layer.update() after purge failed: {exc}")

    root_name = f"SM_{props.kitchen_id}_Root"
    root = bpy.data.objects.new(root_name, None)
    collection.objects.link(root)
    root.empty_display_type = 'PLAIN_AXES'
    root.empty_display_size = 0.2

    log(f"\n--- [GENERATION START: {props.kitchen_id}] ---")
    log(f"  Purge old objects: {len(to_remove)} objects, {purged_meshes} meshes, {t_purge_ms:.2f} ms")

    t_base_start = time.perf_counter()
    build_cabinet_row(
        props=props, sections=props.sections, row_name="Base",
        depth=props.depth, height=props.height, is_upper=False, base_z=0.0,
        root=root, collection=collection, gen_collisions=gen_collisions
    )
    t_base_ms = (time.perf_counter() - t_base_start) * 1000.0
    log(f"  Row 'Base' total: {t_base_ms:.2f} ms")

    t_upper_ms = 0.0
    if props.gen_upper:
        t_upper_start = time.perf_counter()
        base_z_upper = props.plinth_height + props.height + props.countertop_thickness + props.backsplash_height
        sections_upper = list(props.upper_sections) if not props.sync_upper_with_lower else []

        if props.sync_upper_with_lower:
            for s in props.sections:
                st = SEC_CORNER if s.sec_type == SEC_CORNER else (
                    SEC_HOOD_GAP if s.sec_type == SEC_APPLIANCE else SEC_NORMAL)
                dummy = type("DummySec", (), {
                    "width": s.width, "sec_type": st, "corner_style": s.corner_style,
                    "is_corner": (st == SEC_CORNER),
                    "override_height": s.override_height, "custom_height": s.custom_height,
                    "override_depth": s.override_depth,
                    "custom_depth": s.custom_depth, "doors": s.doors, "handle_orient": s.handle_orient,
                    "override_handle_z": s.override_handle_z, "custom_handle_z": s.custom_handle_z,
                    "shelves": s.shelves,
                    "has_mid_divider": False, "shelf_thickness": s.shelf_thickness, "drawer_count": 0,
                    "drawer_height": 0.0,
                    "sink_w": 0, "sink_d": 0, "sink_margin_f": 0, "sink_margin_b": 0, "sink_margin_l": 0,
                    "sink_margin_r": 0,
                    "sink_recess_depth": 0, "sink_recess_margin_f": 0, "sink_recess_margin_b": 0,
                    "sink_recess_margin_l": 0, "sink_recess_margin_r": 0,
                    "sink_bevel_floor_w": 0, "sink_bevel_vert_w": 0, "sink_bevel_top_w": 0,
                    "sink_bevel_segments": 1, "sink_bevel_miter": 'SHARP',
                    "sink_drain_on": False, "sink_drain_d1": 0, "sink_drain_d2": 0,
                    "sink_drain_dia1": 0, "sink_drain_dia2": 0,
                    "sink_drain_bevel_top": 0, "sink_drain_bevel_mid": 0, "sink_drain_bevel_low": 0,
                    "sink_drain_bevel_segments": 1,
                    "sink_strainer_on": False, "sink_strainer_thickness": 0,
                    "sink_strainer_gap": 0,
                    "has_bottom": s.has_bottom, "has_top": s.has_top,
                    "has_back_panel": s.has_back_panel, "shelf_rows": s.shelf_rows,
                    "no_side_walls": s.no_side_walls, "shelves_span_walls": s.shelves_span_walls,
                    "z_anchor": s.z_anchor, "z_offset": s.z_offset,
                    "tiers": list(s.tiers),
                    "columns": [], "override_mat": s.override_mat, "custom_mat_facade": s.custom_mat_facade,
                    "custom_mat_carcass": s.custom_mat_carcass,
                    "is_island": False, "has_upstand": False
                })()
                sections_upper.append(dummy)

        build_cabinet_row(
            props=props, sections=sections_upper, row_name="Upper",
            depth=props.upper_depth, height=props.upper_height, is_upper=True, base_z=base_z_upper,
            root=root, collection=collection, gen_collisions=gen_collisions
        )
        t_upper_ms = (time.perf_counter() - t_upper_start) * 1000.0
        log(f"  Row 'Upper' total: {t_upper_ms:.2f} ms")

    root["is_kitchen_module"] = True

    # Bbox colliders are authored in their target's local frame, and a handle's
    # collider is built before the handle is placed - so the pass runs once the
    # whole run exists. all_objects: the colliders live in the generation's
    # _Colliders sub-collection, not in the generation collection itself.
    # See AGENT_NOTES.md [NOTE_16546]
    moved = sync_bbox_colliders(list(collection.all_objects))
    log(f"  Collider sync: {moved} bbox collider(s) re-aligned to their target")

    t_total_ms = (time.perf_counter() - t_gen_start) * 1000.0
    log(f"--- [GENERATION DONE: {t_total_ms:.2f} ms] ---\n")

    if GEN_WARNINGS:
        print(f"  !! {len(GEN_WARNINGS)} warning(s):")
        for message in GEN_WARNINGS:
            print(f"     - {message}")

    return t_total_ms


# [ANCHOR: LIVE_PREVIEW]
# ============================================================
# Live preview (T-41). The panel draw pass is the change notification: every panel in the
# sidebar region redraws whenever a property inside it changes, so after the redraw the
# signature of all build inputs either matches the last build or it does not. On a
# difference a rebuild is scheduled LIVE_DEBOUNCE seconds later. The delay is the design:
# a slider fires a property change per mouse-move, one rebuild costs 120-1200 ms
# (measured, AGENT_TASKS T-41), so rebuilding per change would freeze the UI, while a
# rebuild 0.3 s after the last change runs exactly once per drag. Colliders are excluded
# deliberately - they exist for the export, and dropping them also removes the stale
# boxes of the build being replaced, which is what the user asked to not see.

LIVE_DEBOUNCE = 0.30

# One pending rebuild at a time, same shape as _GRID_FIX in properties.py. "built" is the
# signature the scene was last built with; it lives only for the session.
_LIVE = {"scene": None, "registered": False, "built": None}


def live_signature(props):
    """A string that changes exactly when a rebuild input changes.

    serialize_kitchen() is the property set the generator consumes, so reusing it keeps
    the signature from drifting away from the real build inputs. gen_collisions is
    dropped: the live pass never builds colliders, so flipping that switch alone must
    not queue a rebuild.
    """
    try:
        data = serialize_kitchen(props)
    except Exception:
        return None
    data.pop("gen_collisions", None)
    try:
        return json.dumps(data, sort_keys=True)
    except (TypeError, ValueError):
        return None


def request_live_rebuild(scene):
    """Queue a debounced rebuild unless the scene matches the last live build.

    Called from the panel draw pass on every redraw, so it must be cheap and must never
    touch ID data - it only reads properties and (de)registers a timer.
    """
    props = getattr(scene, "kitchen_props", None)
    if props is None or not props.live_preview:
        # Switch off: drop the seed, so the next activation compares against the state it
        # is switched on with instead of against a build from before it was turned off.
        _LIVE["built"] = None
        return
    if _LIVE["registered"]:
        return
    signature = live_signature(props)
    if signature is None:
        return
    if _LIVE["built"] is None:
        # First draw of an activation: record the current state, build nothing. Flipping the
        # switch is not an edit, and rebuilding here would delete the colliders the previous
        # Generate made without the user having changed anything.
        _LIVE["built"] = signature
        return
    if signature == _LIVE["built"]:
        return
    _LIVE["scene"] = scene
    _LIVE["registered"] = True
    bpy.app.timers.register(_live_rebuild_job, first_interval=LIVE_DEBOUNCE)


def _live_rebuild_job():
    """The timer callback: rebuild from the CURRENT properties, without colliders."""
    _LIVE["registered"] = False
    scene = _LIVE["scene"]
    _LIVE["scene"] = None
    if scene is None:
        return None
    try:
        props = getattr(scene, "kitchen_props", None)
    except ReferenceError:
        return None
    if props is None or not props.live_preview:
        _LIVE["built"] = None
        return None
    signature = live_signature(props)
    if signature is None or signature == _LIVE["built"]:
        return None
    # Recorded before the build, not after: a build that raises would otherwise be
    # re-queued by every following redraw and flood the console with the same error.
    _LIVE["built"] = signature
    try:
        run_generation(props, scene, gen_collisions=False)
    except Exception as exc:
        warn(f"Live preview: rebuild failed: {exc}")
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
    return None


def unregister_live_timer():
    if bpy.app.timers.is_registered(_live_rebuild_job):
        bpy.app.timers.unregister(_live_rebuild_job)
    _LIVE["scene"] = None
    _LIVE["registered"] = False


# ============================================================
