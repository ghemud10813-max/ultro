package com.letvler.nixin.ui

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.util.Base64
import android.widget.Toast
import com.letvler.nixin.Nixin
import com.letvler.nixin.core.AppState
import com.letvler.nixin.core.jsonOf
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.UUID

/**
 * Share sheet target: "Send to PC (Nixin)". Text and links go to the PC inbox (and clipboard);
 * photos and files are streamed in chunks to the PC's "Nixin Inbox" folder.
 */
class ShareActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!handle(intent)) finish()
    }

    private fun toast(msg: String) = Toast.makeText(applicationContext, msg, Toast.LENGTH_SHORT).show()

    /** Returns true when a background copy is running (it finishes the activity itself). */
    private fun handle(intent: Intent?): Boolean {
        if (intent == null) return false
        if (!Nixin.link.connected) {
            toast("PC connected nahi hai — pehle Nixin app kholo")
            return false
        }
        val uris: List<Uri> = when (intent.action) {
            Intent.ACTION_SEND -> listOfNotNull(streamExtra(intent))
            Intent.ACTION_SEND_MULTIPLE -> streamListExtra(intent)
            else -> emptyList()
        }
        if (uris.isEmpty()) {
            val text = intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()?.trim()
            if (text.isNullOrEmpty()) {
                toast("Kuch bhejne layak nahi mila")
                return false
            }
            val subject = intent.getStringExtra(Intent.EXTRA_SUBJECT)
            Nixin.link.send(jsonOf("t" to "share", "text" to text.take(20_000), "subject" to subject))
            AppState.addChat(AppState.ChatMessage(true, "📤 PC ko bheja: ${text.take(80)}"))
            toast("PC pe bhej diya ✓")
            return false
        }
        toast(if (uris.size == 1) "PC pe bhej raha hoon…" else "${uris.size} files PC pe bhej raha hoon…")
        val app = applicationContext
        Nixin.scope.launch {
            // copy while we still hold the read grant, then let the user go back and stream in the background
            val copies = withContext(Dispatchers.IO) { uris.mapNotNull { uri -> runCatching { copyToCache(uri) }.getOrNull() } }
            withContext(Dispatchers.Main) { finish() }
            for ((file, name, mime) in copies) {
                val ok = withContext(Dispatchers.IO) { runCatching { sendFile(file, name, mime) }.getOrDefault(false) }
                file.delete()
                AppState.addChat(AppState.ChatMessage(true, if (ok) "📤 $name" else "✗ $name nahi gaya"))
            }
            withContext(Dispatchers.Main) { Toast.makeText(app, "PC pe bhej diya ✓", Toast.LENGTH_SHORT).show() }
        }
        return true
    }

    private fun copyToCache(uri: Uri): Triple<File, String, String> {
        val (name, mime) = meta(uri)
        val f = File(cacheDir, "share-" + UUID.randomUUID())
        contentResolver.openInputStream(uri)?.use { input -> f.outputStream().use { input.copyTo(it) } }
            ?: error("cannot read $uri")
        if (f.length() > 500L * 1024 * 1024) {
            f.delete()
            error("too large")
        }
        return Triple(f, name, mime)
    }

    @Suppress("DEPRECATION")
    private fun streamExtra(i: Intent): Uri? =
        if (Build.VERSION.SDK_INT >= 33) i.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java) else i.getParcelableExtra(Intent.EXTRA_STREAM)

    @Suppress("DEPRECATION")
    private fun streamListExtra(i: Intent): List<Uri> =
        (if (Build.VERSION.SDK_INT >= 33) i.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java)
        else i.getParcelableArrayListExtra(Intent.EXTRA_STREAM)).orEmpty()

    private fun meta(uri: Uri): Pair<String, String> {
        var name = uri.lastPathSegment?.substringAfterLast('/') ?: "file"
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) c.getString(0)?.let { name = it }
        }
        return name to (contentResolver.getType(uri) ?: "application/octet-stream")
    }

    private suspend fun sendFile(file: File, name: String, mime: String): Boolean {
        val chunk = 300_000
        val total = ((file.length() + chunk - 1) / chunk).toInt().coerceAtLeast(1)
        if (total > 2000) return false
        val tid = UUID.randomUUID().toString()
        file.inputStream().use { input ->
            val buf = ByteArray(chunk)
            for (i in 0 until total) {
                var read = 0
                while (read < chunk) {
                    val n = input.read(buf, read, chunk - read)
                    if (n <= 0) break
                    read += n
                }
                val data = Base64.encodeToString(buf, 0, read, Base64.NO_WRAP)
                if (!Nixin.link.sendLarge(jsonOf("t" to "file", "transferId" to tid, "name" to name, "mime" to mime,
                        "index" to i, "total" to total, "data" to data))) return false
            }
        }
        return true
    }
}
