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

    /** Quick-action chip sent by the PC (scenes and taught skills): tapping it sends [text] as a command. */
    data class Scene(val label: String, val text: String)

    /** A file the PC pushed into Downloads/Nixin. */
    data class ReceivedFile(val name: String, val uri: String, val size: Long, val mime: String?, val ts: Long = System.currentTimeMillis())

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

    private val _scenes = MutableStateFlow<List<Scene>>(emptyList())
    val scenes: StateFlow<List<Scene>> = _scenes

    private val _files = MutableStateFlow<List<ReceivedFile>>(emptyList())
    val files: StateFlow<List<ReceivedFile>> = _files

    /** Name of the skill being recorded in teach mode, or null. */
    private val _recording = MutableStateFlow<String?>(null)
    val recording: StateFlow<String?> = _recording

    fun setScenes(s: List<Scene>) { _scenes.value = s }
    fun addFile(f: ReceivedFile) = _files.update { (listOf(f) + it).take(50) }
    fun setRecording(name: String?) { _recording.value = name }

    fun setLink(l: Link) { _link.value = l }
    fun setAsk(a: Ask?) { _ask.value = a }
    fun setBusy(b: Boolean) { _busy.value = b }
    fun setForeground(pkg: String?) { _foreground.value = pkg }

    fun addChat(m: ChatMessage) = _chat.update { (it + m).takeLast(200) }

    fun addLog(e: ActionLog) = _log.update { (listOf(e) + it).take(300) }
}
