import sys
import os
import re
from PySide6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
                               QLabel, QFileDialog, QDockWidget, QFormLayout, QPushButton,
                               QDoubleSpinBox, QMessageBox, QSlider, QGroupBox)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

try:
    import pyvista as pv
    from pyvistaqt import QtInteractor
except ImportError:
    print("Please install required packages: pip install pyvista pyvistaqt PySide6")
    sys.exit(1)


def format_vector3(vec):
    return f"{vec[0]:.4f}, {vec[1]:.4f}, {vec[2]:.4f}"

class SuspensionFile:
    def __init__(self, filepath):
        self.filepath = filepath
        self.lines = []
        # Keyed by (section, key), value is dict with val, line_idx, indent, comment
        self.points = {} 
        self.scalars = {}
        self.load()

    def load(self):
        if not os.path.exists(self.filepath):
            return False

        with open(self.filepath, 'r', encoding='utf-8') as f:
            self.lines = f.readlines()
            
        current_section = None
        # Regex to capture: indent, key, space, value, optional comment
        prop_re = re.compile(r'^(\s*)([a-zA-Z0-9_]+)\s*=\s*([^;]+?)\s*(;.*)?$')
        sec_re = re.compile(r'^\[([a-zA-Z0-9_]+)\]')
        
        for i, line in enumerate(self.lines):
            stripped = line.strip()
            sec_match = sec_re.match(stripped)
            if sec_match:
                current_section = sec_match.group(1).upper()
                continue
                
            if current_section in ['FRONT', 'REAR', 'AXLE', 'BASIC']:
                match = prop_re.match(line)
                if match:
                    key = match.group(2)
                    val_str = match.group(3).strip()
                    parts = [p.strip() for p in val_str.split(',')]
                    if len(parts) == 3:
                        try:
                            vec = [float(parts[0]), float(parts[1]), float(parts[2])]
                            self.points[(current_section, key)] = {
                                "val": vec,
                                "line_idx": i,
                                "indent": match.group(1),
                                "comment": match.group(4) or ""
                            }
                        except ValueError:
                            pass
                    elif len(parts) == 1:
                        try:
                            self.scalars[(current_section, key)] = float(parts[0])
                        except ValueError:
                            pass
        return True

    def get_wheel_center(self, section):
        wheelbase = self.scalars.get(("BASIC", "WHEELBASE"), 0.0)
        
        var_sec = section
        if section == "AXLE" and ("AXLE", "TRACK") not in self.scalars:
            var_sec = "REAR"
            
        track = self.scalars.get((var_sec, "TRACK"), 0.0)
        basey = self.scalars.get((var_sec, "BASEY"), 0.0)
        rim_offset = self.scalars.get((var_sec, "RIM_OFFSET"), 0.0)
        
        z_offset = (wheelbase / 2.0) if section == "FRONT" else (-wheelbase / 2.0)
        x_offset = (track / 2.0) + rim_offset
        y_offset = basey
        return [x_offset, y_offset, z_offset]

    def to_absolute(self, section, relative_vec):
        wc_x, wc_y, wc_z = self.get_wheel_center(section)
        return [wc_x - relative_vec[0], wc_y + relative_vec[1], wc_z + relative_vec[2]]

    def to_relative(self, section, absolute_vec):
        wc_x, wc_y, wc_z = self.get_wheel_center(section)
        return [wc_x - absolute_vec[0], absolute_vec[1] - wc_y, absolute_vec[2] - wc_z]

    def save(self):
        for (section, key), data in self.points.items():
            vec = data["val"]
            line_idx = data["line_idx"]
            indent = data["indent"]
            comment = data["comment"]
            new_val_str = format_vector3(vec)
            if comment:
                self.lines[line_idx] = f"{indent}{key}={new_val_str}\t\t{comment}\n"
            else:
                self.lines[line_idx] = f"{indent}{key}={new_val_str}\n"

        with open(self.filepath, 'w', encoding='utf-8') as f:
            f.writelines(self.lines)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Assetto Corsa Visual Suspension Editor")
        self.resize(1200, 800)

        self.suspension_file = None
        self.current_point_key = None
        self.actor_to_key = {}
        self.meshes = {}
        self.line_actors = []

        self.setup_ui()
        self.setup_menu()

        # Load default file if exists
        default_file = os.path.join(os.getcwd(), "suspensions.ini")
        if os.path.exists(default_file):
            self.load_file(default_file)

    def setup_ui(self):
        central_widget = QWidget()
        layout = QVBoxLayout()
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

        # PyVista Viewport
        self.plotter = QtInteractor(self)
        layout.addWidget(self.plotter.interactor)
        
        # Add legend cube
        self.plotter.add_axes()
        self.plotter.add_camera_orientation_widget()

        # Setup Mesh picking
        self.plotter.enable_mesh_picking(callback=self.on_mesh_picked, show_message=False)

        # Dock Widget for the properties panel
        self.dock = QDockWidget("Point Properties", self)
        self.dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)

        panel = QWidget()
        self.panel_layout = QVBoxLayout()
        panel.setLayout(self.panel_layout)
        self.dock.setWidget(panel)

        # Camera Orbit controls
        cam_group = QVBoxLayout()
        lbl_cam = QLabel("Camera Orbit (Y Axis)")
        lbl_cam.setStyleSheet("font-weight: bold; font-size: 14px; margin-top: 10px;")
        cam_group.addWidget(lbl_cam)
        
        self.cam_slider = QSlider(Qt.Horizontal)
        self.cam_slider.setRange(0, 360)
        self.cam_slider.setValue(0)
        self.cam_slider.valueChanged.connect(self.on_camera_slider_moved)
        cam_group.addWidget(self.cam_slider)
        
        self.panel_layout.addLayout(cam_group)
        self.panel_layout.addSpacing(15)

        self.lbl_point_name = QLabel("Select a point")
        self.lbl_point_name.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.panel_layout.addWidget(self.lbl_point_name)

        # Relative Group
        self.group_rel = QGroupBox("Relative (File) Coordinates")
        form_rel = QFormLayout()
        self.slider_rel_x, self.spin_rel_x = self._create_slider_row("Rel X (m):", form_rel, self.on_rel_value_changed)
        self.slider_rel_y, self.spin_rel_y = self._create_slider_row("Rel Y (m):", form_rel, self.on_rel_value_changed)
        self.slider_rel_z, self.spin_rel_z = self._create_slider_row("Rel Z (m):", form_rel, self.on_rel_value_changed)
        self.group_rel.setLayout(form_rel)
        self.panel_layout.addWidget(self.group_rel)

        # Absolute Group
        self.group_abs = QGroupBox("Absolute (World) Coordinates")
        form_abs = QFormLayout()
        self.slider_abs_x, self.spin_abs_x = self._create_slider_row("Abs X (m):", form_abs, self.on_abs_value_changed)
        self.slider_abs_y, self.spin_abs_y = self._create_slider_row("Abs Y (m):", form_abs, self.on_abs_value_changed)
        self.slider_abs_z, self.spin_abs_z = self._create_slider_row("Abs Z (m):", form_abs, self.on_abs_value_changed)
        self.group_abs.setLayout(form_abs)
        self.panel_layout.addWidget(self.group_abs)

        btn_save = QPushButton("Save to suspensions.ini")
        btn_save.clicked.connect(self.save_file)
        self.panel_layout.addWidget(btn_save)

        self.panel_layout.addStretch()

        self.set_sliders_enabled(False)
        self._updating_sliders = False

    def _create_slider_row(self, label, form, callback):
        row = QHBoxLayout()
        slider = QSlider(Qt.Horizontal)
        slider.setRange(-5000, 5000) # -5m to +5m in mm
        
        spin = QDoubleSpinBox()
        spin.setRange(-5.0, 5.0)
        spin.setDecimals(4)
        spin.setSingleStep(0.005)
        
        row.addWidget(slider)
        row.addWidget(spin)
        form.addRow(label, row)
        
        slider.valueChanged.connect(lambda v: spin.setValue(v / 1000.0))
        spin.valueChanged.connect(lambda v: self._safe_set_slider(slider, v))
        spin.valueChanged.connect(callback)
        return slider, spin

    def _safe_set_slider(self, slider, v):
        slider.blockSignals(True)
        slider.setValue(int(v * 1000.0))
        slider.blockSignals(False)

    def setup_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        
        open_action = QAction("Open", self)
        open_action.triggered.connect(self.open_dialog)
        file_menu.addAction(open_action)

        save_action = QAction("Save", self)
        save_action.triggered.connect(self.save_file)
        file_menu.addAction(save_action)

    def open_dialog(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Open suspensions.ini", "", "INI Files (*.ini);;All Files (*)")
        if filename:
            self.load_file(filename)

    def load_file(self, filepath=None):
        if not filepath:
            filepath, _ = QFileDialog.getOpenFileName(self, "Open Suspension File", "", "INI Files (*.ini)")
            if not filepath:
                return

        self.suspension_file = SuspensionFile(filepath)
        if not self.suspension_file.lines:
            QMessageBox.critical(self, "Error", "Failed to load file.")
            self.suspension_file = None
            return

        # Validate Critical Physical Scale Variables
        wb = self.suspension_file.scalars.get(("BASIC", "WHEELBASE"), 0.0)
        t_front = self.suspension_file.scalars.get(("FRONT", "TRACK"), 0.0)
        
        # Check Rear explicitly or fallback to Axle
        t_rear = self.suspension_file.scalars.get(("REAR", "TRACK"), 0.0)
        if ("AXLE", "TRACK") in self.suspension_file.scalars:
            t_rear = self.suspension_file.scalars.get(("AXLE", "TRACK"), 0.0)

        missing_vars = []
        if wb == 0.0: missing_vars.append("WHEELBASE in [BASIC]")
        if t_front == 0.0: missing_vars.append("TRACK in [FRONT]")
        if t_rear == 0.0: missing_vars.append("TRACK in [REAR]/[AXLE]")

        if missing_vars:
            msg = f"Critical coordinate scalars were evaluated as 0.0 or not found:\n\n{chr(10).join(missing_vars)}\n\nAbsolute geometries will stack or misalign."
            QMessageBox.warning(self, "Mathematical Warning", msg)

        self.current_point_key = None
        self.set_sliders_enabled(False)
        self.lbl_point_name.setText("Select a point")
        self.rebuild_scene()

    def save_file(self):
        if self.suspension_file:
            self.suspension_file.save()
            QMessageBox.information(self, "Success", "Saved successfully!")

    def on_camera_slider_moved(self, value):
        if self.plotter:
            self.plotter.camera.azimuth = value
            self.plotter.render()

    def rebuild_scene(self):
        self.plotter.clear()
        self.plotter.add_axes()
        self.plotter.add_camera_orientation_widget()
        
        # Lock UP vector to Y and enable Turntable (Terrain) style
        self.plotter.camera.up = (0, 1, 0)
        self.plotter.enable_terrain_style(mouse_wheel_zooms=True)
        
        self.actor_to_key.clear()
        self.meshes.clear()
        self.line_actors.clear()

        if not self.suspension_file:
            return

        # Draw Points
        for (section, key), data in self.suspension_file.points.items():
            rel_vec = data["val"]
            abs_vec = self.suspension_file.to_absolute(section, rel_vec)
            color = "red" if section == "FRONT" else "blue"
            
            # Primary sphere (World/Absolute space)
            sphere = pv.Sphere(radius=0.015, center=abs_vec)
            actor = self.plotter.add_mesh(sphere, color=color, pickable=True, name=f"{section}_{key}")
            self.actor_to_key[actor] = (section, key)
            self.meshes[(section, key)] = sphere
            
            # Mirrored sphere across Absolute X=0
            m_vec = [-abs_vec[0], abs_vec[1], abs_vec[2]]
            m_sphere = pv.Sphere(radius=0.015, center=m_vec)
            m_color = "pink" if section == "FRONT" else "cyan"
            self.plotter.add_mesh(m_sphere, color=m_color, pickable=False, name=f"{section}_{key}_mirrored")

        # Origin Box to denote Chassis Center
        origin_box = pv.Cube(center=(0, 0, 0), x_length=0.1, y_length=0.05, z_length=0.1)
        self.plotter.add_mesh(origin_box, color="white", pickable=False, name="chassis_origin_center")

        # Draw Center of Gravity (CG)
        wheelbase = self.suspension_file.scalars.get(("BASIC", "WHEELBASE"), 0.0)
        cg_fraction = self.suspension_file.scalars.get(("BASIC", "CG_LOCATION"), 0.5)
        cg_z = wheelbase * (cg_fraction - 0.5)
        cg_point = [0, 0, cg_z]
        cg_sphere = pv.Sphere(radius=0.04, center=cg_point)
        self.plotter.add_mesh(cg_sphere, color="yellow", pickable=False, name="cg_indicator")
        
        # Draw Tires (Wireframe Cylinders)
        tire_radius = 25.7 * 0.0254 / 2.0  # 25.7 inches diameter in m
        tire_width = 0.245 # 245mm out to m
        for axle in ["FRONT", "REAR"]:
            wc_x, wc_y, wc_z = self.suspension_file.get_wheel_center(axle)
            
            # Since tire sits at wheel center
            tire_c = pv.Cylinder(center=(wc_x, wc_y, wc_z), direction=(1,0,0), radius=tire_radius, height=tire_width, resolution=32)
            self.plotter.add_mesh(tire_c, color="gray", style="wireframe", pickable=False, name=f"{axle}_TIRE_L")
            
            # Mirrored Right tire
            tire_c_r = pv.Cylinder(center=(-wc_x, wc_y, wc_z), direction=(1,0,0), radius=tire_radius, height=tire_width, resolution=32)
            self.plotter.add_mesh(tire_c_r, color="gray", style="wireframe", pickable=False, name=f"{axle}_TIRE_R")

        self.draw_wireframes()
        self.plotter.reset_camera()

    def draw_wireframes(self):
        # Remove old lines
        for actor in self.line_actors:
            self.plotter.remove_actor(actor)
        self.line_actors.clear()

        # Connect standard A-Arms, Struts, and Axles if they exist
        lines_to_draw = [
            ("FRONT", [("WBCAR_BOTTOM_FRONT", "WBTYRE_BOTTOM"), ("WBCAR_BOTTOM_REAR", "WBTYRE_BOTTOM")]),
            ("FRONT", [("WBCAR_TOP_FRONT", "WBTYRE_TOP"), ("WBCAR_TOP_REAR", "WBTYRE_TOP")]),
            ("FRONT", [("WBCAR_STEER", "WBTYRE_STEER")]),
            ("FRONT", [("STRUT_CAR", "STRUT_TYRE"), ("STRUT_TYRE", "WBTYRE_BOTTOM")]),
            ("REAR", [("WBCAR_BOTTOM_FRONT", "WBTYRE_BOTTOM"), ("WBCAR_BOTTOM_REAR", "WBTYRE_BOTTOM")]),
            ("REAR", [("WBCAR_TOP_FRONT", "WBTYRE_TOP"), ("WBCAR_TOP_REAR", "WBTYRE_TOP")]),
            ("REAR", [("WBCAR_STEER", "WBTYRE_STEER")]),
            ("REAR", [("STRUT_CAR", "STRUT_TYRE"), ("STRUT_TYRE", "WBTYRE_BOTTOM")]),
            ("AXLE", [("J0_CAR", "J0_AXLE"), ("J1_CAR", "J1_AXLE"), ("J2_CAR", "J2_AXLE"), ("J3_CAR", "J3_AXLE"), ("J4_CAR", "J4_AXLE")]),
        ]

        def add_line(p1, p2, color, mirrored=False):
            if mirrored:
                p1 = [-p1[0], p1[1], p1[2]]
                p2 = [-p2[0], p2[1], p2[2]]
            line = pv.Line(p1, p2)
            actor = self.plotter.add_mesh(line, color=color, line_width=3, pickable=False)
            self.line_actors.append(actor)

        for section, connections in lines_to_draw:
            for p1_key, p2_key in connections:
                k1 = (section, p1_key)
                k2 = (section, p2_key)
                if k1 in self.suspension_file.points and k2 in self.suspension_file.points:
                    p1_rel = self.suspension_file.points[k1]["val"]
                    p2_rel = self.suspension_file.points[k2]["val"]
                    p1 = self.suspension_file.to_absolute(section, p1_rel)
                    p2 = self.suspension_file.to_absolute(section, p2_rel)
                    color = "pink" if section == "FRONT" else "cyan"
                    
                    add_line(p1, p2, color)
                    add_line(p1, p2, color, mirrored=True)

        # Forward Direction Indicator Arrow (World Space)
        max_z = 0
        if self.suspension_file and self.suspension_file.points:
            # We want max Z in absolute space
            zs = [self.suspension_file.to_absolute(s, d["val"])[2] for (s, k), d in self.suspension_file.points.items()]
            if zs:
                max_z = max(zs)
                
        arrow_start = [0, 0.4, max_z + 0.2]
        arrow = pv.Arrow(start=arrow_start, direction=[0, 0, 0.5], scale=1.0)
        arrow_actor = self.plotter.add_mesh(arrow, color="green", pickable=False, name="forward_arrow")
        self.line_actors.append(arrow_actor)
        
        label_actor = self.plotter.add_point_labels([arrow_start], ["FORWARD"], text_color='green', font_size=20, point_size=0, name="forward_label", always_visible=True)
        self.line_actors.append(label_actor)

    def on_mesh_picked(self, mesh):
        # Find which key this mesh maps to
        picked_key = None
        for key, sphere in self.meshes.items():
            if sphere == mesh:
                picked_key = key
                break
                
        if picked_key:
            self.select_point(picked_key)

    def select_point(self, point_key):
        self.current_point_key = point_key
        section, key = point_key
        self.lbl_point_name.setText(f"[{section}] {key}")
        
        vec_rel = self.suspension_file.points[point_key]["val"]
        vec_abs = self.suspension_file.to_absolute(section, vec_rel)
        
        self._updating_sliders = True
        
        # Relative
        self.spin_rel_x.setValue(vec_rel[0])
        self.spin_rel_y.setValue(vec_rel[1])
        self.spin_rel_z.setValue(vec_rel[2])
        self._safe_set_slider(self.slider_rel_x, vec_rel[0])
        self._safe_set_slider(self.slider_rel_y, vec_rel[1])
        self._safe_set_slider(self.slider_rel_z, vec_rel[2])
        
        # Absolute
        self.spin_abs_x.setValue(vec_abs[0])
        self.spin_abs_y.setValue(vec_abs[1])
        self.spin_abs_z.setValue(vec_abs[2])
        self._safe_set_slider(self.slider_abs_x, vec_abs[0])
        self._safe_set_slider(self.slider_abs_y, vec_abs[1])
        self._safe_set_slider(self.slider_abs_z, vec_abs[2])

        self._updating_sliders = False
        self.set_sliders_enabled(True)

    def set_sliders_enabled(self, enabled):
        self.spin_rel_x.setEnabled(enabled)
        self.spin_rel_y.setEnabled(enabled)
        self.spin_rel_z.setEnabled(enabled)
        self.slider_rel_x.setEnabled(enabled)
        self.slider_rel_y.setEnabled(enabled)
        self.slider_rel_z.setEnabled(enabled)
        
        self.spin_abs_x.setEnabled(enabled)
        self.spin_abs_y.setEnabled(enabled)
        self.spin_abs_z.setEnabled(enabled)
        self.slider_abs_x.setEnabled(enabled)
        self.slider_abs_y.setEnabled(enabled)
        self.slider_abs_z.setEnabled(enabled)

    def on_rel_value_changed(self):
        if self._updating_sliders or not self.current_point_key or not self.suspension_file:
            return

        x = self.spin_rel_x.value()
        y = self.spin_rel_y.value()
        z = self.spin_rel_z.value()
        
        section, _ = self.current_point_key
        abs_vec = self.suspension_file.to_absolute(section, [x, y, z])
        
        self._updating_sliders = True
        self.spin_abs_x.setValue(abs_vec[0])
        self.spin_abs_y.setValue(abs_vec[1])
        self.spin_abs_z.setValue(abs_vec[2])
        self._safe_set_slider(self.slider_abs_x, abs_vec[0])
        self._safe_set_slider(self.slider_abs_y, abs_vec[1])
        self._safe_set_slider(self.slider_abs_z, abs_vec[2])
        self._updating_sliders = False
        
        self._update_point_in_scene([x, y, z], abs_vec)

    def on_abs_value_changed(self):
        if self._updating_sliders or not self.current_point_key or not self.suspension_file:
            return

        x = self.spin_abs_x.value()
        y = self.spin_abs_y.value()
        z = self.spin_abs_z.value()
        
        section, _ = self.current_point_key
        rel_vec = self.suspension_file.to_relative(section, [x, y, z])
        
        self._updating_sliders = True
        self.spin_rel_x.setValue(rel_vec[0])
        self.spin_rel_y.setValue(rel_vec[1])
        self.spin_rel_z.setValue(rel_vec[2])
        self._safe_set_slider(self.slider_rel_x, rel_vec[0])
        self._safe_set_slider(self.slider_rel_y, rel_vec[1])
        self._safe_set_slider(self.slider_rel_z, rel_vec[2])
        self._updating_sliders = False
        
        self._update_point_in_scene(rel_vec, [x, y, z])

    def _update_point_in_scene(self, rel_vec, abs_vec):
        # Update data model (saves relative!)
        self.suspension_file.points[self.current_point_key]["val"] = rel_vec

        section, key = self.current_point_key
        new_sphere = pv.Sphere(radius=0.015, center=abs_vec)
        
        color = "red" if section == "FRONT" else "blue"
        name_id = f"{section}_{key}"
        self.plotter.add_mesh(new_sphere, color=color, pickable=True, name=name_id)
        
        self.meshes[self.current_point_key] = new_sphere
        
        # Mirrored across absolute X=0
        m_vec = [-abs_vec[0], abs_vec[1], abs_vec[2]]
        m_sphere = pv.Sphere(radius=0.015, center=m_vec)
        m_color = "pink" if section == "FRONT" else "cyan"
        self.plotter.add_mesh(m_sphere, color=m_color, pickable=False, name=f"{section}_{key}_mirrored")

        self.draw_wireframes()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
