package com.letvler.nixin

import android.app.Application
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import com.letvler.nixin.capabilities.AppControl
import com.letvler.nixin.capabilities.CommControl
import com.letvler.nixin.capabilities.DeviceControl
import com.letvler.nixin.core.AppState
import com.letvler.nixin.core.Settings
import com.letvler.nixin.core.jsonOf
import com.letvler.nixin.dispatch.Dispatcher
import com.letvler.nixin.link.LinkClient
import com.letvler.nixin.service.ActionReceiver
import com.letvler.nixin.service.LinkService
import com.letvler.nixin.service.NotificationWatcher
import com.letvler.nixin.ui.MainActivity
import com.letvler.nixin.voice.Speaker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import java.util.concurrent.ConcurrentHashMap

/** Process-wide singletons (a tiny service locator; no DI framework needed). */
object Nixin {
    lateinit var app: Application
        private set
    lateinit var settings: Settings
        private set
    lateinit var device: DeviceControl
        private set
    lateinit var apps: AppControl
        private set
    lateinit var comm: CommControl
        private set
    lateinit var dispatcher: Dispatcher
        private set
    lateinit var link: LinkClient
        private set
    lateinit var speaker: Speaker
        private set

    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    const val CHANNEL_LINK = "nixin_link"
    const val CHANNEL_ASK = "nixin_ask"
    const val NOTIF_LINK = 1
    const val NOTIF_ASK = 2

    private val labels = ConcurrentHashMap<String, String>()

    fun init(application: Application) {
        app = application
        settings = Settings(application)
        device = DeviceControl(application)
        apps = AppControl(application)
        comm = CommControl(application)
        dispatcher = Dispatcher(device, apps, comm)
        link = LinkClient(scope, dispatcher)
        speaker = Speaker(application)
        createChannels(application)
    }

    fun appLabel(pkg: String?): String? {
        if (pkg == null) return null
        return labels.getOrPut(pkg) {
            runCatching {
                val pm = app.packageManager
                @Suppress("DEPRECATION")
                pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString()
            }.getOrDefault(pkg)
        }
    }

    // ------------------------------------------------------------------ lifecycle hooks
    fun startService(ctx: Context = app) {
        ctx.startForegroundService(Intent(ctx, LinkService::class.java))
    }

    fun onConnected() = LinkService.refresh()
    fun onDisconnected() = LinkService.refresh()

    fun onAccessibilityChanged(@Suppress("UNUSED_PARAMETER") enabled: Boolean) {
        if (::link.isInitialized) link.sendStatus()
    }

    fun onForegroundChanged(pkg: String) {
        if (::link.isInitialized) link.sendForeground(pkg)
    }

    fun onNotification(@Suppress("UNUSED_PARAMETER") item: NotificationWatcher.Item) {
        // Notifications stay on the phone until the PC asks (notif.list). Nothing is pushed.
    }

    // ------------------------------------------------------------------ kill switch
    /** Durable stop: survives restarts; only a tap on Resume inside the app clears it. */
    fun stop(reason: String) {
        settings.setStopped(true)
        dispatcher.cancelAll()
        speaker.stop()
        AppState.setBusy(false)
        link.sendEvent("stopped", jsonOf("reason" to reason))
        LinkService.refresh()
    }

    fun resume() {
        settings.setStopped(false)
        link.sendEvent("resumed", jsonOf())
        link.sendStatus()
        LinkService.refresh()
    }

    // ------------------------------------------------------------------ notifications
    private fun createChannels(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_LINK, ctx.getString(R.string.channel_link), NotificationManager.IMPORTANCE_LOW).apply {
                description = "Shows that Nixin is connected; contains the Stop button"
                setShowBadge(false)
            },
        )
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ASK, ctx.getString(R.string.channel_ask), NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Confirmations Nixin needs from you (send this message? which contact?)"
            },
        )
    }

    fun showAskNotification(ask: AppState.Ask) {
        val ctx = app
        val open = PendingIntent.getActivity(
            ctx, 10, Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val b = Notification.Builder(ctx, CHANNEL_ASK)
            .setSmallIcon(R.drawable.ic_stat_nixin)
            .setContentTitle("Nixin asks")
            .setContentText(ask.text)
            .setStyle(Notification.BigTextStyle().bigText(ask.text))
            .setContentIntent(open)
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_MESSAGE)
        if (ask.kind == "confirm") {
            b.addAction(Notification.Action.Builder(null, "Haan / Yes", ActionReceiver.answerIntent(ctx, ask.id, "yes", 11)).build())
            b.addAction(Notification.Action.Builder(null, "Nahi / No", ActionReceiver.answerIntent(ctx, ask.id, "no", 12)).build())
        } else if (ask.kind == "choose") {
            ask.options.take(3).forEachIndexed { i, o ->
                b.addAction(Notification.Action.Builder(null, o, ActionReceiver.answerIntent(ctx, ask.id, o, 20 + i)).build())
            }
        }
        runCatching { ctx.getSystemService(NotificationManager::class.java).notify(NOTIF_ASK, b.build()) }
    }

    fun clearAskNotification() {
        runCatching { app.getSystemService(NotificationManager::class.java).cancel(NOTIF_ASK) }
    }
}

class NixinApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Nixin.init(this)
    }
}
