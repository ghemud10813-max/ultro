package com.letvler.nixin.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SuggestionChip
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.letvler.nixin.Nixin
import com.letvler.nixin.core.AppState
import com.letvler.nixin.voice.VoiceInput

private val EXAMPLES = listOf(
    "volume badha do", "briefing do", "mere messages summarize karo", "har raat 11 baje phone silent kar dena",
    "WhatsApp pe Mummy ko bol main 10 min late hoon", "PC ka screenshot bhejo", "sikho: chai order",
)

/** Quick PC controls (sent as ordinary commands, so they work by voice too). */
private val PC_CHIPS = listOf(
    "🔒 Lock PC" to "PC lock karo", "🔉 PC vol −" to "PC ka volume kam karo", "🔊 PC vol +" to "PC ka volume badhao",
    "⏯ PC media" to "PC pe gaana pause karo", "📸 PC screenshot" to "PC ka screenshot bhejo",
    "📋 PC clipboard" to "PC ka clipboard phone pe bhejo", "💻 PC status" to "PC ka status batao",
)

@Composable
fun HomeScreen(onOpenSetup: () -> Unit) {
    val link by AppState.link.collectAsStateWithLifecycle()
    val stopped by Nixin.settings.stopped.collectAsStateWithLifecycle()
    val chat by AppState.chat.collectAsStateWithLifecycle()
    val busy by AppState.busy.collectAsStateWithLifecycle()
    val ctx = LocalContext.current
    var input by remember { mutableStateOf("") }
    var listening by remember { mutableStateOf(false) }
    var partial by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    val listState = rememberLazyListState()
    val connected = link is AppState.Link.Connected

    fun send(text: String, source: String) {
        val t = text.trim()
        if (t.isEmpty()) return
        if (!Nixin.link.sendCommand(t, source)) error = "PC se connected nahi hai" else error = null
    }

    val voice = remember {
        VoiceInput(ctx,
            onPartial = { partial = it },
            onResult = { partial = ""; send(it, "phone_voice") },
            onError = { partial = ""; error = it },
            onListening = { listening = it })
    }
    DisposableEffect(Unit) { onDispose { voice.stop() } }
    val micPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) voice.start(Nixin.settings.voiceLanguage.value) else error = "Microphone permission chahiye"
    }
    fun startVoice() {
        if (ctx.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            voice.start(Nixin.settings.voiceLanguage.value)
        } else micPermission.launch(Manifest.permission.RECORD_AUDIO)
    }

    LaunchedEffect(chat.size) { if (chat.isNotEmpty()) listState.animateScrollToItem(chat.size - 1) }

    val scenes by AppState.scenes.collectAsStateWithLifecycle()
    val recording by AppState.recording.collectAsStateWithLifecycle()

    Column(Modifier.fillMaxSize().imePadding()) {
        StatusCard(link, stopped, onOpenSetup)
        recording?.let { name ->
            Card(
                Modifier.fillMaxWidth().padding(horizontal = 12.dp),
                colors = CardDefaults.cardColors(containerColor = NixinDanger.copy(alpha = 0.18f)),
            ) {
                Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("🔴 Learning “$name” — karke dikhao", Modifier.weight(1f), fontSize = 13.sp)
                    TextButton(onClick = { send("recording cancel karo", "phone_text") }) { Text("Cancel") }
                    Button(onClick = { send("recording save karo", "phone_text") }) { Text("Save") }
                }
            }
        }
        if (connected && !stopped) {
            QuickChips(scenes.map { it.label to it.text } + PC_CHIPS) { send(it, "phone_text") }
        }
        if (busy) LinearProgressIndicator(Modifier.fillMaxWidth().padding(horizontal = 16.dp))

        LazyColumn(
            state = listState,
            modifier = Modifier.weight(1f).fillMaxWidth().padding(horizontal = 12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (chat.isEmpty()) {
                item {
                    Column(Modifier.padding(vertical = 24.dp, horizontal = 8.dp)) {
                        Text("Bolo ya likho — Nixin tumhara phone chalayega.", style = MaterialTheme.typography.titleMedium)
                        Spacer(Modifier.size(8.dp))
                        Text("Try:", color = MaterialTheme.colorScheme.onSurfaceVariant)
                        EXAMPLES.forEach { ex ->
                            TextButton(onClick = { input = ex }) { Text("“$ex”") }
                        }
                    }
                }
            }
            items(chat) { m -> ChatBubble(m) }
        }

        if (listening || partial.isNotEmpty()) {
            Text(if (partial.isEmpty()) "Sun raha hoon…" else partial, color = NixinCyan,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
        }
        error?.let { Text(it, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(horizontal = 16.dp)) }

        Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = input,
                onValueChange = { input = it },
                modifier = Modifier.weight(1f),
                placeholder = { Text("Command likho…") },
                maxLines = 4,
                enabled = connected && !stopped,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = { send(input, "phone_text"); input = "" }),
                shape = RoundedCornerShape(20.dp),
            )
            Spacer(Modifier.size(8.dp))
            if (input.isBlank()) {
                FilledIconButton(
                    onClick = { if (listening) voice.stop() else startVoice() },
                    enabled = connected && !stopped,
                    modifier = Modifier.size(52.dp),
                    colors = IconButtonDefaults.filledIconButtonColors(
                        containerColor = if (listening) NixinDanger else MaterialTheme.colorScheme.primary,
                    ),
                ) { Text(if (listening) "■" else "🎤", fontSize = 20.sp) }
            } else {
                FilledIconButton(onClick = { send(input, "phone_text"); input = "" }, modifier = Modifier.size(52.dp)) {
                    Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "Send")
                }
            }
        }
    }
}

@Composable
private fun QuickChips(items: List<Pair<String, String>>, onClick: (String) -> Unit) {
    LazyRow(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        contentPadding = PaddingValues(horizontal = 12.dp),
    ) {
        items(items) { (label, text) ->
            SuggestionChip(onClick = { onClick(text) }, label = { Text(label, fontSize = 13.sp) })
        }
    }
}

@Composable
private fun StatusCard(link: AppState.Link, stopped: Boolean, onOpenSetup: () -> Unit) {
    val (label, color) = when {
        stopped -> "STOPPED — kill switch on" to NixinDanger
        link is AppState.Link.Connected -> "Connected · ${link.pcName}" to NixinOk
        link is AppState.Link.Connecting -> "Connecting…" to NixinWarn
        link is AppState.Link.Error -> link.message to NixinDanger
        link is AppState.Link.Unpaired -> "Not paired with a PC" to NixinWarn
        else -> "PC offline — retrying" to NixinWarn
    }
    Card(
        Modifier.fillMaxWidth().padding(12.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(12.dp).background(color, CircleShape))
            Spacer(Modifier.size(10.dp))
            Column(Modifier.weight(1f)) {
                Text("Nixin", fontWeight = FontWeight.Bold)
                Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 13.sp, maxLines = 2)
            }
            when {
                stopped -> Button(onClick = { Nixin.resume() }) { Text("Resume") }
                link is AppState.Link.Unpaired || link is AppState.Link.Error -> Button(onClick = onOpenSetup) { Text("Setup") }
                else -> Button(
                    onClick = { Nixin.stop("app") },
                    colors = ButtonDefaults.buttonColors(containerColor = NixinDanger, contentColor = Color.White),
                ) { Text("STOP") }
            }
        }
    }
}

@Composable
private fun ChatBubble(m: AppState.ChatMessage) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (m.fromUser) Arrangement.End else Arrangement.Start) {
        Box(
            Modifier
                .widthIn(max = 300.dp)
                .background(
                    if (m.fromUser) MaterialTheme.colorScheme.primary.copy(alpha = 0.85f) else MaterialTheme.colorScheme.surfaceVariant,
                    RoundedCornerShape(16.dp),
                )
                .padding(horizontal = 12.dp, vertical = 8.dp),
        ) {
            Text(m.text, color = if (m.fromUser) Color.White else MaterialTheme.colorScheme.onSurface)
        }
    }
}
