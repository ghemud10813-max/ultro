package com.letvler.nixin.a11y

import android.app.Notification
import android.app.NotificationManager
import android.content.Intent
import android.graphics.Rect
import android.os.Build
import android.view.accessibility.AccessibilityEvent
import com.letvler.nixin.Nixin
import com.letvler.nixin.R
import com.letvler.nixin.core.AppState
import com.letvler.nixin.core.bool
import com.letvler.nixin.core.jsonOf
import com.letvler.nixin.core.str
import com.letvler.nixin.policy.SafetyRules
import com.letvler.nixin.service.ActionReceiver
import kotlinx.serialization.json.JsonObject

/**
 * Teach mode: records what YOU do on the phone as semantic steps (which app, which labelled element,
 * what text) so the PC can replay it later ("chai order chalao"). Password fields and blocked apps
 * are never recorded; a notification with Save / Cancel is visible the whole time.
 */
object Recorder {
    @Volatile var active: String? = null
        private set
    private val steps = ArrayList<Map<String, Any?>>()
    private var lastPkg: String? = null
    private var homes: Set<String> = emptySet()

    fun start(p: JsonObject): JsonObject {
        val name = p.str("name")?.takeIf { it.isNotBlank() } ?: "skill"
        synchronized(steps) {
            steps.clear()
            lastPkg = null
        }
        homes = runCatching {
            Nixin.app.packageManager.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME), 0)
                .map { it.activityInfo.packageName }.toSet()
        }.getOrDefault(emptySet())
        active = name
        AppState.setRecording(name)
        showNotification(name)
        return jsonOf("recording" to true, "name" to name)
    }

    fun stop(p: JsonObject): JsonObject {
        val name = active
        val out = synchronized(steps) { steps.toList().also { steps.clear() } }
        active = null
        AppState.setRecording(null)
        runCatching { Nixin.app.getSystemService(NotificationManager::class.java).cancel(Nixin.NOTIF_RECORD) }
        if (p.bool("cancel") == true) return jsonOf("cancelled" to true, "steps" to emptyList<Any>())
        return jsonOf("name" to name, "steps" to out, "package" to out.firstOrNull()?.get("package"))
    }

    fun onEvent(event: AccessibilityEvent) {
        if (active == null) return
        val pkg = event.packageName?.toString() ?: return
        if (pkg == Nixin.app.packageName || pkg == "com.android.systemui") return
        if (SafetyRules.isBlocked(pkg, Nixin.settings.blocked)) return
        val step: Map<String, Any?> = when (event.eventType) {
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> {
                if (pkg == lastPkg || pkg in homes) {
                    if (pkg in homes) lastPkg = pkg
                    return
                }
                if (Nixin.app.packageManager.getLaunchIntentForPackage(pkg) == null) return // dialogs, keyboards…
                lastPkg = pkg
                mapOf("a" to "open", "package" to pkg, "label" to Nixin.appLabel(pkg))
            }
            AccessibilityEvent.TYPE_VIEW_CLICKED -> {
                if (pkg in homes) return // tapping an app icon is recorded as "open" when the app appears
                val n = event.source
                if (n?.isPassword == true || event.isPassword) return
                val text = n?.text?.toString()?.takeIf { it.isNotBlank() }
                    ?: event.text.joinToString(" ").takeIf { it.isNotBlank() }
                val desc = n?.contentDescription?.toString()?.takeIf { it.isNotBlank() }
                val res = n?.viewIdResourceName?.substringAfter(":id/", "")?.takeIf { it.isNotEmpty() }
                val r = Rect().also { n?.getBoundsInScreen(it) }
                if (text == null && desc == null && res == null && r.isEmpty) return
                mapOf("a" to "tap", "package" to pkg, "text" to text?.take(120), "desc" to desc?.take(120), "res" to res,
                    "role" to (n?.let { ScreenSerializer.roleOf(AndroidUiNode(it)) }), "b" to listOf(r.left, r.top, r.right, r.bottom))
            }
            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> {
                if (event.isPassword || event.source?.isPassword == true) return
                val text = event.text.joinToString("")
                val n = event.source
                val res = n?.viewIdResourceName?.substringAfter(":id/", "")?.takeIf { it.isNotEmpty() }
                val hint = n?.hintText?.toString()
                synchronized(steps) {
                    val last = steps.lastOrNull()
                    if (last != null && last["a"] == "type" && last["res"] == res && last["hint"] == hint && last["package"] == pkg) {
                        steps[steps.size - 1] = last + ("text" to text) // keep only the final text of the field
                        return
                    }
                }
                mapOf("a" to "type", "package" to pkg, "text" to text, "res" to res, "hint" to hint)
            }
            AccessibilityEvent.TYPE_VIEW_SCROLLED -> {
                val dy = if (Build.VERSION.SDK_INT >= 28) event.scrollDeltaY else 0
                if (dy == 0) return
                val dir = if (dy > 0) "down" else "up"
                synchronized(steps) {
                    val last = steps.lastOrNull()
                    if (last != null && last["a"] == "scroll" && last["dir"] == dir) return
                }
                mapOf("a" to "scroll", "package" to pkg, "dir" to dir)
            }
            else -> return
        }
        synchronized(steps) { if (steps.size < 200) steps.add(step) }
        Nixin.link.sendEvent("recorded_step", jsonOf(*step.entries.map { it.key to it.value }.toTypedArray()))
    }

    private fun showNotification(name: String) {
        val ctx = Nixin.app
        val n = Notification.Builder(ctx, Nixin.CHANNEL_ALERTS)
            .setSmallIcon(R.drawable.ic_stat_nixin)
            .setContentTitle("Nixin is learning “$name”")
            .setContentText("Do it once on the phone, then tap Save")
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null, "Save", ActionReceiver.recordIntent(ctx, save = true)).build())
            .addAction(Notification.Action.Builder(null, "Cancel", ActionReceiver.recordIntent(ctx, save = false)).build())
            .build()
        runCatching { ctx.getSystemService(NotificationManager::class.java).notify(Nixin.NOTIF_RECORD, n) }
    }
}
