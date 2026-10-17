import math
import blf
import gpu
from gpu_extras.batch import batch_for_shader

try:
    UNIFORM_SHADER = gpu.shader.from_builtin('UNIFORM_COLOR')
except Exception:
    UNIFORM_SHADER = gpu.shader.from_builtin('2D_UNIFORM_COLOR')

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