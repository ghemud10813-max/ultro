package com.letvler.nixin.policy

/**
 * Kotlin mirror of shared/protocol/methods.json (method -> risk).
 * MethodsRegistryTest fails if the two ever drift apart.
 */
object Methods {
    const val READ = "read"
    const val NAV = "nav"
    const val LOCAL = "local"
    const val EXTERNAL = "external"

    val RISK: Map<String, String> = mapOf(
        "device.status" to READ,
        "device.volume" to LOCAL,
        "device.torch" to LOCAL,
        "device.brightness" to LOCAL,
        "device.ringer" to LOCAL,
        "device.dnd" to LOCAL,
        "device.global" to NAV,
        "device.settings" to NAV,
        "app.list" to READ,
        "app.open" to NAV,
        "app.current" to READ,
        "intent.url" to NAV,
        "intent.search" to NAV,
        "intent.navigate" to NAV,
        "intent.alarm" to LOCAL,
        "intent.timer" to LOCAL,
        "media.control" to LOCAL,
        "contacts.search" to READ,
        "comm.call" to EXTERNAL,
        "comm.sms" to EXTERNAL,
        "comm.whatsapp" to EXTERNAL,
        "notif.list" to READ,
        "ui.snapshot" to READ,
        "ui.tap" to NAV,
        "ui.long_press" to NAV,
        "ui.type" to NAV,
        "ui.scroll" to NAV,
        "ui.swipe" to NAV,
        "ui.key" to NAV,
        "ui.tap_text" to NAV,
        "ui.wait" to READ,
        "screen.capture" to READ,
    )

    /** Methods allowed while the kill switch is active (read-only status for the PC). */
    val ALLOWED_WHEN_STOPPED = setOf("device.status", "app.list")

    /** Methods that read or act on the foreground app's UI. */
    val SCREEN_METHODS = setOf(
        "ui.snapshot", "ui.tap", "ui.long_press", "ui.type", "ui.scroll", "ui.swipe", "ui.key",
        "ui.tap_text", "ui.wait", "screen.capture",
    )

    fun risk(method: String): String? = RISK[method]
}
