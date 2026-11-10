"""
LanDrop para Windows - interfaz gráfica.

Enviar archivos entre tu PC, tu celular (iPhone o Android) y otras PCs con LanDrop
en la misma red WiFi, sin cables ni internet.
"""

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import core

try:
    import qrcode
except ImportError:  # sin la librería se muestra solo el enlace
    qrcode = None

IS_WINDOWS = sys.platform == "win32"
FONT = "Segoe UI" if IS_WINDOWS else "Helvetica"
ACCENT = "#2f6bff"
BG = "#f3f5f9"
CARD = "#ffffff"
MUTED = "#6b7385"


def resource(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def open_path(p):
    p = str(p)
    if IS_WINDOWS:
        os.startfile(p)  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


def reveal_in_explorer(p):
    if IS_WINDOWS:
        subprocess.Popen(["explorer", "/select,", str(p)])
    else:
        open_path(Path(p).parent)


# ------------------------------------------------------------------ puente núcleo -> interfaz

class GuiEvents(core.Events):
    """Los eventos llegan desde hilos de red; se pasan al hilo de la interfaz por una cola."""

    def __init__(self, ui: "App"):
        self.ui = ui

    def received(self, path, sender):
        self.ui.post(self.ui.on_received, path, sender)

    def text(self, text, sender):
        self.ui.post(self.ui.on_text, text, sender)

    def log(self, msg):
        self.ui.post(self.ui.log, msg)

    def peers_changed(self):
        self.ui.post(self.ui.refresh_peers)

    def local_files(self, paths):
        self.ui.post(self.ui.on_local_files, paths)

    def show_window(self):
        self.ui.post(self.ui.bring_to_front)

    def ask_accept(self, sender, files, total):
        done = threading.Event()
        result = {}
        self.ui.post(self.ui.ask_dialog, sender, files, total, done, result)
        done.wait(core.ASK_TIMEOUT + 5)
        return result.get("ok", False)


# ------------------------------------------------------------------ ventana principal

class App:
    def __init__(self, root: tk.Tk, start_files=None, minimized=False):
        self.root = root
        self.queue = queue.Queue()
        self.core = core.LanDrop(GuiEvents(self))
        self.sending = False
        self.cancel_event = None
        self.last_progress = 0
        self.shown_url = ""
        self.chooser = None
        self.peers = []
        self._toast_win = None
        self.start_files = start_files or []

        root.title("LanDrop")
        root.geometry("900x640")
        root.minsize(780, 560)
        root.configure(bg=BG)
        try:
            root.iconbitmap(resource("landrop.ico"))
        except tk.TclError:
            pass
        self._styles()
        self._build()
        if minimized:
            root.iconify()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(80, self._pump)

    # ---------------- infraestructura
    def post(self, fn, *args):
        self.queue.put((fn, args))

    def _pump(self):
        try:
            while True:
                fn, args = self.queue.get_nowait()
                try:
                    fn(*args)
                except Exception as e:  # que un error no tumbe la app
                    self.log(f"Error interno: {e}")
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def start(self) -> bool:
        try:
            self.core.start()
        except OSError as e:
            messagebox.showerror("LanDrop",
                                 f"No se pudo abrir el puerto {self.core.http_port}.\n"
                                 f"¿LanDrop ya está abierto?\n\n{e}")
            return False
        self.log(f"Listo. Visible en la red como \"{self.core.name}\".")
        self.log(f"Los archivos recibidos se guardan en: {self.core.download_dir}")
        self.update_qr()
        self.root.after(5000, self._watch_ip)
        if self.start_files:
            self.root.after(400, lambda: self.on_local_files(self.start_files))
        return True

    def quit(self):
        try:
            self.core.stop()
        finally:
            self.root.destroy()

    # ---------------- estilos
    def _styles(self):
        s = ttk.Style()
        try:
            s.theme_use("vista" if IS_WINDOWS else "clam")
        except tk.TclError:
            pass
        s.configure("Card.TFrame", background=CARD)
        s.configure("Bg.TFrame", background=BG)
        s.configure("Title.TLabel", background=BG, font=(FONT, 18, "bold"))
        s.configure("Sub.TLabel", background=BG, foreground=MUTED, font=(FONT, 10))
        s.configure("H.TLabel", background=CARD, font=(FONT, 12, "bold"))
        s.configure("Card.TLabel", background=CARD, font=(FONT, 10))
        s.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=(FONT, 9))
        s.configure("TButton", font=(FONT, 10), padding=(10, 5))
        s.configure("Accent.TButton", font=(FONT, 10, "bold"))
        s.configure("Card.TCheckbutton", background=CARD, font=(FONT, 10))

    def _card(self, parent, title):
        outer = ttk.Frame(parent, style="Card.TFrame", padding=14)
        ttk.Label(outer, text=title, style="H.TLabel").pack(anchor="w", pady=(0, 8))
        return outer

    def _listbox(self, parent, height):
        lb = tk.Listbox(parent, height=height, activestyle="none", relief="flat", bd=0,
                        highlightthickness=1, highlightbackground="#e3e7ef", highlightcolor=ACCENT,
                        selectbackground=ACCENT, selectforeground="white", font=(FONT, 10))
        return lb

    # ---------------- construcción de la ventana
    def _build(self):
        r = self.root
        top = ttk.Frame(r, style="Bg.TFrame", padding=(18, 14, 18, 6))
        top.pack(fill="x")
        ttk.Label(top, text="LanDrop", style="Title.TLabel").pack(side="left")
        self.name_lbl = ttk.Label(top, style="Sub.TLabel")
        self.name_lbl.pack(side="left", padx=14, pady=(6, 0))
        ttk.Button(top, text="Cambiar nombre", command=self.rename).pack(side="right")
        self._update_name_label()

        body = ttk.Frame(r, style="Bg.TFrame", padding=(18, 6, 18, 6))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        # --- celular (QR)
        phone = self._card(body, "Conectar celular")
        phone.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 12))
        self.qr = tk.Canvas(phone, width=230, height=230, bg="white", highlightthickness=0)
        self.qr.pack(pady=(2, 8))
        ttk.Label(phone, text="Escanea con la cámara del\niPhone o Android (misma WiFi).",
                  style="Card.TLabel", justify="center").pack()
        self.url_var = tk.StringVar()
        url = ttk.Entry(phone, textvariable=self.url_var, state="readonly", width=34, justify="center")
        url.pack(pady=(10, 4))
        row = ttk.Frame(phone, style="Card.TFrame")
        row.pack(pady=(4, 0))
        ttk.Button(row, text="Copiar enlace", command=self.copy_url).pack(side="left", padx=3)
        ttk.Button(row, text="Nueva clave", command=self.new_key).pack(side="left", padx=3)
        ttk.Label(phone, text="\"Nueva clave\" desconecta a los celulares\nque ya escanearon el código.",
                  style="Muted.TLabel", justify="center").pack(pady=(8, 0))

        # --- PCs cercanas
        peers = self._card(body, "PCs cercanas con LanDrop")
        peers.grid(row=0, column=1, sticky="nsew", pady=(0, 10))
        self.peer_lb = self._listbox(peers, 4)
        self.peer_lb.pack(fill="both", expand=True)
        self.peer_lb.bind("<Double-Button-1>", lambda e: self.send_files_to_peer())
        self.peer_hint = ttk.Label(peers, text="Buscando otras PCs en tu red…", style="Muted.TLabel")
        self.peer_hint.pack(anchor="w", pady=(6, 6))
        row = ttk.Frame(peers, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Button(row, text="Enviar archivos…", style="Accent.TButton",
                   command=self.send_files_to_peer).pack(side="left")
        ttk.Button(row, text="Enviar carpeta…", command=self.send_folder_to_peer).pack(side="left", padx=6)

        # --- compartir con el celular
        share = self._card(body, "Enviar al celular")
        share.grid(row=1, column=1, sticky="nsew")
        self.share_lb = self._listbox(share, 4)
        self.share_lb.pack(fill="both", expand=True)
        ttk.Label(share, text="Lo que pongas aquí aparece en la página del celular para descargar.",
                  style="Muted.TLabel").pack(anchor="w", pady=(6, 6))
        row = ttk.Frame(share, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Button(row, text="Agregar archivos…", style="Accent.TButton",
                   command=self.add_shared).pack(side="left")
        ttk.Button(row, text="Quitar", command=self.remove_shared).pack(side="left", padx=6)
        ttk.Button(row, text="Enviar portapapeles", command=self.share_clipboard).pack(side="left")
        self.shared_ids = []

        # --- progreso
        prog = ttk.Frame(r, style="Bg.TFrame", padding=(18, 4, 18, 0))
        prog.pack(fill="x")
        self.status = ttk.Label(prog, text="", style="Sub.TLabel")
        self.status.pack(anchor="w")
        row = ttk.Frame(prog, style="Bg.TFrame")
        row.pack(fill="x")
        self.pbar = ttk.Progressbar(row, mode="determinate", maximum=1000)
        self.pbar.pack(side="left", fill="x", expand=True)
        self.cancel_btn = ttk.Button(row, text="Cancelar", command=self.cancel_send, state="disabled")
        self.cancel_btn.pack(side="left", padx=(8, 0))

        # --- actividad
        bottom = ttk.Frame(r, style="Bg.TFrame", padding=(18, 8, 18, 14))
        bottom.pack(fill="both")
        self.logbox = tk.Text(bottom, height=7, relief="flat", bd=0, wrap="word", font=(FONT, 9),
                              bg=CARD, padx=10, pady=8, highlightthickness=1,
                              highlightbackground="#e3e7ef", state="disabled")
        self.logbox.pack(fill="both", expand=True)
        row = ttk.Frame(bottom, style="Bg.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Abrir carpeta de recibidos", command=self.open_downloads).pack(side="left")
        ttk.Button(row, text="Cambiar carpeta…", command=self.change_downloads).pack(side="left", padx=6)
        if IS_WINDOWS:
            ttk.Button(row, text="Agregar a \"Enviar a\"", command=self.install_sendto).pack(side="left")
            self.autostart = tk.BooleanVar(value=self._startup_link().exists())
            ttk.Checkbutton(row, text="Iniciar con Windows", variable=self.autostart,
                            command=self.toggle_autostart).pack(side="right")

    # ---------------- utilidades de la interfaz
    def log(self, msg):
        stamp = time.strftime("%H:%M")
        self.logbox.configure(state="normal")
        self.logbox.insert("end", f"{stamp}  {msg}\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def bring_to_front(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(300, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

    def toast(self, title, msg, action=None, action_text="Abrir"):
        """Aviso pequeño en la esquina inferior derecha que se cierra solo."""
        if self._toast_win is not None and self._toast_win.winfo_exists():
            self._toast_win.destroy()  # solo un aviso a la vez
        t = self._toast_win = tk.Toplevel(self.root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.configure(bg="#151922")
        f = tk.Frame(t, bg="#151922", padx=16, pady=12)
        f.pack()
        tk.Label(f, text=title, bg="#151922", fg="white", font=(FONT, 10, "bold"),
                 anchor="w", justify="left").pack(anchor="w")
        tk.Label(f, text=msg, bg="#151922", fg="#c9d0dc", font=(FONT, 9), wraplength=300,
                 anchor="w", justify="left").pack(anchor="w", pady=(2, 6))
        row = tk.Frame(f, bg="#151922")
        row.pack(anchor="e")
        if action:
            tk.Button(row, text=action_text, relief="flat", bg=ACCENT, fg="white", padx=10,
                      command=lambda: (action(), t.destroy())).pack(side="left", padx=4)
        tk.Button(row, text="Cerrar", relief="flat", bg="#2a2f3a", fg="white", padx=10,
                  command=t.destroy).pack(side="left")
        t.update_idletasks()
        w, h = t.winfo_width(), t.winfo_height()
        sw, sh = t.winfo_screenwidth(), t.winfo_screenheight()
        t.geometry(f"+{sw - w - 24}+{sh - h - 72}")
        t.after(7000, lambda: t.winfo_exists() and t.destroy())

    def _update_name_label(self):
        self.name_lbl.configure(text=f"Visible como: {self.core.name}")

    # ---------------- QR
    def update_qr(self):
        url = self.core.phone_url()
        self.shown_url = url
        self.url_var.set(url)
        c = self.qr
        c.delete("all")
        size = 230
        if qrcode is None:
            c.create_text(size / 2, size / 2, text="Abre en el celular\nel enlace de abajo",
                          justify="center", font=(FONT, 11))
            return
        q = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
        q.add_data(url)
        q.make(fit=True)
        m = q.get_matrix()
        n = len(m)
        cell = size // n
        off = (size - cell * n) // 2
        for y, rowv in enumerate(m):
            for x, v in enumerate(rowv):
                if v:
                    c.create_rectangle(off + x * cell, off + y * cell,
                                       off + (x + 1) * cell, off + (y + 1) * cell,
                                       fill="black", outline="")

    def _watch_ip(self):
        """Si cambias de red WiFi, actualiza el QR."""
        if self.core.phone_url() != self.shown_url:
            self.update_qr()
            self.log("La red cambió; el código QR se actualizó.")
        self.root.after(5000, self._watch_ip)

    def copy_url(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.core.phone_url())
        self.log("Enlace copiado.")

    def new_key(self):
        if messagebox.askyesno("Nueva clave", "Los celulares conectados tendrán que volver a escanear "
                                              "el código. ¿Continuar?"):
            self.core.regenerate_key()
            self.update_qr()
            self.log("Se generó una nueva clave.")

    def rename(self):
        n = simpledialog.askstring("Nombre del equipo", "¿Cómo quieres que se vea esta PC?",
                                   initialvalue=self.core.name, parent=self.root)
        if n:
            self.core.set_name(n)
            self._update_name_label()

    # ---------------- PCs cercanas
    def refresh_peers(self):
        self.peers = self.core.peer_list()
        self.peer_lb.delete(0, "end")
        for p in self.peers:
            self.peer_lb.insert("end", f"  {p['name']}    ({p['ip']})")
        self.peer_hint.configure(text="Doble clic en una PC para enviarle archivos." if self.peers
                                 else "Buscando otras PCs en tu red…")
        if self.chooser and self.chooser.win.winfo_exists():
            self.chooser.refresh()

    def _selected_peer(self):
        peers = getattr(self, "peers", [])
        sel = self.peer_lb.curselection()
        if sel and sel[0] < len(peers):
            return peers[sel[0]]
        if len(peers) == 1:
            return peers[0]
        messagebox.showinfo("LanDrop", "Selecciona primero una PC de la lista." if peers else
                            "No hay otras PCs con LanDrop abierto en esta red.")
        return None

    def send_files_to_peer(self):
        peer = self._selected_peer()
        if not peer:
            return
        files = filedialog.askopenfilenames(title=f"Enviar a {peer['name']}")
        if files:
            self.start_send(peer, list(files))

    def send_folder_to_peer(self):
        peer = self._selected_peer()
        if not peer:
            return
        d = filedialog.askdirectory(title=f"Enviar carpeta a {peer['name']}")
        if d:
            self.start_send(peer, [d])

    def start_send(self, peer, paths):
        if self.sending:
            messagebox.showinfo("LanDrop", "Espera a que termine el envío actual.")
            return
        self.sending = True
        self.cancel_event = threading.Event()
        self.cancel_btn.configure(state="normal")
        self.pbar.configure(value=0)
        self.status.configure(text=f"Esperando a que {peer['name']} acepte…")
        self.log(f"Solicitando envío a {peer['name']}…")

        def progress(sent, total, name):
            now = time.time()
            if now - self.last_progress > 0.1 or sent == total:
                self.last_progress = now
                self.post(self._show_progress, sent, total, name)

        def work():
            t0 = time.time()
            ok, msg = self.core.send_to_peer(peer, paths, progress, self.cancel_event)
            self.post(self._send_finished, ok, msg, time.time() - t0)

        threading.Thread(target=work, daemon=True).start()

    def _show_progress(self, sent, total, name):
        self.pbar.configure(value=1000 * sent / max(total, 1))
        self.status.configure(text=f"Enviando {name} — {core.human_size(sent)} de {core.human_size(total)}")

    def _send_finished(self, ok, msg, secs):
        self.sending = False
        self.cancel_btn.configure(state="disabled")
        self.status.configure(text=msg)
        if ok:
            self.pbar.configure(value=1000)
            self.log(f"{msg} en {secs:.0f} s")
        else:
            self.pbar.configure(value=0)
            self.log(msg)
            if msg != "Envío cancelado":
                messagebox.showwarning("LanDrop", msg)

    def cancel_send(self):
        if self.cancel_event:
            self.cancel_event.set()

    # ---------------- solicitud entrante de otra PC
    def ask_dialog(self, sender, files, total, done, result):
        self.bring_to_front()
        w = tk.Toplevel(self.root)
        w.title("Archivos entrantes")
        w.configure(bg=CARD)
        w.resizable(False, False)
        w.attributes("-topmost", True)
        w.transient(self.root)
        f = ttk.Frame(w, style="Card.TFrame", padding=20)
        f.pack(fill="both")
        ttk.Label(f, text=f"{sender}", style="H.TLabel").pack(anchor="w")
        ttk.Label(f, text=f"quiere enviarte {len(files)} archivo(s) · {core.human_size(total)}",
                  style="Card.TLabel").pack(anchor="w", pady=(2, 10))
        names = [x.get("name", "?") for x in files[:6]]
        if len(files) > 6:
            names.append(f"… y {len(files) - 6} más")
        ttk.Label(f, text="\n".join(names), style="Muted.TLabel", justify="left").pack(anchor="w")
        timer = ttk.Label(f, style="Muted.TLabel")
        timer.pack(anchor="w", pady=(10, 0))
        row = ttk.Frame(f, style="Card.TFrame")
        row.pack(anchor="e", pady=(12, 0))

        def answer(ok):
            if not done.is_set():
                result["ok"] = ok
                done.set()
            if w.winfo_exists():
                w.destroy()
            if ok:
                self.log(f"Aceptaste archivos de {sender}.")
                self.status.configure(text=f"Recibiendo de {sender}…")

        ttk.Button(row, text="Rechazar", command=lambda: answer(False)).pack(side="left", padx=6)
        ttk.Button(row, text="Aceptar", style="Accent.TButton", command=lambda: answer(True)).pack(side="left")
        w.protocol("WM_DELETE_WINDOW", lambda: answer(False))
        deadline = time.time() + core.ASK_TIMEOUT - 3

        def tick():
            if not w.winfo_exists():
                return
            left = int(deadline - time.time())
            if left <= 0:
                answer(False)
                return
            timer.configure(text=f"Se rechazará automáticamente en {left} s")
            w.after(1000, tick)
        tick()
        self.root.bell()

    # ---------------- recibido
    def on_received(self, path: Path, sender):
        try:
            size = core.human_size(path.stat().st_size)
        except OSError:
            size = "?"
        self.log(f"Recibido de {sender}: {path.name} ({size})")
        self.status.configure(text=f"Recibido: {path.name}")
        self.toast("Archivo recibido", f"{path.name}\nde {sender}", lambda: reveal_in_explorer(path),
                   "Mostrar")

    def on_text(self, text, sender):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        short = text if len(text) <= 120 else text[:117] + "…"
        self.log(f"Texto de {sender} (copiado al portapapeles): {short}")
        is_link = text.strip().startswith(("http://", "https://")) and " " not in text.strip()
        self.toast("Texto copiado al portapapeles", short,
                   (lambda: webbrowser.open(text.strip())) if is_link else None, "Abrir enlace")

    # ---------------- compartir con el celular
    def _refresh_shared(self):
        self.share_lb.delete(0, "end")
        self.shared_ids = []
        for f in self.core.shared.values():
            self.share_lb.insert("end", f"  {f.name}    ({core.human_size(f.size)})")
            self.shared_ids.append(f.id)

    def share_paths_with_phone(self, paths):
        files = [str(full) for full, _rel, _sz in core.expand_paths(paths)]
        added = self.core.share_files(files)
        self._refresh_shared()
        if added:
            self.log(f"{len(added)} archivo(s) listos para descargar en el celular.")

    def add_shared(self):
        files = filedialog.askopenfilenames(title="Archivos para el celular")
        if files:
            self.share_paths_with_phone(files)

    def remove_shared(self):
        sel = self.share_lb.curselection()
        if not sel:
            if self.shared_ids and messagebox.askyesno("LanDrop", "¿Quitar todos los archivos compartidos?"):
                self.core.clear_shared()
        else:
            for i in sel:
                self.core.unshare(self.shared_ids[i])
        self._refresh_shared()

    def share_clipboard(self):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""
        if not text.strip():
            messagebox.showinfo("LanDrop", "El portapapeles no tiene texto.")
            return
        self.core.share_text(text)
        self.log("Texto del portapapeles enviado a la página del celular.")

    # ---------------- archivos que llegan por "Enviar a" o arrastrados al ícono
    def on_local_files(self, paths):
        self.bring_to_front()
        if self.chooser and self.chooser.win.winfo_exists():
            self.chooser.win.destroy()
        self.chooser = TargetChooser(self, paths)

    # ---------------- carpeta de recibidos
    def open_downloads(self):
        self.core.download_dir.mkdir(parents=True, exist_ok=True)
        open_path(self.core.download_dir)

    def change_downloads(self):
        d = filedialog.askdirectory(title="Carpeta para archivos recibidos",
                                    initialdir=str(self.core.download_dir))
        if d:
            self.core.set_download_dir(Path(d))
            self.log(f"Ahora los archivos se guardan en: {d}")

    # ---------------- integración con Windows
    def _launch_target(self):
        """(programa, argumentos) para crear accesos directos."""
        if getattr(sys, "frozen", False):
            return sys.executable, ""
        pyw = Path(sys.executable).with_name("pythonw.exe")
        exe = str(pyw if pyw.exists() else sys.executable)
        return exe, f'"{os.path.abspath(__file__)}"'

    def _make_shortcut(self, link: Path, extra_args=""):
        target, args = self._launch_target()
        args = (args + " " + extra_args).strip()
        q = lambda s: str(s).replace("'", "''")
        ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(link)}');"
              f"$s.TargetPath='{q(target)}';$s.Arguments='{q(args)}';"
              f"$s.WorkingDirectory='{q(Path(target).parent)}';"
              f"$s.IconLocation='{q(target)},0';$s.Save()")
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def install_sendto(self):
        link = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "SendTo" / "LanDrop.lnk"
        try:
            self._make_shortcut(link)
            self.log("Listo: clic derecho en cualquier archivo > Enviar a > LanDrop.")
            messagebox.showinfo("LanDrop", "Ahora puedes hacer clic derecho en archivos o carpetas y "
                                           "elegir \"Enviar a > LanDrop\".\n\n(En Windows 11: "
                                           "\"Mostrar más opciones\" > \"Enviar a\".)")
        except (OSError, subprocess.CalledProcessError) as e:
            messagebox.showerror("LanDrop", f"No se pudo crear el acceso directo:\n{e}")

    def _startup_link(self) -> Path:
        return (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" /
                "Programs" / "Startup" / "LanDrop.lnk")

    def toggle_autostart(self):
        link = self._startup_link()
        try:
            if self.autostart.get():
                self._make_shortcut(link, "--min")
                self.log("LanDrop se abrirá al iniciar Windows (minimizado).")
            elif link.exists():
                link.unlink()
                self.log("LanDrop ya no se abrirá al iniciar Windows.")
        except (OSError, subprocess.CalledProcessError) as e:
            messagebox.showerror("LanDrop", str(e))


# ------------------------------------------------------------------ "¿A dónde lo envío?"

class TargetChooser:
    def __init__(self, app: App, paths):
        self.app = app
        self.paths = paths
        items = core.expand_paths(paths)
        total = sum(sz for *_, sz in items)
        w = self.win = tk.Toplevel(app.root)
        w.title("Enviar con LanDrop")
        w.configure(bg=CARD)
        w.geometry("420x360")
        w.transient(app.root)
        w.attributes("-topmost", True)
        f = ttk.Frame(w, style="Card.TFrame", padding=18)
        f.pack(fill="both", expand=True)
        first = Path(paths[0]).name
        what = first if len(paths) == 1 else f"{first} y {len(paths) - 1} más"
        ttk.Label(f, text="¿A dónde lo envías?", style="H.TLabel").pack(anchor="w")
        ttk.Label(f, text=f"{what} · {len(items)} archivo(s) · {core.human_size(total)}",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 10))
        self.lb = app._listbox(f, 7)
        self.lb.pack(fill="both", expand=True)
        self.lb.bind("<Double-Button-1>", lambda e: self.go())
        row = ttk.Frame(f, style="Card.TFrame")
        row.pack(anchor="e", pady=(12, 0))
        ttk.Button(row, text="Cancelar", command=w.destroy).pack(side="left", padx=6)
        ttk.Button(row, text="Enviar", style="Accent.TButton", command=self.go).pack(side="left")
        self.refresh()
        self.lb.selection_set(0)

    def refresh(self):
        sel = self.lb.curselection()
        self.targets = [None] + self.app.core.peer_list()  # None = celular
        self.lb.delete(0, "end")
        self.lb.insert("end", "  Celular (aparecerá en la página del QR)")
        for p in self.targets[1:]:
            self.lb.insert("end", f"  PC: {p['name']}    ({p['ip']})")
        if sel and sel[0] < len(self.targets):
            self.lb.selection_set(sel[0])

    def go(self):
        sel = self.lb.curselection()
        if not sel:
            return
        target = self.targets[sel[0]]
        self.win.destroy()
        if target is None:
            self.app.share_paths_with_phone(self.paths)
            self.app.toast("Listo para el celular", "Abre la página del QR en tu celular para descargar.")
        else:
            self.app.start_send(target, self.paths)


# ------------------------------------------------------------------ inicio

def main():
    files = [a for a in sys.argv[1:] if not a.startswith("--")]
    minimized = "--min" in sys.argv

    # Si ya está abierto, le pasamos los archivos y salimos (una sola instancia).
    if core.forward_to_running_instance(files):
        return

    if IS_WINDOWS:
        try:  # texto nítido en pantallas con escala 125%/150%
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass

    root = tk.Tk()
    app = App(root, files, minimized)
    if not app.start():
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
