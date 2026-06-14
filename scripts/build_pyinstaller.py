import os
import sys
import subprocess
import shutil

def check_requirements():
    """Check if PyInstaller is installed."""
    try:
        import PyInstaller
        print(f"[OK] PyInstaller {PyInstaller.__version__} is installed.")
    except ImportError:
        print("[ERROR] PyInstaller is not installed. Run: pip install pyinstaller")
        return False
    return True

def build():
    if not check_requirements():
        return

    print("Starting PyInstaller build for PyLog...")
    
    # Project root is parent of scripts/
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    os.chdir(project_root)
    
    entry_point = "main.py"
    output_name = "PyLog"
    dist_dir = "dist/pyinstaller"
    
    # Clean up previous build
    if os.path.exists(dist_dir):
        print(f"Cleaning previous build at {dist_dir}...")
        # Note: shutil.rmtree might fail if files are locked
        try:
            shutil.rmtree(dist_dir)
        except Exception as e:
            print(f"Warning: Could not clean {dist_dir}: {e}")

    # Build the command
   # Build the command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",            # Directory mode
        "--windowed",          # [NEW] 隐藏控制台黑框 (如果需要调试可以暂时注释掉这行)
        f"--name={output_name}",
        f"--distpath={dist_dir}",
        
        # [HIDDEN IMPORTS]
        # 删除了所有常规的 PySide6 模块，PyInstaller 会自动分析依赖！
        # 只有当你代码里使用 importlib 动态加载，或者真的报 ImportError 时，才写在这里。
        
        # [EXCLUSIONS] (反向瘦身：剔除绝对用不到的库)
        "--exclude-module=PyQt5",
        "--exclude-module=PyQt6",
        "--exclude-module=PySide2",
        "--exclude-module=tkinter",
        "--exclude-module=unittest",
        "--hidden-import=pydoc",
        "--exclude-module=IPython",     # openai 等库经常会顺带引入 IPython 等无用大包
        "--exclude-module=jedi",
        
        # [CRITICAL] 如果你的程序没有使用到网页浏览器控件，强烈建议取消注释下面这行！
        # "--exclude-module=PySide6.QtWebEngineCore", 
        # "--exclude-module=PySide6.QtWebEngineWidgets",
        
        # [DATA FILES]
        # Format: source;destination (Windows)
        "--add-data=icons;icons",
        "--add-data=plugins;plugins",
        "--add-data=data;data",
        "--add-data=docs;docs",
        "--add-data=wellData;wellData",
        "--add-data=scripts_user;scripts_user",
        "--add-data=matplotlibrc;.",
        
        # [HOOKS / METADATA]
        # 很多现代库(如 openai)只需要读取自身的版本元数据，不需要 collect-all 这种重型操作
        "--copy-metadata=openai", 
        
        # 先尝试注释掉 collect-all。如果运行后真的报错缺文件，再加回来
        # "--collect-all=pyqtgraph", 
        "--collect-all=openai",
        
        # Entry point
        entry_point
    ]
    
    print(f"Running command: {' '.join(cmd)}")
    
    try:
        subprocess.run(cmd, check=True)
        
        # --- [POST-BUILD] Move data folders to root for better visibility ---
        print("\n[POST-BUILD] Moving data folders to root for visibility...")
        root_dist = os.path.join(project_root, dist_dir, output_name)
        internal_dir = os.path.join(root_dist, "_internal")
        
        for folder in ["data", "docs", "scripts_user", "wellData"]:
            src = os.path.join(internal_dir, folder)
            dst = os.path.join(root_dist, folder)
            if os.path.exists(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.move(src, dst)
                print(f"  Moved {folder} to root distribution folder.")

        print("\n[SUCCESS] Build completed successfully!")
        print(f"Output located in: {root_dist}")
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Build failed with error code {e.returncode}")
    except Exception as e:
        print(f"\n[ERROR] An unexpected error occurred: {e}")

if __name__ == "__main__":
    build()
