import bpy, os, shutil
from bpy.props import StringProperty, BoolProperty

bl_info = {
    "name": "Playblast Quad View",
    "author": "Nguyen Phuc Nguyen",
    "version": (1, 0),
    "blender": (4, 3, 2),
    "location": "View3D > Sidebar > Playblast",
    "description": "Playblast review screenshot and video sequences for viewport - quadview",
    "category": "3D View",
}

# ------------------------------------------------------------------------
# Property Group
# ------------------------------------------------------------------------

class QP_Props(bpy.types.PropertyGroup):
    # Filepath for saving renders
    render_filepath: StringProperty(
        name="Save Path",
        subtype='FILE_PATH',
        default="//quadview_render.mp4"
    )
    # Boolean to track if Quad View is active
    is_quad_active: BoolProperty(
        name="Quad View Active",
        default=False
    )

# ------------------------------------------------------------------------
# Operators
# ------------------------------------------------------------------------

# Operator to toggle between Quad View and original layout
class QP_OT_switch_layout(bpy.types.Operator):
    """Switch between Quad View and original layout"""
    bl_idname = "qp.switch_layout"
    bl_label = "Switch Quad Layout"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.qp_props
        view3d_area = None
        view3d_region = None
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        view3d_area = area
                        view3d_region = region
                        break
                if view3d_area:
                    break

        if not view3d_area or not view3d_region:
            self.report({'ERROR'}, "Could not find a View3D area with a WINDOW region.")
            return {'CANCELLED'}

        try:
            with context.temp_override(area=view3d_area, region=view3d_region):
                bpy.ops.screen.region_quadview()
            props.is_quad_active = not props.is_quad_active

            if props.is_quad_active:
                self.report({'INFO'}, "Quad View enabled")
            else:
                self.report({'INFO'}, "Returned to original layout")
        except Exception as e:
            self.report({'ERROR'}, f"Error: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}

# Operator to open the folder where renders are saved
class QP_OT_open_render_folder(bpy.types.Operator):
    """Open saved folder"""
    bl_idname = "qp.open_render_folder"
    bl_label = "Open Saved Folder"

    def execute(self, context):
        folder_path = bpy.path.abspath(os.path.dirname(context.scene.qp_props.render_filepath))
        if os.path.exists(folder_path):
            import platform
            import subprocess
            
            if platform.system() == 'Windows':
                os.startfile(folder_path)
            elif platform.system() == 'Darwin':
                subprocess.Popen(['open', folder_path])
            else:
                subprocess.Popen(['xdg-open', folder_path])
            self.report({'INFO'}, f"Opened folder: {folder_path}")
        else:
            self.report({'ERROR'}, "Folder does not exist")
        return {'FINISHED'}


# Operator to take a screenshot of the current frame in Quad View
class QP_OT_screenshot_quadview(bpy.types.Operator):
    """Take a screenshot of the Quad View (hides N-Panel and T-Panel before taking the shot)"""
    bl_idname = "qp.screenshot_quadview"
    bl_label = "Screenshot Current Frame"

    _timer = None
    _view3d_area = None
    _region_window = None
    _ui_was_visible = False
    _toolbar_was_visible = False
    _file_path = ""

    def execute(self, context):
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                self._view3d_area = area
                break
        if not self._view3d_area:
            self.report({'ERROR'}, "VIEW_3D not found")
            return {'CANCELLED'}

        self._region_window = next((r for r in self._view3d_area.regions if r.type == 'WINDOW'), None)
        if not self._region_window:
            self.report({'ERROR'}, "WINDOW region not found")
            return {'CANCELLED'}
        
        user_filepath = bpy.path.abspath(context.scene.qp_props.render_filepath)
        folder_path = os.path.dirname(user_filepath)
        filename = os.path.splitext(os.path.basename(user_filepath))[0] + ".png"
        self._file_path = os.path.join(folder_path, filename)
        os.makedirs(folder_path, exist_ok=True)
        
        space = self._view3d_area.spaces.active
        self._ui_was_visible = space.show_region_ui
        self._toolbar_was_visible = space.show_region_toolbar
        space.show_region_ui = False
        space.show_region_toolbar = False
        
        if hasattr(context.space_data, 'show_gizmo'):
            context.space_data.show_gizmo = False
        if hasattr(context.space_data, 'show_region_tool_header'):
            context.space_data.show_region_tool_header = False

        bpy.context.view_layer.update()

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.2, window=context.window)
        wm.modal_handler_add(self)

        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'TIMER':
            wm = context.window_manager
            wm.event_timer_remove(self._timer)

            with context.temp_override(area=self._view3d_area, region=self._region_window):
                bpy.ops.screen.screenshot_area(filepath=self._file_path)

            space = self._view3d_area.spaces.active
            space.show_region_ui = self._ui_was_visible
            space.show_region_toolbar = self._toolbar_was_visible
            
            if hasattr(context.space_data, 'show_gizmo'):
                context.space_data.show_gizmo = True
            if hasattr(context.space_data, 'show_region_tool_header'):
                context.space_data.show_region_tool_header = True

            bpy.context.view_layer.update()

            self.report({'INFO'}, f"Image saved: {self._file_path}")
            return {'FINISHED'}

        return {'RUNNING_MODAL'}


# Operator to export a sequence of screenshots as an animation
class QP_OT_screenshot_quadview_anim(bpy.types.Operator):
    """Export the screenshot sequences of 3D viewport, keep same Fps rate"""
    bl_idname = "qp.screenshot_quadview_anim"
    bl_label = "Playblast Animation"

    _view3d_area = None
    _region_window = None
    _frame_current = 0
    _frame_start = 0
    _frame_end = 0
    _folder_path = ""
    _ui_was_visible = False
    _toolbar_was_visible = False
    _timer = None
    _wait_frames = 2

    def execute(self, context):
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                self._view3d_area = area
                break
        if not self._view3d_area:
            self.report({'ERROR'}, "VIEW_3D not found")
            return {'CANCELLED'}

        self._region_window = next((r for r in self._view3d_area.regions if r.type == 'WINDOW'), None)
        if not self._region_window:
            self.report({'ERROR'}, "WINDOW region not found")
            return {'CANCELLED'}

        scene = context.scene
        scene.frame_set(1)
        self._frame_start = scene.frame_start
        self._frame_end = scene.frame_end
        self._frame_current = self._frame_start

        # Create temp folder
        user_filepath = bpy.path.abspath(scene.qp_props.render_filepath)
        folder_main = os.path.dirname(user_filepath)

        filename_base = os.path.splitext(os.path.basename(user_filepath))[0]
        self._folder_path = os.path.join(folder_main, f"{filename_base}_temp")
        os.makedirs(self._folder_path, exist_ok=True)

        space = self._view3d_area.spaces.active
        self._ui_was_visible = space.show_region_ui
        self._toolbar_was_visible = space.show_region_toolbar
        space.show_region_ui = False
        space.show_region_toolbar = False
        
        if hasattr(context.space_data, 'show_gizmo'):
            context.space_data.show_gizmo = False
        if hasattr(context.space_data, 'show_region_tool_header'):
            context.space_data.show_region_tool_header = False

        bpy.context.view_layer.update()

        context.window_manager.modal_handler_add(self)
        self._timer = context.window_manager.event_timer_add(0.05, window=context.window)

        self._wait_frames = 2

        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'TIMER':
            if self._wait_frames > 0:
                self._wait_frames -= 1
                return {'RUNNING_MODAL'}

            scene = context.scene
            if self._frame_current > self._frame_end:
                space = self._view3d_area.spaces.active
                space.show_region_ui = self._ui_was_visible
                space.show_region_toolbar = self._toolbar_was_visible
                
                if hasattr(context.space_data, 'show_gizmo'):
                    context.space_data.show_gizmo = True
                if hasattr(context.space_data, 'show_region_tool_header'):
                    context.space_data.show_region_tool_header = True
                    
                bpy.context.view_layer.update()
                context.window_manager.event_timer_remove(self._timer)
                self.report({'INFO'}, f"Finished video with {self._frame_end - self._frame_start + 1} frames.")
                
                bpy.ops.qp.combine_images_to_video()
                
                return {'FINISHED'}
                
            scene.frame_set(self._frame_current)
            bpy.context.view_layer.update()

            filename = os.path.join(self._folder_path, f"quadview_frame_{self._frame_current:04d}.png")

            with context.temp_override(area=self._view3d_area, region=self._region_window):
                bpy.ops.screen.screenshot_area(filepath=filename)

            self._frame_current += 1

        return {'RUNNING_MODAL'}

# Operator to combine image sequences into a video
class QP_OT_combine_images_to_video(bpy.types.Operator):
    """Combine image sequence into an MP4 video and delete the image folder"""
    bl_idname = "qp.combine_images_to_video"
    bl_label = "Combine Images to Video"

    def execute(self, context):
        scene = context.scene
        props = scene.qp_props
        
        user_filepath = bpy.path.abspath(props.render_filepath)
        folder_main = os.path.dirname(user_filepath)
        filename_base = os.path.splitext(os.path.basename(user_filepath))[0]
        folder_temp = os.path.join(folder_main, f"{filename_base}_temp")

        if not os.path.exists(folder_temp):
            self.report({'ERROR'}, "Temporary image folder does not exist.")
            return {'CANCELLED'}

        images = sorted([f for f in os.listdir(folder_temp) if f.endswith('.png')])
        if not images:
            self.report({'ERROR'}, "No images found to combine into a video.")
            return {'CANCELLED'}

        first_image_path = os.path.join(folder_temp, images[0])
        img_data = bpy.data.images.load(first_image_path)
        img_width, img_height = img_data.size
        bpy.data.images.remove(img_data)
        
        # Round if width or height is odd
        if img_width % 2 != 0:
            img_width += 1
        if img_height % 2 != 0:
            img_height += 1

        video_scene_name = "CombineVideoScene"
        if video_scene_name in bpy.data.scenes:
            bpy.data.scenes.remove(bpy.data.scenes[video_scene_name])
        video_scene = bpy.data.scenes.new(video_scene_name)

        video_scene.render.resolution_x = img_width
        video_scene.render.resolution_y = img_height
        video_scene.render.fps = scene.render.fps
        video_scene.render.image_settings.file_format = 'FFMPEG'
        video_scene.render.ffmpeg.format = 'MPEG4'
        video_scene.render.ffmpeg.codec = 'H264'
        video_scene.render.ffmpeg.constant_rate_factor = 'HIGH'
        video_scene.render.ffmpeg.ffmpeg_preset = 'GOOD'

        video_scene.frame_start = 1
        video_scene.frame_end = len(images)

        if not video_scene.sequence_editor:
            video_scene.sequence_editor_create()
        seq_editor = video_scene.sequence_editor

        for s in seq_editor.sequences_all:
            seq_editor.sequences.remove(s)

        # Use the user-defined filepath
        video_scene.render.filepath = user_filepath

        try:
            original_scene = context.window.scene
            context.window.scene = video_scene

            image_strip = seq_editor.sequences.new_image(
                name="QuadViewImages",
                filepath=first_image_path,
                channel=1,
                frame_start=1
            )

            for img in images[1:]:
                image_strip.elements.append(img)

            image_strip.frame_final_duration = len(images)

            bpy.ops.render.render(animation=True, use_viewport=True)

            context.window.scene = original_scene

        except Exception as e:
            self.report({'ERROR'}, f"Error creating video: {e}")
            if video_scene_name in bpy.data.scenes:
                bpy.data.scenes.remove(bpy.data.scenes[video_scene_name])
            return {'CANCELLED'}

        try:
            shutil.rmtree(folder_temp)
            self.report({'INFO'}, "Temporary image folder deleted")
        except Exception as e:
            self.report({'WARNING'}, f"Could not delete temp folder: {e}")

        if video_scene_name in bpy.data.scenes:
            bpy.data.scenes.remove(bpy.data.scenes[video_scene_name])

        self.report({'INFO'}, f"Video completed: {user_filepath}")
        return {'FINISHED'}
    
# ------------------------------------------------------------------------
# Panel
# ------------------------------------------------------------------------

# Define the UI panel for the add-on
class QP_PT_panel(bpy.types.Panel):
    bl_label = "Playblast Panel"
    bl_idname = "QP_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Playblast"

    def draw(self, context):
        layout = self.layout
        props = context.scene.qp_props

        col = layout.column(align=True)
        if not props.is_quad_active:
            col.operator("qp.switch_layout", text="Switch Quad Layout", icon='WINDOW')
            col.label(text="Click to enable Quad View", icon='INFO')
        else:
            col.operator("qp.switch_layout", text="Reset Layout", icon='SCREEN_BACK')
            col.label(text="Quad View is active", icon='INFO')

        layout.separator()

        view3d_area = next((a for a in context.screen.areas if a.type == 'VIEW_3D'), None)

        if view3d_area:
            width = view3d_area.width
            height = view3d_area.height
        else:
            width = height = 0
        
        layout.label(text="Render Controls", icon='RENDER_STILL')
        col = layout.column(align=True)
       
        col.prop(props, "render_filepath")
        
        row = layout.row()
        row.label(text=f"Output Width: {width}")
        row = layout.row()
        row.label(text=f"Output Height: {height}")
        col = layout.column(align=True)
        col.operator("qp.screenshot_quadview", text="Screenshot Current Frame", icon='IMAGE_PLANE')
        col.operator("qp.screenshot_quadview_anim", text="Playblast Animation", icon='RENDER_ANIMATION')
        col = layout.column(align=True)
        col.operator("qp.open_render_folder", icon='FOLDER_REDIRECT')


# ------------------------------------------------------------------------
# Register
# ------------------------------------------------------------------------

# List of classes to register
classes = (
    QP_Props,
    QP_OT_switch_layout,
    QP_OT_open_render_folder,
    QP_OT_screenshot_quadview,
    QP_OT_screenshot_quadview_anim,
    QP_OT_combine_images_to_video,
    QP_PT_panel
)

# Register the add-on
def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.qp_props = bpy.props.PointerProperty(type=QP_Props)

# Unregister the add-on
def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.qp_props

# Entry point for the script
if __name__ == "__main__":
    register()