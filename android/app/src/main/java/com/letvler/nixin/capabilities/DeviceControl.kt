package com.letvler.nixin.capabilities

import android.Manifest
import android.app.KeyguardManager
import android.app.NotificationManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.BatteryManager
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import android.view.KeyEvent
import com.letvler.nixin.BuildConfig
import com.letvler.nixin.Nixin
import com.letvler.nixin.a11y.NixinAccessibilityService
import com.letvler.nixin.a11y.UiController
import com.letvler.nixin.core.ErrorCode
import com.letvler.nixin.core.bool
import com.letvler.nixin.core.fail
import com.letvler.nixin.core.int
import com.letvler.nixin.core.jsonOf
import com.letvler.nixin.core.reqBool
import com.letvler.nixin.core.reqStr
import com.letvler.nixin.core.str
import com.letvler.nixin.service.NotificationWatcher
import kotlinx.serialization.json.JsonObject
import kotlin.math.roundToInt

/** Native, deterministic controls — no screen reading involved. */
class DeviceControl(private val ctx: Context) {
    private val audio = ctx.getSystemService(AudioManager::class.java)
    private val camera = ctx.getSystemService(CameraManager::class.java)
    private val nm = ctx.getSystemService(NotificationManager::class.java)

    @Volatile private var torchOn: Boolean? = null

    init {
        runCatching {
            camera.registerTorchCallback(object : CameraManager.TorchCallback() {
                override fun onTorchModeChanged(cameraId: String, enabled: Boolean) { torchOn = enabled }
            }, null)
        }
    }

    private fun granted(p: String) = ctx.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED

    // ------------------------------------------------------------------ status
    fun permissions(): Map<String, Boolean> {
        val pm = ctx.getSystemService(PowerManager::class.java)
        return mapOf(
            "accessibility" to (NixinAccessibilityService.instance != null),
            "notifications" to notificationAccess(),
            "contacts" to granted(Manifest.permission.READ_CONTACTS),
            "call" to granted(Manifest.permission.CALL_PHONE),
            "sms" to granted(Manifest.permission.SEND_SMS),
            "microphone" to granted(Manifest.permission.RECORD_AUDIO),
            "writeSettings" to Settings.System.canWrite(ctx),
            "dnd" to nm.isNotificationPolicyAccessGranted,
            "postNotifications" to (Build.VERSION.SDK_INT < 33 || granted(Manifest.permission.POST_NOTIFICATIONS)),
            "batteryUnrestricted" to pm.isIgnoringBatteryOptimizations(ctx.packageName),
            "location" to (granted(Manifest.permission.ACCESS_FINE_LOCATION) || granted(Manifest.permission.ACCESS_COARSE_LOCATION)),
            "backgroundLocation" to granted(Manifest.permission.ACCESS_BACKGROUND_LOCATION),
            "usage" to usageAccess(),
            "answerCalls" to granted(Manifest.permission.ANSWER_PHONE_CALLS),
        )
    }

    fun usageAccess(): Boolean {
        val aom = ctx.getSystemService(android.app.AppOpsManager::class.java)
        return aom.unsafeCheckOpNoThrow(android.app.AppOpsManager.OPSTR_GET_USAGE_STATS, android.os.Process.myUid(), ctx.packageName) ==
            android.app.AppOpsManager.MODE_ALLOWED
    }

    fun notificationAccess(): Boolean {
        val flat = Settings.Secure.getString(ctx.contentResolver, "enabled_notification_listeners") ?: return false
        val me = ComponentName(ctx, NotificationWatcher::class.java).flattenToString()
        return flat.split(":").any { it == me }
    }

    fun status(): JsonObject {
        val battery = ctx.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = ctx.getSystemService(BatteryManager::class.java).getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        val plugged = (battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0) != 0
        val pm = ctx.getSystemService(PowerManager::class.java)
        val km = ctx.getSystemService(KeyguardManager::class.java)
        val cm = ctx.getSystemService(ConnectivityManager::class.java)
        val caps = cm.getNetworkCapabilities(cm.activeNetwork)
        val fg = NixinAccessibilityService.instance?.currentPackage()
        val volumes = STREAMS.mapValues { (_, s) -> mapOf("level" to audio.getStreamVolume(s), "max" to audio.getStreamMaxVolume(s)) }
        return jsonOf(
            "battery" to mapOf("level" to level, "charging" to plugged),
            "volume" to volumes,
            "ringer" to when (audio.ringerMode) {
                AudioManager.RINGER_MODE_SILENT -> "silent"
                AudioManager.RINGER_MODE_VIBRATE -> "vibrate"
                else -> "normal"
            },
            "torch" to torchOn,
            "screenOn" to pm.isInteractive,
            "locked" to km.isKeyguardLocked,
            "foreground" to mapOf("package" to fg, "label" to Nixin.appLabel(fg)),
            "network" to mapOf(
                "wifi" to (caps?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true),
                "cellular" to (caps?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) == true),
            ),
            "dnd" to (nm.currentInterruptionFilter != NotificationManager.INTERRUPTION_FILTER_ALL),
            "stopped" to Nixin.settings.stopped.value,
            "permissions" to permissions(),
            "settings" to mapOf(
                "allowScreenshots" to Nixin.settings.allowScreenshots.value,
                "speakReplies" to Nixin.settings.speakReplies.value,
                "mirrorNotifications" to Nixin.settings.mirrorNotifications.value,
                "phoneEvents" to Nixin.settings.phoneEvents.value,
            ),
            "device" to mapOf(
                "model" to Build.MODEL, "manufacturer" to Build.MANUFACTURER, "sdk" to Build.VERSION.SDK_INT,
                "appVersion" to BuildConfig.VERSION_NAME,
            ),
        )
    }

    // ------------------------------------------------------------------ volume
    fun volume(p: JsonObject): JsonObject {
        val streamName = p.str("stream") ?: "media"
        val stream = STREAMS[streamName] ?: fail(ErrorCode.BAD_REQUEST, "Unknown stream $streamName")
        val flags = if (p.bool("showUi") == true) AudioManager.FLAG_SHOW_UI else 0
        val max = audio.getStreamMaxVolume(stream)
        val prev = audio.getStreamVolume(stream)
        try {
            when (val action = p.reqStr("action")) {
                "up", "down" -> {
                    val dir = if (action == "up") AudioManager.ADJUST_RAISE else AudioManager.ADJUST_LOWER
                    repeat((p.int("steps") ?: 1).coerceIn(1, 15)) { audio.adjustStreamVolume(stream, dir, flags) }
                }
                "set" -> audio.setStreamVolume(stream, ((p.int("percent") ?: 50).coerceIn(0, 100) * max / 100.0).roundToInt(), flags)
                "max" -> audio.setStreamVolume(stream, max, flags)
                "mute" -> audio.adjustStreamVolume(stream, AudioManager.ADJUST_MUTE, flags)
                "unmute" -> audio.adjustStreamVolume(stream, AudioManager.ADJUST_UNMUTE, flags)
                else -> fail(ErrorCode.BAD_REQUEST, "Unknown action $action")
            }
        } catch (e: SecurityException) {
            fail(ErrorCode.PERM_DND, "Android blocks this volume change while Do Not Disturb is on; grant DND access")
        }
        return jsonOf("stream" to streamName, "previous" to prev, "current" to audio.getStreamVolume(stream), "max" to max)
    }

    // ------------------------------------------------------------------ torch
    fun torch(p: JsonObject): JsonObject {
        val on = p.reqBool("on")
        val id = camera.cameraIdList.firstOrNull { id ->
            val c = camera.getCameraCharacteristics(id)
            c.get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true &&
                c.get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_BACK
        } ?: camera.cameraIdList.firstOrNull { camera.getCameraCharacteristics(it).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true }
        ?: fail(ErrorCode.UNSUPPORTED, "This phone has no flashlight")
        try {
            camera.setTorchMode(id, on)
        } catch (e: Exception) {
            fail(ErrorCode.FAILED, "Flashlight busy (camera in use?)")
        }
        torchOn = on
        return jsonOf("on" to on)
    }

    // ------------------------------------------------------------------ brightness
    fun brightness(p: JsonObject): JsonObject {
        if (!Settings.System.canWrite(ctx)) fail(ErrorCode.PERM_WRITE_SETTINGS, "Allow Nixin to modify system settings")
        val cr = ctx.contentResolver
        val prev = Settings.System.getInt(cr, Settings.System.SCREEN_BRIGHTNESS, 128)
        val prevPct = (prev * 100 / 255.0).roundToInt()
        return when (p.reqStr("action")) {
            "auto" -> {
                Settings.System.putInt(cr, Settings.System.SCREEN_BRIGHTNESS_MODE, Settings.System.SCREEN_BRIGHTNESS_MODE_AUTOMATIC)
                jsonOf("previous" to prevPct, "current" to prevPct, "auto" to true)
            }
            else -> {
                val target = when (p.reqStr("action")) {
                    "set" -> (p.int("percent") ?: 50)
                    "up" -> prevPct + 20
                    else -> prevPct - 20
                }.coerceIn(1, 100)
                Settings.System.putInt(cr, Settings.System.SCREEN_BRIGHTNESS_MODE, Settings.System.SCREEN_BRIGHTNESS_MODE_MANUAL)
                Settings.System.putInt(cr, Settings.System.SCREEN_BRIGHTNESS, (target * 255 / 100.0).roundToInt())
                jsonOf("previous" to prevPct, "current" to target, "auto" to false)
            }
        }
    }

    // ------------------------------------------------------------------ ringer / DND
    fun ringer(p: JsonObject): JsonObject {
        val mode = p.reqStr("mode")
        try {
            audio.ringerMode = when (mode) {
                "silent" -> AudioManager.RINGER_MODE_SILENT
                "vibrate" -> AudioManager.RINGER_MODE_VIBRATE
                else -> AudioManager.RINGER_MODE_NORMAL
            }
        } catch (e: SecurityException) {
            fail(ErrorCode.PERM_DND, "Grant Do Not Disturb access to change silent mode")
        }
        return jsonOf("mode" to mode)
    }

    fun dnd(p: JsonObject): JsonObject {
        if (!nm.isNotificationPolicyAccessGranted) fail(ErrorCode.PERM_DND, "Grant Do Not Disturb access")
        val on = p.reqBool("on")
        nm.setInterruptionFilter(if (on) NotificationManager.INTERRUPTION_FILTER_PRIORITY else NotificationManager.INTERRUPTION_FILTER_ALL)
        return jsonOf("on" to on)
    }

    // ------------------------------------------------------------------ navigation
    fun global(p: JsonObject): JsonObject {
        val action = p.reqStr("action")
        if (NixinAccessibilityService.instance == null && action == "home") {
            Launcher.start(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME))
            return jsonOf("action" to action)
        }
        if (!UiController.global(action)) fail(ErrorCode.FAILED, "Android refused $action")
        UiController.invalidate()
        return jsonOf("action" to action)
    }

    fun settingsPanel(p: JsonObject): JsonObject {
        val panel = p.reqStr("panel")
        val intent = when (panel) {
            "wifi" -> Intent(Settings.Panel.ACTION_WIFI)
            "internet", "mobile_data" -> Intent(Settings.Panel.ACTION_INTERNET_CONNECTIVITY)
            "nfc" -> Intent(Settings.Panel.ACTION_NFC)
            "volume" -> Intent(Settings.Panel.ACTION_VOLUME)
            "bluetooth" -> Intent(Settings.ACTION_BLUETOOTH_SETTINGS)
            "display" -> Intent(Settings.ACTION_DISPLAY_SETTINGS)
            "battery" -> Intent(Intent.ACTION_POWER_USAGE_SUMMARY)
            "location" -> Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS)
            "sound" -> Intent(Settings.ACTION_SOUND_SETTINGS)
            "apps" -> Intent(Settings.ACTION_APPLICATION_SETTINGS)
            "accessibility" -> Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
            "notification_access" -> Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)
            "write_settings" -> Intent(Settings.ACTION_MANAGE_WRITE_SETTINGS, Uri.parse("package:${ctx.packageName}"))
            "dnd_access" -> Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS)
            "hotspot" -> Intent("android.settings.TETHER_SETTINGS")
            "airplane" -> Intent(Settings.ACTION_AIRPLANE_MODE_SETTINGS)
            else -> Intent(Settings.ACTION_SETTINGS)
        }
        if (!Launcher.start(intent)) {
            if (!Launcher.start(Intent(Settings.ACTION_WIRELESS_SETTINGS))) fail(ErrorCode.FAILED, "Could not open settings")
        }
        UiController.invalidate()
        return jsonOf("opened" to panel)
    }

    fun media(p: JsonObject): JsonObject {
        val action = p.reqStr("action")
        val code = when (action) {
            "play" -> KeyEvent.KEYCODE_MEDIA_PLAY
            "pause" -> KeyEvent.KEYCODE_MEDIA_PAUSE
            "toggle" -> KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE
            "next" -> KeyEvent.KEYCODE_MEDIA_NEXT
            "previous" -> KeyEvent.KEYCODE_MEDIA_PREVIOUS
            "stop" -> KeyEvent.KEYCODE_MEDIA_STOP
            else -> fail(ErrorCode.BAD_REQUEST, "Unknown media action $action")
        }
        audio.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, code))
        audio.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_UP, code))
        return jsonOf("action" to action)
    }

    companion object {
        val STREAMS = mapOf(
            "media" to AudioManager.STREAM_MUSIC,
            "ring" to AudioManager.STREAM_RING,
            "alarm" to AudioManager.STREAM_ALARM,
            "notification" to AudioManager.STREAM_NOTIFICATION,
            "call" to AudioManager.STREAM_VOICE_CALL,
        )
    }
}
