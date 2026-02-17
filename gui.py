import os
import sys
from tkinter import filedialog

import customtkinter as ctk
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib import cm
from matplotlib.colors import Normalize
from mpl_toolkits.mplot3d import proj3d

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from flatten_surface.flatten_surface import flatten_mesh, solve_flatten
    from flatten_surface.import_export import load_with_components, mesh_to_data, component_quality, extract_source_label
    from nesting import run_nesting
except ImportError:
    from flatten_surface.flatten_surface import flatten_mesh, solve_flatten
    from flatten_surface.import_export import load_with_components, mesh_to_data, component_quality, extract_source_label
    from nesting import run_nesting


class FlattenApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("3DXFlat - Surface Flattening for Production")
        self.geometry("1450x900")

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.input_path = ctk.StringVar()
        self.output_path = ctk.StringVar()
        self.unit_var = ctk.StringVar(value="mm")
        self.method_var = ctk.StringVar(value="ARAP")
        self.boundary_mode_var = ctk.StringVar(value="outer_only")
        self.face_pick_mode = ctk.BooleanVar(value=False)
        self.face_pick_strategy_var = ctk.StringVar(value="component")
        self.show_heatmap_var = ctk.BooleanVar(value=False)
        self.allow_dirty_export_var = ctk.BooleanVar(value=False)
        self.auto_relief_var = ctk.BooleanVar(value=True)
        self.relief_threshold_var = ctk.StringVar(value="3.0")
        self.seam_allowance_var = ctk.StringVar(value="12.0")
        self.align_to_x_enabled = False
        self.source_label = ""
        self.nest_input_dir_var = ctk.StringVar(value="")
        self.nest_output_dir_var = ctk.StringVar(value="")
        self.nest_roll_width_var = ctk.StringVar(value="2500")
        self.nest_gap_var = ctk.StringVar(value="20")
        self.nest_rotation_var = ctk.StringVar(value="15")
        self.nest_max_sheet_len_var = ctk.StringVar(value="10000")

        self.components = []
        self.selected_component_idx = 0
        self._pick_connection_id = None
        self._press_connection_id = None
        self._release_connection_id = None
        self._drag_start_px = None
        self._heatmap_cache = {}
        self._heatmap_colorbar = None
        self._selected_faces_by_component = {}
        self._view_name = "iso"

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=3)
        self.grid_rowconfigure(0, weight=1)

        self.left_panel = ctk.CTkFrame(self, width=360)
        self.left_panel.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.left_panel.grid_rowconfigure(0, weight=1)
        self.left_panel.grid_rowconfigure(1, weight=0)
        self.left_panel.grid_columnconfigure(0, weight=1)

        self.controls_frame = ctk.CTkScrollableFrame(self.left_panel)
        self.controls_frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.actions_frame = ctk.CTkFrame(self.left_panel)
        self.actions_frame.grid(row=1, column=0, sticky="ew", padx=0, pady=(8, 0))

        self.tool_tabs = ctk.CTkTabview(self.controls_frame)
        self.tool_tabs.pack(fill="both", expand=True, padx=6, pady=6)
        self.flatten_tab = self.tool_tabs.add("Flatten")
        self.nesting_tab = self.tool_tabs.add("Nesting")

        self.label = ctk.CTkLabel(self.flatten_tab, text="3DXFLAT", font=("Roboto", 24, "bold"))
        self.label.pack(pady=20)

        self.file_frame = ctk.CTkFrame(self.flatten_tab)
        self.file_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(self.file_frame, text="1. Load 3D Model:").pack(anchor="w", padx=5)
        self.input_btn = ctk.CTkButton(self.file_frame, text="Open STL/OBJ/3DS", command=self.browse_input)
        self.input_btn.pack(fill="x", padx=5, pady=5)

        self.comp_frame = ctk.CTkFrame(self.flatten_tab)
        self.comp_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(self.comp_frame, text="2. Select Surface:").pack(anchor="w", padx=5)
        self.comp_menu = ctk.CTkOptionMenu(self.comp_frame, values=["No model loaded"], command=self.on_component_select)
        self.comp_menu.pack(fill="x", padx=5, pady=5)

        self.comp_nav = ctk.CTkFrame(self.comp_frame, fg_color="transparent")
        self.comp_nav.pack(fill="x", padx=5, pady=(0, 6))
        self.prev_btn = ctk.CTkButton(self.comp_nav, text="Prev", width=80, command=self.select_prev_component)
        self.prev_btn.pack(side="left", padx=(0, 8))
        self.next_btn = ctk.CTkButton(self.comp_nav, text="Next", width=80, command=self.select_next_component)
        self.next_btn.pack(side="left")
        self.face_pick_switch = ctk.CTkSwitch(
            self.comp_nav,
            text="Face Pick",
            variable=self.face_pick_mode,
            command=self.toggle_face_pick_mode,
            onvalue=True,
            offvalue=False,
            width=110,
        )
        self.face_pick_switch.pack(side="right")
        self.pick_mode_menu = ctk.CTkOptionMenu(
            self.comp_frame,
            values=["Component Pick", "Area Select (Rect)"],
            command=self.on_pick_mode_change,
        )
        self.pick_mode_menu.pack(fill="x", padx=5, pady=(0, 5))
        self.pick_mode_menu.set("Component Pick")
        self.pick_tools_row = ctk.CTkFrame(self.comp_frame, fg_color="transparent")
        self.pick_tools_row.pack(fill="x", padx=5, pady=(0, 6))
        self.clear_sel_btn = ctk.CTkButton(self.pick_tools_row, text="Clear Selection", command=self.clear_face_selection, width=120)
        self.clear_sel_btn.pack(side="left")

        self.opt_frame = ctk.CTkFrame(self.flatten_tab)
        self.opt_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(self.opt_frame, text="3. Input Units:").pack(anchor="w", padx=5)
        self.unit_menu = ctk.CTkOptionMenu(self.opt_frame, values=["mm", "cm", "m", "inch"], variable=self.unit_var)
        self.unit_menu.pack(fill="x", padx=5, pady=5)

        ctk.CTkLabel(self.opt_frame, text="4. Flattening Method:").pack(anchor="w", padx=5)
        self.method_menu = ctk.CTkOptionMenu(
            self.opt_frame,
            values=["LSCM (Fast)", "ARAP (Advanced - Production)"],
            command=self.on_method_change,
        )
        self.method_menu.pack(fill="x", padx=5, pady=5)
        self.method_menu.set("ARAP (Advanced - Production)")
        self.method_var.set("ARAP")

        ctk.CTkLabel(self.opt_frame, text="5. Boundary Export:").pack(anchor="w", padx=5)
        self.boundary_menu = ctk.CTkOptionMenu(
            self.opt_frame,
            values=["Outer Only (Recommended)", "Outer + Large Holes", "All Loops"],
            command=self.on_boundary_mode_change,
        )
        self.boundary_menu.pack(fill="x", padx=5, pady=5)
        self.boundary_menu.set("Outer Only (Recommended)")
        self.boundary_mode_var.set("outer_only")

        ctk.CTkLabel(self.opt_frame, text="6. Seam Allowance (mm):").pack(anchor="w", padx=5)
        self.seam_entry = ctk.CTkEntry(self.opt_frame, textvariable=self.seam_allowance_var)
        self.seam_entry.pack(fill="x", padx=5, pady=5)

        self.align_btn = ctk.CTkButton(self.opt_frame, text="Align to X-Axis: OFF", command=self.toggle_align_to_x)
        self.align_btn.pack(fill="x", padx=5, pady=5)

        self.heatmap_switch = ctk.CTkSwitch(
            self.opt_frame,
            text="Show Strain Heatmap",
            variable=self.show_heatmap_var,
            command=self.on_heatmap_toggle,
            onvalue=True,
            offvalue=False,
        )
        self.heatmap_switch.pack(anchor="w", padx=5, pady=(2, 6))
        self.allow_dirty_switch = ctk.CTkSwitch(
            self.opt_frame,
            text="Allow Export with Mesh Warnings",
            variable=self.allow_dirty_export_var,
            onvalue=True,
            offvalue=False,
        )
        self.allow_dirty_switch.pack(anchor="w", padx=5, pady=(0, 6))
        self.auto_relief_switch = ctk.CTkSwitch(
            self.opt_frame,
            text="Auto Relief-Cut Suggestion",
            variable=self.auto_relief_var,
            onvalue=True,
            offvalue=False,
        )
        self.auto_relief_switch.pack(anchor="w", padx=5, pady=(0, 4))
        ctk.CTkLabel(self.opt_frame, text="Relief Trigger Strain %:").pack(anchor="w", padx=5)
        self.relief_threshold_entry = ctk.CTkEntry(self.opt_frame, textvariable=self.relief_threshold_var)
        self.relief_threshold_entry.pack(fill="x", padx=5, pady=(0, 6))

        self.out_frame = ctk.CTkFrame(self.flatten_tab)
        self.out_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(self.out_frame, text="7. Output:").pack(anchor="w", padx=5)
        self.out_btn = ctk.CTkButton(self.out_frame, text="Set Export Path", command=self.browse_output)
        self.out_btn.pack(fill="x", padx=5, pady=5)
        self.out_label = ctk.CTkLabel(self.out_frame, textvariable=self.output_path, font=("Roboto", 10), wraplength=320)
        self.out_label.pack(fill="x", padx=5)

        # --- Nesting Tab ---
        self.nest_title = ctk.CTkLabel(self.nesting_tab, text="ROLL NESTING", font=("Roboto", 22, "bold"))
        self.nest_title.pack(pady=18)

        self.nest_in_frame = ctk.CTkFrame(self.nesting_tab)
        self.nest_in_frame.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(self.nest_in_frame, text="Input Folder (flattened DXFs):").pack(anchor="w", padx=5, pady=(4, 2))
        ctk.CTkButton(self.nest_in_frame, text="Select Input Folder", command=self.browse_nesting_input_dir).pack(fill="x", padx=5, pady=4)
        ctk.CTkLabel(self.nest_in_frame, textvariable=self.nest_input_dir_var, wraplength=320).pack(fill="x", padx=5, pady=(0, 6))

        self.nest_out_frame = ctk.CTkFrame(self.nesting_tab)
        self.nest_out_frame.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(self.nest_out_frame, text="Output Folder:").pack(anchor="w", padx=5, pady=(4, 2))
        ctk.CTkButton(self.nest_out_frame, text="Select Output Folder", command=self.browse_nesting_output_dir).pack(fill="x", padx=5, pady=4)
        ctk.CTkLabel(self.nest_out_frame, textvariable=self.nest_output_dir_var, wraplength=320).pack(fill="x", padx=5, pady=(0, 6))

        self.nest_param_frame = ctk.CTkFrame(self.nesting_tab)
        self.nest_param_frame.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(self.nest_param_frame, text="Roll Width (mm):").pack(anchor="w", padx=5, pady=(4, 2))
        ctk.CTkEntry(self.nest_param_frame, textvariable=self.nest_roll_width_var).pack(fill="x", padx=5, pady=2)
        ctk.CTkLabel(self.nest_param_frame, text="Inter-piece Gap (mm):").pack(anchor="w", padx=5, pady=(6, 2))
        ctk.CTkEntry(self.nest_param_frame, textvariable=self.nest_gap_var).pack(fill="x", padx=5, pady=2)
        ctk.CTkLabel(self.nest_param_frame, text="Rotation Step (degrees):").pack(anchor="w", padx=5, pady=(6, 2))
        ctk.CTkEntry(self.nest_param_frame, textvariable=self.nest_rotation_var).pack(fill="x", padx=5, pady=2)
        ctk.CTkLabel(self.nest_param_frame, text="Max Sheet Length (mm):").pack(anchor="w", padx=5, pady=(6, 2))
        ctk.CTkEntry(self.nest_param_frame, textvariable=self.nest_max_sheet_len_var).pack(fill="x", padx=5, pady=(2, 6))

        self.run_nest_btn = ctk.CTkButton(
            self.nesting_tab,
            text="RUN NESTING",
            command=self.run_nesting_job,
            height=42,
            font=("Roboto", 16, "bold"),
        )
        self.run_nest_btn.pack(fill="x", padx=12, pady=10)

        self.run_btn = ctk.CTkButton(
            self.actions_frame,
            text="GENERATE PRODUCTION DXF",
            command=self.run_flattening,
            height=60,
            font=("Roboto", 18, "bold"),
            fg_color="green",
            hover_color="darkgreen",
        )
        self.run_btn.pack(pady=(10, 10), padx=10, fill="x")

        self.status_label = ctk.CTkLabel(self.actions_frame, text="Ready", wraplength=320, justify="left")
        self.status_label.pack(pady=(0, 8), padx=10, anchor="w")

        self.right_panel = ctk.CTkFrame(self)
        self.right_panel.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

        self.fig = plt.figure(figsize=(6, 6), facecolor="#2b2b2b")
        self.ax = self.fig.add_subplot(111, projection="3d")
        self.ax.set_facecolor("#2b2b2b")
        self.ax.set_axis_off()
        self._update_mouse_nav_mode()

        self.toolbar_container = ctk.CTkFrame(self.right_panel)
        self.toolbar_container.pack(fill="x", padx=4, pady=(4, 0))

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.right_panel)
        self.toolbar = NavigationToolbar2Tk(self.canvas, self.toolbar_container, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(fill="x")

        self.view_btn_row = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        self.view_btn_row.pack(fill="x", padx=6, pady=(4, 0))
        self._add_view_button("Front", "front")
        self._add_view_button("Back", "back")
        self._add_view_button("Left", "left")
        self._add_view_button("Right", "right")
        self._add_view_button("Top", "top")
        self._add_view_button("Bottom", "bottom")
        self._add_view_button("ISO", "iso")
        self.fit_btn = ctk.CTkButton(self.view_btn_row, text="Frame", width=58, command=self.frame_current_view)
        self.fit_btn.pack(side="left", padx=2)

        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.viewer_help = ctk.CTkLabel(
            self.right_panel,
            text="Viewport: Orbit=MMB (or toolbar), Zoom=wheel, Pan=toolbar. Area Select uses LMB drag rectangle.",
            text_color="#bfc6d1",
        )
        self.viewer_help.pack(anchor="w", padx=8, pady=(2, 6))
        self._pick_connection_id = self.canvas.mpl_connect("pick_event", self.on_pick)
        self._press_connection_id = self.canvas.mpl_connect("button_press_event", self.on_mouse_press)
        self._release_connection_id = self.canvas.mpl_connect("button_release_event", self.on_mouse_release)

    def on_method_change(self, val):
        self.method_var.set("ARAP" if "ARAP" in val else "LSCM")
        self._heatmap_cache.clear()
        if self.components:
            self.preview_component(self.selected_component_idx)

    def on_boundary_mode_change(self, val):
        mapping = {
            "Outer Only (Recommended)": "outer_only",
            "Outer + Large Holes": "outer_and_large_holes",
            "All Loops": "all_loops",
        }
        self.boundary_mode_var.set(mapping.get(val, "outer_only"))
        self._heatmap_cache.clear()
        if self.components:
            self.preview_component(self.selected_component_idx)

    def on_pick_mode_change(self, val):
        mapping = {
            "Component Pick": "component",
            "Area Select (Rect)": "area",
        }
        self.face_pick_strategy_var.set(mapping.get(val, "component"))
        self._update_mouse_nav_mode()
        if self.components:
            self.preview_component(self.selected_component_idx)

    def on_heatmap_toggle(self):
        if self.components:
            self.preview_component(self.selected_component_idx)

    def toggle_align_to_x(self):
        self.align_to_x_enabled = not self.align_to_x_enabled
        state = "ON" if self.align_to_x_enabled else "OFF"
        self.align_btn.configure(text=f"Align to X-Axis: {state}")

    def _get_seam_allowance_mm(self):
        raw = (self.seam_allowance_var.get() or "").strip()
        if raw == "":
            return 0.0
        val = float(raw)
        if val < 0:
            raise ValueError("Seam allowance must be >= 0")
        return val

    def _get_relief_threshold_pct(self):
        raw = (self.relief_threshold_var.get() or "").strip()
        if raw == "":
            return 3.0
        val = float(raw)
        if val <= 0:
            raise ValueError("Relief trigger strain must be > 0")
        return val

    def _ask_input_unit(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Input Units")
        dialog.geometry("360x170")
        dialog.transient(self)
        dialog.grab_set()

        result = {"unit": None}
        unit_var = ctk.StringVar(value=self.unit_var.get() or "mm")

        ctk.CTkLabel(
            dialog,
            text="Select units used by the loaded model file:",
            wraplength=330,
            justify="left",
        ).pack(padx=12, pady=(12, 8), anchor="w")

        unit_menu = ctk.CTkOptionMenu(dialog, values=["mm", "cm", "m", "inch"], variable=unit_var)
        unit_menu.pack(fill="x", padx=12, pady=4)

        row = ctk.CTkFrame(dialog, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(12, 10))

        def on_ok():
            result["unit"] = unit_var.get()
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        ctk.CTkButton(row, text="Cancel", command=on_cancel, width=90).pack(side="right", padx=(8, 0))
        ctk.CTkButton(row, text="Use Unit", command=on_ok, width=90).pack(side="right")

        self.wait_window(dialog)
        return result["unit"]

    def toggle_face_pick_mode(self):
        if not self.components:
            return
        self._update_mouse_nav_mode()
        self.preview_component(self.selected_component_idx)
        if self.face_pick_mode.get():
            if self.face_pick_strategy_var.get() == "area":
                txt = "Area Select enabled. Drag rectangle in viewport. Shift=Add, Ctrl=Subtract."
            else:
                txt = "Component Pick enabled. Click a surface in the viewer."
            self.status_label.configure(text=txt, text_color="#8ac926")
        else:
            self.status_label.configure(
                text="Face Pick disabled. Use dropdown/Prev/Next to select surfaces.",
                text_color="white",
            )

    def _add_view_button(self, text, view_name):
        btn = ctk.CTkButton(self.view_btn_row, text=text, width=58, command=lambda: self.set_view(view_name))
        btn.pack(side="left", padx=2)

    def _update_mouse_nav_mode(self):
        # Avoid viewport jump during area selection by moving orbit to middle mouse.
        if self.face_pick_mode.get() and self.face_pick_strategy_var.get() == "area":
            self.ax.mouse_init(rotate_btn=2, zoom_btn=3)
        else:
            self.ax.mouse_init(rotate_btn=1, zoom_btn=3)

    def set_view(self, view_name):
        self._view_name = view_name
        if view_name == "front":
            self.ax.view_init(elev=0, azim=-90)
        elif view_name == "back":
            self.ax.view_init(elev=0, azim=90)
        elif view_name == "left":
            self.ax.view_init(elev=0, azim=180)
        elif view_name == "right":
            self.ax.view_init(elev=0, azim=0)
        elif view_name == "top":
            self.ax.view_init(elev=90, azim=-90)
        elif view_name == "bottom":
            self.ax.view_init(elev=-90, azim=-90)
        else:
            self.ax.view_init(elev=28, azim=-55)
        self.canvas.draw_idle()

    def _apply_active_view(self):
        self.set_view(self._view_name)

    def frame_current_view(self):
        if not self.components:
            return
        self.preview_component(self.selected_component_idx)

    def clear_face_selection(self):
        idx = self.selected_component_idx
        if idx in self._selected_faces_by_component:
            self._selected_faces_by_component.pop(idx, None)
        if self.components:
            self.preview_component(idx)

    def browse_input(self):
        filename = filedialog.askopenfilename(filetypes=[("3D files", "*.stl *.obj *.3ds *.stp *.step"), ("All files", "*.*")])
        if filename:
            picked_unit = self._ask_input_unit()
            if not picked_unit:
                return
            self.unit_var.set(picked_unit)
            self.input_path.set(filename)
            base = os.path.splitext(filename)[0]
            self.output_path.set(base + ".dxf")
            self.load_model(filename)

    def _component_name(self, idx, mesh):
        return f"Surface {idx + 1} | Faces: {len(mesh.faces)} | Area: {mesh.area:.1f}"

    def load_model(self, filename):
        try:
            self.status_label.configure(text="Analyzing mesh and extracting selectable surfaces...", text_color="cyan")
            self.update()
            self.components = load_with_components(filename)
            self.source_label = extract_source_label(filename).get("label", os.path.splitext(os.path.basename(filename))[0])
            self._heatmap_cache.clear()
            self._selected_faces_by_component.clear()

            if not self.components:
                raise ValueError("No selectable surfaces found")

            comp_names = [self._component_name(i, c) for i, c in enumerate(self.components)]
            self.comp_menu.configure(values=comp_names)
            self.comp_menu.set(comp_names[0])
            self.selected_component_idx = 0

            self.preview_component(0)
            self.status_label.configure(
                text=f"Loaded {len(self.components)} selectable surfaces. Use dropdown/Prev/Next and 3D viewer controls.",
                text_color="white",
            )
        except Exception as e:
            self.status_label.configure(text=f"Error loading: {str(e)}", text_color="red")

    def on_component_select(self, val):
        values = self.comp_menu.cget("values")
        if val not in values:
            return
        idx = values.index(val)
        self.selected_component_idx = idx
        self.preview_component(idx)

    def select_prev_component(self):
        if not self.components:
            return
        self.selected_component_idx = (self.selected_component_idx - 1) % len(self.components)
        self._sync_component_ui()

    def select_next_component(self):
        if not self.components:
            return
        self.selected_component_idx = (self.selected_component_idx + 1) % len(self.components)
        self._sync_component_ui()

    def _sync_component_ui(self):
        name = self._component_name(self.selected_component_idx, self.components[self.selected_component_idx])
        self.comp_menu.set(name)
        self.preview_component(self.selected_component_idx)

    def _preview_mesh_data(self, mesh, max_faces=30000):
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces, dtype=np.int64)
        indices = np.arange(len(faces), dtype=np.int64)
        if len(faces) > max_faces:
            step = max(1, len(faces) // max_faces)
            indices = indices[::step]
            faces = faces[::step]
        return vertices, faces, indices

    def _preview_mesh_data_all(self, mesh_count, mesh, max_total_faces=80000):
        per_mesh = max(1200, max_total_faces // max(mesh_count, 1))
        return self._preview_mesh_data(mesh, max_faces=per_mesh)

    def _setup_axes(self):
        self.ax.clear()
        self.ax.set_facecolor("#2b2b2b")
        self.ax.set_axis_off()

    def _set_equal_limits(self, all_vertices):
        vertices = np.asarray(all_vertices, dtype=np.float64)
        max_range = np.array([
            vertices[:, 0].max() - vertices[:, 0].min(),
            vertices[:, 1].max() - vertices[:, 1].min(),
            vertices[:, 2].max() - vertices[:, 2].min(),
        ]).max() / 2.0
        mid_x = (vertices[:, 0].max() + vertices[:, 0].min()) * 0.5
        mid_y = (vertices[:, 1].max() + vertices[:, 1].min()) * 0.5
        mid_z = (vertices[:, 2].max() + vertices[:, 2].min()) * 0.5
        self.ax.set_xlim(mid_x - max_range, mid_x + max_range)
        self.ax.set_ylim(mid_y - max_range, mid_y + max_range)
        self.ax.set_zlim(mid_z - max_range, mid_z + max_range)
        self._apply_active_view()

    def _render_all_components_for_picking(self):
        self._clear_heatmap_colorbar()
        self._setup_axes()
        self._update_mouse_nav_mode()
        mesh_count = len(self.components)
        all_vertices = []

        for idx, mesh in enumerate(self.components):
            vertices, faces, _ = self._preview_mesh_data_all(mesh_count, mesh)
            if len(faces) == 0:
                continue
            all_vertices.append(vertices)

            base_color = cm.tab20(idx % 20)
            alpha = 0.85 if idx == self.selected_component_idx else 0.40
            edge_color = "#e8f0ff" if idx == self.selected_component_idx else "none"
            line_width = 0.08 if idx == self.selected_component_idx else 0.0

            collection = self.ax.plot_trisurf(
                vertices[:, 0],
                vertices[:, 1],
                vertices[:, 2],
                triangles=faces,
                color=base_color,
                edgecolor=edge_color,
                linewidth=line_width,
                alpha=alpha,
                shade=True,
            )
            collection.set_picker(True)
            setattr(collection, "_component_idx", idx)

        if all_vertices:
            merged = np.concatenate(all_vertices, axis=0)
            self._set_equal_limits(merged)

        active_mesh = self.components[self.selected_component_idx]
        self.ax.set_title(
            f"Face Pick Mode | Selected: Surface {self.selected_component_idx + 1} ({len(active_mesh.faces)} faces)",
            color="white",
        )
        self.canvas.draw()

    def _clear_heatmap_colorbar(self):
        if self._heatmap_colorbar is not None:
            self._heatmap_colorbar.remove()
            self._heatmap_colorbar = None

    def _get_component_strain(self, idx):
        key = (idx, self.method_var.get(), self.boundary_mode_var.get())
        if key in self._heatmap_cache:
            return self._heatmap_cache[key]
        vertices, faces = mesh_to_data(self.components[idx])
        solved = solve_flatten(
            vertices=vertices,
            faces=faces,
            input_unit=self.unit_var.get(),
            method=self.method_var.get(),
            boundary_mode=self.boundary_mode_var.get(),
        )
        strain = np.asarray(solved.get("strain_percent_per_face", []), dtype=np.float64)
        self._heatmap_cache[key] = strain
        return strain

    def _get_selected_face_ids(self, idx, total_faces):
        selected = self._selected_faces_by_component.get(idx, set())
        if not selected:
            return np.array([], dtype=np.int64)
        ids = np.array(sorted(i for i in selected if 0 <= i < total_faces), dtype=np.int64)
        return ids

    def _render_area_select_mode(self, idx):
        mesh = self.components[idx]
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces, dtype=np.int64)
        total_faces = len(faces)
        selected_ids = set(self._get_selected_face_ids(idx, total_faces).tolist())

        self._clear_heatmap_colorbar()
        self._setup_axes()
        self._update_mouse_nav_mode()

        collection = self.ax.plot_trisurf(
            vertices[:, 0],
            vertices[:, 1],
            vertices[:, 2],
            triangles=faces,
            color="#2a7ab0",
            edgecolor="#89a2b8",
            linewidth=0.15,
            alpha=0.45,
            shade=False,
        )

        base = np.array([0.16, 0.48, 0.69, 0.28])
        sel = np.array([0.97, 0.91, 0.13, 0.92])
        facecolors = np.tile(base, (total_faces, 1))
        if selected_ids:
            sel_idx = np.array(sorted(selected_ids), dtype=np.int64)
            facecolors[sel_idx] = sel
        collection.set_facecolor(facecolors)
        collection.set_edgecolor("#7f8c9e")
        collection.set_linewidth(0.18)
        collection.set_picker(False)

        self._set_equal_limits(vertices)
        self.ax.set_title(
            f"Area Select | Selected Faces: {len(selected_ids)}/{total_faces}",
            color="white",
        )
        self.canvas.draw()

    def _project_face_centroids_to_pixels(self, vertices, faces):
        tri = vertices[faces]
        centroids = tri.mean(axis=1)
        x2, y2, z2 = proj3d.proj_transform(centroids[:, 0], centroids[:, 1], centroids[:, 2], self.ax.get_proj())
        pts = np.vstack([x2, y2]).T
        return self.ax.transData.transform(pts)

    def on_mouse_press(self, event):
        if not self.face_pick_mode.get():
            return
        if self.face_pick_strategy_var.get() != "area":
            return
        if getattr(self.toolbar, "mode", ""):
            return
        if event.inaxes != self.ax:
            return
        if event.button != 1:
            return
        self._drag_start_px = (float(event.x), float(event.y), event.key)

    def on_mouse_release(self, event):
        if self._drag_start_px is None:
            return
        if not self.face_pick_mode.get() or self.face_pick_strategy_var.get() != "area":
            self._drag_start_px = None
            return
        if getattr(self.toolbar, "mode", ""):
            self._drag_start_px = None
            return
        if event.inaxes != self.ax:
            self._drag_start_px = None
            return

        x0, y0, key0 = self._drag_start_px
        x1, y1 = float(event.x), float(event.y)
        self._drag_start_px = None

        if abs(x1 - x0) < 4 or abs(y1 - y0) < 4:
            return

        mesh = self.components[self.selected_component_idx]
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces, dtype=np.int64)
        px = self._project_face_centroids_to_pixels(vertices, faces)
        xmin, xmax = min(x0, x1), max(x0, x1)
        ymin, ymax = min(y0, y1), max(y0, y1)
        hit = np.where((px[:, 0] >= xmin) & (px[:, 0] <= xmax) & (px[:, 1] >= ymin) & (px[:, 1] <= ymax))[0]
        if len(hit) == 0:
            return

        idx = self.selected_component_idx
        cur = set(self._selected_faces_by_component.get(idx, set()))
        key = (event.key or key0 or "").lower()
        if "shift" in key:
            cur.update(hit.tolist())
        elif "control" in key or "ctrl" in key:
            cur.difference_update(hit.tolist())
        else:
            cur = set(hit.tolist())
        self._selected_faces_by_component[idx] = cur
        self._render_area_select_mode(idx)
        self.status_label.configure(
            text=f"Area selection updated: {len(cur)} faces selected.",
            text_color="#8ac926",
        )

    def _extract_selected_submesh(self, component_idx):
        mesh = self.components[component_idx]
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces, dtype=np.int64)
        sel = self._get_selected_face_ids(component_idx, len(faces))
        if len(sel) == 0:
            return vertices, faces, 0

        faces_sel = faces[sel]
        uniq = np.unique(faces_sel.reshape(-1))
        remap = {int(v): i for i, v in enumerate(uniq.tolist())}
        new_vertices = vertices[uniq]
        new_faces = np.vectorize(lambda x: remap[int(x)], otypes=[np.int64])(faces_sel)
        return new_vertices, new_faces, int(len(sel))

    def preview_component(self, idx):
        if not self.components:
            return

        if self.face_pick_mode.get():
            if self.face_pick_strategy_var.get() == "area":
                self._render_area_select_mode(idx)
            else:
                self._render_all_components_for_picking()
            self._show_component_quality(self.components[idx])
            return

        mesh = self.components[idx]
        vertices, faces, face_indices = self._preview_mesh_data(mesh)

        self._setup_axes()
        self._update_mouse_nav_mode()
        collection = self.ax.plot_trisurf(
            vertices[:, 0],
            vertices[:, 1],
            vertices[:, 2],
            triangles=faces,
            cmap="viridis",
            edgecolor="grey",
            linewidth=0.1,
            alpha=0.85,
        )
        if self.show_heatmap_var.get() and self.method_var.get() == "ARAP":
            strain = self._get_component_strain(idx)
            if len(strain) > 0:
                strain_preview = strain[face_indices]
                cmap = cm.get_cmap("RdYlGn_r")
                norm = Normalize(vmin=0.0, vmax=3.0, clip=True)
                facecolors = cmap(norm(strain_preview))
                collection.set_facecolor(facecolors)
                collection.set_edgecolor("none")
                collection.set_linewidth(0.0)
                self._clear_heatmap_colorbar()
                sm = cm.ScalarMappable(norm=norm, cmap=cmap)
                sm.set_array([])
                self._heatmap_colorbar = self.fig.colorbar(sm, ax=self.ax, fraction=0.03, pad=0.02)
                self._heatmap_colorbar.set_label("Strain % (Green=0, Red>3)")
        else:
            self._clear_heatmap_colorbar()
        self.ax.set_title(f"Surface Preview ({len(mesh.faces)} faces)", color="white")

        self._set_equal_limits(vertices)
        self.canvas.draw()
        self._show_component_quality(mesh)

    def on_pick(self, event):
        if not self.face_pick_mode.get() or not self.components:
            return
        if self.face_pick_strategy_var.get() != "component":
            return
        if getattr(self.toolbar, "mode", ""):
            return

        component_idx = getattr(event.artist, "_component_idx", None)
        if component_idx is None:
            return
        if component_idx < 0 or component_idx >= len(self.components):
            return

        self.selected_component_idx = component_idx
        self._sync_component_ui()
        self.status_label.configure(
            text=f"Face Pick: selected Surface {component_idx + 1}.",
            text_color="#8ac926",
        )

    def _show_component_quality(self, mesh):
        q = component_quality(mesh)
        if q["non_manifold_edges"] > 0 or q["degenerate_faces"] > 0:
            color = "#f0ad4e"
            flag = "Mesh warnings"
        else:
            color = "#8ac926"
            flag = "Mesh clean"
        details = (
            f"{flag}: faces={q['faces']}, open_edges={q['open_edges']}, "
            f"non_manifold={q['non_manifold_edges']}, degenerate={q['degenerate_faces']}"
        )
        self.status_label.configure(text=details, text_color=color)

    def browse_output(self):
        filename = filedialog.asksaveasfilename(
            defaultextension=".dxf",
            filetypes=[("DXF files", "*.dxf"), ("SVG files", "*.svg"), ("All files", "*.*")],
        )
        if filename:
            self.output_path.set(filename)

    def browse_nesting_input_dir(self):
        folder = filedialog.askdirectory()
        if folder:
            self.nest_input_dir_var.set(folder)
            if not self.nest_output_dir_var.get():
                self.nest_output_dir_var.set(folder)

    def browse_nesting_output_dir(self):
        folder = filedialog.askdirectory()
        if folder:
            self.nest_output_dir_var.set(folder)

    def run_nesting_job(self):
        try:
            input_dir = (self.nest_input_dir_var.get() or "").strip()
            output_dir = (self.nest_output_dir_var.get() or "").strip()
            if not input_dir:
                raise ValueError("Select nesting input folder first.")
            if not output_dir:
                raise ValueError("Select nesting output folder first.")

            roll_width = float((self.nest_roll_width_var.get() or "").strip())
            gap = float((self.nest_gap_var.get() or "").strip())
            rotation_step = float((self.nest_rotation_var.get() or "").strip())
            max_len = float((self.nest_max_sheet_len_var.get() or "").strip())
            if roll_width <= 0 or gap < 0 or rotation_step <= 0 or max_len <= 0:
                raise ValueError("Invalid nesting parameters.")

            self.status_label.configure(text="Running nesting...", text_color="cyan")
            self.update()
            result = run_nesting(
                input_dir=input_dir,
                output_dir=output_dir,
                roll_width_mm=roll_width,
                gap_mm=gap,
                rotation_step_deg=rotation_step,
                max_sheet_length_mm=max_len,
            )

            sheets = result.get("sheet_count", 0)
            files = result.get("sheet_files", [])
            lengths = result.get("used_length_mm_per_sheet", {})
            length_text = ", ".join(f"S{i+1}:{lengths.get(i, 0.0):.1f}mm" for i in sorted(lengths.keys()))
            status = (
                f"Nesting complete: {result.get('input_count', 0)} piece(s), {sheets} sheet(s)\n"
                f"Output: {os.path.basename(files[0]) if files else 'n/a'}\n"
                f"Used lengths: {length_text}"
            )
            self.status_label.configure(text=status, text_color="#8ac926")
        except Exception as e:
            self.status_label.configure(text=f"Nesting error: {str(e)}", text_color="red")

    def run_flattening(self):
        if not self.components:
            self.status_label.configure(text="Error: No model loaded", text_color="red")
            return

        out = self.output_path.get().strip()
        unit = self.unit_var.get()
        method = self.method_var.get()
        boundary_mode = self.boundary_mode_var.get()
        seam_allowance_mm = self._get_seam_allowance_mm()
        relief_threshold_pct = self._get_relief_threshold_pct()

        if not out:
            self.status_label.configure(text="Error: Set output path first", text_color="red")
            return

        try:
            surface_no = self.selected_component_idx + 1
            self.status_label.configure(text=f"Flattening Surface {surface_no} with {method}...", text_color="cyan")
            self.update()

            q = component_quality(self.components[self.selected_component_idx])
            has_hard_mesh_issue = q["non_manifold_edges"] > 0 or q["degenerate_faces"] > 0
            if has_hard_mesh_issue and not self.allow_dirty_export_var.get():
                self.status_label.configure(
                    text=(
                        "Export blocked: mesh has non-manifold or degenerate faces.\n"
                        "Enable 'Allow Export with Mesh Warnings' to override."
                    ),
                    text_color="red",
                )
                return

            selected_faces_count = 0
            if self.face_pick_mode.get() and self.face_pick_strategy_var.get() == "area":
                vertices, faces, selected_faces_count = self._extract_selected_submesh(self.selected_component_idx)
            else:
                vertices, faces = mesh_to_data(self.components[self.selected_component_idx])
            result = flatten_mesh(
                vertices=vertices,
                faces=faces,
                path_output=out,
                show_plot=False,
                input_unit=unit,
                method=method,
                boundary_mode=boundary_mode,
                seam_allowance_mm=seam_allowance_mm,
                align_to_x=self.align_to_x_enabled,
                label_text=self.source_label,
                auto_relief_cut=self.auto_relief_var.get(),
                relief_threshold_pct=relief_threshold_pct,
            )

            metrics = result.get("metrics", {})
            area_err = metrics.get("area_error_pct", 0.0)
            perim_err = metrics.get("perimeter_error_pct", 0.0)
            loops = result.get("bounds_exported", 0)
            relief_path = result.get("relief_path_2d")
            relief_note = "Yes" if relief_path is not None else "No"

            quality_color = "green" if area_err <= 2.0 and perim_err <= 1.0 else "#f0ad4e"
            warning_note = ""
            if area_err > 3.0 or perim_err > 3.0:
                warning_note = "\nProduction warning: high distortion. Consider different sheet/relief cuts."
            status = (
                f"Success: {os.path.basename(out)}\n"
                f"Area error: {area_err:.2f}% | Perimeter error: {perim_err:.2f}% | Loops: {loops}\n"
                f"Seam allowance: {seam_allowance_mm:.2f} mm | Align X: {'ON' if self.align_to_x_enabled else 'OFF'}\n"
                f"Relief cut suggested: {relief_note} (trigger>{relief_threshold_pct:.2f}%)"
                f"{warning_note}"
            )
            if selected_faces_count > 0:
                status += f"\nExported selected area faces: {selected_faces_count}"
            self.status_label.configure(text=status, text_color=quality_color)
        except Exception as e:
            self.status_label.configure(text=f"Error: {str(e)}", text_color="red")


if __name__ == "__main__":
    app = FlattenApp()
    app.mainloop()
