import os
import sys
import threading
import queue
import subprocess
import tkinter as tk
import webbrowser
from tkinter import ttk, filedialog, messagebox

APP_TITLE = "Compilador EXE (PyInstaller) - GUI"
WIN_ADD_DATA_SEP = ";"  # en Windows PyInstaller usa ; (origen;destino)


def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def quote_if_needed(s: str) -> str:
    # Para mostrar comandos “copiables”. subprocess usará lista, no necesita comillas.
    if not s:
        return s
    if " " in s or "\t" in s:
        return f'"{s}"'
    return s


class CompilerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("980x650")
        self.minsize(900, 600)

        self.log_queue = queue.Queue()
        self.proc = None
        self.stop_requested = False

        # Vars
        self.script_path = tk.StringVar()
        self.icon_path = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.name_var = tk.StringVar()

        self.onefile_var = tk.BooleanVar(value=True)
        self.windowed_var = tk.BooleanVar(value=True)
        self.clean_var = tk.BooleanVar(value=True)
        self.noconfirm_var = tk.BooleanVar(value=True)

        self.dark_var = tk.BooleanVar(value=True)

        # add-data items: list of tuples (src, dest)
        self.add_data = []

        self._build_ui()
        self._apply_theme()
        self._poll_log_queue()

    # ---------------- UI ----------------
    def _build_ui(self):
        top = ttk.Frame(self, padding=12)
        top.pack(fill="both", expand=True)

        # Row: script
        row1 = ttk.LabelFrame(top, text="Proyecto", padding=10)
        row1.pack(fill="x", pady=(0, 10))

        ttk.Label(row1, text="Archivo principal (.py):").grid(row=0, column=0, sticky="w")
        e_script = ttk.Entry(row1, textvariable=self.script_path)
        e_script.grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(row1, text="Buscar…", command=self.pick_script).grid(row=0, column=2)

        ttk.Label(row1, text="Nombre EXE (opcional):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(row1, textvariable=self.name_var).grid(row=1, column=1, sticky="ew", padx=8, pady=(8, 0))
        ttk.Label(row1, text="(si lo dejás vacío, usa el nombre del .py)").grid(row=1, column=2, sticky="w", pady=(8, 0))

        ttk.Label(row1, text="Carpeta salida (opcional):").grid(row=2, column=0, sticky="w", pady=(8, 0))
        e_out = ttk.Entry(row1, textvariable=self.output_dir)
        e_out.grid(row=2, column=1, sticky="ew", padx=8, pady=(8, 0))
        ttk.Button(row1, text="Elegir…", command=self.pick_output_dir).grid(row=2, column=2, pady=(8, 0))

        row1.columnconfigure(1, weight=1)

        # Row: icon + options
        row2 = ttk.LabelFrame(top, text="Opciones", padding=10)
        row2.pack(fill="x", pady=(0, 10))

        ttk.Label(row2, text="Ícono (.ico):").grid(row=0, column=0, sticky="w")
        ttk.Entry(row2, textvariable=self.icon_path).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(row2, text="Buscar…", command=self.pick_icon).grid(row=0, column=2)

        opts = ttk.Frame(row2)
        opts.grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 0))

        ttk.Checkbutton(opts, text="Onefile (1 solo .exe)", variable=self.onefile_var).grid(row=0, column=0, sticky="w", padx=(0, 18))
        ttk.Checkbutton(opts, text="Windowed (sin consola)", variable=self.windowed_var).grid(row=0, column=1, sticky="w", padx=(0, 18))
        ttk.Checkbutton(opts, text="--clean", variable=self.clean_var).grid(row=0, column=2, sticky="w", padx=(0, 18))
        ttk.Checkbutton(opts, text="--noconfirm", variable=self.noconfirm_var).grid(row=0, column=3, sticky="w")

        row2.columnconfigure(1, weight=1)

        # Row: add-data
        row3 = ttk.LabelFrame(top, text="Archivos / carpetas extra (PyInstaller --add-data)", padding=10)
        row3.pack(fill="both", expand=False, pady=(0, 10))

        sub = ttk.Frame(row3)
        sub.pack(fill="x")

        ttk.Button(sub, text="Agregar archivo…", command=self.add_file_data).pack(side="left")
        ttk.Button(sub, text="Agregar carpeta…", command=self.add_folder_data).pack(side="left", padx=8)
        ttk.Button(sub, text="Quitar seleccionado", command=self.remove_selected_data).pack(side="left")

        ttk.Label(sub, text="(Destino = nombre de carpeta dentro del EXE; ej: assets)").pack(side="left", padx=12)

        self.data_list = tk.Listbox(row3, height=5)
        self.data_list.pack(fill="x", pady=(8, 0))

        # Row: actions
        self.row4 = ttk.Frame(top)
        self.row4.pack(fill="x", pady=(0, 10))

        ttk.Button(self.row4, text="✅ Verificar / Instalar PyInstaller", command=self.ensure_pyinstaller).pack(side="left")
        ttk.Button(self.row4, text="🚀 Compilar", command=self.compile_now).pack(side="left", padx=8)
        ttk.Button(self.row4, text="⛔ Detener", command=self.stop_compile, state="disabled").pack(side="left")
        ttk.Button(self.row4, text="🧹 Limpiar log", command=self.clear_log).pack(side="left", padx=8)

        ttk.Checkbutton(self.row4, text="Tema oscuro", variable=self.dark_var, command=self._apply_theme).pack(side="right")

        # Row: log
        row5 = ttk.LabelFrame(top, text="Consola / Log", padding=10)
        row5.pack(fill="both", expand=True)

        self.log = tk.Text(row5, wrap="word", height=18)
        self.log.pack(fill="both", expand=True)

        # Row: command preview
        row6 = ttk.LabelFrame(top, text="Comando (vista previa)", padding=10)
        row6.pack(fill="x")

        self.cmd_preview = ttk.Entry(row6)
        self.cmd_preview.pack(fill="x")

        # >>> GITHUB <<<
        try:
            self.github_img = tk.PhotoImage(file=resource_path("github.png"))
            github = tk.Label(self.row4, image=self.github_img, cursor="hand2")
            github.pack(side="right", padx=8)
            github.bind(
                "<Button-1>",
                lambda e: webbrowser.open("https://github.com/sanb-mov")
            )
        except Exception as e:
            print("GitHub logo no cargado:", e)

    # ---------------- Theme ----------------
    def _apply_theme(self):
        dark = self.dark_var.get()

        # ttk theme base
        style = ttk.Style()
        # En Windows, "vista" suele verse mejor
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        # Colores
        if dark:
            bg = "#000000"
            fg = "#FFFFFF"
            entry_bg = "#000000"
            text_bg = "#000000"
        else:
            bg = "#f3f3f3"
            fg = "#111111"
            entry_bg = "#ffffff"
            text_bg = "#ffffff"

        self.configure(bg=bg)

        # Ajustes generales para ttk (no todos los widgets respetan esto, pero ayuda)
        style.configure(".", background=bg, foreground=fg)
        style.configure("TFrame", background=bg)
        style.configure("TLabelframe", background=bg, foreground=fg)
        style.configure("TLabelframe.Label", background=bg, foreground=fg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TButton", padding=6)
        style.configure("TCheckbutton", background=bg, foreground=fg)

        # Tk widgets
        self.data_list.configure(bg=entry_bg, fg=fg, highlightbackground=bg, selectbackground="#2a5bd7" if not dark else "#2d5aa6")
        self.log.configure(bg=text_bg, fg=fg, insertbackground=fg)

        # Preview entry (ttk)
        # ttk.Entry no deja bg fácil según tema, pero igual queda ok.

    # ---------------- File pickers ----------------
    def pick_script(self):
        path = filedialog.askopenfilename(
            title="Elegí tu archivo principal (.py)",
            filetypes=[("Python files", "*.py"), ("All files", "*.*")]
        )
        if path:
            self.script_path.set(path)
            if not self.name_var.get().strip():
                base = os.path.splitext(os.path.basename(path))[0]
                self.name_var.set(base)

    def pick_icon(self):
        path = filedialog.askopenfilename(
            title="Elegí el ícono (.ico)",
            filetypes=[("Icon files", "*.ico"), ("All files", "*.*")]
        )
        if path:
            self.icon_path.set(path)

    def pick_output_dir(self):
        path = filedialog.askdirectory(title="Elegí carpeta de salida")
        if path:
            self.output_dir.set(path)

    # ---------------- add-data management ----------------
    def add_file_data(self):
        src = filedialog.askopenfilename(title="Agregar archivo para incluir")
        if not src:
            return
        dest = self._ask_dest(default=os.path.basename(os.path.dirname(src)) or "data")
        if not dest:
            return
        self.add_data.append((src, dest))
        self._refresh_data_list()

    def add_folder_data(self):
        src = filedialog.askdirectory(title="Agregar carpeta para incluir")
        if not src:
            return
        dest = self._ask_dest(default=os.path.basename(src) or "assets")
        if not dest:
            return
        self.add_data.append((src, dest))
        self._refresh_data_list()

    def remove_selected_data(self):
        sel = list(self.data_list.curselection())
        if not sel:
            return
        # borrar de atrás para adelante
        for idx in reversed(sel):
            del self.add_data[idx]
        self._refresh_data_list()

    def _refresh_data_list(self):
        self.data_list.delete(0, tk.END)
        for src, dest in self.add_data:
            self.data_list.insert(tk.END, f"{src}  ->  {dest}")

    def _ask_dest(self, default="assets"):
        # mini diálogo simple
        w = tk.Toplevel(self)
        w.title("Destino dentro del paquete")
        w.geometry("420x140")
        w.transient(self)
        w.grab_set()

        ttk.Label(w, text="Destino (carpeta/nombre dentro del EXE):").pack(pady=(14, 6), padx=12, anchor="w")
        var = tk.StringVar(value=default)
        e = ttk.Entry(w, textvariable=var)
        e.pack(fill="x", padx=12)
        e.focus_set()

        out = {"val": None}

        def ok():
            out["val"] = var.get().strip()
            w.destroy()

        def cancel():
            w.destroy()

        btns = ttk.Frame(w)
        btns.pack(fill="x", pady=12, padx=12)
        ttk.Button(btns, text="OK", command=ok).pack(side="left")
        ttk.Button(btns, text="Cancelar", command=cancel).pack(side="left", padx=8)

        self.wait_window(w)
        return out["val"]

    # ---------------- PyInstaller ----------------
    def _pyinstaller_available(self) -> bool:
        try:
            subprocess.check_output([sys.executable, "-m", "PyInstaller", "--version"], stderr=subprocess.STDOUT)
            return True
        except Exception:
            return False

    def ensure_pyinstaller(self):
        if self._pyinstaller_available():
            self._log("✅ PyInstaller ya está instalado.\n")
            return

        if not messagebox.askyesno("PyInstaller no encontrado", "No encontré PyInstaller. ¿Querés instalarlo ahora?"):
            self._log("⚠️ PyInstaller no está instalado.\n")
            return

        def installer():
            self._log("📦 Instalando PyInstaller...\n")
            try:
                cmd = [sys.executable, "-m", "pip", "install", "pyinstaller"]
                self._run_and_stream(cmd)
                if self._pyinstaller_available():
                    self._log("✅ PyInstaller instalado correctamente.\n")
                else:
                    self._log("❌ No pude verificar la instalación de PyInstaller.\n")
            except Exception as e:
                self._log(f"❌ Error instalando PyInstaller: {e}\n")

        threading.Thread(target=installer, daemon=True).start()

    # ---------------- Compile ----------------
    def compile_now(self):
        script = self.script_path.get().strip()
        if not script or not os.path.isfile(script):
            messagebox.showerror("Falta archivo", "Elegí un archivo .py válido.")
            return

        if not self._pyinstaller_available():
            messagebox.showerror("PyInstaller faltante", "No está instalado PyInstaller. Tocá 'Verificar / Instalar PyInstaller'.")
            return

        cmd = self._build_cmd()
        self._set_buttons_compiling(True)

        self.stop_requested = False

        def worker():
            self._log("🚀 Compilación iniciada...\n")
            self._log("Comando:\n  " + " ".join(map(quote_if_needed, cmd)) + "\n\n")
            rc = self._run_and_stream(cmd)
            if self.stop_requested:
                self._log("\n⛔ Proceso detenido por el usuario.\n")
            elif rc == 0:
                self._log("\n✅ Listo. Tu EXE debería estar en la carpeta 'dist'.\n")
            else:
                self._log(f"\n❌ Terminó con error (code {rc}). Mirá el log arriba.\n")

            self._set_buttons_compiling(False)

        threading.Thread(target=worker, daemon=True).start()

    def stop_compile(self):
        self.stop_requested = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass

    def _set_buttons_compiling(self, compiling: bool):
        # Busca botones por texto (simple)
        for child in self.winfo_children():
            pass
        # En vez de navegar, usamos estados guardando referencias:
        # (más simple: recorrer todos los botones del row4)
        # Hack: deshabilitar/activar por nombre de widget no lo tenemos, así que:
        # Mejor: iterar toda la jerarquía y tocar TButton.
        def set_all_buttons(widget):
            for w in widget.winfo_children():
                if isinstance(w, ttk.Button):
                    txt = w.cget("text")
                    if "Compilar" in txt or "Detener" in txt:
                        if "Compilar" in txt:
                            w.configure(state="disabled" if compiling else "normal")
                        if "Detener" in txt:
                            w.configure(state="normal" if compiling else "disabled")
                set_all_buttons(w)

        set_all_buttons(self)

    def _build_cmd(self):
        script = self.script_path.get().strip()
        icon = self.icon_path.get().strip()
        outdir = self.output_dir.get().strip()
        name = self.name_var.get().strip()

        cmd = [sys.executable, "-m", "PyInstaller"]

        if self.noconfirm_var.get():
            cmd.append("--noconfirm")
        if self.clean_var.get():
            cmd.append("--clean")
        if self.onefile_var.get():
            cmd.append("--onefile")
        # windowed implica sin consola. En Windows, --noconsole también existe.
        if self.windowed_var.get():
            cmd.append("--windowed")

        if name:
            cmd += ["--name", name]

        if outdir:
            cmd += ["--distpath", outdir]

        if icon:
            if os.path.isfile(icon) and icon.lower().endswith(".ico"):
                cmd += [f"--icon={icon}"]
            else:
                # no frenar, pero avisar en log
                self._log("⚠️ Ícono inválido o no es .ico. Se compilará sin ícono.\n")

        for src, dest in self.add_data:
            # Windows: "src;dest"
            pair = f"{src}{WIN_ADD_DATA_SEP}{dest}"
            cmd += ["--add-data", pair]

        cmd.append(script)

        # Vista previa
        self.cmd_preview.delete(0, tk.END)
        self.cmd_preview.insert(0, " ".join(map(quote_if_needed, cmd)))

        return cmd

    # ---------------- Run + stream output ----------------
    def _run_and_stream(self, cmd_list):
        try:
            self.proc = subprocess.Popen(
                cmd_list,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            while True:
                if self.stop_requested and self.proc.poll() is None:
                    try:
                        self.proc.terminate()
                    except Exception:
                        pass

                line = self.proc.stdout.readline() if self.proc.stdout else ""
                if line:
                    self._log(line)
                if not line and self.proc.poll() is not None:
                    break

            return self.proc.returncode if self.proc else 1

        except FileNotFoundError:
            self._log("❌ No encontré el ejecutable de Python/PyInstaller.\n")
            return 1
        except Exception as e:
            self._log(f"❌ Error ejecutando comando: {e}\n")
            return 1
        finally:
            self.proc = None

    # ---------------- Logging ----------------
    def _log(self, text: str):
        self.log_queue.put(text)

    def _poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log.insert("end", msg)
                self.log.see("end")
        except queue.Empty:
            pass
        self.after(60, self._poll_log_queue)

    def clear_log(self):
        self.log.delete("1.0", "end")


if __name__ == "__main__":
    app = CompilerApp()
    app.mainloop()
