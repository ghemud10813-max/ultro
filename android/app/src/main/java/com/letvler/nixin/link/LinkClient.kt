package com.letvler.nixin.link

import android.os.Build
import com.letvler.nixin.BuildConfig
import com.letvler.nixin.Nixin
import com.letvler.nixin.core.AppState
import com.letvler.nixin.core.arr
import com.letvler.nixin.core.bool
import com.letvler.nixin.core.jsonOf
import com.letvler.nixin.core.long
import com.letvler.nixin.core.obj
import com.letvler.nixin.core.parseObject
import com.letvler.nixin.core.str
import com.letvler.nixin.dispatch.Dispatcher
import com.letvler.nixin.dispatch.Reply
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.UUID
import javax.net.ssl.SSLException
import kotlin.coroutines.coroutineContext

/**
 * Keeps one authenticated WebSocket to the paired PC:
 *   hello(nonce) -> pair|auth(ECDSA signature) -> welcome -> req/res, say, ask, cancel, ping ...
 * Reconnects with exponential backoff and immediately when the network comes back.
 */
class LinkClient(private val scope: CoroutineScope, private val dispatcher: Dispatcher) {

    private sealed interface Ev {
        data class Msg(val text: String) : Ev
        data class Closed(val code: Int, val reason: String) : Ev
        data class Failed(val error: Throwable) : Ev
    }

    private enum class End { NEVER_CONNECTED, DROPPED, DENIED, CERT_MISMATCH }

    @Volatile private var socket: WebSocket? = null
    @Volatile var connected = false
        private set
    @Volatile private var pendingPairing: PairingPayload? = null
    @Volatile private var fatalError: String? = null
    private var loopJob: Job? = null
    private val wake = Channel<Unit>(Channel.CONFLATED)
    private val clients = HashMap<String, OkHttpClient>()
    private var lastForegroundSent = 0L

    fun start() {
        if (loopJob?.isActive == true) return
        loopJob = scope.launch { loop() }
    }

    fun stop() {
        loopJob?.cancel()
        loopJob = null
        socket?.close(1000, "service stopped")
        socket = null
        connected = false
        AppState.setLink(AppState.Link.Offline)
    }

    fun pair(p: PairingPayload) {
        pendingPairing = p
        fatalError = null
        socket?.close(1000, "re-pairing")
        start()
        reconnectNow()
    }

    fun reconnectNow() {
        wake.trySend(Unit)
    }

    // ------------------------------------------------------------------ outbound API (UI / services)
    fun send(obj: JsonObject): Boolean = socket?.send(obj.toString()) ?: false

    fun sendCommand(text: String, source: String): Boolean {
        val ok = connected && send(jsonOf("t" to "cmd", "id" to UUID.randomUUID().toString(), "text" to text, "source" to source))
        if (ok) {
            AppState.addChat(AppState.ChatMessage(true, text))
            AppState.setBusy(true)
        }
        return ok
    }

    fun answer(askId: String, value: String) {
        send(jsonOf("t" to "answer", "id" to askId, "value" to value))
        if (AppState.ask.value?.id == askId) AppState.setAsk(null)
        Nixin.clearAskNotification()
    }

    /** Send a big message (file chunk) without overflowing OkHttp's 16 MB outgoing queue. */
    suspend fun sendLarge(obj: JsonObject): Boolean {
        while (connected && (socket?.queueSize() ?: 0L) > 2_000_000L) delay(40)
        return connected && send(obj)
    }

    fun sendEvent(name: String, data: JsonObject) {
        if (connected) send(jsonOf("t" to "event", "name" to name, "data" to data))
    }

    fun sendStatus() {
        if (!connected) return
        scope.launch { runCatching { sendEvent("status", Nixin.device.status()) } }
    }

    fun sendForeground(pkg: String) {
        val now = System.currentTimeMillis()
        if (!connected || now - lastForegroundSent < 700) return
        lastForegroundSent = now
        sendEvent("foreground", jsonOf("package" to pkg, "label" to Nixin.appLabel(pkg)))
    }

    // ------------------------------------------------------------------ connection loop
    private suspend fun loop() {
        var backoff = 1_000L
        while (coroutineContext.isActive) {
            val pairing = pendingPairing
            val paired = Nixin.settings.paired.value
            if (pairing == null && paired == null) {
                AppState.setLink(AppState.Link.Unpaired)
                wake.receive()
                continue
            }
            if (fatalError != null && pairing == null) {
                AppState.setLink(AppState.Link.Error(fatalError!!))
                wake.receive()
                continue
            }
            val endpoints = pairing?.endpoints ?: paired!!.endpoints
            val fp = pairing?.fingerprint ?: paired!!.fingerprint
            var end = End.NEVER_CONNECTED
            for (ep in endpoints) {
                AppState.setLink(AppState.Link.Connecting(ep))
                end = runSession(ep, fp, pairing)
                if (end != End.NEVER_CONNECTED) break
            }
            connected = false
            socket = null
            when (end) {
                End.DROPPED -> backoff = 1_000L
                End.DENIED -> Unit
                End.CERT_MISMATCH -> AppState.setLink(AppState.Link.Error("PC certificate changed — scan a new pairing QR"))
                End.NEVER_CONNECTED -> if (AppState.link.value !is AppState.Link.Error) AppState.setLink(AppState.Link.Offline)
            }
            if (end == End.DENIED) continue
            withTimeoutOrNull(backoff) { wake.receive() }
            backoff = (backoff * 2).coerceAtMost(30_000L)
        }
    }

    private fun client(fp: String) = synchronized(clients) { clients.getOrPut(fp) { PinnedTls.client(fp) } }

    private suspend fun runSession(endpoint: String, fp: String, pairing: PairingPayload?): End {
        val events = Channel<Ev>(Channel.UNLIMITED)
        val ws = client(fp).newWebSocket(Request.Builder().url(endpoint).build(), object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) { events.trySend(Ev.Msg(text)) }
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(code, reason)
                events.trySend(Ev.Closed(code, reason))
            }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { events.trySend(Ev.Closed(code, reason)) }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { events.trySend(Ev.Failed(t)) }
        })
        socket = ws
        try {
            // 1. hello
            val hello = when (val e = withTimeoutOrNull(10_000) { events.receive() }) {
                is Ev.Msg -> parseObject(e.text)
                is Ev.Failed -> return if (isCertError(e.error)) End.CERT_MISMATCH else End.NEVER_CONNECTED
                else -> return End.NEVER_CONNECTED
            } ?: return End.NEVER_CONNECTED
            if (hello.str("t") != "hello") return End.NEVER_CONNECTED
            val nonce = hello.str("nonce") ?: return End.NEVER_CONNECTED
            val pcId = hello.str("pcId") ?: return End.NEVER_CONNECTED
            val expectedPc = pairing?.pcId ?: Nixin.settings.paired.value?.pcId
            if (expectedPc != null && expectedPc != pcId) {
                fatalError = "A different PC answered at $endpoint — pair again"
                return End.DENIED
            }

            // 2. prove who we are
            val deviceId = Nixin.settings.deviceId
            val msg = if (pairing != null) {
                jsonOf(
                    "t" to "pair", "v" to 1, "deviceId" to deviceId, "token" to pairing.token,
                    "publicKey" to KeyManager.publicKeyB64(), "deviceName" to deviceName(), "model" to Build.MODEL,
                    "sdk" to Build.VERSION.SDK_INT, "appVersion" to BuildConfig.VERSION_NAME,
                    "sig" to KeyManager.sign(KeyManager.pairMessage(pcId, nonce, pairing.token, deviceId)),
                )
            } else {
                jsonOf(
                    "t" to "auth", "v" to 1, "deviceId" to deviceId, "sdk" to Build.VERSION.SDK_INT,
                    "appVersion" to BuildConfig.VERSION_NAME,
                    "sig" to KeyManager.sign(KeyManager.authMessage(pcId, nonce, deviceId)),
                )
            }
            ws.send(msg.toString())

            // 3. welcome or denied
            val reply = (withTimeoutOrNull(10_000) { events.receive() } as? Ev.Msg)?.let { parseObject(it.text) }
                ?: return End.NEVER_CONNECTED
            if (reply.str("t") == "denied") {
                val code = reply.str("code") ?: "auth.failed"
                fatalError = reply.str("message") ?: code
                if (pairing != null) pendingPairing = null
                AppState.setLink(AppState.Link.Error(fatalError!!))
                return End.DENIED
            }
            if (reply.str("t") != "welcome") return End.NEVER_CONNECTED
            if (pairing != null) {
                Nixin.settings.savePaired(pairing)
                pendingPairing = null
            }
            Nixin.settings.pcBlocked = reply.arr("blocklist")?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }?.toSet().orEmpty()
            val pcName = reply.str("pcName") ?: pairing?.pcName ?: Nixin.settings.paired.value?.pcName ?: "PC"
            fatalError = null
            connected = true
            AppState.setLink(AppState.Link.Connected(pcName))
            Nixin.onConnected()
            sendStatus()
            val statusTicker = scope.launch {
                while (isActive) {
                    delay(60_000)
                    sendStatus()
                }
            }

            // 4. session
            try {
                while (true) {
                    val e = withTimeoutOrNull(65_000) { events.receive() } ?: return End.DROPPED // PC silent too long
                    when (e) {
                        is Ev.Msg -> parseObject(e.text)?.let { handle(it) }
                        is Ev.Closed -> {
                            if (e.code == 4006) {
                                fatalError = "This PC removed the pairing — pair again"
                                return End.DENIED
                            }
                            return End.DROPPED
                        }
                        is Ev.Failed -> return End.DROPPED
                    }
                }
            } finally {
                statusTicker.cancel()
                connected = false
                Nixin.onDisconnected()
            }
        } finally {
            ws.cancel()
        }
    }

    private fun isCertError(t: Throwable): Boolean {
        var c: Throwable? = t
        while (c != null) {
            if (c is SSLException || c is java.security.cert.CertificateException) return true
            c = c.cause
        }
        return false
    }

    private fun deviceName(): String {
        val m = Build.MODEL ?: "Android"
        return if (m.startsWith(Build.MANUFACTURER ?: "", ignoreCase = true)) m else "${Build.MANUFACTURER} $m"
    }

    // ------------------------------------------------------------------ inbound
    private fun handle(m: JsonObject) {
        when (m.str("t")) {
            "req" -> {
                val id = m.str("id") ?: return
                val method = m.str("method") ?: return
                val params = m.obj("params") ?: JsonObject(emptyMap())
                val meta = m.obj("meta")
                val timeout = m.long("timeoutMs") ?: 15_000L
                scope.launch {
                    val reply = dispatcher.handle(id, method, params, meta, timeout)
                    val out = when (reply) {
                        is Reply.Ok -> jsonOf("t" to "res", "id" to id, "ok" to true, "result" to reply.result)
                        is Reply.Err -> jsonOf("t" to "res", "id" to id, "ok" to false,
                            "error" to mapOf("code" to reply.code, "message" to reply.message))
                    }
                    send(out)
                }
            }
            "ping" -> send(jsonOf("t" to "pong", "ts" to m["ts"]))
            "pong" -> Unit
            "say" -> {
                val text = m.str("text") ?: return
                AppState.addChat(AppState.ChatMessage(false, text))
                AppState.setBusy(false)
                if (m.bool("speak") == true && Nixin.settings.speakReplies.value) Nixin.speaker.speak(text)
            }
            "ask" -> {
                val opts = m.arr("options")?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.orEmpty()
                val ask = AppState.Ask(m.str("id") ?: return, m.str("kind") ?: "confirm", m.str("text") ?: "", opts, m.str("taskId"))
                AppState.setAsk(ask)
                Nixin.showAskNotification(ask)
                if (Nixin.settings.speakReplies.value) Nixin.speaker.speak(ask.text)
            }
            "echo" -> m.str("text")?.let { AppState.addChat(AppState.ChatMessage(true, it)) }
            "scenes" -> AppState.setScenes(m.arr("items")?.mapNotNull { el ->
                (el as? JsonObject)?.let { o -> o.str("label")?.let { l -> AppState.Scene(l, o.str("text") ?: l) } }
            }.orEmpty())
            "file_ack" -> AppState.addChat(AppState.ChatMessage(false,
                if (m.bool("ok") == true) "✓ PC pe save ho gaya: ${m.str("name") ?: "file"}" else "✗ PC pe file nahi gayi: ${m.str("error") ?: "?"}"))
            "cancel" -> {
                dispatcher.cancelTask(m.str("taskId"))
                AppState.setBusy(false)
            }
            else -> Unit
        }
    }
}
