package com.letvler.nixin.capabilities

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import android.util.Base64
import com.letvler.nixin.Nixin
import com.letvler.nixin.R
import com.letvler.nixin.core.AppState
import com.letvler.nixin.core.ErrorCode
import com.letvler.nixin.core.fail
import com.letvler.nixin.core.jsonOf
import com.letvler.nixin.core.reqInt
import com.letvler.nixin.core.reqStr
import com.letvler.nixin.core.str
import kotlinx.serialization.json.JsonObject
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.ConcurrentHashMap

/**
 * Receives files the PC pushes (file.push, in order, ~480 KB per chunk) and saves the finished file to
 * Downloads/Nixin through MediaStore (no storage permission needed).
 */
class FileInbox(private val ctx: Context) {
    private class Part(val name: String, val mime: String, val total: Int, val file: File) {
        var next = 0
        var size = 0L
    }

    private val parts = ConcurrentHashMap<String, Part>()

    fun push(p: JsonObject): JsonObject {
        val tid = p.reqStr("transferId").filter { it.isLetterOrDigit() || it == '-' }.take(64)
        val index = p.reqInt("index")
        val total = p.reqInt("total").coerceIn(1, 2000)
        val bytes = runCatching { Base64.decode(p.reqStr("data"), Base64.DEFAULT) }.getOrNull()
            ?: fail(ErrorCode.BAD_REQUEST, "chunk is not base64")
        val part = if (index == 0) {
            parts.remove(tid)?.file?.delete()
            Part(safeName(p.reqStr("name")), p.str("mime") ?: "application/octet-stream", total, File(ctx.cacheDir, "in-$tid"))
                .also { it.file.delete(); parts[tid] = it }
        } else {
            parts[tid] ?: fail(ErrorCode.BAD_REQUEST, "unknown transfer $tid")
        }
        if (index != part.next || total != part.total) {
            parts.remove(tid)?.file?.delete()
            fail(ErrorCode.BAD_REQUEST, "chunk $index out of order (expected ${part.next})")
        }
        FileOutputStream(part.file, true).use { it.write(bytes) }
        part.next++
        part.size += bytes.size
        if (part.next < part.total) return jsonOf("received" to part.next, "total" to part.total)

        parts.remove(tid)
        val uri = saveToDownloads(part)
        part.file.delete()
        AppState.addFile(AppState.ReceivedFile(part.name, uri.toString(), part.size, part.mime))
        showNotification(part, uri)
        return jsonOf("saved" to true, "path" to "Download/Nixin/${part.name}", "uri" to uri.toString(), "size" to part.size)
    }

    private fun saveToDownloads(part: Part): Uri {
        val resolver = ctx.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, part.name)
            put(MediaStore.MediaColumns.MIME_TYPE, part.mime)
            put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/Nixin")
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: fail(ErrorCode.FAILED, "Could not create the file in Downloads")
        resolver.openOutputStream(uri)?.use { out -> part.file.inputStream().use { it.copyTo(out) } }
            ?: fail(ErrorCode.FAILED, "Could not write the file")
        values.clear()
        values.put(MediaStore.MediaColumns.IS_PENDING, 0)
        resolver.update(uri, values, null, null)
        return uri
    }

    private fun showNotification(part: Part, uri: Uri) {
        val view = Intent(Intent.ACTION_VIEW).setDataAndType(uri, part.mime)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        val pi = PendingIntent.getActivity(ctx, uri.hashCode(), view, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n = Notification.Builder(ctx, Nixin.CHANNEL_ALERTS)
            .setSmallIcon(R.drawable.ic_stat_nixin)
            .setContentTitle("From your PC")
            .setContentText("${part.name} saved in Downloads/Nixin")
            .setContentIntent(pi)
            .setAutoCancel(true)
            .build()
        runCatching { ctx.getSystemService(NotificationManager::class.java).notify(4000 + (part.name.hashCode() and 0xfff), n) }
    }

    companion object {
        fun safeName(name: String): String =
            name.substringAfterLast('/').substringAfterLast('\\').replace(Regex("[\\x00-\\x1f<>:\"|?*]"), "_")
                .trim(' ', '.').take(180).ifEmpty { "file" }
    }
}
