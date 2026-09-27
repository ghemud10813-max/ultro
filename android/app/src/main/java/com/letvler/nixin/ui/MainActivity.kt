package com.letvler.nixin.ui

import android.Manifest
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.mutableStateOf
import com.letvler.nixin.Nixin
import com.letvler.nixin.link.PairingPayload

class MainActivity : ComponentActivity() {

    /** Tab to open (set by deep links). */
    private val startTab = mutableStateOf(Tab.Home)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (Build.VERSION.SDK_INT >= 33) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        if (Nixin.settings.paired.value != null) Nixin.startService(this)
        handleIntent(intent)
        setContent {
            NixinTheme {
                NixinRoot(startTab)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        val data = intent?.data ?: return
        if (data.scheme == "nixin" && data.host == "pair") {
            startPairing(this, data.toString())
            startTab.value = Tab.Home
        }
    }

    companion object {
        /** Shared by the QR scanner, the deep link and the paste box. */
        fun startPairing(activity: ComponentActivity, raw: String) {
            val payload = runCatching { PairingPayload.parse(raw) }.getOrElse {
                Toast.makeText(activity, "Invalid pairing code: ${it.message}", Toast.LENGTH_LONG).show()
                return
            }
            if (payload.expired) {
                Toast.makeText(activity, "This pairing QR has expired — create a new one on the PC", Toast.LENGTH_LONG).show()
                return
            }
            Nixin.startService(activity)
            Nixin.link.pair(payload)
            Toast.makeText(activity, "Pairing with ${payload.pcName}…", Toast.LENGTH_SHORT).show()
        }
    }
}
