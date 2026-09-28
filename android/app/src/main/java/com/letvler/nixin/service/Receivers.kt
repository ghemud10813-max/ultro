package com.letvler.nixin.service

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.letvler.nixin.Nixin
import com.letvler.nixin.a11y.Recorder
import com.letvler.nixin.core.jsonOf

/** Notification buttons: kill switch and quick answers to Nixin's questions. */
class ActionReceiver : BroadcastReceiver() {
    companion object {
        private const val ACTION_STOP = "com.letvler.nixin.STOP"
        private const val ACTION_ANSWER = "com.letvler.nixin.ANSWER"
        private const val ACTION_STOP_RING = "com.letvler.nixin.STOP_RING"
        private const val ACTION_RECORD = "com.letvler.nixin.RECORD"

        fun stopRingIntent(ctx: Context): PendingIntent = PendingIntent.getBroadcast(
            ctx, 101, Intent(ctx, ActionReceiver::class.java).setAction(ACTION_STOP_RING),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

        fun recordIntent(ctx: Context, save: Boolean): PendingIntent = PendingIntent.getBroadcast(
            ctx, if (save) 102 else 103, Intent(ctx, ActionReceiver::class.java).setAction(ACTION_RECORD).putExtra("save", save),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

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
            ACTION_STOP_RING -> Nixin.extras.stopRing()
            ACTION_RECORD -> {
                val save = intent.getBooleanExtra("save", false)
                // the PC owns the skill library: ask it to save/cancel (it calls rec.stop); offline -> just stop here
                if (!Nixin.link.sendCommand(if (save) "recording save karo" else "recording cancel karo", "phone_text")) {
                    Recorder.stop(jsonOf("cancel" to true))
                }
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
