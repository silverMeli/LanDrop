"""Página que se abre en el celular al escanear el QR (iPhone y Android, sin instalar nada)."""

LOCKED_PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LanDrop</title>
<style>body{font-family:system-ui,-apple-system,sans-serif;display:grid;place-items:center;
min-height:90vh;margin:0;padding:24px;text-align:center;background:#0f1115;color:#e9ecf1}
.b{max-width:340px}h1{font-size:22px}p{color:#9aa3b2;line-height:1.5}</style></head>
<body><div class="b"><h1>Escanea el código QR</h1>
<p>Abre LanDrop en tu PC y escanea el código QR con la cámara del celular para conectarte.</p>
</div></body></html>"""

PAGE = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0f1115">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>LanDrop · {{NAME}}</title>
<style>
  :root{
    --bg:#f3f5f9; --card:#ffffff; --text:#151922; --muted:#6b7385; --line:#e3e7ef;
    --accent:#2f6bff; --accent2:#00b38a; --danger:#e5484d; --shadow:0 6px 24px rgba(20,30,60,.08);
  }
  @media (prefers-color-scheme: dark){
    :root{ --bg:#0f1115; --card:#191c23; --text:#e9ecf1; --muted:#9aa3b2; --line:#272b35;
           --shadow:0 6px 24px rgba(0,0,0,.35); }
  }
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);
       color:var(--text);padding:calc(16px + env(safe-area-inset-top)) 16px calc(28px + env(safe-area-inset-bottom))}
  .wrap{max-width:520px;margin:0 auto}
  header{display:flex;align-items:center;gap:12px;margin:4px 2px 18px}
  .logo{width:44px;height:44px;border-radius:14px;background:linear-gradient(135deg,var(--accent),var(--accent2));
        display:grid;place-items:center;color:#fff;flex:none}
  header h1{font-size:19px;margin:0}
  header p{margin:2px 0 0;color:var(--muted);font-size:13px}
  .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--accent2);margin-right:6px;vertical-align:1px}
  .dot.off{background:var(--danger)}
  .card{background:var(--card);border-radius:20px;padding:18px;margin-bottom:14px;box-shadow:var(--shadow)}
  .card h2{font-size:15px;margin:0 0 12px;display:flex;align-items:center;gap:8px}
  .drop{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;
        border:2px dashed var(--line);border-radius:16px;padding:26px 12px;text-align:center;cursor:pointer}
  .drop strong{font-size:16px}
  .drop span{color:var(--muted);font-size:13px}
  .drop.over{border-color:var(--accent);background:rgba(47,107,255,.06)}
  .btn{appearance:none;border:0;border-radius:14px;padding:13px 16px;font-size:15px;font-weight:600;
       background:var(--accent);color:#fff;width:100%;cursor:pointer}
  .btn.sec{background:transparent;color:var(--accent);border:1.5px solid var(--line)}
  .btn:disabled{opacity:.5}
  textarea{width:100%;min-height:80px;border-radius:14px;border:1.5px solid var(--line);background:transparent;
           color:var(--text);padding:12px;font:inherit;resize:vertical;margin-bottom:10px}
  .item{display:flex;align-items:center;gap:12px;padding:10px 0;border-top:1px solid var(--line)}
  .item:first-child{border-top:0}
  .ic{width:38px;height:38px;border-radius:11px;background:rgba(47,107,255,.12);color:var(--accent);
      display:grid;place-items:center;font-size:12px;font-weight:700;flex:none;text-transform:uppercase}
  .meta{flex:1;min-width:0}
  .meta b{display:block;font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .meta small{color:var(--muted);font-size:12px}
  .bar{height:5px;border-radius:5px;background:var(--line);margin-top:6px;overflow:hidden}
  .bar i{display:block;height:100%;width:0;background:var(--accent);transition:width .15s}
  .ok .bar i{background:var(--accent2)} .err .bar i{background:var(--danger)}
  a.get{color:var(--accent);font-weight:600;text-decoration:none;font-size:14px;padding:8px 4px}
  .empty{color:var(--muted);font-size:14px;text-align:center;padding:8px 0}
  .pctext{white-space:pre-wrap;word-break:break-word;background:var(--bg);border-radius:12px;padding:12px;font-size:14px;margin-bottom:10px}
  .row{display:flex;gap:10px}
  .toast{position:fixed;left:50%;bottom:calc(20px + env(safe-area-inset-bottom));transform:translateX(-50%) translateY(30px);
         background:#151922;color:#fff;padding:11px 18px;border-radius:999px;font-size:14px;opacity:0;transition:.25s;pointer-events:none}
  .toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 10l5-5 5 5"/><path d="M12 5v10"/><path d="M5 19h14"/></svg>
    </div>
    <div>
      <h1>{{NAME}}</h1>
      <p><span class="dot" id="dot"></span><span id="status">Conectado por WiFi</span></p>
    </div>
  </header>

  <div class="card">
    <h2>Enviar a la PC</h2>
    <label class="drop" id="drop">
      <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="color:var(--accent)"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5"/><path d="M12 3v12"/></svg>
      <strong>Elegir fotos, videos o archivos</strong>
      <span>Puedes seleccionar varios a la vez</span>
      <input type="file" id="file" multiple hidden>
    </label>
    <div id="uploads" style="margin-top:10px"></div>
  </div>

  <div class="card">
    <h2>Recibir de la PC</h2>
    <div id="files"><div class="empty">Cuando la PC comparta archivos, aparecerán aquí.</div></div>
    <div id="pctextbox" hidden>
      <div class="pctext" id="pctext"></div>
      <button class="btn sec" id="copypc">Copiar texto</button>
    </div>
  </div>

  <div class="card">
    <h2>Enviar texto o enlace</h2>
    <textarea id="txt" placeholder="Pega aquí un enlace, una contraseña, una nota…"></textarea>
    <button class="btn" id="sendtxt">Enviar a la PC</button>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
const $ = s => document.querySelector(s);
const fmt = n => n < 1024 ? n + " B" : n < 1048576 ? (n/1024).toFixed(1) + " KB" :
                n < 1073741824 ? (n/1048576).toFixed(1) + " MB" : (n/1073741824).toFixed(2) + " GB";
const ext = n => (n.split(".").pop() || "").slice(0,4) || "?";
const esc = s => s.replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function toast(msg){ const t=$("#toast"); t.textContent=msg; t.classList.add("show");
  clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove("show"),2200); }

// ---------- subir archivos (de uno en uno, con progreso)
const queue = [];
let busy = false;
function addFiles(list){
  for (const f of list){
    const el = document.createElement("div");
    el.className = "item";
    el.innerHTML = `<div class="ic">${esc(ext(f.name))}</div><div class="meta"><b>${esc(f.name)}</b>
      <small>${fmt(f.size)} · en cola</small><div class="bar"><i></i></div></div>`;
    $("#uploads").prepend(el);
    queue.push({f, el});
  }
  next();
}
function next(){
  if (busy || !queue.length) return;
  busy = true;
  const {f, el} = queue.shift();
  const bar = el.querySelector(".bar i"), small = el.querySelector("small");
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/upload");
  xhr.setRequestHeader("X-Filename", encodeURIComponent(f.name));
  xhr.setRequestHeader("Content-Type", "application/octet-stream");
  const t0 = Date.now();
  xhr.upload.onprogress = e => {
    if (!e.lengthComputable) return;
    const p = e.loaded / e.total * 100, secs = (Date.now()-t0)/1000;
    bar.style.width = p + "%";
    small.textContent = `${fmt(e.loaded)} de ${fmt(e.total)}` + (secs > 0.5 ? ` · ${fmt(e.loaded/secs)}/s` : "");
  };
  xhr.onload = () => {
    if (xhr.status === 200){ el.classList.add("ok"); bar.style.width="100%"; small.textContent = fmt(f.size) + " · enviado ✓"; }
    else { el.classList.add("err"); small.textContent = "Error " + xhr.status + (xhr.status===403?" · vuelve a escanear el QR":""); }
    busy = false; next();
    if (!queue.length && !busy && xhr.status === 200) toast("Listo, archivos enviados");
  };
  xhr.onerror = () => { el.classList.add("err"); small.textContent = "Se perdió la conexión"; busy=false; next(); };
  xhr.send(f);
}
$("#file").addEventListener("change", e => { addFiles(e.target.files); e.target.value = ""; });
const drop = $("#drop");
["dragenter","dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave","drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", e => addFiles(e.dataTransfer.files));

// ---------- enviar texto
$("#sendtxt").onclick = async () => {
  const v = $("#txt").value.trim();
  if (!v) return toast("Escribe algo primero");
  try {
    const r = await fetch("/api/text", {method:"POST", body:v, headers:{"Content-Type":"text/plain;charset=utf-8"}});
    if (!r.ok) throw 0;
    $("#txt").value = ""; toast("Texto enviado y copiado en la PC");
  } catch { toast("No se pudo enviar"); }
};

// ---------- recibir de la PC (consulta cada 2.5 s)
let rev = -1, pcText = "";
async function poll(){
  try {
    const r = await fetch("/api/info", {cache:"no-store"});
    if (r.status === 403){ $("#status").textContent = "Clave vencida: vuelve a escanear el QR"; $("#dot").classList.add("off"); return; }
    const d = await r.json();
    $("#status").textContent = "Conectado por WiFi"; $("#dot").classList.remove("off");
    if (d.rev !== rev){
      rev = d.rev;
      const box = $("#files");
      if (!d.files.length) box.innerHTML = '<div class="empty">Cuando la PC comparta archivos, aparecerán aquí.</div>';
      else box.innerHTML = d.files.map(f => `<div class="item"><div class="ic">${esc(ext(f.name))}</div>
          <div class="meta"><b>${esc(f.name)}</b><small>${fmt(f.size)}</small></div>
          <a class="get" href="/dl/${f.id}/${encodeURIComponent(f.name)}" download="${esc(f.name)}">Descargar</a></div>`).join("");
      pcText = d.text || "";
      $("#pctextbox").hidden = !pcText;
      $("#pctext").textContent = pcText;
      if (d.files.length && rev > 0) toast("La PC compartió archivos");
    }
  } catch {
    $("#status").textContent = "Sin conexión con la PC"; $("#dot").classList.add("off");
  }
  setTimeout(poll, 2500);
}
$("#copypc").onclick = async () => {
  try { await navigator.clipboard.writeText(pcText); toast("Copiado"); }
  catch {
    const ta = document.createElement("textarea"); ta.value = pcText; document.body.appendChild(ta);
    ta.select(); document.execCommand("copy"); ta.remove(); toast("Copiado");
  }
};
poll();
</script>
</body>
</html>
"""
