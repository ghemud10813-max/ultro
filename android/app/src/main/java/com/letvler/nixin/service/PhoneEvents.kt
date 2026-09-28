package com.letvler.nixin.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import com.letvler.nixin.Nixin
import com.letvler.nixin.core.jsonOf

/**
 * Phone events for routines on the PC ("jab battery 20% se kam ho…", "jab charger lage…"):
 * battery (on 5% steps, every 1% below 30%), charger in/out, screen on/off/unlocked, Wi-Fi.
 * Can be switched off in Settings → "Send phone events".
 */
class PhoneEvents(private val ctx: Context) : BroadcastReceiver() {
    private var lastLevel = -1
    private var lastCharging: Boolean? = null
    private var lastWifi: Boolean? = null

    fun register() {
        val f = IntentFilter().apply {
            addAction(Intent.ACTION_BATTERY_CHANGED)
            addAction(Intent.ACTION_POWER_CONNECTED)
            addAction(Intent.ACTION_POWER_DISCONNECTED)
            addAction(Intent.ACTION_SCREEN_ON)
            addAction(Intent.ACTION_SCREEN_OFF)
            addAction(Intent.ACTION_USER_PRESENT)
        }
        // protected system broadcasts: no export flag needed, but be explicit on 33+
        ctx.registerReceiver(this, f, Context.RECEIVER_NOT_EXPORTED)
    }

    fun unregister() {
        runCatching { ctx.unregisterReceiver(this) }
    }

    private fun send(name: String, vararg data: Pair<String, Any?>) {
        if (Nixin.settings.phoneEvents.value) Nixin.link.sendEvent(name, jsonOf(*data))
    }

    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            Intent.ACTION_BATTERY_CHANGED -> {
                val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, 100).coerceAtLeast(1)
                val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) * 100 / scale
                val charging = intent.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) != 0
                if (level < 0) return
                val step = if (level <= 30) 1 else 5
                val changed = lastLevel < 0 || kotlin.math.abs(level - lastLevel) >= step || charging != lastCharging ||
                    (level == 100 && lastLevel != 100)
                if (changed) {
                    lastLevel = level
                    lastCharging = charging
                    send("battery", "level" to level, "charging" to charging)
                }
            }
            Intent.ACTION_POWER_CONNECTED -> send("power", "plugged" to true, "level" to lastLevel.takeIf { it >= 0 })
            Intent.ACTION_POWER_DISCONNECTED -> send("power", "plugged" to false, "level" to lastLevel.takeIf { it >= 0 })
            Intent.ACTION_SCREEN_ON -> send("screen", "state" to "on")
            Intent.ACTION_SCREEN_OFF -> send("screen", "state" to "off")
            Intent.ACTION_USER_PRESENT -> send("screen", "state" to "unlocked")
        }
    }

    fun onNetworkChanged() {
        val cm = ctx.getSystemService(ConnectivityManager::class.java)
        val wifi = cm.getNetworkCapabilities(cm.activeNetwork)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true
        if (wifi == lastWifi) return
        lastWifi = wifi
        send("network", "wifi" to wifi, "ssid" to if (wifi) Nixin.extras.wifiSsid() else null)
    }
}
