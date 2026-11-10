"""
LanDrop - núcleo (sin interfaz gráfica).

- Servidor HTTP en la red local:
    * Página web para celulares (iPhone / Android) protegida con una clave que va en el QR.
    * Endpoints PC <-> PC con aceptación (como AirDrop: el otro equipo pregunta "¿Aceptar?").
- Descubrimiento automático de otras PCs con LanDrop por UDP broadcast.
- Cliente para enviar archivos a otra PC con barra de progreso.
"""

import http.client
import http.server
import json
import mimetypes
import os
import re
import secrets
import socket
import socketserver
import sys
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

from webpage import LOCKED_PAGE, PAGE

APP_NAME = "LanDrop"
VERSION = "1.0"
HTTP_PORT = 47820
DISCOVERY_PORT = 47821
CHUNK = 1024 * 1024  # 1 MB
PEER_TIMEOUT = 12     # segundos sin anuncio para quitar un equipo de la lista
ASK_TIMEOUT = 60      # segundos que espera la respuesta "Aceptar / Rechazar"

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


# ----------------------------------------------------------------- utilidades

def config_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_download_dir() -> Path:
    return Path.home() / "Downloads" / APP_NAME


def local_ip() -> str:
    """IP de la PC en la red local (la de la interfaz con salida a internet/WiFi)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no envía nada, solo elige la interfaz
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def safe_component(name: str) -> str:
    name = _INVALID_CHARS.sub("_", name).strip().strip(".")
    if not name:
        name = "archivo"
    stem = name.split(".")[0].upper()
    if stem in _RESERVED:
        name = "_" + name
    return name[:180]


def safe_relpath(name: str) -> Path:
    """Convierte 'carpeta/sub/foto.jpg' en una ruta relativa segura (sin '..')."""
    parts = [p for p in re.split(r"[\\/]+", name) if p not in ("", ".", "..")]
    if not parts:
        parts = ["archivo"]
    return Path(*[safe_component(p) for p in parts])


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    i = 1
    while True:
        cand = path.with_name(f"{stem} ({i}){suffix}")
        if not cand.exists():
            return cand
        i += 1


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ----------------------------------------------------------------- estado

class SharedFile:
    def __init__(self, path: Path):
        self.id = uuid.uuid4().hex[:12]
        self.path = path
        self.name = path.name
        self.size = path.stat().st_size


class Events:
    """Callbacks que la interfaz puede reemplazar. Se llaman desde hilos de red."""

    def received(self, path: Path, sender: str): ...
    def text(self, text: str, sender: str): ...
    def log(self, msg: str): ...
    def peers_changed(self): ...
    def local_files(self, paths: list): ...   # archivos recibidos por "Enviar a" / arrastrar al ícono
    def show_window(self): ...

    def ask_accept(self, sender: str, files: list, total: int) -> bool:
        """Debe devolver True si el usuario acepta. Por defecto rechaza."""
        return False


class LanDrop:
    def __init__(self, events: Events | None = None, http_port=HTTP_PORT,
                 discovery_port=DISCOVERY_PORT, download_dir: Path | None = None,
                 config_path: Path | None = None):
        self.events = events or Events()
        self.http_port = http_port
        self.discovery_port = discovery_port
        self.config_path = config_path or (config_dir() / "config.json")
        self.cfg = self._load_config()
        if download_dir:
            self.cfg["download_dir"] = str(download_dir)
        self.download_dir = Path(self.cfg["download_dir"])
        self.instance_id = uuid.uuid4().hex
        self.shared: dict[str, SharedFile] = {}
        self.shared_text = ""
        self.revision = 0
        self.peers: dict[str, dict] = {}
        self.tickets: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.httpd = None
        self.udp = None
        self.running = False

    # --- configuración persistente
    def _load_config(self) -> dict:
        cfg = {}
        try:
            cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        cfg.setdefault("name", socket.gethostname())
        cfg.setdefault("key", secrets.token_urlsafe(6))
        cfg.setdefault("download_dir", str(default_download_dir()))
        self._save_config(cfg)
        return cfg

    def _save_config(self, cfg=None):
        try:
            self.config_path.write_text(json.dumps(cfg or self.cfg, indent=2, ensure_ascii=False),
                                        encoding="utf-8")
        except OSError:
            pass

    @property
    def name(self) -> str:
        return self.cfg["name"]

    def set_name(self, name: str):
        self.cfg["name"] = name.strip()[:40] or socket.gethostname()
        self._save_config()

    def set_download_dir(self, d: Path):
        self.download_dir = Path(d)
        self.cfg["download_dir"] = str(d)
        self._save_config()

    def regenerate_key(self):
        self.cfg["key"] = secrets.token_urlsafe(6)
        self._save_config()

    @property
    def key(self) -> str:
        return self.cfg["key"]

    def phone_url(self) -> str:
        return f"http://{local_ip()}:{self.http_port}/?k={self.key}"

    # --- archivos compartidos con el celular
    def share_files(self, paths):
        added = []
        with self.lock:
            for p in paths:
                p = Path(p)
                if p.is_file():
                    f = SharedFile(p)
                    self.shared[f.id] = f
                    added.append(f)
            self.revision += 1
        return added

    def unshare(self, file_id: str):
        with self.lock:
            self.shared.pop(file_id, None)
            self.revision += 1

    def clear_shared(self):
        with self.lock:
            self.shared.clear()
            self.revision += 1

    def share_text(self, text: str):
        with self.lock:
            self.shared_text = text
            self.revision += 1

    # --- arranque / parada
    def start(self):
        handler = type("Handler", (_Handler,), {"app": self})
        self.httpd = _Server(("0.0.0.0", self.http_port), handler)
        self.running = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        try:
            self._start_discovery()
        except OSError as e:
            self.events.log(f"Descubrimiento de PCs desactivado: {e}")

    def stop(self):
        self.running = False
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        if self.udp:
            try:
                self._announce(bye=True)
            except OSError:
                pass
            self.udp.close()

    # --- descubrimiento UDP
    def _start_discovery(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("", self.discovery_port))
        self.udp = s
        threading.Thread(target=self._listen_loop, daemon=True).start()
        threading.Thread(target=self._announce_loop, daemon=True).start()

    def _packet(self, bye=False, reply=False) -> bytes:
        return json.dumps({"app": APP_NAME, "v": 1, "id": self.instance_id, "name": self.name,
                           "port": self.http_port, "bye": bye, "reply": reply}).encode()

    def _broadcast_targets(self):
        targets = {"255.255.255.255"}
        ip = local_ip()
        if ip.count(".") == 3 and not ip.startswith("127."):
            targets.add(ip.rsplit(".", 1)[0] + ".255")  # suponiendo red /24 (lo normal en casa)
        return targets

    def _announce(self, bye=False):
        for t in self._broadcast_targets():
            try:
                self.udp.sendto(self._packet(bye=bye), (t, self.discovery_port))
            except OSError:
                pass

    def _announce_loop(self):
        while self.running:
            self._announce()
            self._expire_peers()
            time.sleep(3)

    def _listen_loop(self):
        while self.running:
            try:
                data, addr = self.udp.recvfrom(4096)
                msg = json.loads(data.decode())
            except (OSError, ValueError):
                if not self.running:
                    return
                continue
            if msg.get("app") != APP_NAME or msg.get("id") == self.instance_id:
                continue
            pid = msg["id"]
            changed = False
            with self.lock:
                if msg.get("bye"):
                    changed = self.peers.pop(pid, None) is not None
                else:
                    new = pid not in self.peers or self.peers[pid]["name"] != msg.get("name")
                    self.peers[pid] = {"id": pid, "name": str(msg.get("name", "PC"))[:40],
                                       "ip": addr[0], "port": int(msg.get("port", HTTP_PORT)),
                                       "seen": time.time()}
                    changed = new
            if changed:
                self.events.peers_changed()
            # responder directo para que el otro nos vea de inmediato
            if not msg.get("reply") and not msg.get("bye"):
                try:
                    self.udp.sendto(self._packet(reply=True), (addr[0], self.discovery_port))
                except OSError:
                    pass

    def _expire_peers(self):
        now = time.time()
        with self.lock:
            dead = [k for k, p in self.peers.items() if now - p["seen"] > PEER_TIMEOUT]
            for k in dead:
                del self.peers[k]
        if dead:
            self.events.peers_changed()

    def peer_list(self):
        with self.lock:
            return sorted(self.peers.values(), key=lambda p: p["name"].lower())

    # --- guardar archivo entrante (en streaming)
    def save_stream(self, rfile, length: int, rel_name: str, sender: str) -> Path:
        rel = safe_relpath(rel_name)
        dest = unique_path(self.download_dir / rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        remaining = length
        try:
            with open(tmp, "wb") as f:
                while remaining > 0:
                    chunk = rfile.read(min(CHUNK, remaining))
                    if not chunk:
                        raise ConnectionError("La conexión se cortó")
                    f.write(chunk)
                    remaining -= len(chunk)
            dest = unique_path(dest)  # por si otro archivo igual llegó mientras tanto
            os.replace(tmp, dest)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        self.events.received(dest, sender)
        return dest

    # --- cliente: enviar a otra PC
    def send_to_peer(self, peer: dict, paths, progress=None, cancel: threading.Event = None):
        """
        Envía archivos a otra PC. 'paths' puede tener archivos y carpetas.
        progress(enviado_bytes, total_bytes, nombre_actual) se llama durante el envío.
        Devuelve (True, msg) o (False, msg).
        """
        items = expand_paths(paths)
        if not items:
            return False, "No hay archivos para enviar."
        total = sum(sz for _, _, sz in items)
        host, port = peer["ip"], peer["port"]

        try:
            body = json.dumps({"from": self.name,
                               "files": [{"name": rel, "size": sz} for _, rel, sz in items[:200]],
                               "count": len(items), "total": total}).encode()
            conn = http.client.HTTPConnection(host, port, timeout=ASK_TIMEOUT + 15)
            conn.request("POST", "/p2p/ask", body, {"Content-Type": "application/json"})
            resp = json.loads(conn.getresponse().read().decode() or "{}")
            conn.close()
        except (OSError, ValueError) as e:
            return False, f"No se pudo contactar a {peer['name']}: {e}"
        if not resp.get("ok"):
            return False, f"{peer['name']} rechazó el envío" if resp.get("reason") != "timeout" \
                else f"{peer['name']} no respondió a tiempo"
        ticket = resp["ticket"]

        sent = 0
        for full, rel, size in items:
            if cancel and cancel.is_set():
                return False, "Envío cancelado"
            try:
                conn = http.client.HTTPConnection(host, port, timeout=60)
                conn.putrequest("POST", f"/p2p/upload?ticket={ticket}")
                conn.putheader("Content-Length", str(size))
                conn.putheader("X-Filename", urllib.parse.quote(rel))
                conn.putheader("Content-Type", "application/octet-stream")
                conn.endheaders()
                with open(full, "rb") as f:
                    while True:
                        if cancel and cancel.is_set():
                            conn.close()
                            return False, "Envío cancelado"
                        chunk = f.read(CHUNK)
                        if not chunk:
                            break
                        conn.send(chunk)
                        sent += len(chunk)
                        if progress:
                            progress(sent, total, rel)
                r = conn.getresponse()
                r.read()
                conn.close()
                if r.status != 200:
                    return False, f"Error al enviar {rel} (código {r.status})"
            except OSError as e:
                return False, f"Error al enviar {rel}: {e}"
        try:
            conn = http.client.HTTPConnection(host, port, timeout=10)
            conn.request("POST", f"/p2p/done?ticket={ticket}", b"")
            conn.getresponse().read()
            conn.close()
        except OSError:
            pass
        return True, f"Enviado(s) {len(items)} archivo(s) a {peer['name']} ({human_size(total)})"


def expand_paths(paths):
    """Devuelve [(ruta_completa, nombre_relativo, tamaño)] expandiendo carpetas."""
    out = []
    for p in paths:
        p = Path(p)
        if p.is_file():
            out.append((p, p.name, p.stat().st_size))
        elif p.is_dir():
            for root, _dirs, files in os.walk(p):
                for fn in files:
                    full = Path(root) / fn
                    rel = Path(p.name) / full.relative_to(p)
                    try:
                        out.append((full, rel.as_posix(), full.stat().st_size))
                    except OSError:
                        pass
    return out


# ----------------------------------------------------------------- servidor HTTP

class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    # En Linux/Mac SO_REUSEADDR solo evita el bloqueo tras cerrar; en Windows permitiría
    # dos instancias en el mismo puerto, así que allí se usa SO_EXCLUSIVEADDRUSE.
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self):
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class _Handler(http.server.BaseHTTPRequestHandler):
    app: LanDrop = None
    protocol_version = "HTTP/1.1"
    server_version = f"{APP_NAME}/{VERSION}"

    def log_message(self, fmt, *args):  # silencioso
        pass

    # --- helpers
    def _send(self, code=200, body=b"", ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        elif isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _query(self):
        return urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)

    def _route(self):
        return urllib.parse.urlsplit(self.path).path

    def _is_local(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _cookie_key(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "ldk":
                return v
        return None

    def _authorized(self):
        key = self.app.key
        q = self._query().get("k", [None])[0]
        return secrets.compare_digest(str(q or self._cookie_key() or self.headers.get("X-Key") or ""), key)

    def _sender_name(self):
        ua = self.headers.get("User-Agent", "")
        if "iPhone" in ua:
            dev = "iPhone"
        elif "iPad" in ua:
            dev = "iPad"
        elif "Android" in ua:
            dev = "Android"
        else:
            dev = "Navegador"
        return f"{dev} ({self.client_address[0]})"

    def _read_body(self, limit=1_000_000):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("cuerpo demasiado grande")
        return self.rfile.read(n) if n else b""

    def _drain(self):
        """Descarta el cuerpo pendiente para no romper la conexión keep-alive."""
        n = int(self.headers.get("Content-Length") or 0)
        while n > 0:
            chunk = self.rfile.read(min(CHUNK, n))
            if not chunk:
                break
            n -= len(chunk)

    # --- GET
    def do_GET(self):
        route = self._route()
        app = self.app

        if route == "/":
            if not self._authorized():
                return self._send(403, LOCKED_PAGE, "text/html; charset=utf-8")
            html = PAGE.replace("{{NAME}}", _html_escape(app.name))
            return self._send(200, html, "text/html; charset=utf-8", {
                "Set-Cookie": f"ldk={app.key}; Path=/; Max-Age=31536000; SameSite=Lax"})

        if route == "/ping":
            return self._send(200, {"app": APP_NAME, "name": app.name, "v": VERSION})

        if route == "/api/info":
            if not self._authorized():
                return self._send(403, {"error": "clave inválida"})
            with app.lock:
                files = [{"id": f.id, "name": f.name, "size": f.size} for f in app.shared.values()]
                data = {"name": app.name, "files": files, "text": app.shared_text, "rev": app.revision}
            return self._send(200, data)

        if route.startswith("/dl/"):
            if not self._authorized():
                return self._send(403, {"error": "clave inválida"})
            fid = route[4:].split("/")[0]
            f = app.shared.get(fid)
            if not f or not f.path.is_file():
                return self._send(404, {"error": "archivo no disponible"})
            return self._send_file(f)

        if route == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")

        self._send(404, {"error": "no encontrado"})

    do_HEAD = do_GET

    def _send_file(self, f: SharedFile):
        size = f.path.stat().st_size
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        quoted = urllib.parse.quote(f.name)
        ascii_name = f.name.encode("ascii", "replace").decode().replace('"', "_").replace("?", "_")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition",
                         f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(f.path, "rb") as fh:
            while True:
                chunk = fh.read(CHUNK)
                if not chunk:
                    break
                self.wfile.write(chunk)
        self.app.events.log(f"El celular descargó: {f.name}")

    # --- POST
    def do_POST(self):
        route = self._route()
        app = self.app
        try:
            # ---------- desde el celular (requiere clave del QR)
            if route == "/api/upload":
                if not self._authorized():
                    self._drain()
                    return self._send(403, {"error": "clave inválida"})
                name = urllib.parse.unquote(self.headers.get("X-Filename", "archivo"))
                name = Path(name.replace("\\", "/")).name  # desde el celular solo nombre
                length = int(self.headers.get("Content-Length") or 0)
                dest = app.save_stream(self.rfile, length, name, self._sender_name())
                return self._send(200, {"ok": True, "saved": dest.name})

            if route == "/api/text":
                if not self._authorized():
                    self._drain()
                    return self._send(403, {"error": "clave inválida"})
                text = self._read_body().decode("utf-8", "replace")
                app.events.text(text, self._sender_name())
                return self._send(200, {"ok": True})

            # ---------- PC a PC (el receptor debe aceptar)
            if route == "/p2p/ask":
                info = json.loads(self._read_body() or b"{}")
                sender = str(info.get("from", "PC"))[:40] + f" ({self.client_address[0]})"
                files = info.get("files", [])
                total = int(info.get("total", 0))
                result = {}
                done = threading.Event()

                def ask():
                    try:
                        result["ok"] = bool(app.events.ask_accept(sender, files, total))
                    finally:
                        done.set()
                threading.Thread(target=ask, daemon=True).start()
                if not done.wait(ASK_TIMEOUT):
                    return self._send(200, {"ok": False, "reason": "timeout"})
                if not result.get("ok"):
                    return self._send(200, {"ok": False, "reason": "declined"})
                ticket = secrets.token_urlsafe(16)
                with app.lock:
                    app.tickets[ticket] = {"ip": self.client_address[0], "sender": sender,
                                           "left": int(info.get("count", len(files))),
                                           "expires": time.time() + 6 * 3600, "count": 0}
                return self._send(200, {"ok": True, "ticket": ticket})

            if route == "/p2p/upload":
                ticket = self._query().get("ticket", [""])[0]
                t = app.tickets.get(ticket)
                if not t or t["ip"] != self.client_address[0] or t["expires"] < time.time() or t["left"] <= 0:
                    self._drain()
                    return self._send(403, {"error": "envío no autorizado"})
                t["left"] -= 1
                name = urllib.parse.unquote(self.headers.get("X-Filename", "archivo"))
                length = int(self.headers.get("Content-Length") or 0)
                app.save_stream(self.rfile, length, name, t["sender"])
                t["count"] += 1
                return self._send(200, {"ok": True})

            if route == "/p2p/done":
                ticket = self._query().get("ticket", [""])[0]
                with app.lock:
                    t = app.tickets.pop(ticket, None)
                if t and t["ip"] == self.client_address[0]:
                    app.events.log(f"Recibidos {t['count']} archivo(s) de {t['sender']}")
                return self._send(200, {"ok": True})

            # ---------- control local (segunda instancia, menú "Enviar a")
            if route == "/local/open":
                if not self._is_local():
                    return self._send(403, {"error": "solo local"})
                info = json.loads(self._read_body() or b"{}")
                paths = [p for p in info.get("paths", []) if os.path.exists(p)]
                if paths:
                    app.events.local_files(paths)
                else:
                    app.events.show_window()
                return self._send(200, {"ok": True})

            self._drain()
            self._send(404, {"error": "no encontrado"})
        except (ConnectionError, OSError) as e:
            app.events.log(f"Transferencia interrumpida: {e}")
            self.close_connection = True
        except ValueError as e:
            self.close_connection = True
            try:
                self._send(400, {"error": str(e)})
            except OSError:
                pass


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def forward_to_running_instance(paths, port=HTTP_PORT) -> bool:
    """Si LanDrop ya está abierto, le pasa los archivos y devuelve True."""
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/ping")
        r = conn.getresponse()
        data = json.loads(r.read().decode() or "{}")
        if data.get("app") != APP_NAME:
            return False
        body = json.dumps({"paths": [os.path.abspath(p) for p in paths]}).encode()
        conn.request("POST", "/local/open", body, {"Content-Type": "application/json"})
        conn.getresponse().read()
        conn.close()
        return True
    except (OSError, ValueError):
        return False


if __name__ == "__main__":
    # Modo consola (útil para probar sin interfaz): python core.py
    class ConsoleEvents(Events):
        def received(self, path, sender): print(f"[recibido] {path} de {sender}")
        def text(self, text, sender): print(f"[texto de {sender}] {text}")
        def log(self, msg): print(f"[log] {msg}")
        def peers_changed(self): print("[equipos]", [p["name"] for p in app.peer_list()])
        def ask_accept(self, sender, files, total):
            return input(f"{sender} quiere enviarte {len(files)} archivo(s) ({human_size(total)}). ¿Aceptar? [s/n] ").lower().startswith("s")

    app = LanDrop(ConsoleEvents())
    app.start()
    print(f"{APP_NAME} activo como '{app.name}'. Abre en el celular: {app.phone_url()}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        app.stop()
        sys.exit(0)
