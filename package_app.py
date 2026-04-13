import os
import subprocess
import sys

def package():
    print("--- Starting Packaging Process ---")
    
    # 1. Install PyInstaller if missing
    try:
        import PyInstaller
        print("PyInstaller already installed.")
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 2. Check for spec file
    spec_file = "visual_suspension_editor.spec"
    if not os.path.exists(spec_file):
        print(f"Error: {spec_file} not found!")
        return

    # 3. Check for icon
    if not os.path.exists("app_icon.ico"):
        print("Warning: app_icon.ico not found. PyInstaller will use default icon.")

    # 4. Run PyInstaller
    print(f"Running PyInstaller with {spec_file}...")
    try:
        subprocess.check_call(["pyinstaller", "--noconfirm", "--clean", spec_file])
        print("\n--- Packaging Complete! ---")
        print("Your executable can be found in the 'dist' folder.")
    except subprocess.CalledProcessError as e:
        print(f"\nError during packaging: {e}")
    except FileNotFoundError:
        # Sometimes pyinstaller isn't in PATH even after pip install
        print("pyinstaller command not found in PATH, trying python -m PyInstaller...")
        try:
            subprocess.check_call([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", spec_file])
            print("\n--- Packaging Complete! ---")
            print("Your executable can be found in the 'dist' folder.")
        except Exception as e2:
            print(f"Failed to run PyInstaller: {e2}")

if __name__ == "__main__":
    package()
