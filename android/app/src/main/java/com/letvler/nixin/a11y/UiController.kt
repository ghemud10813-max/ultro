package com.letvler.nixin.a11y

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.app.KeyguardManager
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Path
import android.graphics.Rect
import android.os.Bundle
import android.util.Base64
import android.view.Display
import android.view.WindowManager
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction
import com.letvler.nixin.Nixin
import com.letvler.nixin.core.ErrorCode
import com.letvler.nixin.core.NixinException
import com.letvler.nixin.core.bool
import com.letvler.nixin.core.fail
import com.letvler.nixin.core.int
import com.letvler.nixin.core.jsonOf
import com.letvler.nixin.core.reqInt
import com.letvler.nixin.core.reqStr
import com.letvler.nixin.core.str
import com.letvler.nixin.policy.SafetyRules
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonObject
import java.io.ByteArrayOutputStream
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** Everything Nixin does *inside* apps: read the screen and act on it, with policy checks first. */
object UiController {

    private class Snapshot(val id: String, val pkg: String?, val nodes: Map<Int, AccessibilityNodeInfo>)

    @Volatile private var latest: Snapshot? = null
    private var counter = 0

    fun service(): NixinAccessibilityService =
        NixinAccessibilityService.instance ?: fail(ErrorCode.PERM_ACCESSIBILITY, "Enable Nixin in Accessibility settings")

    private fun ctx(): Context = Nixin.app

    /** Throws when the screen must not be observed/automated right now. */
    fun guardScreen(svc: NixinAccessibilityService = service()): String? {
        val km = ctx().getSystemService(KeyguardManager::class.java)
        if (km.isKeyguardLocked) fail(ErrorCode.LOCKED, "Phone is locked")
        val pkg = svc.currentPackage()
        if (SafetyRules.isBlocked(pkg, Nixin.settings.blocked)) fail(ErrorCode.BLOCKED_APP, "$pkg is blocked for safety")
        return pkg
    }

    fun screenSize(): Pair<Int, Int> {
        val wm = ctx().getSystemService(WindowManager::class.java)
        val b = wm.currentWindowMetrics.bounds
        return b.width() to b.height()
    }

    // ------------------------------------------------------------------ snapshot
    fun snapshot(params: JsonObject): JsonObject {
        val svc = service()
        val pkg = guardScreen(svc)
        val root = svc.appRoot() ?: fail(ErrorCode.FAILED, "No active window")
        val (w, h) = screenSize()
        val ser = ScreenSerializer(maxElements = (params.int("maxElements") ?: 150).coerceIn(10, 300), screenWidth = w, screenHeight = h)
        val elements = ser.serialize(AndroidUiNode(root))
        val id = "s${++counter}"
        latest = Snapshot(id, pkg, elements.associate { it.id to it.node.info })
        return jsonOf(
            "snapshotId" to id,
            "package" to pkg,
            "app" to Nixin.appLabel(pkg),
            "title" to svc.windowTitle(),
            "width" to w,
            "height" to h,
            "keyboard" to svc.keyboardVisible(),
            "truncated" to ser.truncated,
            "elements" to elements.map { it.json },
        )
    }

    private fun resolve(params: JsonObject): AccessibilityNodeInfo {
        val snap = latest ?: fail(ErrorCode.STALE, "Take a snapshot first")
        val sid = params.str("snapshotId")
        if (sid != null && sid != snap.id) fail(ErrorCode.STALE, "Snapshot $sid is out of date (latest ${snap.id})")
        val id = params.reqInt("elementId")
        val node = snap.nodes[id] ?: fail(ErrorCode.NOT_FOUND, "No element $id in ${snap.id}")
        if (!node.refresh() || !node.isVisibleToUser) fail(ErrorCode.STALE, "Element $id is no longer on screen")
        if (SafetyRules.isBlocked(node.packageName?.toString(), Nixin.settings.blocked)) fail(ErrorCode.BLOCKED_APP)
        return node
    }

    private fun labelOf(n: AccessibilityNodeInfo?): String {
        if (n == null) return ""
        val parts = mutableListOf<String>()
        n.text?.let { if (!n.isPassword) parts.add(it.toString()) }
        n.contentDescription?.let { parts.add(it.toString()) }
        n.viewIdResourceName?.substringAfter(":id/", "")?.takeIf { it.isNotEmpty() }?.let { parts.add(it) }
        if (parts.isEmpty()) {
            for (i in 0 until minOf(n.childCount, 4)) labelOf(n.getChild(i)).takeIf { it.isNotBlank() }?.let { parts.add(it) }
        }
        return parts.joinToString(" ")
    }

    private fun requireConfirmationIfSensitive(n: AccessibilityNodeInfo?, confirmed: Boolean) {
        if (!confirmed && SafetyRules.isSensitiveLabel(labelOf(n))) {
            fail(ErrorCode.CONFIRMATION_REQUIRED, "'${labelOf(n).take(40)}' may send or change something")
        }
    }

    private fun center(n: AccessibilityNodeInfo): Pair<Float, Float> {
        val r = Rect()
        n.getBoundsInScreen(r)
        return r.exactCenterX() to r.exactCenterY()
    }

    /** Deepest visible node containing (x, y) — used to safety-check coordinate taps. */
    private fun nodeAt(root: AccessibilityNodeInfo?, x: Int, y: Int, depth: Int = 0): AccessibilityNodeInfo? {
        if (root == null || depth > 50) return null
        val r = Rect()
        root.getBoundsInScreen(r)
        if (!r.contains(x, y) || !root.isVisibleToUser) return null
        for (i in root.childCount - 1 downTo 0) nodeAt(root.getChild(i), x, y, depth + 1)?.let { return it }
        return root
    }

    // ------------------------------------------------------------------ gestures
    suspend fun gesture(path: Path, durationMs: Long): Boolean {
        val svc = service()
        val g = GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(path, 0, durationMs.coerceIn(1, 60_000))).build()
        return withTimeoutOrNull(durationMs + 3000) {
            suspendCancellableCoroutine { cont ->
                val ok = svc.dispatchGesture(g, object : AccessibilityService.GestureResultCallback() {
                    override fun onCompleted(d: GestureDescription?) { if (cont.isActive) cont.resume(true) }
                    override fun onCancelled(d: GestureDescription?) { if (cont.isActive) cont.resume(false) }
                }, null)
                if (!ok && cont.isActive) cont.resume(false)
            }
        } ?: false
    }

    private suspend fun tapAt(x: Float, y: Float, long: Boolean): Boolean {
        val p = Path().apply { moveTo(x, y); lineTo(x + 1, y + 1) }
        return gesture(p, if (long) 800 else 60)
    }

    // ------------------------------------------------------------------ actions
    suspend fun tap(params: JsonObject, confirmed: Boolean, long: Boolean = false): JsonObject {
        val svc = service()
        guardScreen(svc)
        if (params.int("elementId") != null) {
            val n = resolve(params)
            requireConfirmationIfSensitive(n, confirmed)
            val action = if (long) AccessibilityNodeInfo.ACTION_LONG_CLICK else AccessibilityNodeInfo.ACTION_CLICK
            var target: AccessibilityNodeInfo? = n
            var done = false
            while (target != null && !done) {
                if ((if (long) target.isLongClickable else target.isClickable) && target.performAction(action)) done = true
                else target = target.parent
            }
            if (!done) {
                val (x, y) = center(n)
                if (!tapAt(x, y, long)) fail(ErrorCode.FAILED, "Tap was rejected")
            }
            return jsonOf("tapped" to labelOf(n).take(80), "method" to if (done) "action" else "gesture")
        }
        val x = params.reqInt("x")
        val y = params.reqInt("y")
        requireConfirmationIfSensitive(nodeAt(svc.appRoot(), x, y), confirmed)
        if (!tapAt(x.toFloat(), y.toFloat(), long)) fail(ErrorCode.FAILED, "Tap was rejected")
        return jsonOf("tapped" to listOf(x, y), "method" to "gesture")
    }

    private fun findEditable(root: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        root ?: return null
        root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)?.takeIf { it.isEditable }?.let { return it }
        val queue = ArrayDeque<AccessibilityNodeInfo>().apply { add(root) }
        var visited = 0
        while (queue.isNotEmpty() && visited < 2000) {
            val n = queue.removeFirst()
            visited++
            if (n.isEditable && n.isVisibleToUser) return n
            for (i in 0 until n.childCount) n.getChild(i)?.let { queue.add(it) }
        }
        return null
    }

    suspend fun type(params: JsonObject): JsonObject {
        val svc = service()
        guardScreen(svc)
        val text = params.reqStr("text")
        val node = if (params.int("elementId") != null) resolve(params) else findEditable(svc.appRoot())
            ?: fail(ErrorCode.NOT_EDITABLE, "No text field is focused")
        if (!node.isEditable) fail(ErrorCode.NOT_EDITABLE, "Element is not a text field")
        if (SafetyRules.isSensitiveField(node.isPassword, node.hintText?.toString(), node.viewIdResourceName, labelOf(node))) {
            fail(ErrorCode.SENSITIVE_FIELD, "Refusing to type into a password/OTP field")
        }
        val clear = params.bool("clear") ?: true
        val existing = if (node.isShowingHintText) "" else node.text?.toString().orEmpty()
        val value = if (clear) text else existing + text
        node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        val args = Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, value) }
        if (!node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
            // some fields only accept text after a click
            node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            delay(150)
            if (!node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) fail(ErrorCode.FAILED, "Field rejected the text")
        }
        if (params.bool("submit") == true) {
            delay(120)
            node.refresh()
            if (!node.performAction(AccessibilityAction.ACTION_IME_ENTER.id)) {
                fail(ErrorCode.FAILED, "Field has no submit action; tap the search/send button instead")
            }
        }
        return jsonOf("typed" to text.length, "submitted" to (params.bool("submit") == true))
    }

    private fun largestScrollable(root: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        root ?: return null
        var best: AccessibilityNodeInfo? = null
        var bestArea = 0
        val queue = ArrayDeque<AccessibilityNodeInfo>().apply { add(root) }
        var visited = 0
        val r = Rect()
        while (queue.isNotEmpty() && visited < 3000) {
            val n = queue.removeFirst()
            visited++
            if (n.isScrollable && n.isVisibleToUser) {
                n.getBoundsInScreen(r)
                val area = r.width() * r.height()
                if (area > bestArea) { bestArea = area; best = n }
            }
            for (i in 0 until n.childCount) n.getChild(i)?.let { queue.add(it) }
        }
        return best
    }

    suspend fun scroll(params: JsonObject): JsonObject {
        val svc = service()
        guardScreen(svc)
        val dir = params.reqStr("direction")
        val node = if (params.int("elementId") != null) resolve(params) else largestScrollable(svc.appRoot())
        if (node != null) {
            val directional = when (dir) {
                "down" -> AccessibilityAction.ACTION_SCROLL_DOWN
                "up" -> AccessibilityAction.ACTION_SCROLL_UP
                "left" -> AccessibilityAction.ACTION_SCROLL_LEFT
                else -> AccessibilityAction.ACTION_SCROLL_RIGHT
            }
            if (node.performAction(directional.id)) return jsonOf("scrolled" to dir, "method" to "action")
            val generic = if (dir == "down" || dir == "right") AccessibilityNodeInfo.ACTION_SCROLL_FORWARD
            else AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
            if (node.performAction(generic)) return jsonOf("scrolled" to dir, "method" to "action")
        }
        // gesture fallback: swipe opposite to the content direction
        val (w, h) = screenSize()
        val p = Path()
        when (dir) {
            "down" -> { p.moveTo(w / 2f, h * 0.72f); p.lineTo(w / 2f, h * 0.30f) }
            "up" -> { p.moveTo(w / 2f, h * 0.30f); p.lineTo(w / 2f, h * 0.72f) }
            "left" -> { p.moveTo(w * 0.2f, h / 2f); p.lineTo(w * 0.8f, h / 2f) }
            else -> { p.moveTo(w * 0.8f, h / 2f); p.lineTo(w * 0.2f, h / 2f) }
        }
        if (!gesture(p, 350)) fail(ErrorCode.NOT_SCROLLABLE, "Nothing scrolled")
        return jsonOf("scrolled" to dir, "method" to "gesture")
    }

    suspend fun swipe(params: JsonObject): JsonObject {
        guardScreen()
        val p = Path().apply {
            moveTo(params.reqInt("x1").toFloat(), params.reqInt("y1").toFloat())
            lineTo(params.reqInt("x2").toFloat(), params.reqInt("y2").toFloat())
        }
        if (!gesture(p, (params.int("durationMs") ?: 300).toLong())) fail(ErrorCode.FAILED, "Swipe was rejected")
        return jsonOf("swiped" to true)
    }

    fun key(params: JsonObject): JsonObject {
        val svc = service()
        when (val k = params.reqStr("key")) {
            "enter" -> {
                guardScreen(svc)
                val n = findEditable(svc.appRoot()) ?: fail(ErrorCode.NOT_EDITABLE, "No focused text field")
                if (!n.performAction(AccessibilityAction.ACTION_IME_ENTER.id)) fail(ErrorCode.FAILED, "Enter not supported here")
            }
            "back" -> svc.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
            "home" -> svc.performGlobalAction(AccessibilityService.GLOBAL_ACTION_HOME)
            "recents" -> svc.performGlobalAction(AccessibilityService.GLOBAL_ACTION_RECENTS)
            else -> fail(ErrorCode.BAD_REQUEST, "Unknown key $k")
        }
        return jsonOf("key" to params.str("key"))
    }

    suspend fun tapText(params: JsonObject, confirmed: Boolean): JsonObject {
        val svc = service()
        guardScreen(svc)
        val q = params.reqStr("text")
        val exact = params.bool("exact") ?: false
        val index = params.int("index") ?: 0
        val root = svc.appRoot() ?: fail(ErrorCode.FAILED, "No active window")
        val matches = root.findAccessibilityNodeInfosByText(q).filter { n ->
            n.isVisibleToUser && (!exact || n.text?.toString().equals(q, true) || n.contentDescription?.toString().equals(q, true))
        }
        val n = matches.getOrNull(index) ?: fail(ErrorCode.NOT_FOUND, "'$q' is not on screen")
        requireConfirmationIfSensitive(n, confirmed)
        var target: AccessibilityNodeInfo? = n
        while (target != null) {
            if (target.isClickable && target.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return jsonOf("tapped" to q)
            target = target.parent
        }
        val (x, y) = center(n)
        if (!tapAt(x, y, false)) fail(ErrorCode.FAILED, "Tap was rejected")
        return jsonOf("tapped" to q)
    }

    suspend fun waitFor(params: JsonObject): JsonObject {
        val svc = service()
        val text = params.str("text")
        val pkg = params.str("package")
        val gone = params.bool("gone") ?: false
        val timeout = (params.int("timeoutMs") ?: 5000).toLong()
        val start = System.currentTimeMillis()
        while (System.currentTimeMillis() - start < timeout) {
            val pkgOk = pkg == null || svc.currentPackage() == pkg
            val textFound = text == null || (svc.appRoot()?.findAccessibilityNodeInfosByText(text)?.any { it.isVisibleToUser } == true)
            if (pkgOk && (if (gone) !textFound || text == null else textFound)) {
                return jsonOf("matched" to true, "ms" to (System.currentTimeMillis() - start))
            }
            delay(250)
        }
        return jsonOf("matched" to false, "ms" to timeout)
    }

    suspend fun screenshot(params: JsonObject): JsonObject {
        if (!Nixin.settings.allowScreenshots.value) fail(ErrorCode.SCREENSHOTS_DISABLED, "Enable 'Allow screenshots' in the Nixin app")
        val svc = service()
        guardScreen(svc)
        val maxWidth = (params.int("maxWidth") ?: 720).coerceIn(240, 1440)
        val quality = (params.int("quality") ?: 60).coerceIn(30, 95)
        val bmp: Bitmap = suspendCancellableCoroutine { cont ->
            svc.takeScreenshot(Display.DEFAULT_DISPLAY, svc.mainExecutor, object : AccessibilityService.TakeScreenshotCallback {
                override fun onSuccess(result: AccessibilityService.ScreenshotResult) {
                    val hw = Bitmap.wrapHardwareBuffer(result.hardwareBuffer, result.colorSpace)
                    val soft = hw?.copy(Bitmap.Config.ARGB_8888, false)
                    result.hardwareBuffer.close()
                    if (soft != null) cont.resume(soft)
                    else cont.resumeWithException(NixinException(ErrorCode.FAILED, "Screenshot copy failed"))
                }

                override fun onFailure(errorCode: Int) {
                    cont.resumeWithException(NixinException(ErrorCode.FAILED,
                        if (errorCode == AccessibilityService.ERROR_TAKE_SCREENSHOT_SECURE_WINDOW) "This screen is protected (secure window)"
                        else "Screenshot failed (code $errorCode)"))
                }
            })
        }
        val (sw, sh) = bmp.width to bmp.height
        val scale = minOf(1f, maxWidth.toFloat() / sw)
        val out = if (scale < 1f) Bitmap.createScaledBitmap(bmp, (sw * scale).toInt(), (sh * scale).toInt(), true) else bmp
        val bytes = ByteArrayOutputStream().use { os ->
            out.compress(Bitmap.CompressFormat.JPEG, quality, os)
            os.toByteArray()
        }
        return jsonOf(
            "mime" to "image/jpeg", "width" to out.width, "height" to out.height,
            "screenWidth" to sw, "screenHeight" to sh,
            "data" to Base64.encodeToString(bytes, Base64.NO_WRAP),
        )
    }

    fun global(action: String): Boolean {
        val svc = service()
        val id = when (action) {
            "back" -> AccessibilityService.GLOBAL_ACTION_BACK
            "home" -> AccessibilityService.GLOBAL_ACTION_HOME
            "recents" -> AccessibilityService.GLOBAL_ACTION_RECENTS
            "notifications" -> AccessibilityService.GLOBAL_ACTION_NOTIFICATIONS
            "quick_settings" -> AccessibilityService.GLOBAL_ACTION_QUICK_SETTINGS
            "lock_screen" -> AccessibilityService.GLOBAL_ACTION_LOCK_SCREEN
            "screenshot" -> AccessibilityService.GLOBAL_ACTION_TAKE_SCREENSHOT
            "power_dialog" -> AccessibilityService.GLOBAL_ACTION_POWER_DIALOG
            "split_screen" -> AccessibilityService.GLOBAL_ACTION_TOGGLE_SPLIT_SCREEN
            else -> fail(ErrorCode.BAD_REQUEST, "Unknown action $action")
        }
        return svc.performGlobalAction(id)
    }

    // ------------------------------------------------------------------ helpers for workflows
    fun findById(root: AccessibilityNodeInfo?, fullId: String): AccessibilityNodeInfo? =
        root?.findAccessibilityNodeInfosByViewId(fullId)?.firstOrNull { it.isVisibleToUser }

    fun findByDesc(root: AccessibilityNodeInfo?, desc: String): AccessibilityNodeInfo? {
        root ?: return null
        val queue = ArrayDeque<AccessibilityNodeInfo>().apply { add(root) }
        var visited = 0
        while (queue.isNotEmpty() && visited < 3000) {
            val n = queue.removeFirst()
            visited++
            if (n.isVisibleToUser && n.contentDescription?.toString().equals(desc, ignoreCase = true)) return n
            for (i in 0 until n.childCount) n.getChild(i)?.let { queue.add(it) }
        }
        return null
    }

    fun rootText(root: AccessibilityNodeInfo?, limit: Int = 400): String {
        root ?: return ""
        val sb = StringBuilder()
        val queue = ArrayDeque<AccessibilityNodeInfo>().apply { add(root) }
        while (queue.isNotEmpty() && sb.length < 4000) {
            val n = queue.removeFirst()
            if (n.isVisibleToUser && !n.isPassword) n.text?.let { sb.append(it).append(' ') }
            if (queue.size < limit) for (i in 0 until n.childCount) n.getChild(i)?.let { queue.add(it) }
        }
        return sb.toString()
    }

    /** Invalidate element ids after a UI-changing action done outside the agent flow. */
    fun invalidate() { latest = null }
}
