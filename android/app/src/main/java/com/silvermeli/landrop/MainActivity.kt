package com.silvermeli.landrop

import android.app.Application
import android.app.DownloadManager
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.IntentCompat
import kotlinx.coroutines.delay

class App : Application() {
    val engine: Engine by lazy { Engine(this) }
}

fun humanSize(n: Long): String {
    if (n < 1024) return "$n B"
    var v = n.toDouble()
    for (u in listOf("KB", "MB", "GB", "TB")) {
        v /= 1024
        if (v < 1024) return String.format("%.1f %s", v, u)
    }
    return String.format("%.1f TB", v)
}

class MainActivity : ComponentActivity() {
    private val engine get() = (application as App).engine
    private val pendingUris = mutableStateListOf<Uri>()
    private var pendingText by mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        if (savedInstanceState == null) handleShare(intent)
        setContent {
            LanDropTheme {
                MainScreen(
                    engine = engine,
                    pendingUris = pendingUris,
                    pendingText = pendingText,
                    clearPending = { pendingUris.clear(); pendingText = null },
                    openItem = ::openItem,
                    openDownloads = ::openDownloads,
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleShare(intent)
    }

    override fun onStart() {
        super.onStart()
        engine.start()
    }

    override fun onStop() {
        super.onStop()
        if (!isChangingConfigurations) engine.stop()
    }

    private fun handleShare(i: Intent?) {
        if (i == null) return
        when (i.action) {
            Intent.ACTION_SEND -> {
                val u = IntentCompat.getParcelableExtra(i, Intent.EXTRA_STREAM, Uri::class.java)
                if (u != null) {
                    pendingUris.clear(); pendingUris.add(u); pendingText = null
                } else {
                    i.getStringExtra(Intent.EXTRA_TEXT)?.let { pendingUris.clear(); pendingText = it }
                }
            }
            Intent.ACTION_SEND_MULTIPLE -> {
                val l = IntentCompat.getParcelableArrayListExtra(i, Intent.EXTRA_STREAM, Uri::class.java)
                if (!l.isNullOrEmpty()) {
                    pendingUris.clear(); pendingUris.addAll(l); pendingText = null
                }
            }
        }
    }

    private fun openItem(item: ReceivedItem) {
        if (item.uri == null) {
            item.text?.let { engine.copyToClipboard(it) }
            Toast.makeText(this, "Texto copiado", Toast.LENGTH_SHORT).show()
            return
        }
        val i = Intent(Intent.ACTION_VIEW)
            .setDataAndType(item.uri, item.mime)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        try {
            startActivity(i)
        } catch (e: ActivityNotFoundException) {
            Toast.makeText(this, "No hay una app para abrir este archivo", Toast.LENGTH_SHORT).show()
        }
    }

    private fun openDownloads() {
        try {
            startActivity(Intent(DownloadManager.ACTION_VIEW_DOWNLOADS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (e: ActivityNotFoundException) {
            Toast.makeText(this, "Busca la carpeta Descargas/LanDrop en Mis archivos", Toast.LENGTH_LONG).show()
        }
    }
}

// ------------------------------------------------------------------ tema

@Composable
fun LanDropTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    val ctx = LocalContext.current
    val scheme = when {
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> if (dark) dynamicDarkColorScheme(ctx) else dynamicLightColorScheme(ctx)
        dark -> darkColorScheme(primary = Color(0xFF8AB0FF))
        else -> lightColorScheme(primary = Color(0xFF2F6BFF))
    }
    MaterialTheme(colorScheme = scheme, content = content)
}

// ------------------------------------------------------------------ pantalla principal

@Composable
fun MainScreen(
    engine: Engine,
    pendingUris: List<Uri>,
    pendingText: String?,
    clearPending: () -> Unit,
    openItem: (ReceivedItem) -> Unit,
    openDownloads: () -> Unit,
) {
    val peers by engine.peers.collectAsState()
    val progress by engine.progress.collectAsState()
    val received by engine.received.collectAsState()
    val incoming by engine.incoming.collectAsState()
    val name by engine.nameFlow.collectAsState()
    val snackbar = remember { SnackbarHostState() }

    var target by remember { mutableStateOf<Peer?>(null) }
    var textTarget by remember { mutableStateOf<Peer?>(null) }
    var renaming by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        engine.messages.collect { snackbar.showSnackbar(it) }
    }

    val files = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        val t = target
        if (t != null && uris.isNotEmpty()) engine.send(t, uris)
    }
    val media = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia()) { uris ->
        val t = target
        if (t != null && uris.isNotEmpty()) engine.send(t, uris)
    }

    val hasPending = pendingUris.isNotEmpty() || pendingText != null

    Scaffold(snackbarHost = { SnackbarHost(snackbar) }) { inner ->
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                start = 16.dp, end = 16.dp,
                top = inner.calculateTopPadding() + 12.dp,
                bottom = inner.calculateBottomPadding() + 24.dp,
            ),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item { Header(name) { renaming = true } }

            if (hasPending) {
                item {
                    PendingCard(
                        count = pendingUris.size,
                        text = pendingText,
                        onCancel = clearPending,
                    )
                }
            }

            progress?.let { p ->
                item { ProgressCard(p, onCancel = { engine.cancelSend() }) }
            }

            item { SectionTitle("Dispositivos cercanos") }
            if (peers.isEmpty()) {
                item { SearchingCard() }
            } else {
                items(peers, key = { it.id }) { peer ->
                    DeviceCard(
                        peer = peer,
                        highlight = hasPending,
                        onTap = {
                            if (hasPending) {
                                engine.send(peer, pendingUris.toList(), pendingText)
                                clearPending()
                            } else {
                                target = peer
                                media.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageAndVideo))
                            }
                        },
                        onPhotos = {
                            target = peer
                            media.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageAndVideo))
                        },
                        onFiles = {
                            target = peer
                            files.launch(arrayOf("*/*"))
                        },
                        onText = { textTarget = peer },
                    )
                }
            }

            item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    SectionTitle("Recibidos", Modifier.weight(1f))
                    TextButton(onClick = openDownloads) { Text("Ver Descargas") }
                }
            }
            if (received.isEmpty()) {
                item {
                    Text(
                        "Lo que te envíen se guarda en Descargas/LanDrop. Para recibir desde la PC, deja esta app abierta.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 4.dp),
                    )
                }
            } else {
                items(received) { r -> ReceivedRow(r) { openItem(r) } }
            }
        }
    }

    incoming?.let { IncomingDialog(it) }

    textTarget?.let { peer ->
        TextDialog(peer, onDismiss = { textTarget = null }) { text ->
            engine.send(peer, emptyList(), text)
            textTarget = null
        }
    }

    if (renaming) {
        RenameDialog(name, onDismiss = { renaming = false }) {
            engine.rename(it)
            renaming = false
        }
    }
}

// ------------------------------------------------------------------ componentes

@Composable
fun Header(name: String, onRename: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 8.dp)) {
        Box(
            modifier = Modifier
                .size(52.dp)
                .clip(RoundedCornerShape(16.dp))
                .background(Brush.linearGradient(listOf(Color(0xFF2F6BFF), Color(0xFF00B38A)))),
            contentAlignment = Alignment.Center,
        ) {
            Text("↑", color = Color.White, fontSize = 28.sp, fontWeight = FontWeight.Bold)
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text("LanDrop", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text(
                "Visible como $name",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
        }
        IconButton(onClick = onRename) { Icon(Icons.Filled.Edit, contentDescription = "Cambiar nombre") }
    }
}

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier) {
    Text(
        text, modifier = modifier.padding(start = 4.dp, top = 8.dp),
        style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold,
    )
}

@Composable
fun PendingCard(count: Int, text: String?, onCancel: () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
        shape = RoundedCornerShape(20.dp),
    ) {
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    if (text != null) "Texto listo para enviar" else "$count archivo(s) listos para enviar",
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                )
                Text(
                    "Toca un dispositivo de la lista",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                )
            }
            IconButton(onClick = onCancel) { Icon(Icons.Filled.Close, contentDescription = "Cancelar") }
        }
    }
}

@Composable
fun ProgressCard(p: Progress, onCancel: () -> Unit) {
    Card(shape = RoundedCornerShape(20.dp)) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(p.title, Modifier.weight(1f), fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                if (p.outgoing) TextButton(onClick = onCancel) { Text("Cancelar") }
            }
            Spacer(Modifier.height(8.dp))
            if (p.total > 0 && p.done > 0) {
                LinearProgressIndicator(
                    progress = { (p.done.toFloat() / p.total).coerceIn(0f, 1f) },
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    "${humanSize(p.done)} de ${humanSize(p.total)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                LinearProgressIndicator(Modifier.fillMaxWidth())
            }
        }
    }
}

@Composable
fun SearchingCard() {
    Card(shape = RoundedCornerShape(20.dp)) {
        Row(Modifier.padding(18.dp), verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.5.dp)
            Spacer(Modifier.width(14.dp))
            Column {
                Text("Buscando…", fontWeight = FontWeight.SemiBold)
                Text(
                    "Abre LanDrop en tu PC. Ambos deben estar en la misma red WiFi.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
fun DeviceCard(
    peer: Peer,
    highlight: Boolean,
    onTap: () -> Unit,
    onPhotos: () -> Unit,
    onFiles: () -> Unit,
    onText: () -> Unit,
) {
    val isPc = peer.kind != "android"
    Card(
        shape = RoundedCornerShape(20.dp),
        colors = if (highlight) CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer)
        else CardDefaults.cardColors(),
        modifier = Modifier.fillMaxWidth().clickable(onClick = onTap),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier.size(46.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primary),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        if (isPc) "PC" else peer.name.take(1).uppercase(),
                        color = MaterialTheme.colorScheme.onPrimary, fontWeight = FontWeight.Bold,
                    )
                }
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f)) {
                    Text(peer.name, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(
                        (if (isPc) "PC con Windows" else "Android") + " · ${peer.ip}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (!highlight) {
                Spacer(Modifier.height(12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilledTonalButton(onClick = onPhotos, modifier = Modifier.weight(1f)) { Text("Fotos") }
                    FilledTonalButton(onClick = onFiles, modifier = Modifier.weight(1f)) { Text("Archivos") }
                    FilledTonalButton(onClick = onText, modifier = Modifier.weight(1f)) { Text("Texto") }
                }
            }
        }
    }
}

@Composable
fun ReceivedRow(r: ReceivedItem, onClick: () -> Unit) {
    Card(shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            val ext = if (r.uri == null) "TXT" else r.name.substringAfterLast('.', "?").take(4).uppercase()
            Box(
                Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).background(MaterialTheme.colorScheme.tertiaryContainer),
                contentAlignment = Alignment.Center,
            ) {
                Text(ext, fontSize = 11.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onTertiaryContainer)
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    r.text ?: r.name, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.Medium,
                )
                Text(
                    "de ${r.from} · " + if (r.uri == null) "toca para copiar" else "toca para abrir",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
fun IncomingDialog(req: IncomingRequest) {
    var always by remember(req) { mutableStateOf(false) }
    var left by remember(req) { mutableStateOf(((req.deadline - System.currentTimeMillis()) / 1000).toInt()) }
    LaunchedEffect(req) {
        while (left > 0) {
            delay(1000)
            left = ((req.deadline - System.currentTimeMillis()) / 1000).toInt()
        }
        req.answer.complete(Answer.NO)
    }
    AlertDialog(
        onDismissRequest = { req.answer.complete(Answer.NO) },
        title = { Text(req.sender) },
        text = {
            Column {
                Text(
                    if (req.files.isNotEmpty()) "quiere enviarte ${req.files.size} archivo(s) · ${humanSize(req.total)}"
                    else "quiere enviarte un texto"
                )
                Spacer(Modifier.height(8.dp))
                req.files.take(5).forEach {
                    Text(
                        "• ${it.first}", style = MaterialTheme.typography.bodySmall,
                        maxLines = 1, overflow = TextOverflow.Ellipsis,
                    )
                }
                if (req.files.size > 5) Text("… y ${req.files.size - 5} más", style = MaterialTheme.typography.bodySmall)
                req.text?.let {
                    Text(it, style = MaterialTheme.typography.bodySmall, maxLines = 6, overflow = TextOverflow.Ellipsis)
                }
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 8.dp)) {
                    Checkbox(checked = always, onCheckedChange = { always = it })
                    Text("Aceptar siempre de este dispositivo", style = MaterialTheme.typography.bodyMedium)
                }
                Text(
                    "Se rechaza en ${left.coerceAtLeast(0)} s",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { req.answer.complete(if (always) Answer.ALWAYS else Answer.YES) }) { Text("Aceptar") }
        },
        dismissButton = {
            TextButton(onClick = { req.answer.complete(Answer.NO) }) { Text("Rechazar") }
        },
    )
}

@Composable
fun TextDialog(peer: Peer, onDismiss: () -> Unit, onSend: (String) -> Unit) {
    var text by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Texto para ${peer.name}") },
        text = {
            OutlinedTextField(
                value = text, onValueChange = { text = it },
                placeholder = { Text("Enlace, nota, contraseña…") },
                minLines = 3, modifier = Modifier.fillMaxWidth(),
            )
        },
        confirmButton = {
            TextButton(onClick = { if (text.isNotBlank()) onSend(text) }, enabled = text.isNotBlank()) { Text("Enviar") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancelar") } },
    )
}

@Composable
fun RenameDialog(current: String, onDismiss: () -> Unit, onSave: (String) -> Unit) {
    var text by remember { mutableStateOf(current) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Nombre de este celular") },
        text = { OutlinedTextField(value = text, onValueChange = { text = it.take(40) }, singleLine = true) },
        confirmButton = { TextButton(onClick = { onSave(text) }) { Text("Guardar") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancelar") } },
    )
}
