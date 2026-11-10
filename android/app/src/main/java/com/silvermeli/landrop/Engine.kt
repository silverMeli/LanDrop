package com.silvermeli.landrop

import android.content.ClipData
import android.content.ClipboardManager
import android.content.ContentValues
import android.content.Context
import android.net.ConnectivityManager
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.provider.Settings
import android.webkit.MimeTypeMap
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URL
import java.net.URLDecoder
import java.net.URLEncoder
import java.nio.ByteBuffer
import java.security.SecureRandom
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/*
 * Motor de LanDrop: usa el mismo protocolo que la app de Windows.
 *  - Descubrimiento: anuncios JSON por UDP broadcast en el puerto 47821.
 *  - Envío: POST /p2p/ask (el otro acepta) -> POST /p2p/upload por archivo -> POST /p2p/done.
 *  - Recepción: un mini servidor HTTP con esos mismos endpoints.
 */

const val APP = "LanDrop"
const val HTTP_PORT = 47820
const val DISCOVERY_PORT = 47821
const val ASK_TIMEOUT_MS = 55_000L
private const val PEER_TIMEOUT_MS = 12_000L
private const val CHUNK = 256 * 1024

data class Peer(val id: String, val name: String, val ip: String, val port: Int, val kind: String, val seen: Long)

enum class Answer { YES, ALWAYS, NO }

class IncomingRequest(
    val sender: String,
    val files: List<Pair<String, Long>>,
    val total: Long,
    val text: String?,
    val deadline: Long,
    val answer: CompletableDeferred<Answer>,
)

data class Progress(val title: String, val done: Long, val total: Long, val outgoing: Boolean)

data class ReceivedItem(
    val name: String,
    val from: String,
    val uri: Uri?,
    val mime: String?,
    val text: String?,
    val time: Long = System.currentTimeMillis(),
)

class SendItem(val uri: Uri, val name: String, val size: Long)

internal class Ticket(
    val ip: String,
    val sender: String,
    var left: Int,
    val total: Long,
    val expires: Long,
    var received: Long = 0,
    var count: Int = 0,
)

class Engine(private val ctx: Context) {
    private val prefs = ctx.getSharedPreferences("landrop", Context.MODE_PRIVATE)
    private val random = SecureRandom()

    val deviceId: String = prefs.getString("device_id", null)
        ?: UUID.randomUUID().toString().replace("-", "").also { prefs.edit().putString("device_id", it).apply() }

    val nameFlow = MutableStateFlow(prefs.getString("name", null) ?: defaultName())
    val name: String get() = nameFlow.value

    val peers = MutableStateFlow<List<Peer>>(emptyList())
    val incoming = MutableStateFlow<IncomingRequest?>(null)
    val progress = MutableStateFlow<Progress?>(null)
    val received = MutableStateFlow<List<ReceivedItem>>(emptyList())
    val messages = MutableSharedFlow<String>(extraBufferCapacity = 16)

    private val io = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val tickets = ConcurrentHashMap<String, Ticket>()
    private var session: Session? = null
    private var sendJob: Job? = null

    private class Session {
        @Volatile var alive = true
        @Volatile var udp: DatagramSocket? = null
        @Volatile var server: ServerSocket? = null
        @Volatile var port = HTTP_PORT
        val jobs = mutableListOf<Job>()
        var lock: WifiManager.MulticastLock? = null
    }

    private fun defaultName(): String =
        Settings.Global.getString(ctx.contentResolver, Settings.Global.DEVICE_NAME)?.takeIf { it.isNotBlank() }
            ?: Build.MODEL

    fun rename(newName: String) {
        val n = newName.trim().take(40).ifEmpty { defaultName() }
        prefs.edit().putString("name", n).apply()
        nameFlow.value = n
    }

    // ---------------------------------------------------------------- dispositivos de confianza
    private fun trustedIds(): Set<String> = prefs.getStringSet("trusted", emptySet()) ?: emptySet()
    private fun isTrusted(id: String) = id in trustedIds()
    private fun trust(id: String) {
        prefs.edit().putStringSet("trusted", trustedIds() + id).apply()
    }
    fun trustedCount() = trustedIds().size
    fun forgetTrusted() = prefs.edit().remove("trusted").apply()

    // ---------------------------------------------------------------- arranque / parada
    fun start() {
        if (session != null) return
        val s = Session()
        session = s
        val wifi = ctx.applicationContext.getSystemService(WifiManager::class.java)
        s.lock = wifi?.createMulticastLock("landrop")?.apply {
            setReferenceCounted(false)
            acquire()
        }
        s.jobs += io.launch {
            try {
                val srv = try {
                    ServerSocket().apply { reuseAddress = true; bind(InetSocketAddress(HTTP_PORT)) }
                } catch (e: IOException) {
                    ServerSocket(0)
                }
                s.server = srv
                s.port = srv.localPort
                if (!s.alive) srv.close() else serverLoop(s, srv)
            } catch (_: IOException) {
            }
        }
        s.jobs += io.launch {
            try {
                val udp = DatagramSocket(null).apply {
                    reuseAddress = true
                    broadcast = true
                    bind(InetSocketAddress(DISCOVERY_PORT))
                }
                s.udp = udp
                if (!s.alive) {
                    udp.close(); return@launch
                }
                launch {
                    delay(250) // que el servidor ya tenga su puerto
                    while (s.alive) {
                        announce(s, udp)
                        expirePeers()
                        delay(3000)
                    }
                }
                listenLoop(s, udp)
            } catch (e: IOException) {
                messages.tryEmit("No se pudo buscar dispositivos: ${e.message}")
            }
        }
    }

    fun stop() {
        val s = session ?: return
        session = null
        s.alive = false
        Thread {
            try {
                s.udp?.let { sendTo(it, packet(s, bye = true), broadcastTargets()) }
            } catch (_: Exception) {
            }
            try { s.udp?.close() } catch (_: Exception) {}
            try { s.server?.close() } catch (_: Exception) {}
            s.jobs.forEach { it.cancel() }
            try { s.lock?.release() } catch (_: Exception) {}
        }.start()
    }

    // ---------------------------------------------------------------- descubrimiento
    private fun packet(s: Session, bye: Boolean = false, reply: Boolean = false): ByteArray =
        JSONObject()
            .put("app", APP).put("v", 1).put("id", deviceId).put("name", name)
            .put("port", s.port).put("kind", "android").put("bye", bye).put("reply", reply)
            .toString().toByteArray(Charsets.UTF_8)

    private fun broadcastTargets(): Set<InetAddress> {
        val out = mutableSetOf<InetAddress>(InetAddress.getByName("255.255.255.255"))
        try {
            val cm = ctx.getSystemService(ConnectivityManager::class.java)
            val lp = cm?.getLinkProperties(cm.activeNetwork) ?: return out
            for (la in lp.linkAddresses) {
                val a = la.address
                if (a is Inet4Address && la.prefixLength in 1..31) {
                    val ip = ByteBuffer.wrap(a.address).int
                    val mask = -1 shl (32 - la.prefixLength)
                    val bc = ip or mask.inv()
                    out += InetAddress.getByAddress(ByteBuffer.allocate(4).putInt(bc).array())
                }
            }
        } catch (_: Exception) {
        }
        return out
    }

    private fun sendTo(udp: DatagramSocket, data: ByteArray, targets: Collection<InetAddress>) {
        for (t in targets) {
            try {
                udp.send(DatagramPacket(data, data.size, t, DISCOVERY_PORT))
            } catch (_: IOException) {
            }
        }
    }

    private fun announce(s: Session, udp: DatagramSocket) = sendTo(udp, packet(s), broadcastTargets())

    private fun expirePeers() {
        val now = System.currentTimeMillis()
        peers.update { list -> list.filter { now - it.seen < PEER_TIMEOUT_MS } }
    }

    private fun listenLoop(s: Session, udp: DatagramSocket) {
        val buf = ByteArray(4096)
        while (s.alive) {
            val pkt = DatagramPacket(buf, buf.size)
            try {
                udp.receive(pkt)
            } catch (e: IOException) {
                if (!s.alive) return else continue
            }
            val msg = try {
                JSONObject(String(pkt.data, 0, pkt.length, Charsets.UTF_8))
            } catch (e: Exception) {
                continue
            }
            if (msg.optString("app") != APP) continue
            val id = msg.optString("id")
            if (id.isEmpty() || id == deviceId) continue
            if (msg.optBoolean("bye")) {
                peers.update { l -> l.filter { it.id != id } }
                continue
            }
            val p = Peer(
                id = id,
                name = msg.optString("name", "Dispositivo").take(40),
                ip = pkt.address.hostAddress ?: continue,
                port = msg.optInt("port", HTTP_PORT),
                kind = msg.optString("kind", "windows"),
                seen = System.currentTimeMillis(),
            )
            peers.update { l -> (l.filter { it.id != id } + p).sortedBy { it.name.lowercase() } }
            if (!msg.optBoolean("reply")) {
                val r = packet(s, reply = true)
                try {
                    udp.send(DatagramPacket(r, r.size, pkt.address, DISCOVERY_PORT))
                } catch (_: IOException) {
                }
            }
        }
    }

    // ---------------------------------------------------------------- servidor (recibir)
    private fun serverLoop(s: Session, srv: ServerSocket) {
        while (s.alive) {
            val c = try {
                srv.accept()
            } catch (e: IOException) {
                break
            }
            io.launch { handle(c) }
        }
    }

    private fun readLine(input: InputStream): String? {
        val buf = ByteArrayOutputStream()
        while (true) {
            val b = input.read()
            if (b < 0) return if (buf.size() == 0) null else buf.toString("ISO-8859-1")
            if (b == '\n'.code) break
            if (b != '\r'.code) buf.write(b)
            if (buf.size() > 16_384) throw IOException("línea demasiado larga")
        }
        return buf.toString("ISO-8859-1")
    }

    private fun respond(out: OutputStream, code: Int, json: JSONObject) {
        val body = json.toString().toByteArray(Charsets.UTF_8)
        val status = when (code) {
            200 -> "OK"; 400 -> "Bad Request"; 403 -> "Forbidden"; 404 -> "Not Found"; else -> "Error"
        }
        out.write(
            ("HTTP/1.1 $code $status\r\nContent-Type: application/json; charset=utf-8\r\n" +
                "Content-Length: ${body.size}\r\nConnection: close\r\n\r\n").toByteArray(Charsets.ISO_8859_1)
        )
        out.write(body)
        out.flush()
    }

    private suspend fun handle(sock: Socket) {
        try {
            sock.use { s ->
                s.soTimeout = 120_000
                val input = BufferedInputStream(s.getInputStream(), CHUNK)
                val out = BufferedOutputStream(s.getOutputStream())
                val requestLine = readLine(input) ?: return
                val parts = requestLine.split(" ")
                if (parts.size < 2) return
                val method = parts[0]
                val target = parts[1]
                val headers = HashMap<String, String>()
                while (true) {
                    val l = readLine(input) ?: return
                    if (l.isEmpty()) break
                    val i = l.indexOf(':')
                    if (i > 0) headers[l.substring(0, i).trim().lowercase()] = l.substring(i + 1).trim()
                }
                val path = target.substringBefore('?')
                val query = target.substringAfter('?', "").split('&').filter { it.contains('=') }
                    .associate { URLDecoder.decode(it.substringBefore('='), "UTF-8") to URLDecoder.decode(it.substringAfter('='), "UTF-8") }
                val length = headers["content-length"]?.toLongOrNull() ?: 0L
                val remote = s.inetAddress.hostAddress ?: ""

                when {
                    method == "GET" && path == "/ping" ->
                        respond(out, 200, JSONObject().put("app", APP).put("name", name).put("v", "1.0"))

                    method == "POST" && path == "/p2p/ask" -> {
                        if (length > 1_000_000) return respond(out, 400, JSONObject().put("error", "muy grande"))
                        val body = ByteArray(length.toInt())
                        var read = 0
                        while (read < body.size) {
                            val n = input.read(body, read, body.size - read)
                            if (n < 0) return
                            read += n
                        }
                        handleAsk(body, remote, out)
                    }

                    method == "POST" && path == "/p2p/upload" -> {
                        val t = tickets[query["ticket"] ?: ""]
                        if (t == null || t.ip != remote || t.left <= 0 || t.expires < System.currentTimeMillis()) {
                            return respond(out, 403, JSONObject().put("error", "envío no autorizado"))
                        }
                        t.left--
                        val fname = URLDecoder.decode(headers["x-filename"] ?: "archivo", "UTF-8")
                        try {
                            saveIncoming(input, length, fname, t)
                            t.count++
                            respond(out, 200, JSONObject().put("ok", true))
                        } catch (e: IOException) {
                            progress.value = null
                            messages.tryEmit("Se interrumpió la recepción de $fname")
                        }
                    }

                    method == "POST" && path == "/p2p/done" -> {
                        val t = tickets.remove(query["ticket"] ?: "")
                        if (t != null && t.ip == remote) {
                            progress.value = null
                            messages.tryEmit("Recibido(s) ${t.count} archivo(s) de ${t.sender} · en Descargas/LanDrop")
                        }
                        respond(out, 200, JSONObject().put("ok", true))
                    }

                    else -> respond(out, 404, JSONObject().put("error", "no encontrado"))
                }
            }
        } catch (_: IOException) {
        }
    }

    private suspend fun handleAsk(body: ByteArray, remote: String, out: OutputStream) {
        val info = try {
            JSONObject(String(body, Charsets.UTF_8))
        } catch (e: Exception) {
            JSONObject()
        }
        val from = info.optString("from", "PC").take(40)
        val arr = info.optJSONArray("files") ?: JSONArray()
        val files = (0 until arr.length()).mapNotNull { i ->
            arr.optJSONObject(i)?.let { it.optString("name", "?") to it.optLong("size", 0) }
        }
        val total = info.optLong("total", files.sumOf { it.second })
        val text = if (info.has("text") && !info.isNull("text")) info.optString("text").take(100_000).ifEmpty { null } else null
        val id = info.optString("id", "")
        val count = info.optInt("count", files.size)

        val answer: Answer = if (id.isNotEmpty() && isTrusted(id)) {
            Answer.YES
        } else {
            if (incoming.value != null) {
                return respond(out, 200, JSONObject().put("ok", false).put("reason", "busy"))
            }
            val req = IncomingRequest(from, files, total, text, System.currentTimeMillis() + ASK_TIMEOUT_MS, CompletableDeferred())
            incoming.value = req
            val a = withTimeoutOrNull(ASK_TIMEOUT_MS) { req.answer.await() }
            incoming.compareAndSet(req, null)
            a ?: return respond(out, 200, JSONObject().put("ok", false).put("reason", "timeout"))
        }
        if (answer == Answer.NO) return respond(out, 200, JSONObject().put("ok", false).put("reason", "declined"))
        if (answer == Answer.ALWAYS && id.isNotEmpty()) trust(id)

        if (text != null) {
            withContext(Dispatchers.Main) { copyToClipboard(text) }
            received.update { listOf(ReceivedItem("Texto", from, null, null, text)) + it }
            messages.tryEmit("Texto de $from copiado al portapapeles")
        }
        if (files.isEmpty()) return respond(out, 200, JSONObject().put("ok", true).put("ticket", ""))

        val ticket = ByteArray(16).also { random.nextBytes(it) }.joinToString("") { "%02x".format(it) }
        tickets[ticket] = Ticket(remote, from, count, total, System.currentTimeMillis() + 6 * 3600_000L)
        progress.value = Progress("Recibiendo de $from", 0, total, false)
        respond(out, 200, JSONObject().put("ok", true).put("ticket", ticket))
    }

    fun copyToClipboard(text: String) {
        val cm = ctx.getSystemService(ClipboardManager::class.java)
        cm?.setPrimaryClip(ClipData.newPlainText("LanDrop", text))
    }

    private fun safeComponent(s: String): String {
        val r = s.replace(Regex("[\\\\/:*?\"<>|\\u0000-\\u001f]"), "_").trim().trim('.')
        return r.take(150).ifEmpty { "archivo" }
    }

    private fun saveIncoming(input: InputStream, length: Long, relName: String, t: Ticket) {
        val parts = relName.split('/', '\\')
            .filter { it.isNotBlank() && it != "." && it != ".." }
            .map { safeComponent(it) }
            .ifEmpty { listOf("archivo") }
        val display = parts.last()
        val dir = (listOf(Environment.DIRECTORY_DOWNLOADS, APP) + parts.dropLast(1)).joinToString("/") + "/"
        val ext = display.substringAfterLast('.', "").lowercase()
        val mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "application/octet-stream"
        val cr = ctx.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, display)
            put(MediaStore.Downloads.MIME_TYPE, mime)
            put(MediaStore.Downloads.RELATIVE_PATH, dir)
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val uri = cr.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: throw IOException("No se pudo crear el archivo")
        try {
            val os = cr.openOutputStream(uri) ?: throw IOException("No se pudo escribir")
            os.use { o ->
                val buf = ByteArray(CHUNK)
                var left = length
                var lastUi = 0L
                while (left > 0) {
                    val n = input.read(buf, 0, minOf(buf.size.toLong(), left).toInt())
                    if (n < 0) throw IOException("La conexión se cortó")
                    o.write(buf, 0, n)
                    left -= n
                    t.received += n
                    val now = System.currentTimeMillis()
                    if (now - lastUi > 150 || left == 0L) {
                        lastUi = now
                        progress.value = Progress("Recibiendo $display de ${t.sender}", t.received, maxOf(t.total, t.received), false)
                    }
                }
            }
            cr.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }, null, null)
        } catch (e: Exception) {
            try { cr.delete(uri, null, null) } catch (_: Exception) {}
            throw if (e is IOException) e else IOException(e)
        }
        received.update { listOf(ReceivedItem(display, t.sender, uri, mime, null)) + it }
    }

    // ---------------------------------------------------------------- cliente (enviar)
    private fun resolve(uris: List<Uri>): List<SendItem> = uris.mapNotNull { uri ->
        var name: String? = null
        var size = -1L
        try {
            ctx.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)
                ?.use { c ->
                    if (c.moveToFirst()) {
                        val ni = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                        val si = c.getColumnIndex(OpenableColumns.SIZE)
                        if (ni >= 0) name = c.getString(ni)
                        if (si >= 0 && !c.isNull(si)) size = c.getLong(si)
                    }
                }
        } catch (_: Exception) {
        }
        val display = name ?: uri.lastPathSegment?.substringAfterLast('/') ?: "archivo"
        if (size < 0) {
            size = try {
                ctx.contentResolver.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: -1L
            } catch (_: Exception) {
                -1L
            }
        }
        if (size >= 0) {
            SendItem(uri, display, size)
        } else {
            // tamaño desconocido: copiar a caché para poder enviarlo con Content-Length
            try {
                val f = File.createTempFile("envio", null, ctx.cacheDir)
                ctx.contentResolver.openInputStream(uri)?.use { i -> f.outputStream().use { i.copyTo(it) } }
                SendItem(Uri.fromFile(f), display, f.length())
            } catch (_: Exception) {
                null
            }
        }
    }

    private fun postJson(peer: Peer, path: String, json: JSONObject?, timeoutMs: Int): JSONObject {
        val conn = URL("http://${peer.ip}:${peer.port}$path").openConnection() as HttpURLConnection
        try {
            val body = json?.toString()?.toByteArray(Charsets.UTF_8) ?: ByteArray(0)
            conn.requestMethod = "POST"
            conn.connectTimeout = 8000
            conn.readTimeout = timeoutMs
            conn.doOutput = true
            conn.setFixedLengthStreamingMode(body.size)
            conn.setRequestProperty("Content-Type", "application/json")
            conn.outputStream.use { it.write(body) }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.use { it.readBytes().toString(Charsets.UTF_8) } ?: "{}"
            return try { JSONObject(text) } catch (e: Exception) { JSONObject() }
        } finally {
            conn.disconnect()
        }
    }

    private suspend fun upload(peer: Peer, ticket: String, item: SendItem, onBytes: (Int) -> Unit) {
        val url = URL("http://${peer.ip}:${peer.port}/p2p/upload?ticket=${URLEncoder.encode(ticket, "UTF-8")}")
        val conn = url.openConnection() as HttpURLConnection
        try {
            conn.requestMethod = "POST"
            conn.connectTimeout = 8000
            conn.readTimeout = 60_000
            conn.doOutput = true
            conn.setFixedLengthStreamingMode(item.size)
            conn.setRequestProperty("Content-Type", "application/octet-stream")
            conn.setRequestProperty("X-Filename", URLEncoder.encode(item.name, "UTF-8").replace("+", "%20"))
            val input = ctx.contentResolver.openInputStream(item.uri) ?: throw IOException("No se pudo leer ${item.name}")
            input.use { inp ->
                conn.outputStream.use { o ->
                    val buf = ByteArray(CHUNK)
                    var left = item.size
                    while (left > 0) {
                        currentCoroutineContext().ensureActive()
                        val n = inp.read(buf, 0, minOf(buf.size.toLong(), left).toInt())
                        if (n < 0) throw IOException("${item.name} cambió mientras se enviaba")
                        o.write(buf, 0, n)
                        left -= n
                        onBytes(n)
                    }
                }
            }
            val code = conn.responseCode
            if (code != 200) throw IOException("${peer.name} respondió con error $code")
            conn.inputStream.use { it.readBytes() }
        } finally {
            conn.disconnect()
        }
    }

    /** Envía archivos (uris) y/o un texto al dispositivo. */
    fun send(peer: Peer, uris: List<Uri>, text: String? = null) {
        if (sendJob?.isActive == true) {
            messages.tryEmit("Espera a que termine el envío actual")
            return
        }
        sendJob = io.launch {
            try {
                progress.value = Progress("Preparando…", 0, 0, true)
                val items = resolve(uris)
                if (items.isEmpty() && text == null) {
                    messages.tryEmit("No se pudieron leer los archivos")
                    return@launch
                }
                val total = items.sumOf { it.size }
                progress.value = Progress(
                    if (items.isEmpty()) "Enviando texto a ${peer.name}…" else "Esperando a que ${peer.name} acepte…",
                    0, total, true,
                )
                val ask = JSONObject()
                    .put("from", name).put("id", deviceId).put("count", items.size).put("total", total)
                    .put("files", JSONArray().apply {
                        items.take(200).forEach { put(JSONObject().put("name", it.name).put("size", it.size)) }
                    })
                if (text != null) ask.put("text", text)
                val resp = postJson(peer, "/p2p/ask", ask, 75_000)
                if (!resp.optBoolean("ok")) {
                    messages.tryEmit(
                        when (resp.optString("reason")) {
                            "timeout" -> "${peer.name} no respondió a tiempo"
                            "busy" -> "${peer.name} está ocupado, intenta de nuevo"
                            else -> "${peer.name} rechazó el envío"
                        }
                    )
                    return@launch
                }
                if (items.isEmpty()) {
                    messages.tryEmit("Texto enviado a ${peer.name}")
                    return@launch
                }
                val ticket = resp.getString("ticket")
                var sent = 0L
                var lastUi = 0L
                for (item in items) {
                    upload(peer, ticket, item) { n ->
                        sent += n
                        val now = System.currentTimeMillis()
                        if (now - lastUi > 120 || sent == total) {
                            lastUi = now
                            progress.value = Progress("Enviando ${item.name} a ${peer.name}", sent, total, true)
                        }
                    }
                }
                try { postJson(peer, "/p2p/done?ticket=$ticket", null, 10_000) } catch (_: IOException) {}
                messages.tryEmit("Listo: ${items.size} archivo(s) enviados a ${peer.name}")
            } catch (e: CancellationException) {
                messages.tryEmit("Envío cancelado")
                throw e
            } catch (e: Exception) {
                messages.tryEmit("No se pudo enviar: ${e.message ?: e.javaClass.simpleName}")
            } finally {
                progress.value = null
                ctx.cacheDir.listFiles()?.filter { it.name.startsWith("envio") }?.forEach { it.delete() }
            }
        }
    }

    fun cancelSend() {
        sendJob?.cancel()
    }
}
