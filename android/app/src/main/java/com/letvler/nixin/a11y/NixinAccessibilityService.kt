package com.letvler.nixin.a11y

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import com.letvler.nixin.Nixin
import com.letvler.nixin.core.AppState

/**
 * Nixin's eyes and hands inside other apps. It does nothing on its own: it only acts
 * when the paired PC asks (through the policy checks in the dispatcher) or when you use
 * the in-app controls.
 */
class NixinAccessibilityService : AccessibilityService() {

    companion object {
        @Volatile
        var instance: NixinAccessibilityService? = null
            private set

        private val IGNORED_FOREGROUND = setOf("com.android.systemui")
    }

    private var lastPackage: String? = null

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Nixin.onAccessibilityChanged(true)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        if (event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED ||
            event.eventType == AccessibilityEvent.TYPE_WINDOWS_CHANGED
        ) {
            val pkg = currentPackage() ?: return
            if (pkg != lastPackage) {
                lastPackage = pkg
                AppState.setForeground(pkg)
                Nixin.onForegroundChanged(pkg)
            }
        }
    }

    override fun onInterrupt() {}

    override fun onUnbind(intent: Intent?): Boolean {
        instance = null
        Nixin.onAccessibilityChanged(false)
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        instance = null
        Nixin.onAccessibilityChanged(false)
        super.onDestroy()
    }

    /** Root of the focused *application* window (ignores keyboards, system bars, overlays). */
    fun appRoot(): AccessibilityNodeInfo? {
        val ws = runCatching { windows }.getOrNull().orEmpty()
        val app = ws.firstOrNull { it.type == AccessibilityWindowInfo.TYPE_APPLICATION && (it.isActive || it.isFocused) }
            ?: ws.firstOrNull { it.type == AccessibilityWindowInfo.TYPE_APPLICATION }
        return app?.root ?: rootInActiveWindow
    }

    fun currentPackage(): String? {
        val pkg = appRoot()?.packageName?.toString()
        return if (pkg == null || pkg in IGNORED_FOREGROUND) lastPackage ?: pkg else pkg
    }

    fun windowTitle(): String? = runCatching {
        windows.firstOrNull { it.type == AccessibilityWindowInfo.TYPE_APPLICATION && (it.isActive || it.isFocused) }
            ?.title?.toString()
    }.getOrNull()

    fun keyboardVisible(): Boolean =
        runCatching { windows.any { it.type == AccessibilityWindowInfo.TYPE_INPUT_METHOD } }.getOrDefault(false)
}
