package com.letvler.nixin.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.letvler.nixin.core.AppState

enum class Tab(val label: String, val icon: ImageVector) {
    Home("Nixin", Icons.Filled.Home),
    Setup("Setup", Icons.Filled.Build),
    Activity("Activity", Icons.AutoMirrored.Filled.List),
    Settings("Settings", Icons.Filled.Settings),
}

@Composable
fun NixinRoot(tab: MutableState<Tab>) {
    val ask by AppState.ask.collectAsStateWithLifecycle()
    Scaffold(
        bottomBar = {
            NavigationBar {
                Tab.entries.forEach { t ->
                    NavigationBarItem(
                        selected = tab.value == t,
                        onClick = { tab.value = t },
                        icon = { Icon(t.icon, contentDescription = t.label) },
                        label = { Text(t.label) },
                    )
                }
            }
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when (tab.value) {
                Tab.Home -> HomeScreen(onOpenSetup = { tab.value = Tab.Setup })
                Tab.Setup -> SetupScreen()
                Tab.Activity -> ActivityScreen()
                Tab.Settings -> SettingsScreen()
            }
        }
    }
    ask?.let { AskDialog(it) }
}
