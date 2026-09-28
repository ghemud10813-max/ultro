package com.letvler.nixin.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.letvler.nixin.BuildConfig
import com.letvler.nixin.Nixin
import com.letvler.nixin.policy.SafetyRules

@Composable
fun SettingsScreen() {
    val s = Nixin.settings
    val screenshots by s.allowScreenshots.collectAsStateWithLifecycle()
    val speak by s.speakReplies.collectAsStateWithLifecycle()
    val lang by s.voiceLanguage.collectAsStateWithLifecycle()
    val autoStart by s.autoStart.collectAsStateWithLifecycle()
    val mirror by s.mirrorNotifications.collectAsStateWithLifecycle()
    val events by s.phoneEvents.collectAsStateWithLifecycle()
    val extra by s.extraBlocked.collectAsStateWithLifecycle()
    var newBlocked by remember { mutableStateOf("") }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("Settings", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)

        Toggle("Allow screenshots", "Needed for the dashboard's live mirror and for the agent's vision fallback. " +
            "Screenshots go only to your PC; blocked apps and secure screens are never captured.", screenshots) {
            s.setAllowScreenshots(it)
            Nixin.link.sendStatus()
        }
        Toggle("Speak replies on the phone", "Nixin reads its answers aloud when you talk to it from the phone.", speak) {
            s.setSpeakReplies(it)
        }
        Toggle("Connect automatically after reboot", "Starts the PC link when the phone boots.", autoStart) {
            s.setAutoStart(it)
        }
        Toggle("Mirror notifications to the PC", "New notifications (and incoming-call names) appear live on the PC " +
            "dashboard, can be announced there and replied to. OTP-like codes stay masked; blocked apps are never sent.", mirror) {
            s.setMirrorNotifications(it)
            Nixin.link.sendStatus()
        }
        Toggle("Send phone events", "Battery, charger, screen and Wi-Fi changes, so routines on the PC can react " +
            "(\"jab battery 20% se kam ho to bata dena\").", events) {
            s.setPhoneEvents(it)
        }

        Text("Voice language (phone microphone)", fontWeight = FontWeight.SemiBold)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("en-IN" to "Hinglish / English", "hi-IN" to "Hindi").forEach { (tag, label) ->
                FilterChip(selected = lang == tag, onClick = { s.setVoiceLanguage(tag) }, label = { Text(label) })
            }
        }

        Text("Blocked apps", fontWeight = FontWeight.SemiBold)
        Text("${SafetyRules.BUILTIN_BLOCKED.size} banking, UPI, wallet, password and authenticator apps are always " +
            "blocked (plus any package whose name contains bank/upi/wallet/pay…). Add more below:",
            fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        extra.sorted().forEach { pkg ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(pkg, modifier = Modifier.weight(1f), fontSize = 13.sp)
                Button(onClick = { s.setExtraBlocked(extra - pkg) }) { Text("Remove") }
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(newBlocked, { newBlocked = it.trim() }, Modifier.weight(1f),
                label = { Text("package, e.g. com.example.app") }, singleLine = true)
            Button(onClick = {
                if (newBlocked.contains('.')) s.setExtraBlocked(extra + newBlocked)
                newBlocked = ""
            }, modifier = Modifier.padding(start = 8.dp)) { Text("Add") }
        }

        Text("Nixin ${BuildConfig.VERSION_NAME} · device ${s.deviceId.take(8)}", fontSize = 12.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun Toggle(title: String, subtitle: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f).padding(end = 12.dp)) {
            Text(title, fontWeight = FontWeight.SemiBold)
            Text(subtitle, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Switch(checked = checked, onCheckedChange = onChange)
    }
}
