bl_info = {
    "name": "FreePicker",
    "author": "dirun",
    "version": (4, 7, 1),
    "blender": (5, 0, 0),
    "location": "View3D header (Object/Pose Mode) > FreePicker button",
    "description": "A fully self-contained picker with custom Pose/Object sets and a floating editable panel.",
    "category": "Rigging",
}

import bpy
from .core import *
from .operators import *
from .panel import *

# Keep registration order explicit: PropertyGroups first, then operators/menus.
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
    FREEPICKER_OT_duplicate,
    FREEPICKER_OT_remove,
    FREEPICKER_OT_export,
    FREEPICKER_OT_import_choice,
    FREEPICKER_OT_import,
    FREEPICKER_MT_row_menu,
    FREEPICKER_OT_floating_panel,
)

def draw_picker_header_button(self, context):
    if context.mode in {'OBJECT', 'POSE'}:
        self.layout.operator("freepicker.floating_panel", icon='WINDOW', text="FreePicker")

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    FREEPICKER_OT_floating_panel._is_open = False
    bpy.types.Scene.freepicker_sets = bpy.props.CollectionProperty(
        type=FREEPICKER_set, override=_OVR_COLLECTION)
    bpy.types.Object.freepicker_bone_sets = bpy.props.CollectionProperty(
        type=FREEPICKER_pose_set, override=_OVR_COLLECTION)
    bpy.types.VIEW3D_HT_header.append(draw_picker_header_button)

def unregister():
    bpy.types.VIEW3D_HT_header.remove(draw_picker_header_button)
    del bpy.types.Object.freepicker_bone_sets
    del bpy.types.Scene.freepicker_sets
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
