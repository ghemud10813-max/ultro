package com.letvler.nixin.service

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import com.letvler.nixin.Nixin
import com.letvler.nixin.core.ErrorCode
import com.letvler.nixin.core.fail
import com.letvler.nixin.core.int
import com.letvler.nixin.core.jsonOf
import com.letvler.nixin.core.str
import com.letvler.nixin.policy.SafetyRules
import kotlinx.serialization.json.JsonObject
import java.util.concurrent.ConcurrentLinkedDeque

/**
 * Keeps the last ~50 notifications in memory (never on disk) so "latest notification
 * padh ke bata" works. Blocked apps are skipped and OTP-like codes are masked.
 */
class NotificationWatcher : NotificationListenerService() {

    data class Item(val key: String, val pkg: String, val app: String, val title: String?, val text: String?, val time: Long)

    companion object {
        @Volatile var instance: NotificationWatcher? = null
        private val recent = ConcurrentLinkedDeque<Item>()

        fun list(p: JsonObject): JsonObject {
            if (instance == null && !Nixin.device.notificationAccess()) {
                fail(ErrorCode.PERM_NOTIFICATIONS, "Give Nixin notification access")
            }
            val pkg = p.str("package")
            val limit = (p.int("limit") ?: 5).coerceIn(1, 20)
            val items = recent.filter { pkg == null || it.pkg == pkg }.take(limit)
            return jsonOf("notifications" to items.map {
                mapOf("key" to it.key, "package" to it.pkg, "app" to it.app, "title" to it.title, "text" to it.text, "time" to it.time)
            })
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

    private fun add(sbn: StatusBarNotification, announce: Boolean) {
        val n = sbn.notification ?: return
        if (sbn.packageName == packageName) return
        if (sbn.isOngoing || (n.flags and Notification.FLAG_GROUP_SUMMARY) != 0) return
        if (SafetyRules.isBlocked(sbn.packageName, Nixin.settings.blocked)) return
        val extras = n.extras
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()
        val text = (extras.getCharSequence(Notification.EXTRA_BIG_TEXT) ?: extras.getCharSequence(Notification.EXTRA_TEXT))?.toString()
        if (title.isNullOrBlank() && text.isNullOrBlank()) return
        val item = Item(
            sbn.key, sbn.packageName, Nixin.appLabel(sbn.packageName) ?: sbn.packageName,
            SafetyRules.maskOtp(title)?.take(120), SafetyRules.maskOtp(text)?.take(300), sbn.postTime,
        )
        recent.removeIf { it.key == item.key }
        recent.addFirst(item)
        while (recent.size > 50) recent.removeLast()
        if (announce) Nixin.onNotification(item)
    }
}
