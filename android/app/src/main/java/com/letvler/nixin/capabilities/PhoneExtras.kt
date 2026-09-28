package com.letvler.nixin.capabilities

import android.Manifest
import android.annotation.SuppressLint
import android.app.ActivityManager
import android.app.AppOpsManager
import android.app.Notification
import android.app.NotificationManager
import android.app.WallpaperManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.location.Location
import android.location.LocationManager
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.MediaMetadata
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.BatteryManager
import android.os.Build
import android.os.CancellationSignal
import android.os.Environment
import android.os.Process
import android.os.StatFs
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.provider.Settings
import android.telecom.TelecomManager
import android.util.Base64
import com.letvler.nixin.Nixin
import com.letvler.nixin.R
import com.letvler.nixin.a11y.NixinAccessibilityService
import com.letvler.nixin.a11y.UiController
import com.letvler.nixin.core.ErrorCode
import com.letvler.nixin.core.bool
import com.letvler.nixin.core.fail
import com.letvler.nixin.core.int
import com.letvler.nixin.core.jsonOf
import com.letvler.nixin.core.reqStr
import com.letvler.nixin.core.str
import com.letvler.nixin.service.ActionReceiver
import com.letvler.nixin.service.NotificationWatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.intOrNull
import java.util.Calendar
import java.util.concurrent.atomic.AtomicInteger
import kotlin.coroutines.resume

/**
 * Nixin 2.0 native controls: find-my-phone, location, system settings, wallpaper, clipboard,
 * now playing, call control, screen time and device info. All deterministic, no screen reading
 * (except the on-screen fallback for ending a call on phones that block the telecom API).
 */
class PhoneExtras(private val ctx: Context) {
    private val audio = ctx.getSystemService(AudioManager::class.java)
    private val notifIds = AtomicInteger(3000)

    private fun granted(p: String) = ctx.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED

    // ------------------------------------------------------------------ device.info
    @SuppressLint("MissingPermission")
    fun info(): JsonObject {
        val stat = StatFs(Environment.getDataDirectory().path)
        val am = ctx.getSystemService(ActivityManager::class.java)
        val mem = ActivityManager.MemoryInfo().also { am.getMemoryInfo(it) }
        val battery = ctx.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = ctx.getSystemService(BatteryManager::class.java).getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        val health = when (battery?.getIntExtra(BatteryManager.EXTRA_HEALTH, 0)) {
            BatteryManager.BATTERY_HEALTH_GOOD -> "good"
            BatteryManager.BATTERY_HEALTH_OVERHEAT -> "overheating"
            BatteryManager.BATTERY_HEALTH_DEAD -> "dead"
            BatteryManager.BATTERY_HEALTH_OVER_VOLTAGE -> "over voltage"
            BatteryManager.BATTERY_HEALTH_COLD -> "cold"
            else -> "unknown"
        }
        val temp = (battery?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1) ?: -1).takeIf { it > 0 }?.let { it / 10.0 }
        val plugged = (battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0) != 0
        val cm = ctx.getSystemService(ConnectivityManager::class.java)
        val caps = cm.getNetworkCapabilities(cm.activeNetwork)
        val type = when {
            caps == null -> "none"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
            else -> "other"
        }
        val cr = ctx.contentResolver
        return jsonOf(
            "manufacturer" to Build.MANUFACTURER, "model" to Build.MODEL, "android" to Build.VERSION.RELEASE,
            "sdk" to Build.VERSION.SDK_INT,
            "storage" to mapOf("freeBytes" to stat.availableBytes, "totalBytes" to stat.totalBytes),
            "ram" to mapOf("availBytes" to mem.availMem, "totalBytes" to mem.totalMem, "low" to mem.lowMemory),
            "uptimeMs" to SystemClock.elapsedRealtime(),
            "battery" to mapOf("level" to level, "health" to health, "temperatureC" to temp, "charging" to plugged),
            "network" to mapOf("type" to type, "ssid" to if (type == "wifi") wifiSsid() else null),
            "screen" to mapOf(
                "timeoutMs" to Settings.System.getInt(cr, Settings.System.SCREEN_OFF_TIMEOUT, -1),
                "autoRotate" to (Settings.System.getInt(cr, Settings.System.ACCELEROMETER_ROTATION, 0) == 1),
            ),
        )
    }

    /** SSID needs location permission on modern Android; null when unavailable. */
    @SuppressLint("MissingPermission")
    fun wifiSsid(): String? = runCatching {
        @Suppress("DEPRECATION")
        val raw = ctx.getSystemService(WifiManager::class.java).connectionInfo?.ssid
        raw?.trim('"')?.takeIf { it.isNotBlank() && it != "<unknown ssid>" }
    }.getOrNull()

    // ------------------------------------------------------------------ device.ring (find my phone)
    @Volatile private var ringJob: Job? = null
    @Volatile private var player: MediaPlayer? = null
    @Volatile private var restoreAlarmVolume: Int? = null

    fun ring(p: JsonObject): JsonObject {
        if (p.bool("stop") == true) {
            stopRing()
            return jsonOf("ringing" to false)
        }
        val seconds = (p.int("seconds") ?: 30).coerceIn(3, 120)
        stopRing()
        restoreAlarmVolume = audio.getStreamVolume(AudioManager.STREAM_ALARM)
        runCatching { audio.setStreamVolume(AudioManager.STREAM_ALARM, audio.getStreamMaxVolume(AudioManager.STREAM_ALARM), 0) }
        val uri = RingtoneManager.getActualDefaultRingtoneUri(ctx, RingtoneManager.TYPE_ALARM)
            ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
        player = runCatching {
            MediaPlayer().apply {
                // the alarm stream plays even when the phone is on silent / vibrate
                setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
                setDataSource(ctx, uri)
                isLooping = true
                prepare()
                start()
            }
        }.getOrNull()
        showRingNotification()
        ringJob = Nixin.scope.launch {
            val end = System.currentTimeMillis() + seconds * 1000L
            var torch = false
            while (isActive && System.currentTimeMillis() < end) {
                runCatching { vibrator().vibrate(VibrationEffect.createOneShot(400, VibrationEffect.DEFAULT_AMPLITUDE)) }
                torch = !torch
                runCatching { Nixin.device.torch(jsonOf("on" to torch)) }
                delay(600)
            }
            stopRing()
        }
        return jsonOf("ringing" to true, "seconds" to seconds, "sound" to (player != null))
    }

    fun stopRing() {
        ringJob?.cancel()
        ringJob = null
        player?.let { runCatching { it.stop(); it.release() } }
        player = null
        restoreAlarmVolume?.let { runCatching { audio.setStreamVolume(AudioManager.STREAM_ALARM, it, 0) } }
        restoreAlarmVolume = null
        runCatching { Nixin.device.torch(jsonOf("on" to false)) }
        runCatching { ctx.getSystemService(NotificationManager::class.java).cancel(Nixin.NOTIF_RING) }
    }

    private fun showRingNotification() {
        val n = Notification.Builder(ctx, Nixin.CHANNEL_ALERTS)
            .setSmallIcon(R.drawable.ic_stat_nixin)
            .setContentTitle("Nixin: finding your phone")
            .setContentText("Tap Stop when you've found it")
            .setCategory(Notification.CATEGORY_ALARM)
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null, "Stop", ActionReceiver.stopRingIntent(ctx)).build())
            .build()
        runCatching { ctx.getSystemService(NotificationManager::class.java).notify(Nixin.NOTIF_RING, n) }
    }

    private fun vibrator(): Vibrator = if (Build.VERSION.SDK_INT >= 31) {
        ctx.getSystemService(VibratorManager::class.java).defaultVibrator
    } else {
        @Suppress("DEPRECATION")
        ctx.getSystemService(Vibrator::class.java)
    }

    fun vibrate(p: JsonObject): JsonObject {
        val ms = (p.int("ms") ?: 500).coerceIn(50, 5000).toLong()
        vibrator().vibrate(VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE))
        return jsonOf("ms" to ms)
    }

    // ------------------------------------------------------------------ device.location
    @SuppressLint("MissingPermission")
    suspend fun location(p: JsonObject): JsonObject {
        if (!granted(Manifest.permission.ACCESS_FINE_LOCATION) && !granted(Manifest.permission.ACCESS_COARSE_LOCATION)) {
            fail(ErrorCode.PERM_LOCATION, "Allow Nixin to use location (Allow all the time)")
        }
        val lm = ctx.getSystemService(LocationManager::class.java)
        if (!lm.isLocationEnabled) fail(ErrorCode.FAILED, "Location is turned off on the phone")
        val candidates = buildList {
            if (Build.VERSION.SDK_INT >= 31) add(LocationManager.FUSED_PROVIDER)
            add(LocationManager.GPS_PROVIDER)
            add(LocationManager.NETWORK_PROVIDER)
        }.filter { runCatching { lm.isProviderEnabled(it) }.getOrDefault(false) }
        val timeout = (p.int("timeoutMs") ?: 10_000).toLong().coerceIn(1000, 30_000)
        var loc: Location? = null
        for (provider in candidates) {
            loc = withTimeoutOrNull(timeout) {
                suspendCancellableCoroutine { cont ->
                    val cancel = CancellationSignal()
                    lm.getCurrentLocation(provider, cancel, ctx.mainExecutor) { l -> if (cont.isActive) cont.resume(l) }
                    cont.invokeOnCancellation { cancel.cancel() }
                }
            }
            if (loc != null) break
        }
        val found = loc ?: candidates.mapNotNull { runCatching { lm.getLastKnownLocation(it) }.getOrNull() }.maxByOrNull { it.time }
            ?: fail(ErrorCode.FAILED, "No location fix (are you indoors?)")
        return jsonOf("lat" to found.latitude, "lon" to found.longitude, "accuracy" to found.accuracy.toDouble(),
            "provider" to found.provider, "time" to found.time)
    }

    // ------------------------------------------------------------------ device.setting
    fun setting(p: JsonObject): JsonObject {
        if (!Settings.System.canWrite(ctx)) fail(ErrorCode.PERM_WRITE_SETTINGS, "Allow Nixin to modify system settings")
        val cr = ctx.contentResolver
        val name = p.reqStr("name")
        val v = p["value"] as? JsonPrimitive ?: fail(ErrorCode.BAD_REQUEST, "missing 'value'")
        when (name) {
            "auto_rotate" -> Settings.System.putInt(cr, Settings.System.ACCELEROMETER_ROTATION, if (v.booleanOrNull == true) 1 else 0)
            "haptics" -> Settings.System.putInt(cr, Settings.System.HAPTIC_FEEDBACK_ENABLED, if (v.booleanOrNull == true) 1 else 0)
            "screen_timeout" -> {
                val secs = (v.intOrNull ?: fail(ErrorCode.BAD_REQUEST, "screen_timeout needs seconds")).coerceIn(15, 1800)
                Settings.System.putInt(cr, Settings.System.SCREEN_OFF_TIMEOUT, secs * 1000)
            }
            else -> fail(ErrorCode.BAD_REQUEST, "Unknown setting $name")
        }
        return jsonOf("name" to name, "value" to v)
    }

    // ------------------------------------------------------------------ device.wallpaper
    fun wallpaper(p: JsonObject): JsonObject {
        val bytes = runCatching { Base64.decode(p.reqStr("data"), Base64.DEFAULT) }.getOrNull()
            ?: fail(ErrorCode.BAD_REQUEST, "data is not base64")
        val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: fail(ErrorCode.BAD_REQUEST, "Not an image")
        val flags = when (p.str("target")) {
            "home" -> WallpaperManager.FLAG_SYSTEM
            "lock" -> WallpaperManager.FLAG_LOCK
            else -> WallpaperManager.FLAG_SYSTEM or WallpaperManager.FLAG_LOCK
        }
        WallpaperManager.getInstance(ctx).setBitmap(bmp, null, true, flags)
        return jsonOf("set" to (p.str("target") ?: "both"), "width" to bmp.width, "height" to bmp.height)
    }

    // ------------------------------------------------------------------ clipboard
    suspend fun clipboardSet(p: JsonObject): JsonObject = withContext(Dispatchers.Main) {
        val text = p.reqStr("text")
        ctx.getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("Nixin", text))
        jsonOf("ok" to true, "chars" to text.length)
    }

    suspend fun clipboardGet(): JsonObject = withContext(Dispatchers.Main) {
        // Android 10+ only lets the foreground app (or the default IME) read the clipboard.
        val clip = ctx.getSystemService(ClipboardManager::class.java).primaryClip
            ?: fail(ErrorCode.UNSUPPORTED, "Android only allows reading the clipboard while Nixin is open")
        val text = if (clip.itemCount > 0) clip.getItemAt(0).coerceToText(ctx).toString() else ""
        jsonOf("text" to text)
    }

    // ------------------------------------------------------------------ media.now_playing
    fun nowPlaying(): JsonObject {
        if (!Nixin.device.notificationAccess()) fail(ErrorCode.PERM_NOTIFICATIONS, "Give Nixin notification access")
        val msm = ctx.getSystemService(MediaSessionManager::class.java)
        val sessions = msm.getActiveSessions(ComponentName(ctx, NotificationWatcher::class.java))
        val c = sessions.firstOrNull { it.playbackState?.state == PlaybackState.STATE_PLAYING } ?: sessions.firstOrNull()
            ?: return jsonOf()
        val md = c.metadata
        val state = when (c.playbackState?.state) {
            PlaybackState.STATE_PLAYING -> "playing"
            PlaybackState.STATE_PAUSED -> "paused"
            PlaybackState.STATE_BUFFERING -> "buffering"
            PlaybackState.STATE_STOPPED -> "stopped"
            else -> "unknown"
        }
        return jsonOf(
            "title" to md?.getString(MediaMetadata.METADATA_KEY_TITLE),
            "artist" to (md?.getString(MediaMetadata.METADATA_KEY_ARTIST) ?: md?.getString(MediaMetadata.METADATA_KEY_ALBUM_ARTIST)),
            "album" to md?.getString(MediaMetadata.METADATA_KEY_ALBUM),
            "durationMs" to md?.getLong(MediaMetadata.METADATA_KEY_DURATION),
            "positionMs" to c.playbackState?.position,
            "app" to Nixin.appLabel(c.packageName), "package" to c.packageName, "state" to state,
        )
    }

    // ------------------------------------------------------------------ call.control
    @SuppressLint("MissingPermission")
    suspend fun callControl(p: JsonObject): JsonObject {
        val action = p.reqStr("action")
        val tm = ctx.getSystemService(TelecomManager::class.java)
        when (action) {
            "answer", "end" -> {
                if (!granted(Manifest.permission.ANSWER_PHONE_CALLS)) fail(ErrorCode.PERM_PHONE, "Allow Nixin to answer calls")
                val ok = runCatching {
                    @Suppress("DEPRECATION")
                    if (action == "answer") { tm.acceptRingingCall(); true } else tm.endCall()
                }.getOrDefault(false)
                if (!ok && !tapCallButton(action)) fail(ErrorCode.FAILED, "Could not ${if (action == "answer") "answer" else "end"} the call")
            }
            "speaker_on", "speaker_off" -> {
                val on = action == "speaker_on"
                if (Build.VERSION.SDK_INT >= 31) {
                    if (on) {
                        val speaker = audio.availableCommunicationDevices.firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER }
                            ?: fail(ErrorCode.UNSUPPORTED, "No speaker device")
                        audio.setCommunicationDevice(speaker)
                    } else {
                        audio.clearCommunicationDevice()
                    }
                } else {
                    @Suppress("DEPRECATION")
                    audio.isSpeakerphoneOn = on
                }
            }
            "mute", "unmute" -> audio.isMicrophoneMute = action == "mute"
            else -> fail(ErrorCode.BAD_REQUEST, "Unknown call action $action")
        }
        return jsonOf("action" to action, "inCall" to runCatching { tm.isInCall }.getOrDefault(false))
    }

    /** Fallback for phones where the telecom API is restricted: tap the dialer's own button. */
    private suspend fun tapCallButton(action: String): Boolean {
        if (NixinAccessibilityService.instance == null) return false
        val labels = if (action == "answer") listOf("Answer", "Accept", "Uthao") else listOf("End call", "Decline", "Reject", "Hang up")
        for (label in labels) {
            val ok = runCatching { UiController.tapText(jsonOf("text" to label), confirmed = true) }.isSuccess
            if (ok) return true
        }
        return false
    }

    // ------------------------------------------------------------------ usage.stats (screen time)
    fun usage(p: JsonObject): JsonObject {
        val aom = ctx.getSystemService(AppOpsManager::class.java)
        val mode = aom.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), ctx.packageName)
        if (mode != AppOpsManager.MODE_ALLOWED) fail(ErrorCode.PERM_USAGE, "Grant Nixin Usage access")
        val period = p.str("period") ?: "today"
        val limit = (p.int("limit") ?: 8).coerceIn(1, 30)
        val cal = Calendar.getInstance().apply {
            set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
        }
        val now = System.currentTimeMillis()
        val (start, end) = when (period) {
            "yesterday" -> (cal.timeInMillis - 86_400_000L) to cal.timeInMillis
            "week" -> (now - 7 * 86_400_000L) to now
            else -> cal.timeInMillis to now
        }
        val usm = ctx.getSystemService(UsageStatsManager::class.java)
        val events = usm.queryEvents(start, end)
        val ev = UsageEvents.Event()
        val started = HashMap<String, Long>()
        val total = HashMap<String, Long>()
        var unlocks = 0
        while (events.hasNextEvent()) {
            events.getNextEvent(ev)
            val pkg = ev.packageName ?: continue
            when (ev.eventType) {
                UsageEvents.Event.ACTIVITY_RESUMED -> started[pkg] = ev.timeStamp
                UsageEvents.Event.ACTIVITY_PAUSED, UsageEvents.Event.ACTIVITY_STOPPED ->
                    started.remove(pkg)?.let { total[pkg] = (total[pkg] ?: 0L) + (ev.timeStamp - it) }
                UsageEvents.Event.KEYGUARD_HIDDEN -> unlocks++
            }
        }
        started.forEach { (pkg, t) -> if (end == now) total[pkg] = (total[pkg] ?: 0L) + (end - t) }
        val home = homePackages()
        val apps = total.filterKeys { it != ctx.packageName && it !in home && it != "com.android.systemui" }
            .filterValues { it > 30_000 }
            .entries.sortedByDescending { it.value }
        return jsonOf(
            "period" to period, "totalMs" to apps.sumOf { it.value }, "unlocks" to unlocks,
            "apps" to apps.take(limit).map { mapOf("package" to it.key, "label" to Nixin.appLabel(it.key), "ms" to it.value) },
        )
    }

    private fun homePackages(): Set<String> = runCatching {
        ctx.packageManager.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME), 0)
            .map { it.activityInfo.packageName }.toSet()
    }.getOrDefault(emptySet())

    // ------------------------------------------------------------------ nixin.notify
    fun notify(p: JsonObject): JsonObject {
        val id = p.int("id") ?: notifIds.incrementAndGet()
        val text = p.str("text") ?: ""
        val open = android.app.PendingIntent.getActivity(
            ctx, 30, Intent(ctx, com.letvler.nixin.ui.MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            android.app.PendingIntent.FLAG_IMMUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val n = Notification.Builder(ctx, Nixin.CHANNEL_ALERTS)
            .setSmallIcon(R.drawable.ic_stat_nixin)
            .setContentTitle(p.reqStr("title"))
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_REMINDER)
            .build()
        ctx.getSystemService(NotificationManager::class.java).notify(id, n)
        return jsonOf("shown" to true, "id" to id)
    }
}
