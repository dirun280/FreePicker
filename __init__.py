bl_info = {
    "name": "FreePicker",
    "author": "dirun",
    "version": (4, 1, 0),
    "blender": (5, 0, 0),
    "location": "View3D header (Object/Pose Mode) > FreePicker button",
    "description": "A fully self-contained picker: its own Pose-mode bone sets "
                    "and Object-mode sets (does NOT use Blender's native Bone "
                    "Selection Sets, so it will not conflict or share data with "
                    "other addons such as 'Quick Selection Sets'), drawn as a "
                    "floating panel with an Edit Mode that lets you drag and "
                    "resize each button freely to build a custom picker layout.",
    "category": "Rigging",
}

import bpy
import blf
import gpu
import math
import time
import json
from gpu_extras.batch import batch_for_shader
from bpy_extras.io_utils import ExportHelper, ImportHelper


try:
    UNIFORM_SHADER = gpu.shader.from_builtin('UNIFORM_COLOR')
except Exception:
    UNIFORM_SHADER = gpu.shader.from_builtin('2D_UNIFORM_COLOR')


# ---------------------------------------------------------------------------
# Draw helpers -- same technique used by "Animo Sliders": everything is
# hand-drawn vector shapes via the gpu module, not real icon images.
# ---------------------------------------------------------------------------

def rgb01(rgb, alpha=1.0):
    return (rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0, alpha)


def dpi(value, context):
    scale = context.preferences.system.ui_scale if context else 1.0
    scale = max(0.75, min(scale, 3.0))
    return int(value * scale)


def _rounded_rect_verts(x, y, w, h, radius, segments=8):
    radius = max(0.0, min(radius, w / 2.0, h / 2.0))
    verts = []

    def arc(cx, cy, start_angle):
        for i in range(segments + 1):
            a = start_angle + (math.pi / 2.0) * (i / segments)
            verts.append((cx + math.cos(a) * radius, cy + math.sin(a) * radius))

    arc(x + w - radius, y + h - radius, 0.0)
    arc(x + radius, y + h - radius, math.pi / 2.0)
    arc(x + radius, y + radius, math.pi)
    arc(x + w - radius, y + radius, 3.0 * math.pi / 2.0)
    return verts


def draw_rounded_rect(x, y, w, h, radius, color):
    verts = _rounded_rect_verts(x, y, w, h, radius)
    fan = []
    cx, cy = x + w / 2.0, y + h / 2.0
    for i in range(len(verts) - 1):
        fan.append((cx, cy))
        fan.append(verts[i])
        fan.append(verts[i + 1])
    fan.append((cx, cy))
    fan.append(verts[-1])
    fan.append(verts[0])

    batch = batch_for_shader(UNIFORM_SHADER, 'TRIS', {"pos": fan})
    UNIFORM_SHADER.bind()
    UNIFORM_SHADER.uniform_float("color", color)
    gpu.state.blend_set('ALPHA')
    batch.draw(UNIFORM_SHADER)
    gpu.state.blend_set('NONE')


def draw_rounded_rect_outline(x, y, w, h, radius, color, width=1.5):
    verts = _rounded_rect_verts(x, y, w, h, radius)
    verts = verts + [verts[0]]
    batch = batch_for_shader(UNIFORM_SHADER, 'LINE_STRIP', {"pos": verts})
    UNIFORM_SHADER.bind()
    UNIFORM_SHADER.uniform_float("color", color)
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(width)
    batch.draw(UNIFORM_SHADER)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def draw_circle(cx, cy, radius, color, segments=16):
    verts = [(cx, cy)]
    for i in range(segments + 1):
        a = 2.0 * math.pi * i / segments
        verts.append((cx + math.cos(a) * radius, cy + math.sin(a) * radius))
    batch = batch_for_shader(UNIFORM_SHADER, 'TRI_FAN', {"pos": verts})
    UNIFORM_SHADER.bind()
    UNIFORM_SHADER.uniform_float("color", color)
    gpu.state.blend_set('ALPHA')
    batch.draw(UNIFORM_SHADER)
    gpu.state.blend_set('NONE')


def draw_circle_outline(cx, cy, radius, color, width=1.5, segments=16):
    verts = []
    for i in range(segments + 1):
        a = 2.0 * math.pi * i / segments
        verts.append((cx + math.cos(a) * radius, cy + math.sin(a) * radius))
    batch = batch_for_shader(UNIFORM_SHADER, 'LINE_STRIP', {"pos": verts})
    UNIFORM_SHADER.bind()
    UNIFORM_SHADER.uniform_float("color", color)
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(width)
    batch.draw(UNIFORM_SHADER)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def draw_triangle(p1, p2, p3, color):
    batch = batch_for_shader(UNIFORM_SHADER, 'TRIS', {"pos": [p1, p2, p3]})
    UNIFORM_SHADER.bind()
    UNIFORM_SHADER.uniform_float("color", color)
    gpu.state.blend_set('ALPHA')
    batch.draw(UNIFORM_SHADER)
    gpu.state.blend_set('NONE')


def draw_triangle_outline(p1, p2, p3, color, width=1.5):
    verts = [p1, p2, p3, p1]
    batch = batch_for_shader(UNIFORM_SHADER, 'LINE_STRIP', {"pos": verts})
    UNIFORM_SHADER.bind()
    UNIFORM_SHADER.uniform_float("color", color)
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(width)
    batch.draw(UNIFORM_SHADER)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def draw_text(x, y, text, size, color, align_center_width=None):
    font_id = 0
    blf.size(font_id, size)
    blf.color(font_id, *color)
    if align_center_width is not None:
        tw, th = blf.dimensions(font_id, text)
        x = x + (align_center_width - tw) / 2.0
    blf.position(font_id, x, y, 0)
    blf.draw(font_id, text)


def draw_text_vcenter(x, y, h, text, size, color, align_center_width=None):
    """Draw text vertically centered within a box spanning [y, y + h]."""
    font_id = 0
    blf.size(font_id, size)
    tw, th = blf.dimensions(font_id, text if text else "Hy")
    ty = y + (h - th) / 2.0
    if align_center_width is not None:
        tw2, _ = blf.dimensions(font_id, text)
        x = x + (align_center_width - tw2) / 2.0
    blf.color(font_id, *color)
    blf.position(font_id, x, ty, 0)
    blf.draw(font_id, text)


def char_index_at_x(text, size, box_x, mouse_x):
    """Return the character index in text nearest to mouse_x, given text starts at box_x."""
    font_id = 0
    blf.size(font_id, size)
    if mouse_x <= box_x or not text:
        return 0
    for i in range(1, len(text) + 1):
        w = blf.dimensions(font_id, text[:i])[0]
        if box_x + w >= mouse_x:
            prev_w = blf.dimensions(font_id, text[:i - 1])[0]
            mid = box_x + (prev_w + w) / 2.0
            return i - 1 if mouse_x < mid else i
    return len(text)


def clip_text(text, size, max_width):
    font_id = 0
    blf.size(font_id, size)
    tw, th = blf.dimensions(font_id, text)
    if tw <= max_width or len(text) <= 1:
        return text
    while text and blf.dimensions(font_id, text + "...")[0] > max_width:
        text = text[:-1]
    return text + "..." if text else "..."


# ---------------------------------------------------------------------------
# Multi-select color sync -- when several buttons are selected together in
# Edit Mode (box-select), changing one's color via the right-click menu
# broadcasts that color to the rest of the selection too. This has to sit
# above the data classes below since it's wired in as a property update
# callback at class-definition time.
# ---------------------------------------------------------------------------

_active_panel = {"instance": None}
_color_sync_guard = {"active": False}


def _sync_color_to_selection(entry, context):
    if _color_sync_guard["active"]:
        return
    panel = _active_panel["instance"]
    if panel is None or not getattr(panel, "edit_mode", False):
        return
    selected = getattr(panel, "edit_selected", None)
    if not selected or len(selected) <= 1:
        return

    mode = context.mode
    idx = None
    if mode == 'POSE':
        arm = context.object
        if arm and arm.type == 'ARMATURE':
            for i, item in enumerate(arm.freepicker_bone_sets):
                if item.as_pointer() == entry.as_pointer():
                    idx = i
                    break
    elif mode == 'OBJECT':
        scene = context.scene
        for i, item in enumerate(scene.freepicker_sets):
            if item.as_pointer() == entry.as_pointer():
                idx = i
                break

    if idx is None or idx not in selected:
        return

    _color_sync_guard["active"] = True
    try:
        color = entry.color[:]
        for other_idx in selected:
            if other_idx == idx:
                continue
            other = get_layout_entry(context, other_idx)
            if other is not None:
                other.color = color
    finally:
        _color_sync_guard["active"] = False

    if context.area:
        context.area.tag_redraw()


# ---------------------------------------------------------------------------
# Data  (unchanged from the original addon)
# ---------------------------------------------------------------------------

class FREEPICKER_member(bpy.types.PropertyGroup):
    obj_name: bpy.props.StringProperty()


class FREEPICKER_bone_member(bpy.types.PropertyGroup):
    bone_name: bpy.props.StringProperty()


SHAPE_ITEMS = [
    ('SQUARE', "Square", ""),
    ('CIRCLE', "Circle", ""),
    ('TRIANGLE', "Triangle", ""),
]


# Sentinel: -1 on pos_x/pos_y/box_w/box_h means "not customized yet",
# fall back to the default stacked-list arrangement computed at draw time.
class FREEPICKER_set(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name="Set Name", default="Set")
    color: bpy.props.FloatVectorProperty(
        name="Tag Color", subtype='COLOR', size=4,
        default=(0.5, 0.5, 0.5, 1.0), min=0.0, max=1.0,
        update=_sync_color_to_selection,
    )
    highlighted: bpy.props.BoolProperty(default=False)
    members: bpy.props.CollectionProperty(type=FREEPICKER_member)
    pos_x: bpy.props.FloatProperty(default=-1.0)
    pos_y: bpy.props.FloatProperty(default=-1.0)
    box_w: bpy.props.FloatProperty(default=-1.0)
    box_h: bpy.props.FloatProperty(default=-1.0)
    shape: bpy.props.EnumProperty(items=SHAPE_ITEMS, default='SQUARE')
    show_name: bpy.props.BoolProperty(default=False)


# Picker's own Pose-mode sets. Deliberately NOT built on Blender's native
# Armature "Bone Selection Sets" (arm.selection_sets / bpy.ops.pose.selection_set_*)
# -- that native feature is shared, global armature data, so any other addon
# built on top of it (e.g. "Quick Selection Sets") would see and mix with
# Picker's entries. This collection lives only under a picker-prefixed
# property name, so the two stay completely independent.
class FREEPICKER_pose_set(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name="Set Name", default="Set")
    color: bpy.props.FloatVectorProperty(
        name="Tag Color", subtype='COLOR', size=4,
        default=(0.5, 0.5, 0.5, 1.0), min=0.0, max=1.0,
        update=_sync_color_to_selection,
    )
    highlighted: bpy.props.BoolProperty(default=False)
    members: bpy.props.CollectionProperty(type=FREEPICKER_bone_member)
    pos_x: bpy.props.FloatProperty(default=-1.0)
    pos_y: bpy.props.FloatProperty(default=-1.0)
    box_w: bpy.props.FloatProperty(default=-1.0)
    box_h: bpy.props.FloatProperty(default=-1.0)
    shape: bpy.props.EnumProperty(items=SHAPE_ITEMS, default='SQUARE')
    show_name: bpy.props.BoolProperty(default=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pose_set_is_active(context, sel_set):
    if len(sel_set.members) == 0:
        return False
    selected = context.selected_pose_bones
    if not selected:
        return False
    selected_names = {b.name for b in selected}
    return all(m.bone_name in selected_names for m in sel_set.members)


def object_set_is_active(context, sel_set):
    if len(sel_set.members) == 0:
        return False
    selected = context.selected_objects
    if not selected:
        return False
    selected_names = {o.name for o in selected}
    return all(m.obj_name in selected_names for m in sel_set.members)


def get_layout_entry(context, index):
    """Return the PropertyGroup (pose set or object set) holding this row's
    pos_x/pos_y/box_w/box_h, regardless of Pose/Object mode."""
    mode = context.mode
    if mode == 'POSE':
        arm = context.object
        if arm and arm.type == 'ARMATURE' and 0 <= index < len(arm.freepicker_bone_sets):
            return arm.freepicker_bone_sets[index]
    elif mode == 'OBJECT':
        scene = context.scene
        if 0 <= index < len(scene.freepicker_sets):
            return scene.freepicker_sets[index]
    return None


def apply_picker_selection(context, indices, extend):
    """Select (or toggle, if extend) the members of the given selection-set
    indices. Shared by the single-click operator and the box-select
    (marquee) tool so both stay in sync."""
    mode = context.mode

    if mode == 'POSE':
        arm = context.object
        if not arm or arm.type != 'ARMATURE':
            return
        if not extend:
            for pbone in arm.pose.bones:
                pbone.select = False
            for s in arm.freepicker_bone_sets:
                s.highlighted = False
        last_bone = None
        for idx in indices:
            if not (0 <= idx < len(arm.freepicker_bone_sets)):
                continue
            sel_set = arm.freepicker_bone_sets[idx]
            sel_set.highlighted = (not sel_set.highlighted) if extend else True
            for m in sel_set.members:
                pbone = arm.pose.bones.get(m.bone_name)
                if pbone:
                    pbone.select = True
                    last_bone = pbone
        if last_bone:
            arm.data.bones.active = last_bone.bone

    elif mode == 'OBJECT':
        scene = context.scene
        if not extend:
            for obj in context.view_layer.objects:
                obj.select_set(False)
            for s in scene.freepicker_sets:
                s.highlighted = False
        last_obj = None
        for idx in indices:
            if not (0 <= idx < len(scene.freepicker_sets)):
                continue
            sel_set = scene.freepicker_sets[idx]
            sel_set.highlighted = (not sel_set.highlighted) if extend else True
            for m in sel_set.members:
                obj = bpy.data.objects.get(m.obj_name)
                if obj and obj.name in context.view_layer.objects:
                    obj.select_set(True)
                    last_obj = obj
        if last_obj:
            context.view_layer.objects.active = last_obj


_last_click_time = {}
DOUBLE_CLICK_THRESHOLD = 0.35  # seconds


# ---------------------------------------------------------------------------
# Operators  (unchanged from the original addon)
# ---------------------------------------------------------------------------

NEW_BUTTON_SIZE = 46.0  # default square size (px) for a freshly created button


class FREEPICKER_OT_add(bpy.types.Operator):
    """Create a new selection set from the currently selected objects/bones"""
    bl_idname = "freepicker.add_set"
    bl_label = "Add Selection Set"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mode = context.mode

        if mode == 'POSE':
            arm = context.object
            if not arm or arm.type != 'ARMATURE':
                self.report({'WARNING'}, "Active object is not an armature")
                return {'CANCELLED'}
            bones = context.selected_pose_bones
            if not bones:
                self.report({'WARNING'}, "No bones selected")
                return {'CANCELLED'}

            new_set = arm.freepicker_bone_sets.add()
            existing_names = {s.name for s in arm.freepicker_bone_sets}
            i = len(arm.freepicker_bone_sets)
            name = f"Bone Set {i}"
            while name in existing_names:
                i += 1
                name = f"Bone Set {i}"
            new_set.name = name
            new_set.pos_x = 0.0
            new_set.pos_y = 0.0
            new_set.box_w = NEW_BUTTON_SIZE
            new_set.box_h = NEW_BUTTON_SIZE

            for pb in bones:
                m = new_set.members.add()
                m.bone_name = pb.name

            self.report({'INFO'}, f"Set '{new_set.name}' created ({len(bones)} bones)")
            return {'FINISHED'}

        elif mode == 'OBJECT':
            scene = context.scene
            objs = context.selected_objects
            if not objs:
                self.report({'WARNING'}, "No objects selected")
                return {'CANCELLED'}

            new_set = scene.freepicker_sets.add()
            existing_names = {s.name for s in scene.freepicker_sets}
            i = len(scene.freepicker_sets)
            name = f"Object Set {i}"
            while name in existing_names:
                i += 1
                name = f"Object Set {i}"
            new_set.name = name
            new_set.pos_x = 0.0
            new_set.pos_y = 0.0
            new_set.box_w = NEW_BUTTON_SIZE
            new_set.box_h = NEW_BUTTON_SIZE

            for obj in objs:
                m = new_set.members.add()
                m.obj_name = obj.name

            self.report({'INFO'}, f"Set '{new_set.name}' created ({len(objs)} objects)")
            return {'FINISHED'}

        else:
            self.report({'WARNING'}, "Only usable in Object Mode or Pose Mode")
            return {'CANCELLED'}


class FREEPICKER_OT_select(bpy.types.Operator):
    """Click = select. Shift+click = add to selection. Double-click = rename"""
    bl_idname = "freepicker.select_set"
    bl_label = "Select"
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty()
    extend: bpy.props.BoolProperty(default=False)

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        self.do_select(context)
        return {'FINISHED'}

    def do_select(self, context):
        mode = context.mode
        if mode not in {'POSE', 'OBJECT'}:
            self.report({'WARNING'}, "Only usable in Object Mode or Pose Mode")
            return
        apply_picker_selection(context, [self.index], self.extend)


class FREEPICKER_OT_update(bpy.types.Operator):
    """Add the currently selected bones/objects to this set (without removing
    what's already in it)."""
    bl_idname = "freepicker.update_set"
    bl_label = "Add Selected To Set"
    bl_options = {'UNDO'}

    index: bpy.props.IntProperty()

    def execute(self, context):
        mode = context.mode

        if mode == 'POSE':
            arm = context.object
            if not arm or arm.type != 'ARMATURE':
                return {'CANCELLED'}
            if not (0 <= self.index < len(arm.freepicker_bone_sets)):
                return {'CANCELLED'}
            bones = context.selected_pose_bones
            if not bones:
                self.report({'WARNING'}, "No bones selected")
                return {'CANCELLED'}

            sel_set = arm.freepicker_bone_sets[self.index]
            existing = {m.bone_name for m in sel_set.members}
            added = 0
            for pb in bones:
                if pb.name not in existing:
                    m = sel_set.members.add()
                    m.bone_name = pb.name
                    existing.add(pb.name)
                    added += 1
            self.report({'INFO'}, f"Added {added} bone(s) to '{sel_set.name}'")
            return {'FINISHED'}

        elif mode == 'OBJECT':
            scene = context.scene
            if not (0 <= self.index < len(scene.freepicker_sets)):
                return {'CANCELLED'}
            objs = context.selected_objects
            if not objs:
                self.report({'WARNING'}, "No objects selected")
                return {'CANCELLED'}

            sel_set = scene.freepicker_sets[self.index]
            existing = {m.obj_name for m in sel_set.members}
            added = 0
            for obj in objs:
                if obj.name not in existing:
                    m = sel_set.members.add()
                    m.obj_name = obj.name
                    existing.add(obj.name)
                    added += 1
            self.report({'INFO'}, f"Added {added} object(s) to '{sel_set.name}'")
            return {'FINISHED'}

        return {'CANCELLED'}


class FREEPICKER_OT_remove_members(bpy.types.Operator):
    """Remove the currently selected bones/objects from this set (does not
    delete the set itself)."""
    bl_idname = "freepicker.remove_members"
    bl_label = "Remove Selected From Set"
    bl_options = {'UNDO'}

    index: bpy.props.IntProperty()

    def execute(self, context):
        mode = context.mode

        if mode == 'POSE':
            arm = context.object
            if not arm or arm.type != 'ARMATURE':
                return {'CANCELLED'}
            if not (0 <= self.index < len(arm.freepicker_bone_sets)):
                return {'CANCELLED'}
            bones = context.selected_pose_bones
            if not bones:
                self.report({'WARNING'}, "No bones selected")
                return {'CANCELLED'}

            names = {pb.name for pb in bones}
            sel_set = arm.freepicker_bone_sets[self.index]
            removed = 0
            for i in reversed(range(len(sel_set.members))):
                if sel_set.members[i].bone_name in names:
                    sel_set.members.remove(i)
                    removed += 1
            self.report({'INFO'}, f"Removed {removed} bone(s) from '{sel_set.name}'")
            return {'FINISHED'}

        elif mode == 'OBJECT':
            scene = context.scene
            if not (0 <= self.index < len(scene.freepicker_sets)):
                return {'CANCELLED'}
            objs = context.selected_objects
            if not objs:
                self.report({'WARNING'}, "No objects selected")
                return {'CANCELLED'}

            names = {o.name for o in objs}
            sel_set = scene.freepicker_sets[self.index]
            removed = 0
            for i in reversed(range(len(sel_set.members))):
                if sel_set.members[i].obj_name in names:
                    sel_set.members.remove(i)
                    removed += 1
            self.report({'INFO'}, f"Removed {removed} object(s) from '{sel_set.name}'")
            return {'FINISHED'}

        return {'CANCELLED'}


class FREEPICKER_OT_set_shape(bpy.types.Operator):
    """Change this button's shape (square / circle / triangle)"""
    bl_idname = "freepicker.set_shape"
    bl_label = "Set Button Shape"
    bl_options = {'UNDO'}

    index: bpy.props.IntProperty()
    shape: bpy.props.EnumProperty(items=SHAPE_ITEMS, default='SQUARE')

    def execute(self, context):
        entry = get_layout_entry(context, self.index)
        if entry is None:
            return {'CANCELLED'}
        entry.shape = self.shape
        return {'FINISHED'}


class FREEPICKER_OT_remove(bpy.types.Operator):
    """Delete this button entirely (the set and all its members)"""
    bl_idname = "freepicker.remove_set"
    bl_label = "Delete Button"
    bl_options = {'UNDO'}

    index: bpy.props.IntProperty()

    def execute(self, context):
        mode = context.mode

        if mode == 'POSE':
            arm = context.object
            if not arm or arm.type != 'ARMATURE':
                return {'CANCELLED'}
            if not (0 <= self.index < len(arm.freepicker_bone_sets)):
                return {'CANCELLED'}

            name = arm.freepicker_bone_sets[self.index].name
            arm.freepicker_bone_sets.remove(self.index)
            self.report({'INFO'}, f"Set '{name}' deleted")
            return {'FINISHED'}

        elif mode == 'OBJECT':
            scene = context.scene
            if 0 <= self.index < len(scene.freepicker_sets):
                name = scene.freepicker_sets[self.index].name
                scene.freepicker_sets.remove(self.index)
                self.report({'INFO'}, f"Set '{name}' deleted")
            return {'FINISHED'}

        return {'CANCELLED'}


class FREEPICKER_OT_export(bpy.types.Operator, ExportHelper):
    """Export all selection sets in the current mode to a JSON file"""
    bl_idname = "freepicker.export_sets"
    bl_label = "Export Selection Sets"
    bl_options = {'REGISTER'}

    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={'HIDDEN'})

    def execute(self, context):
        mode = context.mode
        data = {"mode": mode, "sets": []}

        if mode == 'POSE':
            arm = context.object
            if not arm or arm.type != 'ARMATURE':
                self.report({'WARNING'}, "Active object is not an armature")
                return {'CANCELLED'}

            for sel_set in arm.freepicker_bone_sets:
                data["sets"].append({
                    "name": sel_set.name,
                    "color": list(sel_set.color),
                    "bone_names": [m.bone_name for m in sel_set.members],
                    "pos_x": sel_set.pos_x,
                    "pos_y": sel_set.pos_y,
                    "box_w": sel_set.box_w,
                    "box_h": sel_set.box_h,
                    "shape": sel_set.shape,
                    "show_name": sel_set.show_name,
                })

        elif mode == 'OBJECT':
            scene = context.scene
            for sel_set in scene.freepicker_sets:
                data["sets"].append({
                    "name": sel_set.name,
                    "color": list(sel_set.color),
                    "object_names": [m.obj_name for m in sel_set.members],
                    "pos_x": sel_set.pos_x,
                    "pos_y": sel_set.pos_y,
                    "box_w": sel_set.box_w,
                    "box_h": sel_set.box_h,
                    "shape": sel_set.shape,
                    "show_name": sel_set.show_name,
                })

        else:
            self.report({'WARNING'}, "Only usable in Object Mode or Pose Mode")
            return {'CANCELLED'}

        if not data["sets"]:
            self.report({'WARNING'}, "No selection sets to export")
            return {'CANCELLED'}

        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        self.report({'INFO'}, f"Exported {len(data['sets'])} set(s) to {self.filepath}")
        return {'FINISHED'}


def _apply_layout_fields(new_set, entry_data):
    """Restore position/size/shape/label fields from an imported JSON entry."""
    new_set.pos_x = entry_data.get("pos_x", -1.0)
    new_set.pos_y = entry_data.get("pos_y", -1.0)
    new_set.box_w = entry_data.get("box_w", -1.0)
    new_set.box_h = entry_data.get("box_h", -1.0)
    shape = entry_data.get("shape", 'SQUARE')
    if shape in {'SQUARE', 'CIRCLE', 'TRIANGLE'}:
        new_set.shape = shape
    new_set.show_name = bool(entry_data.get("show_name", False))


class FREEPICKER_OT_import(bpy.types.Operator, ImportHelper):
    """Import selection sets from a JSON file exported by this addon"""
    bl_idname = "freepicker.import_sets"
    bl_label = "Import Selection Sets"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={'HIDDEN'})

    def execute(self, context):
        mode = context.mode

        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            self.report({'ERROR'}, f"Could not read file: {e}")
            return {'CANCELLED'}

        sets = data.get("sets", [])
        if not sets:
            self.report({'WARNING'}, "File contains no selection sets")
            return {'CANCELLED'}

        missing_total = 0
        imported_count = 0

        if mode == 'POSE':
            arm = context.object
            if not arm or arm.type != 'ARMATURE':
                self.report({'WARNING'}, "Active object is not an armature")
                return {'CANCELLED'}

            pose_bone_names = {pb.name for pb in arm.pose.bones}

            for entry in sets:
                bone_names = entry.get("bone_names", [])
                matched = [n for n in bone_names if n in pose_bone_names]
                missing = len(bone_names) - len(matched)
                missing_total += missing

                if not matched:
                    continue

                new_set = arm.freepicker_bone_sets.add()
                new_set.name = entry.get("name", "Imported Set")
                color = entry.get("color")
                if color and len(color) == 4:
                    new_set.color = color
                _apply_layout_fields(new_set, entry)
                for n in matched:
                    m = new_set.members.add()
                    m.bone_name = n

                imported_count += 1

        elif mode == 'OBJECT':
            scene = context.scene
            existing_names = set(bpy.data.objects.keys())

            for entry in sets:
                object_names = entry.get("object_names", [])
                matched = [n for n in object_names if n in existing_names]
                missing = len(object_names) - len(matched)
                missing_total += missing

                if not matched:
                    continue

                new_set = scene.freepicker_sets.add()
                new_set.name = entry.get("name", "Imported Set")
                color = entry.get("color")
                if color and len(color) == 4:
                    new_set.color = color
                _apply_layout_fields(new_set, entry)
                for n in matched:
                    m = new_set.members.add()
                    m.obj_name = n

                imported_count += 1

        else:
            self.report({'WARNING'}, "Only usable in Object Mode or Pose Mode")
            return {'CANCELLED'}

        if imported_count == 0:
            self.report({'WARNING'}, "No sets could be imported -- no matching names found")
            return {'CANCELLED'}

        msg = f"Imported {imported_count} set(s)"
        if missing_total:
            msg += f" ({missing_total} member name(s) not found and skipped)"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


# Right-click context menu for a single picker button. The index of the
# button that was right-clicked is stashed here just before the menu is
# invoked, since bpy.types.Menu can't take custom call-time arguments.
_context_menu_index = {"value": -1}

# (_active_panel is declared earlier, above the data classes, since the
# color-sync update callback needs it before those classes are defined.)


class FREEPICKER_OT_start_rename(bpy.types.Operator):
    """Rename this button in place -- the same inline editor used by
    double-clicking a button in Edit Mode. A native popup dialog opened
    from inside this right-click menu ends up mispositioned at the
    window's bottom-left corner, so this avoids that entirely."""
    bl_idname = "freepicker.start_rename"
    bl_label = "Rename Button"
    bl_options = {'UNDO'}

    index: bpy.props.IntProperty()

    def execute(self, context):
        panel = _active_panel["instance"]
        entry = get_layout_entry(context, self.index)
        if panel is None or entry is None:
            return {'CANCELLED'}
        panel.editing_index = self.index
        panel.edit_text = entry.name
        panel.edit_cursor = len(panel.edit_text)
        panel.edit_select_start = 0
        panel.edit_dragging_select = False
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class FREEPICKER_MT_row_menu(bpy.types.Menu):
    bl_idname = "FREEPICKER_MT_row_menu"
    bl_label = "Button"

    def draw(self, context):
        layout = self.layout
        idx = _context_menu_index["value"]
        is_pose = context.mode == 'POSE'
        add_label = "Add Bone" if is_pose else "Add Object"
        del_label = "Remove Bone" if is_pose else "Delete Object"

        op = layout.operator("freepicker.update_set", text=add_label, icon='ADD')
        op.index = idx
        op2 = layout.operator("freepicker.remove_members", text=del_label, icon='TRASH')
        op2.index = idx

        entry = get_layout_entry(context, idx)

        if entry is not None:
            name_op = layout.operator("freepicker.start_rename", text="Rename", icon='EVENT_I')
            name_op.index = idx

        layout.separator()
        layout.label(text="Shape")
        shape_row = layout.row(align=True)
        current_shape = entry.shape if entry is not None else 'SQUARE'
        for shape_id, shape_icon in (
            ('SQUARE', 'MESH_PLANE'),
            ('CIRCLE', 'MESH_CIRCLE'),
            ('TRIANGLE', 'MESH_CONE'),
        ):
            sop = shape_row.operator("freepicker.set_shape", text="", icon=shape_icon,
                                      depress=(current_shape == shape_id))
            sop.index = idx
            sop.shape = shape_id

        if entry is not None:
            layout.separator()
            # a plain property swatch opens Blender's native color-field
            # popup right at the click point -- unlike a nested operator
            # popup invoked from inside this menu, this always lands next
            # to the cursor instead of snapping to the window corner.
            color_row = layout.row(align=True)
            color_row.label(text="", icon='COLOR')
            color_row.prop(entry, "color", text="")
            panel = _active_panel["instance"]
            if panel is not None and panel.edit_mode and idx in panel.edit_selected \
                    and len(panel.edit_selected) > 1:
                layout.label(text=f"Applies to {len(panel.edit_selected)} selected buttons",
                             icon='INFO')

        layout.separator()
        dop = layout.operator("freepicker.remove_set", text="Delete Button", icon='X')
        dop.index = idx


# ---------------------------------------------------------------------------
# Floating panel -- custom-drawn UI (Animo-style)
# ---------------------------------------------------------------------------

ACCENT = (90, 170, 255)
DANGER = (230, 90, 90)
OK_GREEN = (110, 200, 120)
EDIT_YELLOW = (235, 195, 60)


class FREEPICKER_OT_floating_panel(bpy.types.Operator):
    """Open the floating FreePicker panel"""
    bl_idname = "freepicker.floating_panel"
    bl_label = "FreePicker"
    bl_options = {'REGISTER'}

    _is_open = False

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'POSE'}

    def invoke(self, context, event):
        if FREEPICKER_OT_floating_panel._is_open:
            self.report({'INFO'}, "FreePicker panel is already open")
            return {'CANCELLED'}

        if context.area is None or context.area.type != 'VIEW_3D':
            self.report({'WARNING'}, "Open this from a 3D Viewport")
            return {'CANCELLED'}

        self.width = dpi(460, context)
        self.pad = dpi(10, context)
        self.header_h = dpi(142, context)
        self.row_h = dpi(30, context)
        self.min_list_h = self.row_h + dpi(10, context)
        self.max_height = dpi(760, context)
        self.manual_height = None  # set once the user drags the corner grip vertically
        self.canvas_zoom = 1.0
        self.zoom_min = 0.3
        self.zoom_max = 3.0
        self.pan_x = 0.0
        self.panning = False
        self.pan_origin = (0, 0)
        self._pan_orig = (0.0, 0.0)
        self.footer_h = dpi(20, context)

        margin = dpi(20, context)
        self.panel_x = margin
        self.panel_y = margin

        FREEPICKER_OT_floating_panel._is_open = True

        self.dragging_panel = False
        self.drag_origin = (0, 0)
        self.resizing = False
        self.scroll_offset = 0.0
        self.closed = False
        self.rows = []
        self.row_areas = {}
        self.editing_index = None
        self.edit_text = ""
        self.edit_cursor = 0
        self.edit_select_start = None
        self.edit_dragging_select = False
        self._last_click_time = {}

        # Free-form layout editing (drag/resize individual buttons) vs
        # Lock mode (fixed layout, click / box-select to select bones).
        self.edit_mode = True
        self.grip_size = dpi(14, context)
        self.dragging_row_index = None
        self.resizing_row_index = None
        self._drag_orig_pos = (0.0, 0.0)
        self._resize_orig_size = (0.0, 0.0)

        # Box-select (marquee), only used in Lock mode.
        self.marquee_start = None
        self.marquee_end = None
        self.marquee_dragging = False
        self.marquee_press_row = None
        self.marquee_shift = False
        self.drag_threshold = dpi(4, context)

        # Multi-select in Edit Mode: box-select several buttons, then drag
        # any of them to move the whole group together.
        self.edit_selected = set()
        self._drag_group_orig = {}

        self.rebuild_rows(context)
        self.recompute_height(context)
        self.clamp_panel_position(context)

        args = (context,)
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_callback, args, 'WINDOW', 'POST_PIXEL'
        )
        self._timer = context.window_manager.event_timer_add(0.2, window=context.window)
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        _active_panel["instance"] = self
        return {'RUNNING_MODAL'}

    # -- geometry / state -----------------------------------------------

    def local_mouse(self, context, event):
        return event.mouse_x - context.region.x, event.mouse_y - context.region.y

    def rebuild_rows(self, context):
        mode = context.mode
        self.rows = []
        if mode == 'POSE':
            arm = context.object
            if arm and arm.type == 'ARMATURE':
                for i, sel_set in enumerate(arm.freepicker_bone_sets):
                    self.rows.append({
                        "index": i,
                        "name": sel_set.name,
                        "color": sel_set.color[:],
                        "highlighted": sel_set.highlighted,
                        "active": pose_set_is_active(context, sel_set),
                        "count": len(sel_set.members),
                        "pos_x": sel_set.pos_x,
                        "pos_y": sel_set.pos_y,
                        "box_w": sel_set.box_w,
                        "box_h": sel_set.box_h,
                        "shape": sel_set.shape,
                        "show_name": sel_set.show_name,
                    })
        elif mode == 'OBJECT':
            scene = context.scene
            for i, sel_set in enumerate(scene.freepicker_sets):
                self.rows.append({
                    "index": i,
                    "name": sel_set.name,
                    "color": sel_set.color[:],
                    "highlighted": sel_set.highlighted,
                    "active": object_set_is_active(context, sel_set),
                    "count": len(sel_set.members),
                    "pos_x": sel_set.pos_x,
                    "pos_y": sel_set.pos_y,
                    "box_w": sel_set.box_w,
                    "box_h": sel_set.box_h,
                    "shape": sel_set.shape,
                    "show_name": sel_set.show_name,
                })
        self.mode_cached = mode

    def recompute_height(self, context):
        if self.manual_height is not None:
            self.height = self.manual_height
        else:
            content_h = self.header_h + max(len(self.rows), 1) * self.row_h + self.pad + self.footer_h
            self.height = max(self.header_h + self.min_list_h + self.footer_h, min(content_h, self.max_height))
        self.list_view_h = self.height - self.header_h - self.pad - self.footer_h
        # scroll_offset also carries the zoom-pan offset now, so its bound
        # needs to scale with the zoom level and allow going negative
        # (panning "up" past the top row once zoomed in).
        max_scroll = max(0.0, len(self.rows) * self.row_h * self.canvas_zoom - self.list_view_h) + self.list_view_h * 3
        self.scroll_offset = max(-max_scroll, min(self.scroll_offset, max_scroll))

    def clamp_panel_position(self, context):
        region_w = context.region.width
        region_h = context.region.height
        self.panel_x = max(0, min(self.panel_x, region_w - self.width))
        self.panel_y = max(0, min(self.panel_y, region_h - self.height))

    # -- free-form layout geometry ------------------------------------------
    # pos_x / pos_y are measured from the canvas's top-left corner to the
    # button's top-left corner (pos_y grows downward). box_w / box_h are the
    # button's own size. A value of -1 means "not customized" -> fall back
    # to the original stacked, full-width row layout.

    def effective_box(self, list_w, row_data):
        box_w = row_data["box_w"] if row_data["box_w"] and row_data["box_w"] > 0 else list_w
        box_h = row_data["box_h"] if row_data["box_h"] and row_data["box_h"] > 0 else self.row_h
        return box_w, box_h

    def effective_pos(self, row_data):
        pos_x = row_data["pos_x"] if row_data["pos_x"] is not None and row_data["pos_x"] >= 0 else 0.0
        if row_data["pos_y"] is not None and row_data["pos_y"] >= 0:
            pos_y = row_data["pos_y"]
        else:
            pos_y = row_data["index"] * self.row_h
        return pos_x, pos_y

    def row_screen_rect(self, list_x, canvas_top, list_w, row_data):
        """Screen-space (x, y, w, h) for a row, y being the bottom edge,
        with the current scroll offset and canvas zoom applied. pos_x/pos_y/
        box_w/box_h stored on the data are always in unzoomed (logical)
        units; zoom only affects how they're displayed and hit-tested."""
        box_w, box_h = self.effective_box(list_w, row_data)
        pos_x, pos_y = self.effective_pos(row_data)
        z = self.canvas_zoom
        x = list_x + pos_x * z + self.pan_x
        top = canvas_top - pos_y * z + self.scroll_offset
        y = top - box_h * z
        return x, y, box_w * z, box_h * z

    # -- drawing -----------------------------------------------------------

    def draw_callback(self, context):
        try:
            self._draw_callback(context)
        except Exception as exc:
            print("Picker: draw error:", exc)

    def _header_rects(self, context):
        x, y, w = self.panel_x, self.panel_y, self.width
        top = y + self.height
        pad = self.pad
        btn = dpi(22, context)

        close_rect = (x + w - pad - btn, top - pad - btn, btn, btn)
        title_rect = (x + pad, top - pad - btn, w - 2 * pad - btn - dpi(6, context), btn)

        add_h = dpi(26, context)
        add_rect = (x + pad, top - pad - btn - dpi(8, context) - add_h, w - 2 * pad, add_h)

        toggle_h = dpi(24, context)
        toggle_gap = dpi(6, context)
        reset_w = dpi(30, context)
        toggle_y = add_rect[1] - dpi(6, context) - toggle_h
        toggle_rect = (x + pad, toggle_y, w - 2 * pad - reset_w - toggle_gap, toggle_h)
        reset_rect = (toggle_rect[0] + toggle_rect[2] + toggle_gap, toggle_y, reset_w, toggle_h)

        small_h = dpi(22, context)
        small_y = toggle_rect[1] - dpi(6, context) - small_h
        gap = dpi(6, context)
        small_w = (w - 2 * pad - gap) / 2.0
        exp_rect = (x + pad, small_y, small_w, small_h)
        imp_rect = (exp_rect[0] + small_w + gap, small_y, small_w, small_h)

        return {
            "close": close_rect, "title": title_rect, "add": add_rect,
            "layout_toggle": toggle_rect, "layout_reset": reset_rect,
            "export": exp_rect, "import": imp_rect,
        }

    def _draw_callback(self, context):
        if self.mode_cached != context.mode:
            self.rebuild_rows(context)
            self.recompute_height(context)

        x, y, w, h = self.panel_x, self.panel_y, self.width, self.height
        draw_rounded_rect(x, y, w, h, dpi(14, context), (0.16, 0.16, 0.17, 0.92))
        draw_rounded_rect_outline(x, y, w, h, dpi(14, context), (0.05, 0.05, 0.05, 0.6), width=1.0)

        r = self._header_rects(context)
        mode_label = "Pose Mode (Bones)" if context.mode == 'POSE' else "Object Mode"
        draw_text(r["title"][0], r["title"][1] + dpi(4, context), mode_label,
                  max(9, dpi(12, context)), (0.85, 0.85, 0.85, 1.0))
        if abs(self.canvas_zoom - 1.0) > 0.001:
            zoom_text = f"{int(round(self.canvas_zoom * 100))}%"
            tx, ty, tw, th = r["title"]
            font_size = max(8, dpi(10, context))
            blf.size(0, font_size)
            zw = blf.dimensions(0, zoom_text)[0]
            draw_text(tx + tw - zw, ty + dpi(4, context), zoom_text, font_size,
                      (0.6, 0.75, 1.0, 1.0))

        cx0, cy0, cw, ch = r["close"]
        draw_rounded_rect(cx0, cy0, cw, ch, dpi(6, context), rgb01(DANGER, 0.85))
        draw_text(cx0, cy0 + ch * 0.16, "x", max(14, dpi(20, context)), (1, 1, 1, 1), align_center_width=cw)

        ax, ay, aw, ah = r["add"]
        draw_rounded_rect(ax, ay, aw, ah, dpi(8, context), rgb01(ACCENT, 0.9))
        draw_text(ax, ay + ah * 0.28, "+  Add From Selection", max(9, dpi(12, context)),
                  (1, 1, 1, 1), align_center_width=aw)

        tx, ty, tw, th = r["layout_toggle"]
        toggle_color = rgb01(EDIT_YELLOW, 0.95) if self.edit_mode else rgb01((90, 130, 200), 0.9)
        toggle_label = "Edit Mode" if self.edit_mode else "Locked"
        toggle_text_color = (0.1, 0.1, 0.1, 1.0) if self.edit_mode else (1, 1, 1, 1)
        draw_rounded_rect(tx, ty, tw, th, dpi(6, context), toggle_color)
        draw_text(tx, ty + th * 0.22, toggle_label, max(8, dpi(10, context)),
                  toggle_text_color, align_center_width=tw)

        rx0, ry0, rw0, rh0 = r["layout_reset"]
        draw_rounded_rect(rx0, ry0, rw0, rh0, dpi(6, context), rgb01((70, 70, 72), 0.9))
        draw_text(rx0, ry0 + rh0 * 0.12, "\u21bb", max(11, dpi(15, context)), (0.9, 0.9, 0.9, 1.0),
                  align_center_width=rw0)

        for key, label in (("export", "Export"), ("import", "Import")):
            bx, by, bw, bh = r[key]
            draw_rounded_rect(bx, by, bw, bh, dpi(6, context), rgb01((70, 70, 72), 0.9))
            draw_text(bx, by + bh * 0.22, label, max(8, dpi(10, context)),
                      (0.9, 0.9, 0.9, 1.0), align_center_width=bw)

        # -- list area, scissor-clipped and scrollable --
        list_x = x + self.pad
        list_y = y + self.pad + self.footer_h
        list_w = w - 2 * self.pad
        list_h = self.list_view_h

        gpu.state.scissor_test_set(True)
        gpu.state.scissor_set(int(list_x), int(list_y), max(1, int(list_w)), max(1, int(list_h)))
        try:
            if not self.rows:
                draw_text(list_x, list_y + list_h / 2.0, "No selection sets yet",
                          max(8, dpi(11, context)), (0.6, 0.6, 0.6, 1.0))
            else:
                canvas_top = list_y + list_h
                for row_data in self.rows:
                    rx, ry, rw, rh = self.row_screen_rect(list_x, canvas_top, list_w, row_data)
                    if ry + rh < list_y - self.row_h or ry > list_y + list_h + self.row_h:
                        continue
                    self.draw_row(context, rx, ry, rw, rh, row_data)
                    if self.edit_mode:
                        is_sel = row_data["index"] in self.edit_selected
                        if is_sel:
                            draw_rounded_rect(rx, ry, rw, rh, dpi(6, context), (0.35, 0.6, 1.0, 0.22))
                        outline_color = rgb01((90, 170, 255), 0.95) if is_sel else rgb01(ACCENT, 0.55)
                        outline_w = 2.2 if is_sel else 1.5
                        draw_rounded_rect_outline(rx, ry, rw, rh, dpi(6, context),
                                                   outline_color, width=outline_w)
                        gx = rx + rw - dpi(3, context)
                        gy = ry + dpi(9, context)
                        for row in range(3):
                            for col in range(row + 1):
                                draw_circle(gx - col * dpi(3, context), gy - row * dpi(3, context),
                                            max(1.2, dpi(1.2, context)), (1, 1, 1, 0.7))

            if self.marquee_dragging and self.marquee_start is not None and self.marquee_end is not None:
                mx, my, mw, mh = self._normalize_rect(self.marquee_start, self.marquee_end)
                draw_rounded_rect(mx, my, mw, mh, 0, rgb01((90, 170, 255), 0.15))
                draw_rounded_rect_outline(mx, my, mw, mh, 0, rgb01((90, 170, 255), 0.9), width=1.2)
        finally:
            gpu.state.scissor_test_set(False)

        # bottom-left hint strip: small always-visible instructions
        hint = "Scroll: list \u00b7 Ctrl+Scroll: zoom \u00b7 MMB drag: pan"
        draw_text(x + self.pad, y + dpi(4, context), hint, max(9, dpi(11, context)),
                  (0.55, 0.55, 0.55, 0.85))

        # resize grip, bottom-right corner
        grip_dot = max(1.5, dpi(1.5, context))
        gx = x + w - dpi(6, context)
        gy = y + dpi(14, context)
        for row in range(3):
            for col in range(row + 1):
                draw_circle(gx - col * dpi(4, context), gy - row * dpi(4, context),
                            grip_dot, (0.75, 0.75, 0.75, 0.5))

    def draw_row(self, context, x, y, w, h, row_data):
        pad_in = dpi(3, context)

        rects = self.row_rects(x, y, w, h)
        box_rect = rects["box"]

        bx, by, bw, bh = box_rect
        shape = row_data.get("shape", 'SQUARE')
        color = rgb01(tuple(int(c * 255) for c in row_data["color"][:3]), 0.95)
        radius = dpi(5, context)

        def tri_points(px, py, pw, ph):
            return (px + pw / 2.0, py + ph), (px, py), (px + pw, py)

        if shape == 'CIRCLE':
            cx, cy = bx + bw / 2.0, by + bh / 2.0
            r = min(bw, bh) / 2.0
            draw_circle(cx, cy, r, color)
            if row_data["highlighted"]:
                draw_circle(cx, cy, r, (1, 1, 1, 0.12))
            if row_data["active"]:
                draw_circle_outline(cx, cy, r + 1.5, (0.35, 1.0, 0.35, 0.35), width=3.0)
                draw_circle_outline(cx, cy, r, (0.55, 1.0, 0.45, 1.0), width=1.6)

        elif shape == 'TRIANGLE':
            p1, p2, p3 = tri_points(bx, by, bw, bh)
            draw_triangle(p1, p2, p3, color)
            if row_data["highlighted"]:
                draw_triangle(p1, p2, p3, (1, 1, 1, 0.12))
            if row_data["active"]:
                pad = 1.5
                p1o, p2o, p3o = tri_points(bx - pad, by - pad, bw + 2 * pad, bh + 2 * pad)
                draw_triangle_outline(p1o, p2o, p3o, (0.35, 1.0, 0.35, 0.35), width=3.0)
                draw_triangle_outline(p1, p2, p3, (0.55, 1.0, 0.45, 1.0), width=1.6)

        else:  # SQUARE (default)
            draw_rounded_rect(bx, by, bw, bh, radius, color)
            if row_data["highlighted"]:
                draw_rounded_rect(bx, by, bw, bh, radius, (1, 1, 1, 0.12))
            if row_data["active"]:
                draw_rounded_rect_outline(bx - 1.5, by - 1.5, bw + 3, bh + 3, dpi(6, context),
                                           (0.35, 1.0, 0.35, 0.35), width=3.0)
                draw_rounded_rect_outline(bx, by, bw, bh, radius,
                                           (0.55, 1.0, 0.45, 1.0), width=1.6)

        # optional name label -- hidden by default, turned on per-button via
        # the right-click menu ("Add Name")
        if row_data.get("show_name") and row_data.get("name") and self.editing_index != row_data["index"]:
            font_size = max(7, int(min(bw, bh) * 0.28))
            label = clip_text(row_data["name"], font_size, max(4, bw - 6))
            draw_text_vcenter(bx, by, bh, label, font_size, (1, 1, 1, 0.95), align_center_width=bw)

        # rename editing overlay (Edit Mode, double-click) -- still works even
        # though the name isn't shown while at rest.
        if self.editing_index == row_data["index"]:
            font_size = max(8, dpi(11, context))
            nx, ny, nw, nh = bx + pad_in, by, bw - 2 * pad_in, bh
            box_x, box_y, box_w2, box_h2 = nx - 4, ny + 2, nw + 8, nh - 4
            draw_rounded_rect(box_x, box_y, box_w2, box_h2, dpi(4, context), (0.05, 0.05, 0.05, 0.95))
            draw_rounded_rect_outline(box_x, box_y, box_w2, box_h2, dpi(4, context),
                                       rgb01(ACCENT, 0.9), width=1.2)

            text = self.edit_text
            blf.size(0, font_size)
            if self.edit_select_start is not None and self.edit_select_start != self.edit_cursor:
                a, b = sorted((self.edit_select_start, self.edit_cursor))
                xa = nx + blf.dimensions(0, text[:a])[0]
                xb = nx + blf.dimensions(0, text[:b])[0]
                draw_rounded_rect(xa, ny + 3, max(2.0, xb - xa), nh - 6, 2, rgb01(ACCENT, 0.45))

            draw_text_vcenter(nx, ny, nh, text, font_size, (1, 1, 1, 1))

            if int(time.time() * 2) % 2 == 0:
                cxpos = nx + blf.dimensions(0, text[:self.edit_cursor])[0]
                draw_rounded_rect(cxpos, ny + 3, max(1.0, dpi(1, context)), nh - 6, 0, (1, 1, 1, 0.9))

    def row_rects(self, x, y, w, h=None):
        h = h if h is not None else self.row_h
        pad_in = 2
        box_rect = (x + pad_in, y + pad_in, max(4, w - 2 * pad_in), max(4, h - 2 * pad_in))

        return {
            # "swatch"/"name" kept as aliases of the whole box so double-click
            # rename hit-testing (Edit Mode) still works without a visible label.
            "swatch": box_rect, "name": box_rect, "box": box_rect,
        }

    # -- hit testing -----------------------------------------------------

    def point_in(self, px, py, rect):
        rx, ry, rw, rh = rect
        return rx <= px <= rx + rw and ry <= py <= ry + rh

    def _canvas_geom(self):
        list_x = self.panel_x + self.pad
        list_y = self.panel_y + self.pad + self.footer_h
        list_w = self.width - 2 * self.pad
        list_h = self.list_view_h
        canvas_top = list_y + list_h
        return list_x, list_y, list_w, list_h, canvas_top

    def _row_screen_rect_now(self, row_data):
        list_x, list_y, list_w, list_h, canvas_top = self._canvas_geom()
        return self.row_screen_rect(list_x, canvas_top, list_w, row_data)

    @staticmethod
    def _normalize_rect(p1, p2):
        x = min(p1[0], p2[0])
        y = min(p1[1], p2[1])
        w = abs(p2[0] - p1[0])
        h = abs(p2[1] - p1[1])
        return (x, y, w, h)

    @staticmethod
    def _rects_intersect(a, b):
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by

    def hit_row_at(self, lx, ly):
        list_x, list_y, list_w, list_h, canvas_top = self._canvas_geom()
        if not (list_x <= lx <= list_x + list_w and list_y <= ly <= list_y + list_h):
            return None, None, None
        # iterate back-to-front so the most-recently-drawn (last) row wins on overlap
        for row_data in reversed(self.rows):
            rx, ry, rw, rh = self.row_screen_rect(list_x, canvas_top, list_w, row_data)
            if rx <= lx <= rx + rw and ry <= ly <= ry + rh:
                rects = self.row_rects(rx, ry, rw, rh)
                return row_data, rects, (rx, ry, rw, rh)
        return None, None, None

    def _editing_row_rect(self, context):
        if self.editing_index is None:
            return None
        list_x = self.panel_x + self.pad
        list_y = self.panel_y + self.pad + self.footer_h
        list_w = self.width - 2 * self.pad
        canvas_top = list_y + self.list_view_h
        row_data = next((r for r in self.rows if r["index"] == self.editing_index), None)
        if row_data is None:
            return None
        rx, ry, rw, rh = self.row_screen_rect(list_x, canvas_top, list_w, row_data)
        rects = self.row_rects(rx, ry, rw, rh)
        return rects["name"]

    def confirm_edit(self, context):
        if self.editing_index is None:
            return
        i = self.editing_index
        new_name = self.edit_text.strip()
        entry = get_layout_entry(context, i)
        if entry is not None:
            if new_name:
                entry.name = new_name
                entry.show_name = True
            else:
                # confirming with an empty field just hides the label again,
                # it doesn't touch the button's internal identifier
                entry.show_name = False
        self.editing_index = None
        self.edit_text = ""
        self.edit_cursor = 0
        self.edit_select_start = None
        self.edit_dragging_select = False
        self.rebuild_rows(context)

    def delete_selection(self):
        if self.edit_select_start is None or self.edit_select_start == self.edit_cursor:
            return False
        a, b = sorted((self.edit_select_start, self.edit_cursor))
        self.edit_text = self.edit_text[:a] + self.edit_text[b:]
        self.edit_cursor = a
        self.edit_select_start = None
        return True

    def cancel_edit(self):
        self.editing_index = None
        self.edit_text = ""
        self.edit_cursor = 0
        self.edit_select_start = None
        self.edit_dragging_select = False

    def finish(self, context):
        FREEPICKER_OT_floating_panel._is_open = False
        if _active_panel["instance"] is self:
            _active_panel["instance"] = None
        try:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
        except Exception:
            pass
        try:
            context.window_manager.event_timer_remove(self._timer)
        except Exception:
            pass
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}

    # -- modal -------------------------------------------------------------

    def modal(self, context, event):
        if self.closed:
            return self.finish(context)
        if context.area is not None:
            context.area.tag_redraw()
        lx, ly = self.local_mouse(context, event)

        if event.type == 'TIMER':
            self.rebuild_rows(context)
            self.recompute_height(context)
            self.clamp_panel_position(context)
            return {'RUNNING_MODAL'}

        if self.editing_index is not None:
            if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                rect = self._editing_row_rect(context)
                box_hit = rect is not None and self.point_in(
                    lx, ly, (rect[0] - 6, rect[1], rect[2] + 12, rect[3]))
                if box_hit:
                    idx = char_index_at_x(self.edit_text, max(8, dpi(11, context)), rect[0], lx)
                    self.edit_cursor = idx
                    self.edit_select_start = idx
                    self.edit_dragging_select = True
                else:
                    self.confirm_edit(context)
                return {'RUNNING_MODAL'}
            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                self.edit_dragging_select = False
                return {'RUNNING_MODAL'}
            if event.type == 'MOUSEMOVE' and self.edit_dragging_select:
                rect = self._editing_row_rect(context)
                if rect:
                    self.edit_cursor = char_index_at_x(
                        self.edit_text, max(8, dpi(11, context)), rect[0], lx)
                return {'RUNNING_MODAL'}

            if event.type == 'LEFT_ARROW' and event.value == 'PRESS':
                if event.shift:
                    if self.edit_select_start is None:
                        self.edit_select_start = self.edit_cursor
                    self.edit_cursor = max(0, self.edit_cursor - 1)
                else:
                    if self.edit_select_start is not None and self.edit_select_start != self.edit_cursor:
                        self.edit_cursor = min(self.edit_select_start, self.edit_cursor)
                    else:
                        self.edit_cursor = max(0, self.edit_cursor - 1)
                    self.edit_select_start = None
                return {'RUNNING_MODAL'}
            if event.type == 'RIGHT_ARROW' and event.value == 'PRESS':
                if event.shift:
                    if self.edit_select_start is None:
                        self.edit_select_start = self.edit_cursor
                    self.edit_cursor = min(len(self.edit_text), self.edit_cursor + 1)
                else:
                    if self.edit_select_start is not None and self.edit_select_start != self.edit_cursor:
                        self.edit_cursor = max(self.edit_select_start, self.edit_cursor)
                    else:
                        self.edit_cursor = min(len(self.edit_text), self.edit_cursor + 1)
                    self.edit_select_start = None
                return {'RUNNING_MODAL'}
            if event.type == 'HOME' and event.value == 'PRESS':
                if event.shift and self.edit_select_start is None:
                    self.edit_select_start = self.edit_cursor
                elif not event.shift:
                    self.edit_select_start = None
                self.edit_cursor = 0
                return {'RUNNING_MODAL'}
            if event.type == 'END' and event.value == 'PRESS':
                if event.shift and self.edit_select_start is None:
                    self.edit_select_start = self.edit_cursor
                elif not event.shift:
                    self.edit_select_start = None
                self.edit_cursor = len(self.edit_text)
                return {'RUNNING_MODAL'}

            if event.type == 'DEL' and event.value == 'PRESS':
                if not self.delete_selection() and self.edit_cursor < len(self.edit_text):
                    self.edit_text = self.edit_text[:self.edit_cursor] + self.edit_text[self.edit_cursor + 1:]
                return {'RUNNING_MODAL'}
            if event.type == 'BACK_SPACE' and event.value == 'PRESS':
                if not self.delete_selection() and self.edit_cursor > 0:
                    self.edit_text = self.edit_text[:self.edit_cursor - 1] + self.edit_text[self.edit_cursor:]
                    self.edit_cursor -= 1
                return {'RUNNING_MODAL'}
            if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
                self.confirm_edit(context)
                return {'RUNNING_MODAL'}
            if event.type == 'ESC' and event.value == 'PRESS':
                self.cancel_edit()
                return {'RUNNING_MODAL'}
            if event.type == 'A' and event.value == 'PRESS' and event.ctrl:
                self.edit_select_start = 0
                self.edit_cursor = len(self.edit_text)
                return {'RUNNING_MODAL'}
            if event.value == 'PRESS' and event.unicode and event.unicode.isprintable() \
                    and not event.ctrl and not event.oskey:
                self.delete_selection()
                self.edit_text = self.edit_text[:self.edit_cursor] + event.unicode + self.edit_text[self.edit_cursor:]
                self.edit_cursor += 1
                return {'RUNNING_MODAL'}
            if event.type == 'TEXTINPUT':
                if event.unicode and event.unicode.isprintable():
                    self.delete_selection()
                    self.edit_text = self.edit_text[:self.edit_cursor] + event.unicode + self.edit_text[self.edit_cursor:]
                    self.edit_cursor += 1
                return {'RUNNING_MODAL'}
            # swallow every other event so viewport shortcuts don't fire while typing
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            if self.panning:
                dx = lx - self.pan_origin[0]
                dy = ly - self.pan_origin[1]
                self.pan_x = self._pan_orig[0] + dx
                self.scroll_offset = self._pan_orig[1] + dy
                return {'RUNNING_MODAL'}
            if self.marquee_start is not None:
                dx = lx - self.marquee_start[0]
                dy = ly - self.marquee_start[1]
                if not self.marquee_dragging and (abs(dx) > self.drag_threshold or abs(dy) > self.drag_threshold):
                    self.marquee_dragging = True
                if self.marquee_dragging:
                    self.marquee_end = (lx, ly)
                return {'RUNNING_MODAL'}
            if self.dragging_row_index is not None:
                z = self.canvas_zoom
                dx = (lx - self.drag_origin[0]) / z
                dy = (ly - self.drag_origin[1]) / z
                for idx, orig_pos in self._drag_group_orig.items():
                    entry = get_layout_entry(context, idx)
                    if entry:
                        entry.pos_x = max(0.0, orig_pos[0] + dx)
                        entry.pos_y = max(0.0, orig_pos[1] - dy)
                self.rebuild_rows(context)
                self.recompute_height(context)
                return {'RUNNING_MODAL'}
            if self.resizing_row_index is not None:
                z = self.canvas_zoom
                dx = (lx - self.drag_origin[0]) / z
                dy = (ly - self.drag_origin[1]) / z
                entry = get_layout_entry(context, self.resizing_row_index)
                if entry:
                    entry.box_w = max(dpi(20, context), self._resize_orig_size[0] + dx)
                    entry.box_h = max(dpi(20, context), self._resize_orig_size[1] - dy)
                self.rebuild_rows(context)
                self.recompute_height(context)
                return {'RUNNING_MODAL'}
            if self.dragging_panel:
                dx = lx - self.drag_origin[0]
                dy = ly - self.drag_origin[1]
                self.panel_x += dx
                self.panel_y += dy
                self.drag_origin = (lx, ly)
                self.clamp_panel_position(context)
                return {'RUNNING_MODAL'}
            if self.resizing:
                region_h = context.region.height
                new_w = max(dpi(220, context), lx - self.panel_x)
                new_h = max(dpi(160, context), self._resize_top_anchor - ly)
                new_h = min(new_h, region_h - dpi(10, context))
                self.width = new_w
                self.manual_height = new_h
                self.panel_y = self._resize_top_anchor - new_h
                self.recompute_height(context)
                self.clamp_panel_position(context)
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}

        if event.type == 'MIDDLEMOUSE' and event.value == 'PRESS':
            if (self.panel_x <= lx <= self.panel_x + self.width and
                    self.panel_y <= ly <= self.panel_y + self.height):
                self.panning = True
                self.pan_origin = (lx, ly)
                self._pan_orig = (self.pan_x, self.scroll_offset)
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}

        if event.type == 'MIDDLEMOUSE' and event.value == 'RELEASE':
            if self.panning:
                self.panning = False
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}

        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            if (self.panel_x <= lx <= self.panel_x + self.width and
                    self.panel_y <= ly <= self.panel_y + self.height):
                row_data, rects, row_rect = self.hit_row_at(lx, ly)
                if row_data is not None:
                    _context_menu_index["value"] = row_data["index"]
                    bpy.ops.wm.call_menu(name="FREEPICKER_MT_row_menu")
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}

        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            list_x = self.panel_x + self.pad
            list_y = self.panel_y + self.pad + self.footer_h
            list_w = self.width - 2 * self.pad
            if list_x <= lx <= list_x + list_w and list_y <= ly <= list_y + self.list_view_h:
                if event.ctrl:
                    # Ctrl + Scroll = zoom the canvas in/out, anchored on the
                    # mouse position (both axes) so whatever's under the
                    # cursor stays put instead of the zoom pivoting from the
                    # canvas's top-left corner.
                    old_zoom = self.canvas_zoom
                    factor = 1.1 if event.type == 'WHEELUPMOUSE' else (1.0 / 1.1)
                    new_zoom = max(self.zoom_min, min(self.zoom_max, old_zoom * factor))
                    if new_zoom != old_zoom:
                        canvas_top = list_y + self.list_view_h
                        # vertical: keep (mouse - canvas_top) in canvas space
                        # the same before/after the zoom change
                        rel_y = (canvas_top + self.scroll_offset) - ly
                        rel_y_new = rel_y * (new_zoom / old_zoom)
                        self.scroll_offset = (ly + rel_y_new) - canvas_top
                        # horizontal: same idea, relative to the canvas's left edge
                        rel_x = lx - (list_x + self.pan_x)
                        rel_x_new = rel_x * (new_zoom / old_zoom)
                        self.pan_x = lx - rel_x_new - list_x
                        self.canvas_zoom = new_zoom
                    return {'RUNNING_MODAL'}
                step = self.row_h * self.canvas_zoom
                max_scroll = max(0.0, len(self.rows) * self.row_h * self.canvas_zoom - self.list_view_h)
                if event.type == 'WHEELUPMOUSE':
                    self.scroll_offset = max(-max_scroll, self.scroll_offset - step)
                else:
                    self.scroll_offset = min(max_scroll, self.scroll_offset + step)
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if not (self.panel_x <= lx <= self.panel_x + self.width and
                    self.panel_y <= ly <= self.panel_y + self.height):
                return {'PASS_THROUGH'}

            r = self._header_rects(context)

            if self.point_in(lx, ly, r["close"]):
                self.closed = True
                return {'RUNNING_MODAL'}

            # the panel can only be dragged from the title bar row, in any mode
            title_x, title_y, title_w, title_h = r["title"]
            if (title_y <= ly <= title_y + title_h and
                    self.panel_x <= lx <= self.panel_x + self.width):
                self.dragging_panel = True
                self.drag_origin = (lx, ly)
                return {'RUNNING_MODAL'}

            # resize grip, bottom-right corner
            grip_zone = (self.panel_x + self.width - dpi(16, context), self.panel_y,
                         dpi(16, context), dpi(16, context))
            if self.point_in(lx, ly, grip_zone):
                self.resizing = True
                self._resize_top_anchor = self.panel_y + self.height
                return {'RUNNING_MODAL'}

            if self.point_in(lx, ly, r["add"]):
                bpy.ops.freepicker.add_set()
                self.rebuild_rows(context)
                self.recompute_height(context)
                return {'RUNNING_MODAL'}
            if self.point_in(lx, ly, r["layout_toggle"]):
                self.edit_mode = not self.edit_mode
                if self.edit_mode:
                    # entering Edit Mode: clear the viewport selection so the
                    # green "currently selected" outline doesn't linger on
                    # buttons while you're just arranging the layout
                    apply_picker_selection(context, [], extend=False)
                    self.rebuild_rows(context)
                return {'RUNNING_MODAL'}
            if self.point_in(lx, ly, r["layout_reset"]):
                for row_data in self.rows:
                    entry = get_layout_entry(context, row_data["index"])
                    if entry:
                        entry.pos_x = -1.0
                        entry.pos_y = -1.0
                        entry.box_w = -1.0
                        entry.box_h = -1.0
                self.canvas_zoom = 1.0
                self.scroll_offset = 0.0
                self.rebuild_rows(context)
                self.recompute_height(context)
                return {'RUNNING_MODAL'}
            if self.point_in(lx, ly, r["export"]):
                bpy.ops.freepicker.export_sets('INVOKE_DEFAULT')
                return {'RUNNING_MODAL'}
            if self.point_in(lx, ly, r["import"]):
                bpy.ops.freepicker.import_sets('INVOKE_DEFAULT')
                return {'RUNNING_MODAL'}

            row_data, rects, row_rect = self.hit_row_at(lx, ly)

            if self.edit_mode:
                if row_data is not None:
                    i = row_data["index"]
                    rrx, rry, rrw, rrh = row_rect
                    grip = (rrx + rrw - self.grip_size, rry, self.grip_size, self.grip_size)
                    if self.point_in(lx, ly, grip):
                        self.resizing_row_index = i
                        self.drag_origin = (lx, ly)
                        list_w = self.width - 2 * self.pad
                        self._resize_orig_size = self.effective_box(list_w, row_data)
                        return {'RUNNING_MODAL'}
                    now = time.time()
                    last = self._last_click_time.get(i, 0.0)
                    self._last_click_time[i] = now
                    if now - last < DOUBLE_CLICK_THRESHOLD:
                        self._last_click_time.pop(i, None)
                        self.editing_index = i
                        self.edit_text = row_data["name"]
                        self.edit_cursor = len(self.edit_text)
                        self.edit_select_start = 0
                        self.edit_dragging_select = False
                        return {'RUNNING_MODAL'}

                    if event.shift:
                        # shift-click only toggles membership in the group,
                        # it doesn't start a drag by itself
                        if i in self.edit_selected:
                            self.edit_selected.discard(i)
                        else:
                            self.edit_selected.add(i)
                        return {'RUNNING_MODAL'}

                    # plain click on the body -> move it (and, if it's part of
                    # a bigger selection, drag the whole group together)
                    if i not in self.edit_selected:
                        self.edit_selected = {i}
                    rows_by_index = {r2["index"]: r2 for r2 in self.rows}
                    self.drag_origin = (lx, ly)
                    self._drag_group_orig = {
                        idx: self.effective_pos(rows_by_index[idx])
                        for idx in self.edit_selected if idx in rows_by_index
                    }
                    self.dragging_row_index = i  # marks "a group drag is active"
                    return {'RUNNING_MODAL'}

                # empty canvas space in Edit Mode, click-drag = box-select
                # (select several buttons so they can be dragged together)
                self.marquee_start = (lx, ly)
                self.marquee_end = (lx, ly)
                self.marquee_dragging = False
                self.marquee_press_row = None
                self.marquee_shift = event.shift
                return {'RUNNING_MODAL'}

            else:
                # LOCK MODE: single click selects; click-drag = box-select (marquee)
                self.marquee_start = (lx, ly)
                self.marquee_end = (lx, ly)
                self.marquee_dragging = False
                self.marquee_press_row = row_data["index"] if row_data is not None else None
                self.marquee_shift = event.shift
                return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if self.marquee_start is not None:
                if self.edit_mode:
                    # marquee in Edit Mode selects buttons for group drag,
                    # it never touches the actual bone/object selection
                    if self.marquee_dragging:
                        rect = self._normalize_rect(self.marquee_start, self.marquee_end)
                        hits = {row["index"] for row in self.rows
                                if self._rects_intersect(self._row_screen_rect_now(row), rect)}
                        if self.marquee_shift:
                            self.edit_selected |= hits
                        else:
                            self.edit_selected = hits
                    elif not self.marquee_shift:
                        self.edit_selected = set()
                else:
                    if self.marquee_dragging:
                        rect = self._normalize_rect(self.marquee_start, self.marquee_end)
                        hits = [row["index"] for row in self.rows
                                if self._rects_intersect(self._row_screen_rect_now(row), rect)]
                        apply_picker_selection(context, hits, extend=self.marquee_shift)
                        self.rebuild_rows(context)
                    else:
                        if self.marquee_press_row is not None:
                            apply_picker_selection(context, [self.marquee_press_row], extend=self.marquee_shift)
                            self.rebuild_rows(context)
                        elif not self.marquee_shift:
                            apply_picker_selection(context, [], extend=False)
                            self.rebuild_rows(context)
                self.marquee_start = None
                self.marquee_end = None
                self.marquee_dragging = False
                self.marquee_press_row = None
                return {'RUNNING_MODAL'}
            if self.dragging_row_index is not None or self.resizing_row_index is not None:
                self.dragging_row_index = None
                self.resizing_row_index = None
                self._drag_group_orig = {}
                return {'RUNNING_MODAL'}
            if self.dragging_panel or self.resizing:
                self.dragging_panel = False
                self.resizing = False
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}

        if event.type == 'ESC':
            self.closed = True
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}


# ---------------------------------------------------------------------------
# Viewport header button (top strip, next to the mode dropdown)
# ---------------------------------------------------------------------------

def draw_picker_header_button(self, context):
    if context.mode in {'OBJECT', 'POSE'}:
        self.layout.operator("freepicker.floating_panel", icon='WINDOW', text="FreePicker")


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

classes = (
    FREEPICKER_member,
    FREEPICKER_set,
    FREEPICKER_bone_member,
    FREEPICKER_pose_set,
    FREEPICKER_OT_add,
    FREEPICKER_OT_select,
    FREEPICKER_OT_update,
    FREEPICKER_OT_remove_members,
    FREEPICKER_OT_set_shape,
    FREEPICKER_OT_start_rename,
    FREEPICKER_OT_remove,
    FREEPICKER_OT_export,
    FREEPICKER_OT_import,
    FREEPICKER_MT_row_menu,
    FREEPICKER_OT_floating_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    FREEPICKER_OT_floating_panel._is_open = False
    bpy.types.Scene.freepicker_sets = bpy.props.CollectionProperty(type=FREEPICKER_set)
    bpy.types.Object.freepicker_bone_sets = bpy.props.CollectionProperty(type=FREEPICKER_pose_set)
    bpy.types.VIEW3D_HT_header.append(draw_picker_header_button)


def unregister():
    bpy.types.VIEW3D_HT_header.remove(draw_picker_header_button)
    del bpy.types.Object.freepicker_bone_sets
    del bpy.types.Scene.freepicker_sets
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
