package com.letvler.nixin.capabilities

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import com.letvler.nixin.Nixin
import com.letvler.nixin.a11y.NixinAccessibilityService

/**
 * Starts activities for the PC. Android blocks background apps from opening screens,
 * but an app with a bound AccessibilityService is exempt — so we launch from that
 * service's context whenever it is running.
 */
object Launcher {
    fun context(): Context = NixinAccessibilityService.instance ?: Nixin.app

    fun start(intent: Intent): Boolean = try {
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context().startActivity(intent)
        true
    } catch (e: ActivityNotFoundException) {
        false
    } catch (e: SecurityException) {
        false
    }
}
