from cx_Freeze import setup, Executable

build_exe_options = {
    "packages": ["pylibobs", "wx", "av", "sounddevice", "numpy",
                  "accessible_output2", "engine", "ui"],
    "include_files": [],
    "excludes": ["tkinter", "matplotlib", "pandas"],
}

setup(
    name="Eternal Recorder",
    version="2.1.2",
    description="Gravador de tela acessível para leitores de tela",
    options={"build_exe": build_exe_options},
    executables=[Executable("launcher.py", base="Win32GUI",
                            target_name="Eternal Recorder")],
)
