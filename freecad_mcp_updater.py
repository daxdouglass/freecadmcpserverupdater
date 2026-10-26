"""GUI utility to install/update the FreeCAD MCP addon (https://github.com/neka-nat/freecad-mcp).

The addon lives in the repo at addon/FreeCADMCP and must be copied into a FreeCAD
"Mod" directory. Only the Python standard library is used.
"""
import io
import json
import os
import shutil
import sys
import threading
import tkinter as tk
import urllib.request
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

REPO = "neka-nat/freecad-mcp"
BRANCH = "main"
ADDON_SUBPATH = "addon/FreeCADMCP"
ADDON_NAME = "FreeCADMCP"
VERSION_FILE = ".installed_commit"
CONFIG_FILE = Path.home() / ".freecad_mcp_updater.json"
UA = {"User-Agent": "freecad-mcp-updater"}


def user_mod_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "FreeCAD" / "Mod"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/FreeCAD/Mod"
    return Path.home() / ".local/share/FreeCAD/Mod"


def detect_freecad() -> str:
    candidates = []
    if sys.platform == "win32":
        for env in ("ProgramFiles", "LOCALAPPDATA", "ProgramFiles(x86)"):
            base = os.environ.get(env)
            if base:
                candidates += sorted(Path(base).glob("FreeCAD*"), reverse=True)
                candidates += sorted((Path(base) / "Programs").glob("FreeCAD*"), reverse=True)
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/FreeCAD.app/Contents"))
    else:
        candidates += [Path("/usr/lib/freecad"), Path("/usr/lib/freecad-python3")]
    for c in candidates:
        if c.is_dir():
            return str(c)
    return ""


def http_get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def latest_commit() -> str:
    data = json.loads(http_get(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"))
    return data["sha"]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FreeCAD MCP Installer / Updater")
        self.geometry("640x430")
        cfg = {}
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
        self.fc_path = tk.StringVar(value=cfg.get("freecad_path") or detect_freecad())
        self.target = tk.StringVar(value=cfg.get("target", "user"))
        self.build_ui()
        self.refresh_status()

    def build_ui(self):
        pad = {"padx": 10, "pady": 4}
        f = ttk.Frame(self)
        f.pack(fill="x", **pad)
        ttk.Label(f, text="FreeCAD install folder:").pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x")
        e = ttk.Entry(row, textvariable=self.fc_path)
        e.pack(side="left", fill="x", expand=True)
        e.bind("<KeyRelease>", lambda _e: self.refresh_status())
        ttk.Button(row, text="Browse...", command=self.browse).pack(side="left", padx=(6, 0))

        t = ttk.LabelFrame(self, text="Install location")
        t.pack(fill="x", **pad)
        ttk.Radiobutton(t, text="User Mod folder (recommended)", value="user",
                        variable=self.target, command=self.refresh_status).pack(anchor="w")
        ttk.Radiobutton(t, text="Inside FreeCAD install folder (<install>/Mod)", value="install",
                        variable=self.target, command=self.refresh_status).pack(anchor="w")

        self.status = ttk.Label(self, justify="left", wraplength=600)
        self.status.pack(fill="x", **pad)

        b = ttk.Frame(self)
        b.pack(fill="x", **pad)
        self.btn = ttk.Button(b, text="Install / Update", command=self.start)
        self.btn.pack(side="left")
        ttk.Button(b, text="Uninstall", command=self.uninstall).pack(side="left", padx=6)

        self.log = tk.Text(self, height=12, state="disabled")
        self.log.pack(fill="both", expand=True, **pad)

    def browse(self):
        d = filedialog.askdirectory(title="Select FreeCAD install folder",
                                    initialdir=self.fc_path.get() or None)
        if d:
            self.fc_path.set(d)
            self.refresh_status()

    def mod_dir(self) -> Path:
        if self.target.get() == "user":
            return user_mod_dir()
        return Path(self.fc_path.get()) / "Mod"

    def refresh_status(self):
        addon = self.mod_dir() / ADDON_NAME
        marker = addon / VERSION_FILE
        if marker.exists():
            st = f"Installed (commit {marker.read_text().strip()[:7]})"
        elif addon.exists():
            st = "Installed (unknown version)"
        else:
            st = "Not installed"
        self.status.config(text=f"Target: {addon}\nStatus: {st}")

    def say(self, msg):
        def w():
            self.log.config(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.log.config(state="disabled")
        self.after(0, w)

    def validate(self) -> bool:
        p = self.fc_path.get().strip()
        if self.target.get() == "install" and not Path(p).is_dir():
            messagebox.showerror("Error", "Select a valid FreeCAD install folder.")
            return False
        if self.target.get() == "user" and p and not Path(p).is_dir():
            messagebox.showerror("Error", "FreeCAD folder does not exist.")
            return False
        return True

    def start(self):
        if not self.validate():
            return
        CONFIG_FILE.write_text(json.dumps(
            {"freecad_path": self.fc_path.get(), "target": self.target.get()}))
        self.btn.config(state="disabled")
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        try:
            dest = self.mod_dir() / ADDON_NAME
            marker = dest / VERSION_FILE
            self.say("Checking latest version on GitHub...")
            sha = latest_commit()
            if marker.exists() and marker.read_text().strip() == sha:
                self.say(f"Already up to date ({sha[:7]}).")
                return
            self.say(f"Downloading {REPO}@{sha[:7]}...")
            z = zipfile.ZipFile(io.BytesIO(
                http_get(f"https://github.com/{REPO}/archive/{sha}.zip")))
            names = z.namelist()
            root = names[0].split("/")[0]
            prefix = f"{root}/{ADDON_SUBPATH}/"
            members = [n for n in names if n.startswith(prefix) and not n.endswith("/")]
            if not members:
                raise RuntimeError("Addon folder not found in repository archive.")
            if dest.exists():
                self.say("Removing old version...")
                shutil.rmtree(dest)
            for n in members:
                out = dest / n[len(prefix):]
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(z.read(n))
            marker.write_text(sha)
            self.say(f"Installed to {dest}")
            self.say("Done. Restart FreeCAD and select the 'MCP Addon' workbench, then start the RPC server.\n"
                     "MCP client config: uvx freecad-mcp")
        except PermissionError:
            self.say("Permission denied. Try the user Mod folder, or run as administrator.")
        except Exception as ex:
            self.say(f"Error: {ex}")
        finally:
            self.after(0, lambda: (self.btn.config(state="normal"), self.refresh_status()))

    def uninstall(self):
        dest = self.mod_dir() / ADDON_NAME
        if not dest.exists():
            self.say("Nothing to uninstall.")
            return
        if messagebox.askyesno("Uninstall", f"Delete {dest}?"):
            try:
                shutil.rmtree(dest)
                self.say("Uninstalled.")
            except Exception as ex:
                self.say(f"Error: {ex}")
            self.refresh_status()


if __name__ == "__main__":
    App().mainloop()
