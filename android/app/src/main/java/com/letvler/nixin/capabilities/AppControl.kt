package com.letvler.nixin.capabilities

import android.app.SearchManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.AlarmClock
import com.letvler.nixin.Nixin
import com.letvler.nixin.a11y.NixinAccessibilityService
import com.letvler.nixin.a11y.UiController
import com.letvler.nixin.core.ErrorCode
import com.letvler.nixin.core.arr
import com.letvler.nixin.core.bool
import com.letvler.nixin.core.fail
import com.letvler.nixin.core.int
import com.letvler.nixin.core.jsonOf
import com.letvler.nixin.core.reqInt
import com.letvler.nixin.core.reqStr
import com.letvler.nixin.core.str
import com.letvler.nixin.policy.SafetyRules
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull

/** Apps and intents: list/open apps, URLs, searches, navigation, alarms, timers. */
class AppControl(private val ctx: Context) {
    private val pm = ctx.packageManager

    @Volatile private var cache: List<AppMatcher.App> = emptyList()
    @Volatile private var cacheAt = 0L

    fun apps(force: Boolean = false): List<AppMatcher.App> {
        if (!force && cache.isNotEmpty() && System.currentTimeMillis() - cacheAt < 120_000) return cache
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        cache = pm.queryIntentActivities(intent, 0)
            .map { AppMatcher.App(it.loadLabel(pm).toString(), it.activityInfo.packageName) }
            .distinctBy { it.pkg }
            .filter { it.pkg != ctx.packageName }
            .sortedBy { it.label.lowercase() }
        cacheAt = System.currentTimeMillis()
        return cache
    }

    fun list(): JsonObject = jsonOf("apps" to apps(force = true).map { mapOf("label" to it.label, "package" to it.pkg) })

    fun open(p: JsonObject): JsonObject {
        val pkg = p.str("package") ?: p.str("name")?.let { name ->
            AppMatcher.best(name, apps())?.pkg ?: AppMatcher.best(name, apps(force = true))?.pkg
        } ?: fail(ErrorCode.APP_NOT_INSTALLED, "No app matches '${p.str("name")}'")
        if (SafetyRules.isBlocked(pkg, Nixin.settings.blocked)) fail(ErrorCode.BLOCKED_APP, "$pkg is blocked for safety")
        val launch = pm.getLaunchIntentForPackage(pkg) ?: fail(ErrorCode.APP_NOT_INSTALLED, "$pkg is not installed")
        launch.addFlags(Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
        if (!Launcher.start(launch)) fail(ErrorCode.FAILED, "Android refused to open $pkg")
        UiController.invalidate()
        return jsonOf("package" to pkg, "label" to Nixin.appLabel(pkg))
    }

    fun current(): JsonObject {
        val pkg = NixinAccessibilityService.instance?.currentPackage()
        return jsonOf("package" to pkg, "label" to Nixin.appLabel(pkg))
    }

    private fun installed(pkg: String) = runCatching { pm.getPackageInfo(pkg, 0); true }.getOrDefault(false)

    private fun view(uri: String, pkg: String? = null): Boolean {
        val i = Intent(Intent.ACTION_VIEW, Uri.parse(uri))
        if (pkg != null && installed(pkg)) i.setPackage(pkg)
        return Launcher.start(i)
    }

    fun url(p: JsonObject): JsonObject {
        val url = p.reqStr("url")
        if (!url.startsWith("http://") && !url.startsWith("https://")) fail(ErrorCode.BAD_REQUEST, "Only http(s) links")
        if (!view(url)) fail(ErrorCode.FAILED, "No browser")
        UiController.invalidate()
        return jsonOf("opened" to true)
    }

    fun search(p: JsonObject): JsonObject {
        val q = p.reqStr("query")
        val enc = Uri.encode(q)
        val ok = when (p.str("engine") ?: "web") {
            "youtube" -> Launcher.start(Intent(Intent.ACTION_SEARCH).setPackage("com.google.android.youtube").putExtra("query", q)) ||
                view("https://www.youtube.com/results?search_query=$enc")
            "playstore" -> view("market://search?q=$enc", "com.android.vending") || view("https://play.google.com/store/search?q=$enc")
            "maps" -> view("geo:0,0?q=$enc", "com.google.android.apps.maps")
            "spotify" -> view("spotify:search:$enc", "com.spotify.music") || view("https://open.spotify.com/search/$enc")
            else -> Launcher.start(Intent(Intent.ACTION_WEB_SEARCH).putExtra(SearchManager.QUERY, q)) ||
                view("https://www.google.com/search?q=$enc")
        }
        if (!ok) fail(ErrorCode.FAILED, "No app can handle this search")
        UiController.invalidate()
        return jsonOf("opened" to true)
    }

    fun navigate(p: JsonObject): JsonObject {
        val dest = Uri.encode(p.reqStr("destination"))
        val mode = p.str("mode") ?: "driving"
        val ok = if (mode == "transit") {
            view("https://www.google.com/maps/dir/?api=1&destination=$dest&travelmode=transit")
        } else {
            val m = mapOf("driving" to "d", "walking" to "w", "bicycling" to "b")[mode] ?: "d"
            view("google.navigation:q=$dest&mode=$m", "com.google.android.apps.maps") ||
                view("https://www.google.com/maps/dir/?api=1&destination=$dest")
        }
        if (!ok) fail(ErrorCode.FAILED, "Google Maps is not available")
        UiController.invalidate()
        return jsonOf("opened" to true)
    }

    fun alarm(p: JsonObject): JsonObject {
        val i = Intent(AlarmClock.ACTION_SET_ALARM)
            .putExtra(AlarmClock.EXTRA_HOUR, p.reqInt("hour"))
            .putExtra(AlarmClock.EXTRA_MINUTES, p.reqInt("minute"))
            .putExtra(AlarmClock.EXTRA_SKIP_UI, p.bool("skipUi") ?: true)
        p.str("label")?.let { i.putExtra(AlarmClock.EXTRA_MESSAGE, it) }
        p.arr("days")?.mapNotNull { (it as? JsonPrimitive)?.intOrNull }?.takeIf { it.isNotEmpty() }?.let {
            i.putExtra(AlarmClock.EXTRA_DAYS, ArrayList(it))
        }
        if (!Launcher.start(i)) fail(ErrorCode.UNSUPPORTED, "No clock app accepts alarms")
        return jsonOf("hour" to p.reqInt("hour"), "minute" to p.reqInt("minute"))
    }

    fun timer(p: JsonObject): JsonObject {
        val i = Intent(AlarmClock.ACTION_SET_TIMER)
            .putExtra(AlarmClock.EXTRA_LENGTH, p.reqInt("seconds"))
            .putExtra(AlarmClock.EXTRA_SKIP_UI, p.bool("skipUi") ?: true)
        p.str("label")?.let { i.putExtra(AlarmClock.EXTRA_MESSAGE, it) }
        if (!Launcher.start(i)) fail(ErrorCode.UNSUPPORTED, "No clock app accepts timers")
        return jsonOf("seconds" to p.int("seconds"))
    }
}
