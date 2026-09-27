package com.letvler.nixin.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import com.letvler.nixin.Nixin
import com.letvler.nixin.core.AppState

/** Confirmation / choice / free-text question coming from the PC brain. */
@Composable
fun AskDialog(ask: AppState.Ask) {
    var text by remember(ask.id) { mutableStateOf("") }
    fun answer(v: String) = Nixin.link.answer(ask.id, v)
    AlertDialog(
        onDismissRequest = { answer("no") },
        title = { Text("Nixin asks") },
        text = {
            Column {
                Text(ask.text)
                when (ask.kind) {
                    "choose" -> ask.options.forEach { o ->
                        TextButton(onClick = { answer(o) }, modifier = Modifier.fillMaxWidth()) { Text(o) }
                    }
                    "input" -> OutlinedTextField(value = text, onValueChange = { text = it }, modifier = Modifier.fillMaxWidth())
                }
            }
        },
        confirmButton = {
            when (ask.kind) {
                "confirm" -> Button(onClick = { answer("yes") }) { Text("Haan / Yes") }
                "input" -> Button(onClick = { answer(text) }, enabled = text.isNotBlank()) { Text("Send") }
                else -> Unit
            }
        },
        dismissButton = { TextButton(onClick = { answer("no") }) { Text(if (ask.kind == "confirm") "Nahi / No" else "Cancel") } },
    )
}
