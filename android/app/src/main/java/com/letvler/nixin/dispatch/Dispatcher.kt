package com.letvler.nixin.dispatch

import com.letvler.nixin.Nixin
import com.letvler.nixin.a11y.UiController
import com.letvler.nixin.capabilities.AppControl
import com.letvler.nixin.capabilities.CommControl
import com.letvler.nixin.capabilities.DeviceControl
import com.letvler.nixin.core.AppState
import com.letvler.nixin.core.ErrorCode
import com.letvler.nixin.core.NixinException
import com.letvler.nixin.core.bool
import com.letvler.nixin.core.jsonOf
import com.letvler.nixin.core.str
import com.letvler.nixin.policy.Methods
import com.letvler.nixin.service.NotificationWatcher
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonObject
import java.util.concurrent.ConcurrentHashMap

/** Result of one PC request, ready to be sent back as {"t":"res",...}. */
sealed interface Reply {
    data class Ok(val result: JsonObject) : Reply
    data class Err(val code: String, val message: String) : Reply
}

/**
 * The phone-side policy firewall + method router. Every PC request passes through here:
 *   unknown method? -> kill switch? -> external needs confirmed? -> handler with timeout.
 * Screen-level checks (lock, blocked app, sensitive fields/taps) live in UiController.
 */
private typealias Handler = suspend (JsonObject, Boolean) -> JsonObject

/** Forces a lambda to be typed as a suspend handler (map literals would infer a plain function). */
private fun h(f: Handler): Handler = f

class Dispatcher(
    private val device: DeviceControl,
    private val apps: AppControl,
    private val comm: CommControl,
) {
    private val handlers: Map<String, Handler> = mapOf(
        "device.status" to h { _, _ -> device.status() },
        "device.volume" to h { p, _ -> device.volume(p) },
        "device.torch" to h { p, _ -> device.torch(p) },
        "device.brightness" to h { p, _ -> device.brightness(p) },
        "device.ringer" to h { p, _ -> device.ringer(p) },
        "device.dnd" to h { p, _ -> device.dnd(p) },
        "device.global" to h { p, _ -> device.global(p) },
        "device.settings" to h { p, _ -> device.settingsPanel(p) },
        "app.list" to h { _, _ -> apps.list() },
        "app.open" to h { p, _ -> apps.open(p) },
        "app.current" to h { _, _ -> apps.current() },
        "intent.url" to h { p, _ -> apps.url(p) },
        "intent.search" to h { p, _ -> apps.search(p) },
        "intent.navigate" to h { p, _ -> apps.navigate(p) },
        "intent.alarm" to h { p, _ -> apps.alarm(p) },
        "intent.timer" to h { p, _ -> apps.timer(p) },
        "media.control" to h { p, _ -> device.media(p) },
        "contacts.search" to h { p, _ -> comm.searchContacts(p) },
        "comm.call" to h { p, _ -> comm.call(p) },
        "comm.sms" to h { p, _ -> comm.sms(p) },
        "comm.whatsapp" to h { p, _ -> comm.whatsapp(p) },
        "notif.list" to h { p, _ -> NotificationWatcher.list(p) },
        "ui.snapshot" to h { p, _ -> UiController.snapshot(p) },
        "ui.tap" to h { p, c -> UiController.tap(p, c) },
        "ui.long_press" to h { p, c -> UiController.tap(p, c, long = true) },
        "ui.type" to h { p, _ -> UiController.type(p) },
        "ui.scroll" to h { p, _ -> UiController.scroll(p) },
        "ui.swipe" to h { p, _ -> UiController.swipe(p) },
        "ui.key" to h { p, _ -> UiController.key(p) },
        "ui.tap_text" to h { p, c -> UiController.tapText(p, c) },
        "ui.wait" to h { p, _ -> UiController.waitFor(p) },
        "screen.capture" to h { p, _ -> UiController.screenshot(p) },
    )

    val implemented: Set<String> get() = handlers.keys

    /** In-flight jobs per task, so the PC (or the kill switch) can cancel them. */
    private val jobs = ConcurrentHashMap<String, MutableSet<Job>>()

    /** Duplicate request ids return the cached reply instead of running twice. */
    private val recent = object : LinkedHashMap<String, Reply>(64, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, Reply>?) = size > 300
    }

    suspend fun handle(id: String, method: String, params: JsonObject, meta: JsonObject?, timeoutMs: Long): Reply {
        synchronized(recent) { recent[id] }?.let { return it }
        val reply = execute(method, params, meta, timeoutMs)
        synchronized(recent) { recent[id] = reply }
        val ok = reply is Reply.Ok
        if (method != "device.status" && method != "ui.snapshot" && method != "screen.capture") {
            AppState.addLog(AppState.ActionLog(method, ok, if (reply is Reply.Err) "${reply.code}: ${reply.message}" else ""))
        }
        return reply
    }

    private suspend fun execute(method: String, params: JsonObject, meta: JsonObject?, timeoutMs: Long): Reply {
        val handler = handlers[method] ?: return Reply.Err(ErrorCode.UNKNOWN_METHOD, "Phone does not support $method")
        val risk = Methods.risk(method) ?: Methods.NAV
        if (Nixin.settings.stopped.value && method !in Methods.ALLOWED_WHEN_STOPPED) {
            return Reply.Err(ErrorCode.STOPPED, "Kill switch is on — resume from the Nixin app")
        }
        val confirmed = meta?.bool("confirmed") == true
        if (risk == Methods.EXTERNAL && !confirmed) {
            return Reply.Err(ErrorCode.CONFIRMATION_REQUIRED, "$method affects other people and needs confirmation")
        }
        val taskId = meta?.str("taskId") ?: "_"
        val job = currentCoroutineContext()[Job]
        job?.let { jobs.getOrPut(taskId) { ConcurrentHashMap.newKeySet() }.add(it) }
        return try {
            Reply.Ok(withTimeout(timeoutMs.coerceIn(500, 120_000)) { handler(params, confirmed) })
        } catch (e: TimeoutCancellationException) {
            Reply.Err(if (risk == Methods.EXTERNAL) ErrorCode.UNCERTAIN else ErrorCode.TIMEOUT, "$method timed out")
        } catch (e: CancellationException) {
            Reply.Err(if (risk == Methods.EXTERNAL) ErrorCode.UNCERTAIN else ErrorCode.CANCELLED, "Cancelled")
        } catch (e: NixinException) {
            Reply.Err(e.code, e.message ?: e.code)
        } catch (e: SecurityException) {
            Reply.Err(ErrorCode.FAILED, "Android denied: ${e.message}")
        } catch (e: Exception) {
            Reply.Err(ErrorCode.INTERNAL, e.javaClass.simpleName + ": " + (e.message ?: ""))
        } finally {
            job?.let { jobs[taskId]?.remove(it) }
        }
    }

    fun cancelTask(taskId: String?) {
        if (taskId == null) return
        jobs.remove(taskId)?.forEach { it.cancel(CancellationException("cancelled by PC")) }
    }

    fun cancelAll() {
        jobs.values.forEach { set -> set.forEach { it.cancel(CancellationException("kill switch")) } }
        jobs.clear()
    }

    companion object {
        fun ok(vararg pairs: Pair<String, Any?>) = Reply.Ok(jsonOf(*pairs))
    }
}
