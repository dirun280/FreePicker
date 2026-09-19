# FreePicker

A floating, hand-drawn bone/object picker for Blender's Pose Mode (bones) and Object Mode.
Fully self-contained -- it keeps its own data (`freepicker_bone_sets` /
`freepicker_sets`) and never touches Blender's native "Bone Selection Sets"
feature, so it won't conflict with other addons built on that.

## Install (Blender 4.2+, Extensions Platform)

1. Zip this whole folder's **contents** (not the folder itself) so that
   `blender_manifest.toml` sits at the root of the zip -- `freepicker.zip` in
   this package is already built that way.
2. In Blender: `Edit > Preferences > Get Extensions > (dropdown, top-right)
   Install from Disk...`, pick `freepicker.zip`.
3. Enable it, then open a 3D Viewport in Object or Pose Mode -- a **FreePicker**
   button appears in the viewport header.

## Requirements

Requires **Blender 5.0+** (uses `PoseBone.select`, which replaced
`Bone.select` in that version).

## Quick usage

- Click **FreePicker** in the viewport header to open the floating panel.
- Select bones/objects, click **+ Add From Selection** to create a button.
- **Edit Mode** (yellow toggle): drag buttons to move them, drag the
  bottom-right corner to resize, double-click to rename, box-select several
  buttons to move them together.
- **Locked**: click a button to select its members; click-drag on empty
  canvas to box-select several buttons at once.
- Right-click any button: add/remove members, rename, change its color or
  shape (square / circle / triangle).
- `Ctrl + Scroll` zooms the canvas, `MMB drag` pans it, plain `Scroll`
  moves the list.
- **Export/Import** save/load your layout (including position, size, shape
  and color) as a `.json` file.
