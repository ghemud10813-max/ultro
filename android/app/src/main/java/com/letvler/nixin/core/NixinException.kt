package com.letvler.nixin.core

/** Stable protocol error codes (see shared/protocol/methods.json "errors"). */
object ErrorCode {
    const val BAD_REQUEST = "bad_request"
    const val UNKNOWN_METHOD = "unknown_method"
    const val INTERNAL = "internal"
    const val TIMEOUT = "timeout"
    const val CANCELLED = "cancelled"
    const val LOCKED = "device.locked"
    const val UNSUPPORTED = "device.unsupported"
    const val STOPPED = "policy.stopped"
    const val BLOCKED_APP = "policy.blocked_app"
    const val SENSITIVE_FIELD = "policy.sensitive_field"
    const val CONFIRMATION_REQUIRED = "policy.confirmation_required"
    const val SCREENSHOTS_DISABLED = "policy.screenshots_disabled"
    const val PERM_ACCESSIBILITY = "permission.accessibility"
    const val PERM_NOTIFICATIONS = "permission.notifications"
    const val PERM_CONTACTS = "permission.contacts"
    const val PERM_CALL = "permission.call"
    const val PERM_SMS = "permission.sms"
    const val PERM_WRITE_SETTINGS = "permission.write_settings"
    const val PERM_DND = "permission.dnd"
    const val STALE = "target.stale"
    const val NOT_FOUND = "target.not_found"
    const val NOT_EDITABLE = "target.not_editable"
    const val NOT_SCROLLABLE = "target.not_scrollable"
    const val APP_NOT_INSTALLED = "app.not_installed"
    const val FAILED = "action.failed"
    const val UNCERTAIN = "action.uncertain"
}

class NixinException(val code: String, message: String = code) : Exception(message)

fun fail(code: String, message: String = code): Nothing = throw NixinException(code, message)
