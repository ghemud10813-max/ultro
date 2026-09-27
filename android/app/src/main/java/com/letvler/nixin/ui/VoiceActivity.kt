package com.letvler.nixin.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.letvler.nixin.Nixin
import com.letvler.nixin.core.AppState
import com.letvler.nixin.voice.VoiceInput
import kotlinx.coroutines.delay

/** Floating "listening" card started from the Quick Settings tile or the notification's Talk button. */
class VoiceActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 7)
        }
        setContent {
            NixinTheme {
                var status by remember { mutableStateOf("Bolo…") }
                var listening by remember { mutableStateOf(false) }
                var done by remember { mutableStateOf(false) }
                val chat by AppState.chat.collectAsStateWithLifecycle()
                val sentAt = remember { mutableIntStateOf(0) }
                val voice = remember {
                    VoiceInput(this,
                        onPartial = { status = it },
                        onResult = { text ->
                            status = "“$text”"
                            if (!Nixin.link.sendCommand(text, "phone_voice")) status = "PC se connected nahi hai"
                            sentAt.value = AppState.chat.value.size
                            done = true
                        },
                        onError = { status = it; done = true },
                        onListening = { listening = it })
                }
                LaunchedEffect(Unit) {
                    delay(250)
                    voice.start(Nixin.settings.voiceLanguage.value)
                }
                LaunchedEffect(done, chat.size) {
                    if (done) {
                        // show Nixin's reply briefly, then close
                        val reply = chat.lastOrNull()?.takeIf { !it.fromUser }
                        if (reply != null && chat.size > sentAt.value) status = reply.text
                        delay(if (reply != null) 3500 else 6000)
                        finish()
                    }
                }
                DisposableEffect(Unit) { onDispose { voice.stop() } }
                Box(Modifier.fillMaxSize().clickable { finish() }, contentAlignment = Alignment.BottomCenter) {
                    Column(
                        Modifier.fillMaxWidth().padding(16.dp)
                            .background(MaterialTheme.colorScheme.surface, RoundedCornerShape(24.dp))
                            .padding(24.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(14.dp),
                    ) {
                        Box(
                            Modifier.size(72.dp).background(if (listening) NixinDanger else NixinPurple, CircleShape)
                                .clickable { if (listening) voice.stop() else voice.start(Nixin.settings.voiceLanguage.value) },
                            contentAlignment = Alignment.Center,
                        ) { Text("🎤", fontSize = 30.sp) }
                        Text(status, textAlign = TextAlign.Center, style = MaterialTheme.typography.titleMedium)
                        Text("Nixin", color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 12.sp)
                    }
                }
            }
        }
    }
}
