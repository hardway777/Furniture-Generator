"""mesh_ops - Operations applied to a finished mesh: shading, bevel, UV, colliders.

Moved verbatim from the single-module addon; no body was edited during the move.
"""
import bpy
import bmesh
import math
import random
import zlib
import os
from mathutils import Vector, Matrix
from .core import (
    COLLIDER_COLL_SUFFIX,
    GN_SMOOTH_ANGLE_SOCKETS,
    GN_SMOOTH_BY_ANGLE_ASSET,
    GN_SMOOTH_ENABLED_SOCKETS,
    UBX_FOLLOW_KEY,
    UBX_LOCAL_CENTER_KEY,
    warn,
)

# [ANCHOR: MATERIAL_SHADING]
# ============================================================
# PBR maps dropped into the package textures/ folder (see textures/README.txt).
# Suffix -> (socket name on Principled BSDF, colorspace). The normal map goes
# through a Normal Map node, so it is linked to that node's Color instead.
_PBR_MAPS = (
    ("basecolor", "Base Color", "sRGB", None),
    ("roughness", "Roughness", "Non-Color", None),
    ("metallic", "Metallic", "Non-Color", None),
    ("normal", "Normal Map", "Non-Color", "Normal Map"),
)
_PBR_EXTS = (".png", ".jpg", ".jpeg", ".tga", ".bmp", ".webp")
_TEX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "textures")


def _pbr_set_name(mat_name):
    """Material name -> texture set prefix, from textures/materials.txt.

    PBR packs arrive named after the pack (T_WoodDark_001_...), not after the
    generator's material - forcing a rename of every drop is friction the user
    does not want. A plain text mapping the user can edit without touching code
    beats hardcoding pack names into the addon. No entry / no file: the material
    name itself is the set prefix, which keeps the direct convention working.
    """
    path = os.path.join(_TEX_DIR, "materials.txt")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                if "=" in line:
                    key, value = (part.strip() for part in line.split("=", 1))
                    if key == mat_name:
                        return value or mat_name
    except OSError:
        pass
    return mat_name


_MAP_ALIASES = {
    "basecolor": ("basecolor", "base_color", "albedo", "diffuse", "diff", "color", "col", "_d", "_c"),
    "roughness": ("roughness", "rough", "rgh", "_r"),
    "metallic": ("metallic", "metalness", "metal", "met", "_m"),
    "normal": ("normal", "norm", "nor", "nrm", "_n"),
}


def _find_pbr_file(mat_name, suffix):
    raw_set = _pbr_set_name(mat_name).lower()
    # Отрезаем UE-префиксы, чтобы искать "WoodDark_01" вместо "MI_WoodDark_01"
    clean_set = raw_set.removeprefix("mi_").removeprefix("m_").removeprefix("t_")
    aliases = _MAP_ALIASES.get(suffix, (suffix,))

    search_dirs = [_TEX_DIR, os.path.dirname(os.path.abspath(__file__))]

    for base_folder in search_dirs:
        if not os.path.exists(base_folder):
            continue
        try:
            # os.walk заходит в любые вложенные папки архива
            for root, dirs, files in os.walk(base_folder):
                root_low = os.path.basename(root).lower()
                folder_matches = (raw_set in root_low or clean_set in root_low)
                for f in files:
                    stem, ext = os.path.splitext(f)
                    if ext.lower() not in _PBR_EXTS:
                        continue
                    s_low = stem.lower()
                    file_matches = (raw_set in s_low or clean_set in s_low or folder_matches)
                    if file_matches and any(alias in s_low for alias in aliases):
                        return os.path.join(root, f)
        except OSError:
            continue
    return None


def _link_pbr_maps(mat, mat_name):
    """Link PBR image maps from textures/ into the material's node tree.

    No-op when the folder holds no maps for this material, so a stock install
    behaves exactly as before. Idempotent: a node named PBR_<suffix> is only
    built once, so re-running the generator never stacks duplicate nodes.
    """
    if not mat.use_nodes or mat.node_tree is None:
        return
    tree = mat.node_tree
    bsdf = tree.nodes.get("Principled BSDF")
    if bsdf is None:
        return
    for suffix, socket, colorspace, via in _PBR_MAPS:
        node_name = f"PBR_{suffix}"
        existing = tree.nodes.get(node_name)
        if existing is not None:
            img = getattr(existing, "image", None)
            # Idempotence with a health check: skip only while the linked image
            # still resolves (file on disk or packed into the .blend). A node
            # whose file was renamed or re-dropped under another name is a dead
            # link that renders flat - rebuild it instead of skipping it.
            if img is not None and (img.packed_file is not None
                                    or os.path.exists(bpy.path.abspath(img.filepath))):
                continue
            tree.nodes.remove(existing)
        path = _find_pbr_file(mat_name, suffix)
        if path is None:
            continue
        # Reuse an already-loaded image with the same file, so a re-run after
        # the user replaced the file on disk still points at the same datablock.
        image = next(
            (img for img in bpy.data.images
             if os.path.abspath(bpy.path.abspath(img.filepath)) == path),
            None)
        if image is None:
            image = bpy.data.images.load(path)
        image.colorspace_settings.name = colorspace
        tex_node = tree.nodes.new("ShaderNodeTexImage")
        tex_node.name = node_name
        tex_node.label = f"{mat_name} {suffix}"
        tex_node.image = image
        tex_node.location = (bsdf.location.x - 380, bsdf.location.y + 120)
        target_socket = socket
        if via:
            map_node = tree.nodes.new(f"ShaderNode{via.replace(' ', '')}")
            map_node.name = f"PBR_{suffix}_map"
            map_node.location = (bsdf.location.x - 190, bsdf.location.y + 120)
            tree.links.new(tex_node.outputs["Color"], map_node.inputs["Color"])
            tree.links.new(map_node.outputs["Normal"], bsdf.inputs["Normal"])
            continue
        tree.links.new(tex_node.outputs["Color"], bsdf.inputs[target_socket])


def ensure_material(name):
    if name not in bpy.data.materials:
        mat = bpy.data.materials.new(name=name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            if "WoodDark" in name:
                # MI_WoodDark_01: #1C1A19, roughness 0.096, non-metallic.
                bsdf.inputs["Base Color"].default_value = (0.10980, 0.10196, 0.09804, 1)
                bsdf.inputs["Roughness"].default_value = 0.096
                bsdf.inputs["Metallic"].default_value = 0.0
            elif "WoodLight" in name:
                # MI_WoodLight_01: #A08A78, roughness 0.14, non-metallic.
                bsdf.inputs["Base Color"].default_value = (0.62745, 0.54118, 0.47059, 1)
                bsdf.inputs["Roughness"].default_value = 0.14
                bsdf.inputs["Metallic"].default_value = 0.0
            elif "Wood" in name:
                bsdf.inputs["Base Color"].default_value = (0.55, 0.42, 0.32, 1)
                bsdf.inputs["Roughness"].default_value = 0.45
            elif "MetalChrome" in name:
                # MI_MetalChrome_01: chrome - ORM (0.0, 0.2, 1.0), i.e. roughness 0.2,
                # metallic 1.0. The 0.0 occlusion has no Principled input.
                bsdf.inputs["Base Color"].default_value = (0.90, 0.90, 0.92, 1)
                bsdf.inputs["Roughness"].default_value = 0.2
                bsdf.inputs["Metallic"].default_value = 1.0
            elif "Metal" in name:
                bsdf.inputs["Base Color"].default_value = (0.80, 0.80, 0.82, 1)
                bsdf.inputs["Metallic"].default_value = 0.95
                bsdf.inputs["Roughness"].default_value = 0.20
            elif "Stone" in name:
                bsdf.inputs["Base Color"].default_value = (0.92, 0.92, 0.90, 1)
                bsdf.inputs["Roughness"].default_value = 0.35
            else:
                bsdf.inputs["Base Color"].default_value = (0.8, 0.8, 0.8, 1)
    mat = bpy.data.materials[name]
    # PBR maps, if the user dropped any into textures/ (no-op otherwise).
    _link_pbr_maps(mat, name)
    return mat


def _selected_objects():
    """Previously selected objects, tolerant to a stale view-layer object map.

    view_layer.objects may still hold slots of objects removed since the last depsgraph
    evaluation (they iterate as None), so the already-resolved selected_objects list is used.
    """
    try:
        return [o for o in bpy.context.selected_objects if o is not None]
    except Exception:
        return []


def _select_only(obj):
    """Make obj the single selected+active object, return the previous selection to restore."""
    view_layer = bpy.context.view_layer
    prev_sel = _selected_objects()
    try:
        prev_active = view_layer.objects.active
    except Exception:
        prev_active = None
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    view_layer.objects.active = obj
    return prev_sel, prev_active


def _restore_selection(state):
    """Undo _select_only(); the operated object may have been replaced by bpy.ops.convert."""
    prev_sel, prev_active = state
    view_layer = bpy.context.view_layer
    try:
        bpy.ops.object.select_all(action='DESELECT')
    except Exception:
        return
    for o in prev_sel:
        try:
            if o.name in bpy.data.objects:
                o.select_set(True)
        except ReferenceError:
            continue
    try:
        if prev_active is None or prev_active.name not in bpy.data.objects:
            view_layer.objects.active = None
        else:
            view_layer.objects.active = prev_active
    except Exception:
        pass


def _set_gn_input(mod, socket_names, value):
    """Assign a value to a node-group modifier input, tolerant to socket renaming."""
    inputs = mod.properties.inputs
    for name in socket_names:
        socket = getattr(inputs, name, None)
        if socket is None:
            socket = inputs.get(name) if hasattr(inputs, "get") else None
        if socket is not None:
            try:
                socket.value = value
                return True
            except Exception:
                continue
    return False


def add_and_apply_smooth(obj, angle_deg=60, apply=True):
    if not obj or obj.type != 'MESH':
        return
    selection_state = _select_only(obj)
    added = False
    # The asset path separator is platform dependent, so try both spellings.
    for identifier in (GN_SMOOTH_BY_ANGLE_ASSET, GN_SMOOTH_BY_ANGLE_ASSET.replace("/", os.sep)):
        try:
            result = bpy.ops.object.modifier_add_node_group(
                asset_library_type='ESSENTIALS',
                asset_library_identifier="",
                relative_asset_identifier=identifier
            )
            if 'CANCELLED' in result or not obj.modifiers:
                continue
            mod = obj.modifiers[-1]
            bpy.context.view_layer.update()
            _set_gn_input(mod, GN_SMOOTH_ANGLE_SOCKETS, math.radians(angle_deg))
            _set_gn_input(mod, GN_SMOOTH_ENABLED_SOCKETS, True)
            added = True
            break
        except Exception:
            continue

    if added:
        if apply:
            try:
                bpy.ops.object.convert(target='MESH')
            except Exception:
                bpy.ops.object.shade_smooth()
    else:
        warn(f"Smooth by Angle asset not found, plain shade_smooth used on '{obj.name}'")
        try:
            bpy.ops.object.shade_smooth()
        except Exception:
            pass

    _restore_selection(selection_state)


# ============================================================
# [ANCHOR: BEVEL_SYSTEM]
# ============================================================
def apply_edge_bevel_weights(mesh, edge_indices, weight=1.0):
    if not mesh or not edge_indices:
        return
    attr_ok = False
    try:
        attr = mesh.attributes.get("bevel_weight_edge")
        if not attr:
            attr = mesh.attributes.new(name="bevel_weight_edge", type='FLOAT', domain='EDGE')
        for idx in edge_indices:
            attr.data[idx].value = weight
        attr_ok = True
    except Exception as exc:
        warn(f"bevel_weight_edge attribute failed on '{mesh.name}': {exc}")
    legacy_ok = True
    try:
        for idx in edge_indices:
            mesh.edges[idx].bevel_weight = weight
    except Exception as exc:
        legacy_ok = False
        if not attr_ok:
            warn(f"mesh.bevel_weight fallback failed on '{mesh.name}': {exc}")
    if not attr_ok and not legacy_ok:
        warn(f"No bevel weights set on '{mesh.name}', micro-bevel will be missing")


def mark_mesh_facade_bevel_weights(mesh, weight=1.0, face="front"):
    """Marks the visible facade side of a panel.

    The choice is purely about the mesh's own local Y axis, so it depends on how the panel
    was built, not on where it ends up in the kitchen:

    face='front' -> visible side is local -Y (min_y): regular doors/drawers, whose panel body
        spans y=[0, t] and whose handles sit at negative local Y.
    face='back'  -> visible side is local +Y (max_y): island back panels facing the rear
        countertop overhang, and the mirrored second door of a two-door corner section.
    """
    if not mesh or not mesh.edges:
        return
    verts = mesh.vertices
    min_y = min(v.co.y for v in verts)
    max_y = max(v.co.y for v in verts)
    facade_y = max_y if face == "back" else min_y

    front_verts = [v.co for v in verts if abs(v.co.y - facade_y) < 1e-4]
    if not front_verts:
        return

    min_x = min(v.x for v in front_verts)
    max_x = max(v.x for v in front_verts)
    min_z = min(v.z for v in front_verts)
    max_z = max(v.z for v in front_verts)

    target_edges = []
    for e in mesh.edges:
        v1 = verts[e.vertices[0]].co
        v2 = verts[e.vertices[1]].co

        is_front = (abs(v1.y - facade_y) < 1e-4 and abs(v2.y - facade_y) < 1e-4)
        if is_front:
            target_edges.append(e.index)
            continue

        nearest_y = max(v1.y, v2.y) if face == "back" else min(v1.y, v2.y)
        touches_front = (abs(nearest_y - facade_y) < 1e-4)
        is_parallel_y = (abs(v1.x - v2.x) < 1e-4 and abs(v1.z - v2.z) < 1e-4 and abs(v1.y - v2.y) > 1e-4)

        if touches_front and is_parallel_y:
            is_corner_x = (abs(v1.x - min_x) < 1e-4 or abs(v1.x - max_x) < 1e-4)
            is_corner_z = (abs(v1.z - min_z) < 1e-4 or abs(v1.z - max_z) < 1e-4)
            if is_corner_x and is_corner_z:
                target_edges.append(e.index)

    apply_edge_bevel_weights(mesh, target_edges, weight)


def mark_mesh_countertop_bevel_weights(mesh, front_y=None, top_z=0.0, back_y=None, left_x=None, right_x=None,
                                       weight=1.0):
    """Marks top outer perimeter edges of countertops (front, back for islands, exposed sides)."""
    if not mesh or not mesh.edges:
        return
    verts = mesh.vertices
    target_edges = []
    for e in mesh.edges:
        v1 = verts[e.vertices[0]].co
        v2 = verts[e.vertices[1]].co
        is_top = (abs(v1.z - top_z) < 1e-4 and abs(v2.z - top_z) < 1e-4)
        if not is_top:
            continue

        if front_y is not None and (abs(v1.y - front_y) < 1e-4 and abs(v2.y - front_y) < 1e-4):
            target_edges.append(e.index)
        elif back_y is not None and (abs(v1.y - back_y) < 1e-4 and abs(v2.y - back_y) < 1e-4):
            target_edges.append(e.index)
        elif left_x is not None and (abs(v1.x - left_x) < 1e-4 and abs(v2.x - left_x) < 1e-4):
            target_edges.append(e.index)
        elif right_x is not None and (abs(v1.x - right_x) < 1e-4 and abs(v2.x - right_x) < 1e-4):
            target_edges.append(e.index)

    apply_edge_bevel_weights(mesh, target_edges, weight)


def add_chamfered_corner_box(verts, faces, x0, y0, z0, sx, sy, sz, cut):
    """Box with the (x0, y0) corner cut vertically through the full height.

    The corner slab's front vertex used to get a bmesh vertex bevel, which triangulates
    into a fan on a 3-edge corner (the chamfer in CornerVertexChamfer.jpg). A plan cut
    keeps the chamfer face a single quad; the weighted top edges now end at the cut's
    vertices instead of meeting there, so the Bevel modifier terminates its chain
    without pinching.
    """
    c = min(cut, sx * 0.5, sy * 0.5)
    x1, y1, z1 = x0 + sx, y0 + sy, z0 + sz
    b = len(verts)
    verts.extend([
        Vector((x0 + c, y0, z1)),  # 0: top, cut start on the front edge
        Vector((x1, y0, z1)),      # 1
        Vector((x1, y1, z1)),      # 2
        Vector((x0, y1, z1)),      # 3
        Vector((x0, y0 + c, z1)),  # 4: top, cut end on the side edge
        Vector((x0 + c, y0, z0)),  # 5
        Vector((x1, y0, z0)),      # 6
        Vector((x1, y1, z0)),      # 7
        Vector((x0, y1, z0)),      # 8
        Vector((x0, y0 + c, z0)),  # 9
    ])
    faces.extend([
        (b + 0, b + 1, b + 2, b + 3, b + 4),  # top pentagon
        (b + 5, b + 9, b + 8, b + 7, b + 6),  # bottom pentagon
        (b + 0, b + 5, b + 6, b + 1),         # front
        (b + 1, b + 6, b + 7, b + 2),         # right
        (b + 2, b + 7, b + 8, b + 3),         # back
        (b + 3, b + 8, b + 9, b + 4),         # side
        (b + 0, b + 4, b + 9, b + 5),         # the quad chamfer
    ])


def apply_bevel_to_object(obj, width=0.002, segments=2):
    if not obj or obj.type != 'MESH' or width <= 0.0001:
        return
    selection_state = _select_only(obj)

    mod = obj.modifiers.new(name="Bevel", type='BEVEL')
    mod.width = width
    mod.segments = segments
    mod.limit_method = 'WEIGHT'
    mod.harden_normals = True
    mod.use_clamp_overlap = True
    mod.miter_outer = 'MITER_SHARP'

    add_and_apply_smooth(obj, angle_deg=60, apply=False)
    try:
        wn = obj.modifiers.new(name="WeightedNormal", type='WEIGHTED_NORMAL')
        wn.keep_sharp = True
    except Exception as exc:
        warn(f"WeightedNormal modifier unavailable for '{obj.name}': {exc}")

    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.object.convert(target='MESH')
    except Exception as exc:
        warn(f"Could not apply modifiers on '{obj.name}', bevel stays live: {exc}")

    _restore_selection(selection_state)


# See AGENT_NOTES.md [NOTE_16565]
SINK_BEVEL_ATTR = "sink_bevel_weight"
SINK_DRAIN_BEVEL_ATTR = "sink_drain_bevel_weight"


def _set_weight_attribute(mesh, attr_name, groups, widths):
    """Write per-group bevel weights into a FLOAT/EDGE attribute; returns the base width."""
    active = {g: w for g, w in (widths or {}).items() if w > 0.0001}
    if not active:
        return 0.0
    base = max(active.values())
    attr = mesh.attributes.get(attr_name)
    if attr is None:
        attr = mesh.attributes.new(name=attr_name, type='FLOAT', domain='EDGE')
    for group, width in active.items():
        weight = width / base
        for idx in groups.get(group, []):
            attr.data[idx].value = weight
    return base


def apply_sink_bowl_bevel(obj, groups, widths, segments, miter,
                          drain_groups=None, drain_widths=None, drain_segments=2):
    """Bevel the sink edge groups with weight-limited Bevel modifiers.

    A single modifier covers the whole bowl, so `segments` and the miter type are shared;
    only the width differs per group. Blender scales the bevel width by the edge weight,
    so each group gets weight = width / max_width and the modifier's width is max_width -
    the per-group widths come out exact (measured). `miter` is 'SHARP' or 'ARC' and drives
    the outer miter only (see below).

    One pass keeps the three crease chains manifold: the bowl's crease loops meet at the
    four corners, and splitting the bevel into per-group passes left junction n-gons
    (up to a 9-gon the size of a rim cell), while a single pass leaves none. Measured:
    no edge ever carries more than two faces.

    The drain (stamped earlier by primitives.stamp_sink_drain) is a separate island on the
    floor, so it gets its OWN Bevel modifier with its own segment count, limited by a
    second edge-weight attribute. Both modifiers are set up before the single convert, so
    the drain edge indices stay valid. See AGENT_NOTES.md [NOTE_16580].
    """
    if not obj or obj.type != 'MESH':
        return
    base = _set_weight_attribute(obj.data, SINK_BEVEL_ATTR, groups, widths)
    drain_base = 0.0
    if drain_groups:
        drain_base = _set_weight_attribute(obj.data, SINK_DRAIN_BEVEL_ATTR,
                                           drain_groups, drain_widths)
    if base <= 0.0 and drain_base <= 0.0:
        return

    selection_state = _select_only(obj)
    if base > 0.0:
        mod = obj.modifiers.new(name="Bevel_sink", type='BEVEL')
        mod.width = base
        mod.segments = segments
        mod.limit_method = 'WEIGHT'
        mod.edge_weight = SINK_BEVEL_ATTR
        mod.harden_normals = True
        mod.use_clamp_overlap = True
        # The miter type is shared by the whole modifier. Only the OUTER miter follows it:
        # Blender's Arc inner miter overshoots on the bowl's concave corners - measured, the
        # bowl grew 0.044 past its floor and rim with miter_inner='MITER_ARC', while with a
        # sharp inner miter the Arc outer patches stay inside the bowl (span unchanged).
        mod.miter_outer = 'MITER_ARC' if miter == 'ARC' else 'MITER_SHARP'
        mod.miter_inner = 'MITER_SHARP'
    if drain_base > 0.0:
        dmod = obj.modifiers.new(name="Bevel_drain", type='BEVEL')
        dmod.width = drain_base
        dmod.segments = drain_segments
        dmod.limit_method = 'WEIGHT'
        dmod.edge_weight = SINK_DRAIN_BEVEL_ATTR
        dmod.harden_normals = True
        dmod.use_clamp_overlap = True
        dmod.miter_outer = 'MITER_SHARP'
        dmod.miter_inner = 'MITER_SHARP'

    add_and_apply_smooth(obj, angle_deg=60, apply=False)
    try:
        wn = obj.modifiers.new(name="WeightedNormal", type='WEIGHTED_NORMAL')
        wn.keep_sharp = True
    except Exception as exc:
        warn(f"WeightedNormal modifier unavailable for '{obj.name}': {exc}")

    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.object.convert(target='MESH')
    except Exception as exc:
        warn(f"Could not apply sink bevel on '{obj.name}', it stays live: {exc}")

    _restore_selection(selection_state)


# ============================================================
# [ANCHOR: UV_SYSTEM]
# ============================================================
def apply_box_uvs(obj, tile_u=1.0, tile_v=1.0, rotate_90=False):
    if not obj or obj.type != 'MESH':
        return
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    uv_layer = bm.loops.layers.uv.verify()

    # crc32 keeps UV offsets stable across sessions (unlike hash(), which is salted per process)
    rng = random.Random(zlib.crc32(obj.name.encode("utf-8")))
    u_off = rng.uniform(0.0, 20.0)
    v_off = rng.uniform(0.0, 20.0)

    for face in bm.faces:
        norm = face.normal
        ax, ay, az = abs(norm.x), abs(norm.y), abs(norm.z)
        for loop in face.loops:
            co = loop.vert.co
            if ax >= ay and ax >= az:
                u = co.y if norm.x >= 0 else -co.y
                v = co.z
            elif ay >= ax and ay >= az:
                u = -co.x if norm.y >= 0 else co.x
                v = co.z
            else:
                u = co.x
                v = co.y if norm.z >= 0 else -co.y

            if rotate_90:
                u, v = v, u

            loop[uv_layer].uv = ((u + u_off) * tile_u, (v + v_off) * tile_v)

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


# ============================================================
# [ANCHOR: COLLISION_UBX]
# ============================================================
# See AGENT_NOTES.md [NOTE_16546]
def collider_collection(collection):
    """The one sub-collection that holds every collider of one generation, created on demand.

    Colliders used to be linked into the same collection as the furniture they belong to and
    parented to it, so the outliner showed a UBX between the door and its handle, and
    selecting all colliders meant box-selecting the furniture. They are now a flat list of
    unparented objects in a sub-collection of the generation (`FURNITURE_<id>_Colliders`,
    `BAKE_<bake>_Colliders`), which can be hidden, selected or deleted as one unit while the
    generation collection still hides the whole run the way T-33 intended.

    A Collection has no upward link in this Blender API (no parent, no users_collection), so
    the sub-collection is found by looking through the children of the collection the caller
    was building into - which is always the generation root, the one place the generator and
    the bake both hand down.
    """
    if collection is None:
        return None
    if collection.name.endswith(COLLIDER_COLL_SUFFIX):
        return collection
    for child in collection.children:
        if child.name.endswith(COLLIDER_COLL_SUFFIX):
            return child
    coll = bpy.data.collections.new(f"{collection.name}{COLLIDER_COLL_SUFFIX}")
    collection.children.link(coll)
    return coll


def apply_collider_flags(obj):
    """Viewport and render behaviour shared by every collider this addon makes.

    Wire in the viewport and invisible to the camera, plus all five Cycles ray visibility
    flags off: a collider is engine data, it must neither show up in a render nor cast
    shadows or bounce light, and in the working model the wire display is what the user
    reads the collision layout by.
    """
    obj.display_type = 'WIRE'
    obj.hide_viewport = False
    obj.hide_render = True
    obj.visible_camera = False
    obj.visible_diffuse = False
    obj.visible_glossy = False
    obj.visible_transmission = False
    obj.visible_volume_scatter = False
    obj.visible_shadow = False


def collider_cube(size):
    """A unit cube scaled to `size` around its own origin - no offset in the mesh.

    Every collider is authored this way: the box centre is the object origin, never a
    translation baked into the vertices. Unreal reads an object's transform as the collision
    body's placement and takes its origin for the body centre, so an off-centre pivot makes
    the body sit wrong in the engine even when the world-space box is correct. The offset to
    the box centre therefore lives in the object matrix (see `collider_matrix`).
    """
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Diagonal(Vector((size.x, size.y, size.z, 1.0))))
    return bm


def collider_matrix(target_matrix, local_center):
    """World matrix that puts a centred collider box at `local_center` of the target frame.

    Composing rather than baking the offset into the mesh is what keeps the pivot at the box
    centre while the box still lands where the target's bound box was.
    """
    return target_matrix @ Matrix.Translation(local_center)


def create_ubx_from_bbox(target_obj, col_idx=1, collection=None):
    if not target_obj or collection is None:
        return None
    bbox_corners = [Vector(c) for c in target_obj.bound_box]
    min_co = Vector((min(c.x for c in bbox_corners), min(c.y for c in bbox_corners), min(c.z for c in bbox_corners)))
    max_co = Vector((max(c.x for c in bbox_corners), max(c.y for c in bbox_corners), max(c.z for c in bbox_corners)))
    size = max_co - min_co
    center = min_co + size / 2

    mesh = bpy.data.meshes.new(f"UBX_{target_obj.name}_{col_idx:02d}")
    bm = collider_cube(size)
    bm.to_mesh(mesh)
    bm.free()

    ubx = bpy.data.objects.new(f"UBX_{target_obj.name}_{col_idx:02d}", mesh)
    # The bound box is in the target's local frame, so the collider's world transform is the
    # target's own transform moved out to the box centre: the pivot ends up at the centre of
    # the box (engine requirement, see `collider_cube`). The centre is recorded as a local
    # offset because the collider does not parent to its target - colliders are a flat list
    # in their own collection. A handle is the case that needs the record: create_handle
    # builds the collider while the handle still sits at the origin and the caller moves it
    # afterwards, so sync_bbox_colliders re-composes the matrix once the run is complete.
    #
    # The depsgraph must be updated before the world matrix is read: a freshly placed
    # target has not been evaluated yet, and without the update the collider is snapshotted
    # against the stale pre-placement state and lands on the world origin. Measured A/B.
    # See AGENT_NOTES.md [NOTE_16546]
    colliders = collider_collection(collection)
    colliders.objects.link(ubx)
    bpy.context.view_layer.update()
    ubx.matrix_world = collider_matrix(target_obj.matrix_world, center)
    ubx[UBX_FOLLOW_KEY] = target_obj.name
    ubx[UBX_LOCAL_CENTER_KEY] = center[:]
    apply_collider_flags(ubx)
    return ubx


def sync_bbox_colliders(objs):
    """Align every bbox collider with its target, once the target is placed.

    A bbox collider is authored in its target's local frame, so it must carry the target's
    world transform moved out to the box centre. That is true at build time for a door or a
    drawer front, whose collider is created after the object is placed - but NOT for a
    handle: create_handle builds the collider while the handle still sits at the origin and
    the caller parents and moves the handle afterwards, so the matrix composed at build time
    is the one built around the world origin.

    Running this pass after a whole row is built re-reads each recorded target's final world
    matrix and re-composes the collider's matrix from it and the recorded local centre, so
    the box and its centred pivot move onto the target together. Only colliders carrying
    UBX_FOLLOW_KEY are touched: the box-primitive colliders (drawer walls, carcass,
    countertop cutout) were authored in a frame of their own and must keep the transform
    they were given.

    See AGENT_NOTES.md [NOTE_16546]
    """
    moved = 0
    for ubx in objs:
        if ubx is None or ubx.type != 'MESH' or not ubx.name.startswith("UBX_"):
            continue
        target_name = ubx.get(UBX_FOLLOW_KEY)
        if not target_name:
            continue
        target = bpy.data.objects.get(target_name)
        if target is None:
            continue
        center = ubx.get(UBX_LOCAL_CENTER_KEY)
        ubx.matrix_world = collider_matrix(target.matrix_world,
                                           Vector(center) if center else Vector((0.0, 0.0, 0.0)))
        moved += 1
    if moved:
        bpy.context.view_layer.update()
    return moved


def create_ubx_box_primitive(target_obj, col_idx, x0, y0, z0, sx, sy, sz, collection, matrix):
    if collection is None:
        return None
    bm = collider_cube(Vector((sx, sy, sz)))
    center = Vector((x0 + sx / 2, y0 + sy / 2, z0 + sz / 2))
    mesh = bpy.data.meshes.new(f"UBX_{target_obj.name}_{col_idx:02d}")
    bm.to_mesh(mesh)
    bm.free()

    ubx = bpy.data.objects.new(f"UBX_{target_obj.name}_{col_idx:02d}", mesh)
    collider_collection(collection).objects.link(ubx)
    # The piece is authored around its own origin and moved out to its centre, so the pivot
    # is the box centre (engine requirement, see `collider_cube`). No parenting: `matrix` is
    # already the world matrix the piece was authored against, and colliders live as a flat
    # list in their own collection. The target is deliberately NOT recorded as a follow
    # target - a drawer wall or a carcass panel is positioned in a frame of its own, so
    # re-composing from the target's matrix would collapse the piece onto it.
    ubx.matrix_world = collider_matrix(matrix, center)
    apply_collider_flags(ubx)
    return ubx


# ============================================================
