package com.letvler.nixin.service

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.letvler.nixin.Nixin

/** Notification buttons: kill switch and quick answers to Nixin's questions. */
class ActionReceiver : BroadcastReceiver() {
    companion object {
        private const val ACTION_STOP = "com.letvler.nixin.STOP"
        private const val ACTION_ANSWER = "com.letvler.nixin.ANSWER"

        fun stopIntent(ctx: Context): PendingIntent = PendingIntent.getBroadcast(
            ctx, 100, Intent(ctx, ActionReceiver::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

        fun answerIntent(ctx: Context, askId: String, value: String, requestCode: Int): PendingIntent = PendingIntent.getBroadcast(
            ctx, requestCode,
            Intent(ctx, ActionReceiver::class.java).setAction(ACTION_ANSWER).putExtra("id", askId).putExtra("value", value),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
    }

    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            ACTION_STOP -> Nixin.stop("notification")
            ACTION_ANSWER -> {
                val id = intent.getStringExtra("id") ?: return
                Nixin.link.answer(id, intent.getStringExtra("value") ?: "no")
            }
        }
    }
}

/** Reconnect to the PC after reboot / app update (if paired and auto-start is on). */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED && intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        if (Nixin.settings.autoStart.value && Nixin.settings.paired.value != null) {
            runCatching { Nixin.startService(context) }
        }
    }
}
