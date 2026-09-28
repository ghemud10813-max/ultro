package com.letvler.nixin.service

import android.app.ActivityOptions
import android.app.Notification
import android.app.PendingIntent
import android.app.RemoteInput
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import com.letvler.nixin.Nixin
import com.letvler.nixin.core.ErrorCode
import com.letvler.nixin.core.bool
import com.letvler.nixin.core.fail
import com.letvler.nixin.core.int
import com.letvler.nixin.core.jsonOf
import com.letvler.nixin.core.reqStr
import com.letvler.nixin.core.str
import com.letvler.nixin.policy.SafetyRules
import kotlinx.serialization.json.JsonObject
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ConcurrentLinkedDeque

/**
 * Keeps the last ~50 notifications in memory (never on disk). Blocked apps are skipped and OTP-like
 * codes are masked. v2: reply through the notification's own reply action, dismiss, open, and — only
 * when "Mirror notifications" is on — push new ones to the PC live.
 */
class NotificationWatcher : NotificationListenerService() {

    data class Item(
        val key: String, val pkg: String, val app: String, val title: String?, val text: String?, val time: Long,
        val canReply: Boolean = false,
    ) {
        fun toMap() = mapOf("key" to key, "package" to pkg, "app" to app, "title" to title, "text" to text, "time" to time,
            "canReply" to canReply)
    }

    companion object {
        @Volatile var instance: NotificationWatcher? = null
        private val recent = ConcurrentLinkedDeque<Item>()
        private val live = ConcurrentHashMap<String, StatusBarNotification>()
        private val callsAnnounced = ConcurrentHashMap<String, Long>()

        private fun requireAccess(): NotificationWatcher {
            return instance ?: fail(ErrorCode.PERM_NOTIFICATIONS, "Give Nixin notification access")
        }

        fun list(p: JsonObject): JsonObject {
            if (instance == null && !Nixin.device.notificationAccess()) {
                fail(ErrorCode.PERM_NOTIFICATIONS, "Give Nixin notification access")
            }
            val pkg = p.str("package")
            val limit = (p.int("limit") ?: 5).coerceIn(1, 20)
            val items = recent.filter { pkg == null || it.pkg == pkg }.take(limit)
            return jsonOf("notifications" to items.map { it.toMap() })
        }

        private fun replyAction(n: Notification): Notification.Action? =
            n.actions?.firstOrNull { a -> a.remoteInputs?.any { it.allowFreeFormInput } == true }

        fun reply(p: JsonObject): JsonObject {
            val svc = requireAccess()
            val key = p.reqStr("key")
            val text = p.reqStr("text")
            val sbn = live[key] ?: fail(ErrorCode.NOT_FOUND, "That notification is gone")
            val action = replyAction(sbn.notification) ?: fail(ErrorCode.NOT_FOUND, "This notification has no reply button")
            val inputs = action.remoteInputs ?: fail(ErrorCode.NOT_FOUND, "No reply field")
            val results = Bundle().apply { inputs.forEach { putCharSequence(it.resultKey, text) } }
            val intent = Intent()
            RemoteInput.addResultsToIntent(inputs, intent, results)
            try {
                action.actionIntent.send(svc, 0, intent)
            } catch (e: PendingIntent.CanceledException) {
                fail(ErrorCode.UNCERTAIN, "The app closed the reply action")
            }
            return jsonOf("sent" to true, "app" to Nixin.appLabel(sbn.packageName))
        }

        fun dismiss(p: JsonObject): JsonObject {
            val svc = requireAccess()
            if (p.bool("all") == true) {
                val n = live.size
                svc.cancelAllNotifications()
                return jsonOf("dismissed" to n)
            }
            val key = p.reqStr("key")
            svc.cancelNotification(key)
            recent.removeIf { it.key == key }
            return jsonOf("dismissed" to 1)
        }

        fun open(p: JsonObject): JsonObject {
            val svc = requireAccess()
            val sbn = live[p.reqStr("key")] ?: fail(ErrorCode.NOT_FOUND, "That notification is gone")
            val pi = sbn.notification.contentIntent ?: fail(ErrorCode.NOT_FOUND, "Nothing to open")
            val opts = if (Build.VERSION.SDK_INT >= 34) {
                @Suppress("DEPRECATION")
                ActivityOptions.makeBasic()
                    .setPendingIntentBackgroundActivityStartMode(ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED).toBundle()
            } else null
            try {
                pi.send(svc, 0, null, null, null, null, opts)
            } catch (e: PendingIntent.CanceledException) {
                fail(ErrorCode.FAILED, "The app no longer accepts this notification")
            }
            return jsonOf("opened" to true)
        }
    }

    override fun onListenerConnected() {
        instance = this
        runCatching { activeNotifications?.sortedBy { it.postTime }?.forEach { add(it, announce = false) } }
    }

    override fun onListenerDisconnected() {
        instance = null
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        sbn?.let { add(it, announce = true) }
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification?) {
        val key = sbn?.key ?: return
        live.remove(key)
        if (recent.removeIf { it.key == key } && Nixin.settings.mirrorNotifications.value) {
            Nixin.link.sendEvent("notification_removed", jsonOf("key" to key))
        }
    }

    private fun add(sbn: StatusBarNotification, announce: Boolean) {
        val n = sbn.notification ?: return
        if (sbn.packageName == packageName) return
        if (SafetyRules.isBlocked(sbn.packageName, Nixin.settings.blocked)) return
        val extras = n.extras
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()
        if (announce && n.category == Notification.CATEGORY_CALL) onCall(sbn, title)
        if (sbn.isOngoing || (n.flags and Notification.FLAG_GROUP_SUMMARY) != 0) return
        val text = (extras.getCharSequence(Notification.EXTRA_BIG_TEXT) ?: extras.getCharSequence(Notification.EXTRA_TEXT))?.toString()
        if (title.isNullOrBlank() && text.isNullOrBlank()) return
        val item = Item(
            sbn.key, sbn.packageName, Nixin.appLabel(sbn.packageName) ?: sbn.packageName,
            SafetyRules.maskOtp(title)?.take(120), SafetyRules.maskOtp(text)?.take(300), sbn.postTime,
            canReply = replyAction(n) != null,
        )
        live[sbn.key] = sbn
        recent.removeIf { it.key == item.key }
        recent.addFirst(item)
        while (recent.size > 50) recent.pollLast()?.let { live.remove(it.key) }
        if (announce) Nixin.onNotification(item)
    }

    /** Incoming-call notifications (ongoing, category "call") become a call_incoming event once per call. */
    private fun onCall(sbn: StatusBarNotification, title: String?) {
        val now = System.currentTimeMillis()
        if (now - (callsAnnounced[sbn.key] ?: 0L) < 60_000) return
        callsAnnounced[sbn.key] = now
        if (Nixin.settings.mirrorNotifications.value) {
            Nixin.link.sendEvent("call_incoming", jsonOf("caller" to SafetyRules.maskOtp(title)?.take(80),
                "app" to Nixin.appLabel(sbn.packageName)))
        }
    }
}
