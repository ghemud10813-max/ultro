package com.letvler.nixin.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val NixinPurple = Color(0xFF7C5CFF)
val NixinCyan = Color(0xFF22D3EE)
val NixinDanger = Color(0xFFEF4444)
val NixinOk = Color(0xFF34D399)
val NixinWarn = Color(0xFFFBBF24)

private val Dark = darkColorScheme(
    primary = NixinPurple,
    onPrimary = Color.White,
    secondary = NixinCyan,
    background = Color(0xFF0B0D12),
    surface = Color(0xFF12151D),
    surfaceVariant = Color(0xFF1B1F2B),
    onBackground = Color(0xFFE8EAF2),
    onSurface = Color(0xFFE8EAF2),
    onSurfaceVariant = Color(0xFF9AA0B2),
    error = NixinDanger,
)

private val Light = lightColorScheme(
    primary = NixinPurple,
    onPrimary = Color.White,
    secondary = Color(0xFF0891B2),
    background = Color(0xFFF5F6FA),
    surface = Color.White,
    surfaceVariant = Color(0xFFECEFF6),
    error = NixinDanger,
)

@Composable
fun NixinTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) Dark else Light, content = content)
}
