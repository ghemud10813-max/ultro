package com.letvler.nixin.ui

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import com.letvler.nixin.Nixin
import com.letvler.nixin.core.AppState
import com.letvler.nixin.link.KeyManager

private data class PermRow(val key: String, val title: String, val why: String, val required: Boolean)

private val ROWS = listOf(
    PermRow("accessibility", "Accessibility (phone control)", "Read the screen, tap, type, scroll. Required for apps & agent tasks.", true),
    PermRow("batteryUnrestricted", "Battery: Unrestricted", "Keeps the PC connection alive with the screen off (Samsung!).", true),
    PermRow("postNotifications", "Notifications", "Shows the connection + STOP button and confirmation prompts.", true),
    PermRow("notifications", "Notification access", "\"Latest notification padh ke bata\". OTPs are masked.", false),
    PermRow("contacts", "Contacts", "Find \"Rahul\" when you ask to message or call.", false),
    PermRow("call", "Phone calls", "Place calls directly (otherwise the dialer opens).", false),
    PermRow("sms", "SMS", "Send SMS directly (otherwise the composer opens).", false),
    PermRow("microphone", "Microphone", "Talk to Nixin from the phone.", false),
    PermRow("writeSettings", "Modify system settings", "Screen brightness.", false),
    PermRow("dnd", "Do Not Disturb access", "DND and silent mode.", false),
    PermRow("location", "Location", "\"Mera phone kahan hai?\" and weather for your area.", false),
    PermRow("backgroundLocation", "Location: Allow all the time", "Lets the PC find the phone while Nixin is in the background.", false),
    PermRow("usage", "Usage access", "Screen time: \"aaj maine phone kitna chalaya?\"", false),
    PermRow("answerCalls", "Answer calls", "\"Call utha lo / kaat do\".", false),
)

@SuppressLint("BatteryLife")
@Composable
fun SetupScreen() {
    val ctx = LocalContext.current
    val activity = ctx as? ComponentActivity
    val paired by Nixin.settings.paired.collectAsStateWithLifecycle()
    val link by AppState.link.collectAsStateWithLifecycle()
    var refresh by remember { mutableIntStateOf(0) }
    var paste by remember { mutableStateOf("") }

    val owner = LocalLifecycleOwner.current
    DisposableEffect(owner) {
        val obs = LifecycleEventObserver { _, e -> if (e == Lifecycle.Event.ON_RESUME) refresh++ }
        owner.lifecycle.addObserver(obs)
        onDispose { owner.lifecycle.removeObserver(obs) }
    }
    val perms = remember(refresh) { Nixin.device.permissions() }

    val scanner = rememberLauncherForActivityResult(ScanContract()) { res ->
        res.contents?.let { if (activity != null) MainActivity.startPairing(activity, it) }
    }
    val runtime = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { refresh++ }

    fun open(intent: Intent) {
        runCatching { ctx.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
    }

    fun grant(key: String) {
        when (key) {
            "accessibility" -> open(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
            "batteryUnrestricted" -> open(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${ctx.packageName}")))
            "postNotifications" -> if (Build.VERSION.SDK_INT >= 33) runtime.launch(arrayOf(Manifest.permission.POST_NOTIFICATIONS))
            "notifications" -> open(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
            "contacts" -> runtime.launch(arrayOf(Manifest.permission.READ_CONTACTS))
            "call" -> runtime.launch(arrayOf(Manifest.permission.CALL_PHONE))
            "sms" -> runtime.launch(arrayOf(Manifest.permission.SEND_SMS))
            "microphone" -> runtime.launch(arrayOf(Manifest.permission.RECORD_AUDIO))
            "writeSettings" -> open(Intent(Settings.ACTION_MANAGE_WRITE_SETTINGS, Uri.parse("package:${ctx.packageName}")))
            "dnd" -> open(Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS))
            "location" -> runtime.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
            "backgroundLocation" -> runtime.launch(arrayOf(Manifest.permission.ACCESS_BACKGROUND_LOCATION))
            "usage" -> open(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS))
            "answerCalls" -> runtime.launch(arrayOf(Manifest.permission.ANSWER_PHONE_CALLS))
        }
    }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("1 · Pair with your PC", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                val p = paired
                if (p != null) {
                    Text("Paired with ${p.pcName}", fontWeight = FontWeight.SemiBold)
                    Text(p.endpoints.joinToString("\n"), fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text("Status: " + when (val l = link) {
                        is AppState.Link.Connected -> "connected"
                        is AppState.Link.Connecting -> "connecting…"
                        is AppState.Link.Error -> l.message
                        else -> "offline"
                    }, fontSize = 13.sp)
                } else {
                    Text("On the PC run `nixin run`, then scan the QR it shows (or open the dashboard → Pair).", fontSize = 13.sp)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = {
                        scanner.launch(ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                            .setPrompt("Scan the Nixin pairing QR").setBeepEnabled(false).setOrientationLocked(false))
                    }) { Text(if (p == null) "Scan QR" else "Re-pair") }
                    if (p != null) {
                        OutlinedButton(onClick = { Nixin.link.reconnectNow() }) { Text("Reconnect") }
                    }
                }
                OutlinedTextField(
                    value = paste, onValueChange = { paste = it }, modifier = Modifier.fillMaxWidth(),
                    label = { Text("…or paste the nixin://pair link") }, singleLine = true,
                )
                if (paste.isNotBlank()) {
                    Button(onClick = { activity?.let { MainActivity.startPairing(it, paste) }; paste = "" }) { Text("Pair") }
                }
                if (p != null) {
                    TextButton(onClick = {
                        Nixin.link.stop()
                        Nixin.settings.forgetPc()
                        KeyManager.reset()
                    }) { Text("Forget this PC", color = MaterialTheme.colorScheme.error) }
                }
            }
        }

        Text("2 · Permissions", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        ROWS.forEach { row ->
            val ok = perms[row.key] == true
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(if (ok) "✅" else if (row.required) "⚠️" else "○", fontSize = 18.sp)
                    Spacer(Modifier.size(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(row.title + if (row.required) "" else "  (optional)", fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                        Text(row.why, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    if (!ok) TextButton(onClick = { grant(row.key) }) { Text("Allow") }
                }
            }
        }
        Text(
            "Samsung tip: Settings → Apps → Nixin → Battery → Unrestricted, and remove Nixin from " +
                "\"Sleeping/Deep sleeping apps\". Accessibility may show under \"Installed apps\".",
            fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
