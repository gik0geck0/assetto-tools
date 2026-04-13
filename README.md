# Assetto Corsa Tire Tools

A collection of Python utilities for analyzing, predicting, and modifying tire physics properties in Assetto Corsa.

## Components

- **predict_gforce.py**: Calculates and predicts tire G-forces (lateral, longitudinal, and combined) across different slip angles.
- **analyze_tires.py**: Analyzes trends between various tire widths and parameters.
- **modify_tires.py**: Modifies and generates new tire configurations based on input data.
- **verify_resize.py**: Verifies resized tire properties.
- **visual_suspension_editor.py**: A 3D visual editor for Assetto Corsa suspension configuration files (`suspensions.ini`). Supports bidirectional editing of relative and absolute coordinates.

## Getting Started

1. Activate the Python virtual environment:
   ```cmd
   venv\Scripts\activate
   ```
2. Install required dependencies:
   ```cmd
   pip install pyvista pyvistaqt PySide6
   ```
3. Run any script directly, for example:
   ```cmd
   python predict_gforce.py
   ```

## Usage: Visual Suspension Editor

### Launching
Run the editor with:
```cmd
python visual_suspension_editor.py
```
It will attempt to load a `suspensions.ini` file in the current directory by default. You can also use **File > Open** to load a specific file.

### Controls
- **3D Viewport**:
  - **Right Click**: Select a suspension point (highlighted in the properties panel).
  - **Left Click + Drag**: Orbit the camera.
  - **Middle Click + Drag**: Pan the camera.
  - **Scroll Wheel**: Zoom in/out.
- **Properties Panel**:
  - **Relative (File) Coordinates**: Modify the values as they appear in the `.ini` file.
  - **Absolute (World) Coordinates**: Modify the physical world-space position (centered on the car chassis).
  - **Camera Orbit Slider**: Rotate the camera precisely around the Y-axis.
- **Saving**:
  - Click **Save to suspensions.ini** or use **File > Save** to write changes back to the configuration file.

### Features
- **Bidirectional Sync**: Changing a value in relative space updates absolute space and the 3D scene, and vice versa.
- **Automatic Scaling**: Uses `WHEELBASE` and `TRACK` to correctly position the front and rear axles.
- **Visual References**:
  - **Green Box**: Chassis center (0,0,0).
  - **Yellow Sphere**: Center of Gravity (based on `CG_LOCATION`).
  - **Wireframe Cylinders**: Tire positions and dimensions.
  - **Green Arrow**: Forward axis indicator.
  - **Pink/Cyan Lines**: Suspension arm and strut geometry wireframes.
