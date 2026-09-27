package com.letvler.nixin.core

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update

/** Live state shared by the service, the accessibility service and the UI. */
object AppState {
    sealed interface Link {
        data object Unpaired : Link
        data object Offline : Link
        data class Connecting(val endpoint: String?) : Link
        data class Connected(val pcName: String) : Link
        data class Error(val message: String) : Link
    }

    data class ChatMessage(val fromUser: Boolean, val text: String, val ts: Long = System.currentTimeMillis())

    data class Ask(val id: String, val kind: String, val text: String, val options: List<String>, val taskId: String?)

    data class ActionLog(val method: String, val ok: Boolean, val detail: String, val ts: Long = System.currentTimeMillis())

    private val _link = MutableStateFlow<Link>(Link.Offline)
    val link: StateFlow<Link> = _link

    private val _chat = MutableStateFlow<List<ChatMessage>>(emptyList())
    val chat: StateFlow<List<ChatMessage>> = _chat

    private val _ask = MutableStateFlow<Ask?>(null)
    val ask: StateFlow<Ask?> = _ask

    private val _log = MutableStateFlow<List<ActionLog>>(emptyList())
    val log: StateFlow<List<ActionLog>> = _log

    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy

    private val _foreground = MutableStateFlow<String?>(null)
    val foreground: StateFlow<String?> = _foreground

    fun setLink(l: Link) { _link.value = l }
    fun setAsk(a: Ask?) { _ask.value = a }
    fun setBusy(b: Boolean) { _busy.value = b }
    fun setForeground(pkg: String?) { _foreground.value = pkg }

    fun addChat(m: ChatMessage) = _chat.update { (it + m).takeLast(200) }

    fun addLog(e: ActionLog) = _log.update { (listOf(e) + it).take(300) }
}
