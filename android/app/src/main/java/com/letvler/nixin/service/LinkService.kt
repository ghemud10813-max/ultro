package com.letvler.nixin.service

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.Build
import android.os.IBinder
import com.letvler.nixin.Nixin
import com.letvler.nixin.R
import com.letvler.nixin.core.AppState
import com.letvler.nixin.ui.MainActivity
import com.letvler.nixin.ui.VoiceActivity
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

/**
 * Foreground service that owns the PC link. Its persistent notification shows the
 * connection state and carries the KILL SWITCH (Stop) button.
 */
class LinkService : Service() {

    companion object {
        @Volatile private var instance: LinkService? = null

        fun refresh() {
            instance?.updateNotification()
        }
    }

    private var observer: Job? = null
    private var netCallback: ConnectivityManager.NetworkCallback? = null
    private var events: PhoneEvents? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        instance = this
        startForeground(Nixin.NOTIF_LINK, build(), ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        Nixin.link.start()
        observer = Nixin.scope.launch {
            combine(AppState.link, Nixin.settings.stopped) { a, b -> a to b }.collect { updateNotification() }
        }
        events = PhoneEvents(this).also { it.register() }
        val cm = getSystemService(ConnectivityManager::class.java)
        netCallback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                Nixin.link.reconnectNow()
                events?.onNetworkChanged()
            }

            override fun onLost(network: Network) {
                events?.onNetworkChanged()
            }
        }
        runCatching {
            cm.registerNetworkCallback(
                NetworkRequest.Builder().addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET).build(), netCallback!!,
            )
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Nixin.link.start()
        Nixin.link.reconnectNow()
        return START_STICKY
    }

    override fun onDestroy() {
        events?.unregister()
        observer?.cancel()
        netCallback?.let { runCatching { getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(it) } }
        Nixin.link.stop()
        instance = null
        super.onDestroy()
    }

    fun updateNotification() {
        runCatching { getSystemService(NotificationManager::class.java).notify(Nixin.NOTIF_LINK, build()) }
    }

    private fun build(): Notification {
        val stopped = Nixin.settings.stopped.value
        val (title, text) = when {
            stopped -> "Nixin STOPPED" to "Kill switch is on. Open Nixin and tap Resume."
            else -> when (val l = AppState.link.value) {
                is AppState.Link.Connected -> "Nixin · connected to ${l.pcName}" to "Tap Stop to halt everything instantly"
                is AppState.Link.Connecting -> "Nixin · connecting…" to (l.endpoint ?: "")
                is AppState.Link.Error -> "Nixin · problem" to l.message
                AppState.Link.Unpaired -> "Nixin · not paired" to "Open the app and scan the pairing QR"
                AppState.Link.Offline -> "Nixin · PC offline" to "Retrying automatically"
            }
        }
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val b = Notification.Builder(this, Nixin.CHANNEL_LINK)
            .setSmallIcon(R.drawable.ic_stat_nixin)
            .setContentTitle(title)
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(open)
        if (Build.VERSION.SDK_INT >= 31) b.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE)
        if (!stopped) {
            b.addAction(Notification.Action.Builder(null, "■ STOP", ActionReceiver.stopIntent(this)).build())
            val talk = PendingIntent.getActivity(this, 1, Intent(this, VoiceActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            b.addAction(Notification.Action.Builder(null, "🎤 Talk", talk).build())
        } else {
            b.addAction(Notification.Action.Builder(null, "Open to resume", open).build())
        }
        return b.build()
    }
}
