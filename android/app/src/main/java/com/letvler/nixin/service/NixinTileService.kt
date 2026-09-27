package com.letvler.nixin.service

import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import com.letvler.nixin.core.AppState
import com.letvler.nixin.ui.VoiceActivity

/** Quick Settings tile: one tap to talk to Nixin from anywhere. */
class NixinTileService : TileService() {

    override fun onStartListening() {
        super.onStartListening()
        qsTile?.apply {
            state = if (AppState.link.value is AppState.Link.Connected) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
            subtitle = if (state == Tile.STATE_ACTIVE) "Tap to talk" else "PC offline"
            updateTile()
        }
    }

    override fun onClick() {
        super.onClick()
        val intent = Intent(this, VoiceActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Build.VERSION.SDK_INT >= 34) {
            startActivityAndCollapse(PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE))
        } else {
            @Suppress("DEPRECATION")
            startActivityAndCollapse(intent)
        }
    }
}
