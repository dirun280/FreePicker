"""FreePicker operators and button context menu."""
import bpy
import json
import re
from bpy_extras.io_utils import ExportHelper, ImportHelper
from .core import *

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

            blocked = _linked_data_message(arm)
            if blocked:
                self.report({'ERROR'}, blocked)
                return {'CANCELLED'}
            try:
                new_set = arm.freepicker_bone_sets.add()
            except TypeError:
                self.report({'ERROR'}, _ADD_REFUSED_MSG)
                return {'CANCELLED'}
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
    """Change this button's shape (square / circle / triangle). If this
    button is part of a multi-selection (box-selected in Edit Mode, or
    multiple buttons currently active in Locked mode), all of them change
    together."""
    bl_idname = "freepicker.set_shape"
    bl_label = "Set Button Shape"
    bl_options = {'UNDO'}

    index: bpy.props.IntProperty()
    shape: bpy.props.EnumProperty(items=SHAPE_ITEMS, default='SQUARE')

    def execute(self, context):
        entry = get_layout_entry(context, self.index)
        if entry is None:
            return {'CANCELLED'}

        panel = _active_panel["instance"]
        group = _get_broadcast_group(panel, self.index)
        for idx in group:
            other = entry if idx == self.index else get_layout_entry(context, idx)
            if other is not None:
                other.shape = self.shape
        return {'FINISHED'}


class FREEPICKER_OT_duplicate(bpy.types.Operator):
    """Duplicate this button (color, shape, name and members), placed right
    next to the original."""
    bl_idname = "freepicker.duplicate_set"
    bl_label = "Duplicate Button"
    bl_options = {'UNDO'}

    index: bpy.props.IntProperty()

    def _place_next_to(self, new_set, src):
        gap = 8.0
        panel = _active_panel["instance"]
        row = None
        if panel is not None:
            row = next((r for r in panel.rows if r["index"] == self.index), None)
        if panel is not None and row is not None:
            list_w = panel.width - 2 * panel.pad
            box_w, box_h = panel.effective_box(list_w, row)
            pos_x, pos_y = panel.effective_pos(row)
        else:
            # panel/row info not available -- fall back to the source's own
            # stored values (or sane defaults if it was never customized)
            box_w = src.box_w if src.box_w > 0 else NEW_BUTTON_SIZE
            box_h = src.box_h if src.box_h > 0 else NEW_BUTTON_SIZE
            pos_x = src.pos_x if src.pos_x >= 0 else 0.0
            pos_y = src.pos_y if src.pos_y >= 0 else 0.0
        new_set.box_w = box_w
        new_set.box_h = box_h
        new_set.pos_x = pos_x + box_w + gap
        new_set.pos_y = pos_y

    def execute(self, context):
        mode = context.mode

        if mode == 'POSE':
            arm = context.object
            if not arm or arm.type != 'ARMATURE':
                return {'CANCELLED'}
            if not (0 <= self.index < len(arm.freepicker_bone_sets)):
                return {'CANCELLED'}
            src = arm.freepicker_bone_sets[self.index]
            new_set = arm.freepicker_bone_sets.add()
            new_set.name = src.name
            new_set.color = src.color[:]
            new_set.shape = src.shape
            new_set.show_name = src.show_name
            for m in src.members:
                nm = new_set.members.add()
                nm.bone_name = m.bone_name
            self._place_next_to(new_set, src)
            self.report({'INFO'}, f"Duplicated '{src.name}'")
            return {'FINISHED'}

        elif mode == 'OBJECT':
            scene = context.scene
            if not (0 <= self.index < len(scene.freepicker_sets)):
                return {'CANCELLED'}
            src = scene.freepicker_sets[self.index]
            new_set = scene.freepicker_sets.add()
            new_set.name = src.name
            new_set.color = src.color[:]
            new_set.shape = src.shape
            new_set.show_name = src.show_name
            for m in src.members:
                nm = new_set.members.add()
                nm.obj_name = m.obj_name
            self._place_next_to(new_set, src)
            self.report({'INFO'}, f"Duplicated '{src.name}'")
            return {'FINISHED'}

        return {'CANCELLED'}


class FREEPICKER_OT_remove(bpy.types.Operator):
    """Delete this button entirely (the set and all its members). If this
    button is part of a multi-selection (box-selected in Edit Mode, or
    multiple buttons currently active in Locked mode), all of the selected
    buttons are deleted together."""
    bl_idname = "freepicker.remove_set"
    bl_label = "Delete Button"
    bl_options = {'UNDO'}

    index: bpy.props.IntProperty()

    def execute(self, context):
        mode = context.mode

        panel = _active_panel["instance"]
        indices = _get_broadcast_group(panel, self.index)

        # remove highest index first so earlier indices in the same
        # collection don't shift out from under us
        for idx in sorted(indices, reverse=True):
            if mode == 'POSE':
                arm = context.object
                if not arm or arm.type != 'ARMATURE':
                    continue
                if 0 <= idx < len(arm.freepicker_bone_sets):
                    try:
                        arm.freepicker_bone_sets.remove(idx)
                    except TypeError:
                        # buttons that come from the linked source rig can't
                        # be removed from a Library Override -- only ones
                        # added locally in this file can
                        self.report({'ERROR'},
                                    "Can't delete buttons that come from the linked rig. "
                                    "Delete them in the rig's own file instead.")
                        return {'CANCELLED'}
            elif mode == 'OBJECT':
                scene = context.scene
                if 0 <= idx < len(scene.freepicker_sets):
                    scene.freepicker_sets.remove(idx)

        if panel is not None:
            panel.edit_selected = set()

        self.report({'INFO'}, f"Deleted {len(indices)} button(s)" if len(indices) > 1
                    else "Button deleted")
        return {'FINISHED'}

        return {'CANCELLED'}


class FREEPICKER_OT_export(bpy.types.Operator, ExportHelper):
    """Export all selection sets in the current mode to a JSON file"""
    bl_idname = "freepicker.export_sets"
    bl_label = "Export Selection Sets"
    bl_options = {'REGISTER'}

    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={'HIDDEN'})
    after_import_path: bpy.props.StringProperty(options={'HIDDEN'})

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

        # When called from the import confirmation dialog, export the current
        # picker first, then continue with the selected JSON import.
        if self.after_import_path:
            bpy.ops.freepicker.import_sets(
                'EXEC_DEFAULT',
                filepath=self.after_import_path,
                import_action='REPLACE',
            )
        return {'FINISHED'}


_DUP_SUFFIX = re.compile(r"\.\d{3}$")

_ADD_REFUSED_MSG = (
    "Blender refused to add buttons to this rig because it's linked from "
    "another file. Make it a Library Override (Object > Library Override > "
    "Make), or set the picker up in the rig's own file."
)


def _linked_data_message(obj):
    """If `obj` is a plain linked (read-only) datablock, return a message
    explaining how to get around it; otherwise None. (Library Overrides are
    fine -- the properties are flagged to be editable there.)"""
    if obj is not None and getattr(obj, "library", None) is not None:
        return ("This rig is linked from another file, so it's read-only "
                "here. Make a Library Override first (Object > Library "
                "Override > Make), or set the picker up in the rig's own file.")
    return None


def _match_object_names(wanted, available):
    """Resolve object names from an exported file to real object names in
    this file. Exact matches win. Otherwise Blender's ".001"-style duplicate
    suffix is ignored -- it gets added to appended copies whenever the name
    was already taken, so "Body" in the JSON can match "Body.001" here. That
    fallback is only used when it points at exactly one object (never guess
    between e.g. "Cube.001" and "Cube.002"). Returns (resolved, fuzzy_count)."""
    available = list(available)
    exact = set(available)
    by_base = {}
    for n in available:
        by_base.setdefault(_DUP_SUFFIX.sub("", n), []).append(n)
    resolved, seen, fuzzy = [], set(), 0
    for w in wanted:
        if w in exact:
            hit = w
        else:
            candidates = by_base.get(_DUP_SUFFIX.sub("", w), [])
            if len(candidates) != 1:
                continue
            hit = candidates[0]
            fuzzy += 1
        if hit not in seen:
            seen.add(hit)
            resolved.append(hit)
    return resolved, fuzzy


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


class FREEPICKER_OT_import_choice(bpy.types.Operator):
    """Popup shown after choosing a JSON file when picker buttons already exist."""
    bl_idname = "freepicker.import_choice"
    bl_label = "Existing Picker Found"

    filepath: bpy.props.StringProperty(options={'HIDDEN'})
    action: bpy.props.EnumProperty(
        name="Action",
        items=(
            ('MENU', "Choose Action", "Show the import choices"),
            ('SAVE', "Save", "Export the current picker, then import the new JSON"),
            ('REPLACE', "Replace", "Delete current picker buttons, then import the new JSON"),
            ('CANCEL', "Cancel", "Cancel this import"),
        ),
        default='MENU',
        options={'HIDDEN'},
    )

    def invoke(self, context, event):
        if self.action != 'MENU':
            return self.execute(context)

        filepath = self.filepath

        def draw_menu(menu, menu_context):
            layout = menu.layout
            layout.label(text="Picker buttons already exist.", icon='ERROR')
            save = layout.operator("freepicker.import_choice", text="Save", icon='EXPORT')
            save.filepath = filepath
            save.action = 'SAVE'
            replace = layout.operator("freepicker.import_choice", text="Replace", icon='TRASH')
            replace.filepath = filepath
            replace.action = 'REPLACE'
            cancel = layout.operator("freepicker.import_choice", text="Cancel Import", icon='CANCEL')
            cancel.filepath = filepath
            cancel.action = 'CANCEL'

        context.window_manager.popup_menu(
            draw_menu, title="Existing Picker Found", icon='ERROR'
        )
        return {'FINISHED'}

    def execute(self, context):
        if self.action == 'SAVE':
            # Use the existing Export feature. It will continue the import
            # only after the user successfully saves the backup JSON.
            bpy.ops.freepicker.export_sets(
                'INVOKE_DEFAULT', after_import_path=self.filepath
            )
            return {'FINISHED'}

        if self.action == 'REPLACE':
            return bpy.ops.freepicker.import_sets(
                'EXEC_DEFAULT', filepath=self.filepath, import_action='REPLACE'
            )

        return {'CANCELLED'}


class FREEPICKER_OT_import(bpy.types.Operator, ImportHelper):
    """Import selection sets from a JSON file exported by this addon"""
    bl_idname = "freepicker.import_sets"
    bl_label = "Import Selection Sets"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={'HIDDEN'})
    import_action: bpy.props.EnumProperty(
        name="Import Action",
        description="Choose what to do with the current picker buttons",
        items=(
            ('UNDECIDED', "Choose Action", "Choose how to handle the existing picker"),
            ('SAVE', "Save Existing, Then Replace", "Export the current picker before replacing it"),
            ('REPLACE', "Replace", "Delete the current picker and import the new one"),
            ('CANCEL', "Cancel Import", "Do not import the file"),
        ),
        default='UNDECIDED',
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="This will replace your current picker.", icon='ERROR')
        layout.label(text="Choose whether to export a backup first.")
        layout.prop(self, "import_action", text="Action")

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

        # Determine the active picker collection and check whether a warning
        # is needed before touching any existing buttons.
        if mode == 'POSE':
            arm = context.object
            if not arm or arm.type != 'ARMATURE':
                self.report({'WARNING'}, "Active object is not an armature")
                return {'CANCELLED'}
            blocked = _linked_data_message(arm)
            if blocked:
                self.report({'ERROR'}, blocked)
                return {'CANCELLED'}
            collection = arm.freepicker_bone_sets
            pose_bone_names = {pb.name for pb in arm.pose.bones}
            can_import = any(
                any(name in pose_bone_names for name in entry.get("bone_names", []))
                for entry in sets
            )
        elif mode == 'OBJECT':
            scene = context.scene
            collection = scene.freepicker_sets
            existing_names = set(bpy.data.objects.keys())
            can_import = any(
                _match_object_names(entry.get("object_names", []), existing_names)[0]
                for entry in sets
            )
        else:
            self.report({'WARNING'}, "Only usable in Object Mode or Pose Mode")
            return {'CANCELLED'}

        if not can_import:
            self.report({'WARNING'}, "No sets could be imported -- no matching names found")
            return {'CANCELLED'}

        # The file browser has already returned the selected JSON path. If
        # buttons exist in this mode, show a real popup menu with the three
        # choices instead of trying to open a props dialog from execute().
        if len(collection) and self.import_action == 'UNDECIDED':
            bpy.ops.freepicker.import_choice(
                'INVOKE_DEFAULT', filepath=self.filepath, action='MENU'
            )
            return {'FINISHED'}

        if self.import_action == 'CANCEL':
            return {'CANCELLED'}

        if self.import_action == 'SAVE':
            # The export operator will continue this import after the backup
            # file has been successfully written.
            bpy.ops.freepicker.export_sets(
                'INVOKE_DEFAULT', after_import_path=self.filepath
            )
            return {'FINISHED'}

        replacing = self.import_action == 'REPLACE'
        if replacing:
            # Clear any UI multi-selection first so Delete Button removes only
            # the requested index each time, then use the addon's own delete
            # operator rather than removing collection items behind its back.
            panel = _active_panel.get("instance")
            if panel is not None:
                panel.edit_selected = set()
                for row in getattr(panel, "rows", []):
                    row["active"] = False

            while len(collection):
                result = bpy.ops.freepicker.remove_set(
                    'EXEC_DEFAULT', index=len(collection) - 1
                )
                if 'CANCELLED' in result:
                    self.report({'ERROR'}, "Could not delete the existing picker buttons")
                    return {'CANCELLED'}

        missing_total = 0
        imported_count = 0

        if mode == 'POSE':
            for entry in sets:
                bone_names = entry.get("bone_names", [])
                matched = [n for n in bone_names if n in pose_bone_names]
                missing_total += len(bone_names) - len(matched)
                if not matched:
                    continue

                try:
                    new_set = arm.freepicker_bone_sets.add()
                except TypeError:
                    self.report({'ERROR'}, _ADD_REFUSED_MSG)
                    return {'CANCELLED'}
                new_set.name = entry.get("name", "Imported Set")
                color = entry.get("color")
                if color and len(color) == 4:
                    new_set.color = color
                _apply_layout_fields(new_set, entry)
                for name in matched:
                    member = new_set.members.add()
                    member.bone_name = name
                imported_count += 1

        else:  # OBJECT mode
            fuzzy_total = 0
            for entry in sets:
                object_names = entry.get("object_names", [])
                matched, fuzzy = _match_object_names(object_names, existing_names)
                fuzzy_total += fuzzy
                missing_total += len(object_names) - len(matched)
                if not matched:
                    continue

                new_set = scene.freepicker_sets.add()
                new_set.name = entry.get("name", "Imported Set")
                color = entry.get("color")
                if color and len(color) == 4:
                    new_set.color = color
                _apply_layout_fields(new_set, entry)
                for name in matched:
                    member = new_set.members.add()
                    member.obj_name = name
                imported_count += 1

        if imported_count == 0:
            self.report({'WARNING'}, "No sets could be imported -- no matching names found")
            return {'CANCELLED'}

        action_word = "Replaced with" if replacing else "Imported"
        msg = f"{action_word} {imported_count} set(s)"
        if missing_total:
            msg += f" ({missing_total} member name(s) not found and skipped)"
        if mode == 'OBJECT' and fuzzy_total:
            msg += f" ({fuzzy_total} matched by ignoring the .001 suffix)"
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

        panel = _active_panel["instance"]
        group = _get_broadcast_group(panel, idx)
        if len(group) > 1:
            layout.label(text=f"Color / Shape / Delete apply to {len(group)} buttons",
                         icon='INFO')
            layout.separator()

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

        layout.separator()
        dupop = layout.operator("freepicker.duplicate_set", text="Duplicate Button", icon='DUPLICATE')
        dupop.index = idx

        layout.separator()
        delete_label = f"Delete {len(group)} Buttons" if len(group) > 1 else "Delete Button"
        dop = layout.operator("freepicker.remove_set", text=delete_label, icon='X')
        dop.index = idx




# Export operator classes and shared private helpers used by panel.py.
__all__ = [name for name in globals() if not name.startswith("__")]
