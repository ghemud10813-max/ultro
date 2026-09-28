package com.letvler.nixin.core

import android.content.Context
import android.content.SharedPreferences
import com.letvler.nixin.link.PairingPayload
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.util.UUID

/** Persistent app settings (SharedPreferences) exposed as StateFlows for the UI. */
class Settings(context: Context) {
    private val prefs: SharedPreferences = context.getSharedPreferences("nixin", Context.MODE_PRIVATE)

    data class PairedPc(val pcId: String, val pcName: String, val endpoints: List<String>, val fingerprint: String)

    val deviceId: String = prefs.getString("device_id", null) ?: UUID.randomUUID().toString().also {
        prefs.edit().putString("device_id", it).apply()
    }

    private val _paired = MutableStateFlow(loadPaired())
    val paired: StateFlow<PairedPc?> = _paired

    private val _stopped = MutableStateFlow(prefs.getBoolean("stopped", false))
    val stopped: StateFlow<Boolean> = _stopped

    private val _allowScreenshots = MutableStateFlow(prefs.getBoolean("allow_screenshots", false))
    val allowScreenshots: StateFlow<Boolean> = _allowScreenshots

    private val _speakReplies = MutableStateFlow(prefs.getBoolean("speak_replies", true))
    val speakReplies: StateFlow<Boolean> = _speakReplies

    private val _voiceLanguage = MutableStateFlow(prefs.getString("voice_language", "en-IN") ?: "en-IN")
    val voiceLanguage: StateFlow<String> = _voiceLanguage

    private val _extraBlocked = MutableStateFlow(prefs.getStringSet("extra_blocked", emptySet())!!.toSet())
    val extraBlocked: StateFlow<Set<String>> = _extraBlocked

    private val _autoStart = MutableStateFlow(prefs.getBoolean("auto_start", true))
    val autoStart: StateFlow<Boolean> = _autoStart

    private val _mirrorNotifications = MutableStateFlow(prefs.getBoolean("mirror_notifications", false))
    /** Push every new notification (and incoming-call names) to the PC live. Off by default. */
    val mirrorNotifications: StateFlow<Boolean> = _mirrorNotifications

    private val _phoneEvents = MutableStateFlow(prefs.getBoolean("phone_events", true))
    /** Battery / charger / screen / Wi-Fi events for routines on the PC ("jab battery 20% se kam ho…"). */
    val phoneEvents: StateFlow<Boolean> = _phoneEvents

    /** Blocklist entries pushed by the PC (nixin.toml [blocklist]); in-memory only. */
    @Volatile var pcBlocked: Set<String> = emptySet()

    val blocked: Set<String> get() = _extraBlocked.value + pcBlocked

    private fun loadPaired(): PairedPc? {
        val id = prefs.getString("pc_id", null) ?: return null
        return PairedPc(
            id,
            prefs.getString("pc_name", "PC") ?: "PC",
            (prefs.getString("pc_endpoints", "") ?: "").split("\n").filter { it.isNotBlank() },
            prefs.getString("pc_fp", "") ?: "",
        )
    }

    fun savePaired(p: PairingPayload) {
        prefs.edit()
            .putString("pc_id", p.pcId)
            .putString("pc_name", p.pcName)
            .putString("pc_endpoints", p.endpoints.joinToString("\n"))
            .putString("pc_fp", p.fingerprint)
            .apply()
        _paired.value = loadPaired()
    }

    fun updateEndpoints(endpoints: List<String>) {
        prefs.edit().putString("pc_endpoints", endpoints.joinToString("\n")).apply()
        _paired.value = loadPaired()
    }

    fun forgetPc() {
        prefs.edit().remove("pc_id").remove("pc_name").remove("pc_endpoints").remove("pc_fp").apply()
        _paired.value = null
    }

    fun setStopped(v: Boolean) {
        @Suppress("ApplySharedPref")
        prefs.edit().putBoolean("stopped", v).commit() // commit: must survive an immediate process death
        _stopped.value = v
    }

    fun setAllowScreenshots(v: Boolean) {
        prefs.edit().putBoolean("allow_screenshots", v).apply()
        _allowScreenshots.value = v
    }

    fun setSpeakReplies(v: Boolean) {
        prefs.edit().putBoolean("speak_replies", v).apply()
        _speakReplies.value = v
    }

    fun setVoiceLanguage(v: String) {
        prefs.edit().putString("voice_language", v).apply()
        _voiceLanguage.value = v
    }

    fun setExtraBlocked(v: Set<String>) {
        prefs.edit().putStringSet("extra_blocked", v).apply()
        _extraBlocked.value = v
    }

    fun setMirrorNotifications(v: Boolean) {
        prefs.edit().putBoolean("mirror_notifications", v).apply()
        _mirrorNotifications.value = v
    }

    fun setPhoneEvents(v: Boolean) {
        prefs.edit().putBoolean("phone_events", v).apply()
        _phoneEvents.value = v
    }

    fun setAutoStart(v: Boolean) {
        prefs.edit().putBoolean("auto_start", v).apply()
        _autoStart.value = v
    }
}
