import bpy
import blf
import gpu
import time
from .utils import (
    rgb01, dpi, draw_rounded_rect, draw_rounded_rect_outline,
    draw_circle, draw_circle_outline, draw_triangle, draw_triangle_outline,
    draw_text, draw_text_vcenter, char_index_at_x, clip_text
)
from .properties import (
    _active_panel, _last_geometry, _context_menu_index,
    _get_broadcast_group, get_layout_entry
)
from .operators import (
    pose_set_is_active, object_set_is_active, apply_picker_selection,
    DOUBLE_CLICK_THRESHOLD
)

ACCENT = (90, 170, 255)
DANGER = (230, 90, 90)
OK_GREEN = (110, 200, 120)
EDIT_YELLOW = (235, 195, 60)

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
            layout.label(text=f"Color / Shape / Delete apply to {len(group)} buttons", icon='INFO')
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


class FREEPICKER_OT_floating_panel(bpy.types.Operator):
    bl_idname = "freepicker.floating_panel"
    bl_label = "FreePicker"
    bl_options = {'REGISTER'}

    _is_open = False

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'POSE'}

    def invoke(self, context, event):
        try:
            return self._invoke_impl(context, event)
        except Exception as exc:
            print("FreePicker: failed to open, resetting state:", exc)
            FREEPICKER_OT_floating_panel._is_open = False
            if _active_panel["instance"] is self:
                _active_panel["instance"] = None
            try:
                if hasattr(self, "_handle"):
                    bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            except Exception:
                pass
            try:
                if hasattr(self, "_timer"):
                    context.window_manager.event_timer_remove(self._timer)
            except Exception:
                pass
            self.report({'ERROR'}, f"FreePicker failed to open: {exc}")
            return {'CANCELLED'}

    def _invoke_impl(self, context, event):
        if FREEPICKER_OT_floating_panel._is_open:
            panel = _active_panel["instance"]
            if panel is not None:
                panel.closed = True
            if context.area:
                context.area.tag_redraw()
            return {'CANCELLED'}

        if context.area is None or context.area.type != 'VIEW_3D':
            self.report({'WARNING'}, "Open this from a 3D Viewport")
            return {'CANCELLED'}

        self.width = _last_geometry["width"] if _last_geometry["width"] is not None else dpi(460, context)
        self.pad = dpi(10, context)
        self.header_h = dpi(142, context)
        self.row_h = dpi(30, context)
        self.min_list_h = self.row_h + dpi(10, context)
        self.max_height = dpi(760, context)
        self.manual_height = _last_geometry["manual_height"]
        self.canvas_zoom = 1.0
        self.zoom_min = 0.3
        self.zoom_max = 3.0
        self.pan_x = 0.0
        self.panning = False
        self.pan_origin = (0, 0)
        self._pan_orig = (0.0, 0.0)
        self.footer_h = dpi(20, context)

        if _last_geometry["panel_x"] is not None:
            self.panel_x = _last_geometry["panel_x"]
            self.panel_y = _last_geometry["panel_y"]
        else:
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

        self.edit_mode = True
        self.grip_size = dpi(14, context)
        self.dragging_row_index = None
        self.resizing_row_index = None
        self._drag_orig_pos = (0.0, 0.0)
        self._resize_orig_size = (0.0, 0.0)

        self.marquee_start = None
        self.marquee_end = None
        self.marquee_dragging = False
        self.marquee_press_row = None
        self.marquee_shift = False
        self.drag_threshold = dpi(4, context)

        self._mouse_x = -100000.0
        self._mouse_y = -100000.0

        self.edit_selected = set()
        self._drag_group_orig = {}

        self.rebuild_rows(context)
        self.recompute_height(context)
        self.clamp_panel_position(context)

        args = ()
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_callback, args, 'WINDOW', 'POST_PIXEL'
        )
        self._timer = context.window_manager.event_timer_add(0.2, window=context.window)
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        _active_panel["instance"] = self
        self._home_region_ptr = context.region.as_pointer()
        return {'RUNNING_MODAL'}

    def local_mouse(self, context, event):
        region = context.region
        if region is None:
            return -100000.0, -100000.0
        return event.mouse_x - region.x, event.mouse_y - region.y

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
        max_scroll = max(0.0, len(self.rows) * self.row_h * self.canvas_zoom - self.list_view_h) + self.list_view_h * 3
        self.scroll_offset = max(-max_scroll, min(self.scroll_offset, max_scroll))

    def clamp_panel_position(self, context):
        region_w = context.region.width
        region_h = context.region.height
        self.panel_x = max(0, min(self.panel_x, region_w - self.width))
        self.panel_y = max(0, min(self.panel_y, region_h - self.height))

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
        box_w, box_h = self.effective_box(list_w, row_data)
        pos_x, pos_y = self.effective_pos(row_data)
        z = self.canvas_zoom
        x = list_x + pos_x * z + self.pan_x
        top = canvas_top - pos_y * z + self.scroll_offset
        y = top - box_h * z
        return x, y, box_w * z, box_h * z

    def draw_callback(self):
        context = bpy.context
        try:
            self._draw_callback(context)
        except Exception as exc:
            print("FreePicker: draw error:", exc)

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
        toggle_y = add_rect[1] - dpi(6, context) - toggle_h
        toggle_rect = (x + pad, toggle_y, w - 2 * pad, toggle_h)

        small_h = dpi(22, context)
        small_y = toggle_rect[1] - dpi(6, context) - small_h
        gap = dpi(6, context)
        small_w = (w - 2 * pad - gap) / 2.0
        exp_rect = (x + pad, small_y, small_w, small_h)
        imp_rect = (exp_rect[0] + small_w + gap, small_y, small_w, small_h)

        return {
            "close": close_rect, "title": title_rect, "add": add_rect,
            "layout_toggle": toggle_rect,
            "export": exp_rect, "import": imp_rect,
        }

    def _draw_callback(self, context):
        region = context.region
        if region is None or region.as_pointer() != self._home_region_ptr:
            return

        if self.mode_cached != context.mode:
            self.rebuild_rows(context)
            self.recompute_height(context)

        x, y, w, h = self.panel_x, self.panel_y, self.width, self.height
        draw_rounded_rect(x, y, w, h, dpi(14, context), (0.16, 0.16, 0.17, 0.92))
        draw_rounded_rect_outline(x, y, w, h, dpi(14, context), (0.05, 0.05, 0.05, 0.6), width=1.0)

        mouse_x, mouse_y = self._mouse_x, self._mouse_y

        def is_hovered(rect):
            return self.point_in(mouse_x, mouse_y, rect)

        def hover_ring(rect, radius):
            rx, ry, rw, rh = rect
            draw_rounded_rect_outline(rx - 1.5, ry - 1.5, rw + 3, rh + 3, radius,
                                       (1, 1, 1, 0.9), width=1.5)

        hover_tip = None

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
        if is_hovered(r["title"]):
            hover_tip = "Drag here to move the panel"

        cx0, cy0, cw, ch = r["close"]
        draw_rounded_rect(cx0, cy0, cw, ch, dpi(6, context), rgb01(DANGER, 0.85))
        draw_text(cx0, cy0 + ch * 0.16, "x", max(14, dpi(20, context)), (1, 1, 1, 1), align_center_width=cw)
        if is_hovered(r["close"]):
            hover_ring(r["close"], dpi(6, context))
            hover_tip = "Close this panel"

        ax, ay, aw, ah = r["add"]
        draw_rounded_rect(ax, ay, aw, ah, dpi(8, context), rgb01(ACCENT, 0.9))
        draw_text(ax, ay + ah * 0.28, "+  Add From Selection", max(9, dpi(12, context)),
                  (1, 1, 1, 1), align_center_width=aw)
        if is_hovered(r["add"]):
            hover_ring(r["add"], dpi(8, context))
            hover_tip = "Create a new button from the currently selected bones/objects"

        tx, ty, tw, th = r["layout_toggle"]
        toggle_color = rgb01(EDIT_YELLOW, 0.95) if self.edit_mode else rgb01((90, 130, 200), 0.9)
        toggle_label = "Edit Mode" if self.edit_mode else "Locked"
        toggle_text_color = (0.1, 0.1, 0.1, 1.0) if self.edit_mode else (1, 1, 1, 1)
        draw_rounded_rect(tx, ty, tw, th, dpi(6, context), toggle_color)
        draw_text(tx, ty + th * 0.22, toggle_label, max(8, dpi(10, context)),
                  toggle_text_color, align_center_width=tw)
        if is_hovered(r["layout_toggle"]):
            hover_ring(r["layout_toggle"], dpi(6, context))
            hover_tip = ("Switch to Locked mode -- click/box-select buttons to select bones"
                         if self.edit_mode else
                         "Switch to Edit Mode -- drag, resize and rename buttons")

        for key, label, tip in (
            ("export", "Export", "Save all buttons (position, size, shape, color) to a .json file"),
            ("import", "Import", "Load buttons from a .json file exported by FreePicker"),
        ):
            bx, by, bw, bh = r[key]
            draw_rounded_rect(bx, by, bw, bh, dpi(6, context), rgb01((70, 70, 72), 0.9))
            draw_text(bx, by + bh * 0.22, label, max(8, dpi(10, context)),
                      (0.9, 0.9, 0.9, 1.0), align_center_width=bw)
            if is_hovered(r[key]):
                hover_ring(r[key], dpi(6, context))
                hover_tip = tip

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
                    if is_hovered((rx, ry, rw, rh)):
                        hover_ring((rx, ry, rw, rh), dpi(5, context))
                        shown_name = row_data["name"] if row_data.get("show_name") else "(unnamed)"
                        count_label = "bone" if context.mode == 'POSE' else "object"
                        n = row_data["count"]
                        hover_tip = f"{shown_name} -- {n} {count_label}{'s' if n != 1 else ''}"
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

        grip_zone = (x + w - dpi(16, context), y, dpi(16, context), dpi(16, context))
        grip_hovered = is_hovered(grip_zone)
        grip_dot = max(1.5, dpi(1.5, context)) * (1.6 if grip_hovered else 1.0)
        grip_color = (1, 1, 1, 0.9) if grip_hovered else (0.75, 0.75, 0.75, 0.5)
        gx = x + w - dpi(6, context)
        gy = y + dpi(14, context)
        for row in range(3):
            for col in range(row + 1):
                draw_circle(gx - col * dpi(4, context), gy - row * dpi(4, context),
                            grip_dot, grip_color)
        if grip_hovered:
            hover_tip = "Drag to resize the panel"

        if hover_tip is not None:
            hint = hover_tip
            hint_color = (0.85, 0.85, 0.75, 1.0)
        else:
            hint = "Scroll: list \u00b7 Ctrl+Scroll: zoom \u00b7 MMB drag: pan"
            hint_color = (0.55, 0.55, 0.55, 0.85)
        font_size = max(9, dpi(11, context))
        hint = clip_text(hint, font_size, w - 2 * self.pad)
        draw_text(x + self.pad, y + dpi(4, context), hint, font_size, hint_color)

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
            if row_data["active"]:
                draw_circle_outline(cx, cy, r + 2.0, (0.0, 0.0, 0.0, 0.55), width=3.5)
                draw_circle_outline(cx, cy, r, (1.0, 1.0, 1.0, 1.0), width=1.8)

        elif shape == 'TRIANGLE':
            p1, p2, p3 = tri_points(bx, by, bw, bh)
            draw_triangle(p1, p2, p3, color)
            if row_data["active"]:
                pad = 2.0
                p1o, p2o, p3o = tri_points(bx - pad, by - pad, bw + 2 * pad, bh + 2 * pad)
                draw_triangle_outline(p1o, p2o, p3o, (0.0, 0.0, 0.0, 0.55), width=3.5)
                draw_triangle_outline(p1, p2, p3, (1.0, 1.0, 1.0, 1.0), width=1.8)

        else:
            draw_rounded_rect(bx, by, bw, bh, radius, color)
            if row_data["active"]:
                draw_rounded_rect_outline(bx - 2.0, by - 2.0, bw + 4, bh + 4, dpi(7, context),
                                           (0.0, 0.0, 0.0, 0.55), width=3.5)
                draw_rounded_rect_outline(bx, by, bw, bh, radius,
                                           (1.0, 1.0, 1.0, 1.0), width=1.8)

        if row_data.get("show_name") and row_data.get("name") and self.editing_index != row_data["index"]:
            font_size = max(7, int(min(bw, bh) * 0.28))
            label = clip_text(row_data["name"], font_size, max(4, bw - 6))
            draw_text_vcenter(bx, by, bh, label, font_size, (1, 1, 1, 0.95), align_center_width=bw)

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
            "swatch": box_rect, "name": box_rect, "box": box_rect,
        }

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
        _last_geometry["width"] = self.width
        _last_geometry["manual_height"] = self.manual_height
        _last_geometry["panel_x"] = self.panel_x
        _last_geometry["panel_y"] = self.panel_y
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

    def modal(self, context, event):
        try:
            return self._modal_impl(context, event)
        except Exception as exc:
            print("FreePicker: modal error, closing panel cleanly:", exc)
            try:
                return self.finish(context)
            except Exception:
                FREEPICKER_OT_floating_panel._is_open = False
                if _active_panel["instance"] is self:
                    _active_panel["instance"] = None
                return {'CANCELLED'}

    def _modal_impl(self, context, event):
        if self.closed:
            return self.finish(context)

        area = context.area
        region = context.region
        in_view3d = (area is not None and area.type == 'VIEW_3D'
                     and region is not None and region.type == 'WINDOW'
                     and region.as_pointer() == self._home_region_ptr)

        if area is not None:
            area.tag_redraw()

        if not in_view3d:
            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                self.marquee_start = None
                self.marquee_end = None
                self.marquee_dragging = False
                self.marquee_press_row = None
                self.dragging_row_index = None
                self.resizing_row_index = None
                self._drag_group_orig = {}
                self.dragging_panel = False
                self.resizing = False
                self.edit_dragging_select = False
            return {'PASS_THROUGH'}

        lx, ly = self.local_mouse(context, event)
        self._mouse_x, self._mouse_y = lx, ly

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
                    old_zoom = self.canvas_zoom
                    factor = 1.1 if event.type == 'WHEELUPMOUSE' else (1.0 / 1.1)
                    new_zoom = max(self.zoom_min, min(self.zoom_max, old_zoom * factor))
                    if new_zoom != old_zoom:
                        canvas_top = list_y + self.list_view_h
                        rel_y = (canvas_top + self.scroll_offset) - ly
                        rel_y_new = rel_y * (new_zoom / old_zoom)
                        self.scroll_offset = (ly + rel_y_new) - canvas_top
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

            title_x, title_y, title_w, title_h = r["title"]
            panel_top = self.panel_y + self.height
            if (title_y <= ly <= panel_top and
                    self.panel_x <= lx <= self.panel_x + self.width):
                self.dragging_panel = True
                self.drag_origin = (lx, ly)
                return {'RUNNING_MODAL'}

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
                    apply_picker_selection(context, [], extend=False)
                    self.rebuild_rows(context)
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
                        if i in self.edit_selected:
                            self.edit_selected.discard(i)
                        else:
                            self.edit_selected.add(i)
                        return {'RUNNING_MODAL'}

                    if i not in self.edit_selected:
                        self.edit_selected = {i}
                    rows_by_index = {r2["index"]: r2 for r2 in self.rows}
                    self.drag_origin = (lx, ly)
                    self._drag_group_orig = {
                        idx: self.effective_pos(rows_by_index[idx])
                        for idx in self.edit_selected if idx in rows_by_index
                    }
                    self.dragging_row_index = i
                    return {'RUNNING_MODAL'}

                self.marquee_start = (lx, ly)
                self.marquee_end = (lx, ly)
                self.marquee_dragging = False
                self.marquee_press_row = None
                self.marquee_shift = event.shift
                return {'RUNNING_MODAL'}

            else:
                self.marquee_start = (lx, ly)
                self.marquee_end = (lx, ly)
                self.marquee_dragging = False
                self.marquee_press_row = row_data["index"] if row_data is not None else None
                self.marquee_shift = event.shift
                return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if self.marquee_start is not None:
                if self.edit_mode:
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

        return {'PASS_THROUGH'}

def draw_picker_header_button(self, context):
    if context.mode in {'OBJECT', 'POSE'}:
        self.layout.operator("freepicker.floating_panel", icon='WINDOW', text="FreePicker")

classes = (
    FREEPICKER_MT_row_menu,
    FREEPICKER_OT_floating_panel,
)