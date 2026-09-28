package com.letvler.nixin.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.letvler.nixin.core.AppState
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Everything the PC made this phone do (in-memory, newest first), plus files the PC sent. */
@Composable
fun ActivityScreen() {
    val log by AppState.log.collectAsStateWithLifecycle()
    val files by AppState.files.collectAsStateWithLifecycle()
    val ctx = LocalContext.current
    val fmt = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        if (files.isNotEmpty()) {
            Text("From your PC", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text("Saved in Downloads/Nixin — tap to open.", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            files.take(5).forEach { f ->
                Text(
                    "📄 ${f.name}  ·  ${f.size / 1024} KB",
                    modifier = Modifier.fillMaxWidth().clickable {
                        runCatching {
                            ctx.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(Uri.parse(f.uri), f.mime ?: "*/*")
                                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
                        }
                    }.padding(vertical = 6.dp),
                    fontSize = 14.sp,
                )
            }
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
        }
        Text("Activity", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Text("Every action the PC asked for, with the result. Kept only in memory.", fontSize = 12.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (log.isEmpty()) {
            Text("Nothing yet.", modifier = Modifier.padding(top = 24.dp))
        }
        LazyColumn(Modifier.fillMaxSize().padding(top = 8.dp)) {
            items(log) { e ->
                Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                    Text(
                        "${fmt.format(Date(e.ts))}  ${if (e.ok) "✓" else "✗"}  ${e.method}",
                        fontFamily = FontFamily.Monospace, fontSize = 13.sp,
                        color = if (e.ok) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.error,
                    )
                    if (e.detail.isNotBlank()) {
                        Text(e.detail, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                HorizontalDivider()
            }
        }
    }
}
