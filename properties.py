import bpy

_active_panel = {"instance": None}
_last_geometry = {
    "width": None, "manual_height": None, "panel_x": None, "panel_y": None,
}
_color_sync_guard = {"active": False}
_context_menu_index = {"value": -1}

_OVR = {'LIBRARY_OVERRIDABLE'}
_OVR_COLLECTION = {'LIBRARY_OVERRIDABLE', 'USE_INSERTION', 'NO_PROPERTY_NAME'}

SHAPE_ITEMS = [
    ('SQUARE', "Square", ""),
    ('CIRCLE', "Circle", ""),
    ('TRIANGLE', "Triangle", ""),
]

def _get_broadcast_group(panel, idx):
    if panel is None:
        return {idx}
    if getattr(panel, "edit_mode", False):
        group = set(getattr(panel, "edit_selected", None) or set())
    else:
        group = {row["index"] for row in getattr(panel, "rows", []) if row.get("active")}
    if idx in group and len(group) > 1:
        return group
    return {idx}

def get_layout_entry(context, index):
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

def _sync_color_to_selection(entry, context):
    if _color_sync_guard["active"]:
        return
    panel = _active_panel["instance"]
    if panel is None:
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

    if idx is None:
        return

    selected = _get_broadcast_group(panel, idx)
    if len(selected) <= 1:
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

class FREEPICKER_member(bpy.types.PropertyGroup):
    obj_name: bpy.props.StringProperty(override=_OVR)

class FREEPICKER_bone_member(bpy.types.PropertyGroup):
    bone_name: bpy.props.StringProperty(override=_OVR)

class FREEPICKER_set(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name="Set Name", default="Set", override=_OVR)
    color: bpy.props.FloatVectorProperty(
        name="Tag Color", subtype='COLOR', size=4,
        default=(0.5, 0.5, 0.5, 1.0), min=0.0, max=1.0,
        update=_sync_color_to_selection,
        override=_OVR,
    )
    members: bpy.props.CollectionProperty(type=FREEPICKER_member, override=_OVR_COLLECTION)
    pos_x: bpy.props.FloatProperty(default=-1.0, override=_OVR)
    pos_y: bpy.props.FloatProperty(default=-1.0, override=_OVR)
    box_w: bpy.props.FloatProperty(default=-1.0, override=_OVR)
    box_h: bpy.props.FloatProperty(default=-1.0, override=_OVR)
    shape: bpy.props.EnumProperty(items=SHAPE_ITEMS, default='SQUARE', override=_OVR)
    show_name: bpy.props.BoolProperty(default=False, override=_OVR)

class FREEPICKER_pose_set(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name="Set Name", default="Set", override=_OVR)
    color: bpy.props.FloatVectorProperty(
        name="Tag Color", subtype='COLOR', size=4,
        default=(0.5, 0.5, 0.5, 1.0), min=0.0, max=1.0,
        update=_sync_color_to_selection,
        override=_OVR,
    )
    members: bpy.props.CollectionProperty(type=FREEPICKER_bone_member, override=_OVR_COLLECTION)
    pos_x: bpy.props.FloatProperty(default=-1.0, override=_OVR)
    pos_y: bpy.props.FloatProperty(default=-1.0, override=_OVR)
    box_w: bpy.props.FloatProperty(default=-1.0, override=_OVR)
    box_h: bpy.props.FloatProperty(default=-1.0, override=_OVR)
    shape: bpy.props.EnumProperty(items=SHAPE_ITEMS, default='SQUARE', override=_OVR)
    show_name: bpy.props.BoolProperty(default=False, override=_OVR)

classes = (
    FREEPICKER_member,
    FREEPICKER_bone_member,
    FREEPICKER_set,
    FREEPICKER_pose_set,
)
