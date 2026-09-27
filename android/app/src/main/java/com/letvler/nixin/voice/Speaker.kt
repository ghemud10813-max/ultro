package com.letvler.nixin.voice

import android.content.Context
import android.speech.tts.TextToSpeech
import java.util.Locale

/** Android TextToSpeech for Nixin's replies on the phone (Indian English reads Hinglish well). */
class Speaker(private val ctx: Context) {
    @Volatile private var tts: TextToSpeech? = null
    @Volatile private var ready = false
    private val queue = ArrayList<String>()

    private fun ensure() {
        if (tts != null) return
        tts = TextToSpeech(ctx.applicationContext) { status ->
            ready = status == TextToSpeech.SUCCESS
            if (ready) {
                tts?.language = Locale.forLanguageTag("en-IN")
                tts?.setSpeechRate(1.05f)
                synchronized(queue) {
                    queue.forEach { speakNow(it) }
                    queue.clear()
                }
            }
        }
    }

    private fun speakNow(text: String) {
        tts?.speak(text, TextToSpeech.QUEUE_ADD, null, "nixin-" + System.nanoTime())
    }

    fun speak(text: String) {
        if (text.isBlank()) return
        ensure()
        if (ready) speakNow(text) else synchronized(queue) { queue.add(text) }
    }

    fun stop() {
        tts?.stop()
        synchronized(queue) { queue.clear() }
    }
}
