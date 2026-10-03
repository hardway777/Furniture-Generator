# ============================================================

import bpy
from bpy.props import PointerProperty

from . import strings, core, mesh_ops, primitives, solver, sections, row, properties, operators, debug_scenes, panels, bake
from .bake import KITCHEN_OT_Bake
from .debug_scenes import KITCHEN_OT_DebugScene
from .operators import KITCHEN_OT_CopyCol1ToAll, KITCHEN_OT_CopyLowerToUpper, KITCHEN_OT_DeletePreset, KITCHEN_OT_Generate, KITCHEN_OT_LoadPreset, KITCHEN_OT_SavePreset, KITCHEN_OT_SetSectionsExpanded, unregister_live_timer
from .panels import KITCHEN_PT_BakePanel, KITCHEN_PT_BevelPanel, KITCHEN_PT_Countertop, KITCHEN_PT_DebugPanel, KITCHEN_PT_GeneralPanel, KITCHEN_PT_Handles, KITCHEN_PT_LowerGlobal, KITCHEN_PT_LowerSections, KITCHEN_PT_MainPanel, KITCHEN_PT_Materials, KITCHEN_PT_UpperGlobal, KITCHEN_PT_UpperSections
from .properties import CabinetColumn, CabinetZone, KitchenGeneratorProps, KitchenSection, ShelfBay, ShelfTier, unregister_grid_fix_timer, update_section_columns

# [ANCHOR: REGISTRATION]
# ============================================================
classes = (
    ShelfTier,
    ShelfBay,
    CabinetZone,
    CabinetColumn,
    KitchenSection,
    KitchenGeneratorProps,
    KITCHEN_OT_CopyCol1ToAll,
    KITCHEN_OT_SetSectionsExpanded,
    KITCHEN_OT_SavePreset,
    KITCHEN_OT_LoadPreset,
    KITCHEN_OT_DeletePreset,
    KITCHEN_OT_CopyLowerToUpper,
    KITCHEN_OT_Generate,
    KITCHEN_OT_Bake,
    KITCHEN_OT_DebugScene,
    KITCHEN_PT_MainPanel,
    KITCHEN_PT_BevelPanel,
    KITCHEN_PT_BakePanel,
    KITCHEN_PT_GeneralPanel,
    KITCHEN_PT_LowerGlobal,
    KITCHEN_PT_LowerSections,
    KITCHEN_PT_UpperGlobal,
    KITCHEN_PT_UpperSections,
    KITCHEN_PT_Countertop,
    KITCHEN_PT_Handles,
    KITCHEN_PT_Materials,
    KITCHEN_PT_DebugPanel,
)
from bpy.app.handlers import persistent

@persistent
def _on_load_post(dummy):
    """Initializes section collections when Blender opens a new file."""
    for scene in bpy.data.scenes:
        try:
            ensure_collections_ready(scene)
        except Exception:
            pass


def _init_scenes_timer():
    """Initializes section collections right after addon registration unlocks context."""
    for scene in bpy.data.scenes:
        try:
            ensure_collections_ready(scene)
        except Exception:
            pass
    return None


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except (RuntimeError, ValueError):
            try:
                bpy.utils.unregister_class(cls)
            except Exception:
                pass
            bpy.utils.register_class(cls)

    bpy.types.Scene.kitchen_props = PointerProperty(type=KitchenGeneratorProps)

    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)

    # Запуск через 10 мс: даем Blender завершить регистрацию и снять блокировку контекста
    bpy.app.timers.register(_init_scenes_timer, first_interval=0.01)


def unregister():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    unregister_grid_fix_timer()
    # A queued live rebuild must not outlive the addon: its callback holds module state.
    unregister_live_timer()
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
    if hasattr(bpy.types.Scene, "kitchen_props"):
        del bpy.types.Scene.kitchen_props

if __name__ == "__main__":
    register()
    props = bpy.context.scene.kitchen_props
    if len(props.sections) == 0:
        s = props.sections.add()
        if len(s.tiers) == 0:
            s.tiers.add()
        if len(s.columns) == 0:
            update_section_columns(s, bpy.context)
    if len(props.upper_sections) == 0:
        s = props.upper_sections.add()
        if len(s.tiers) == 0:
            s.tiers.add()
        if len(s.columns) == 0:
            update_section_columns(s, bpy.context)
