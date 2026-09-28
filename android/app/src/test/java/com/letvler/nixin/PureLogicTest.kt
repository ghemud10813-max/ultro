package com.letvler.nixin

import com.letvler.nixin.a11y.ScreenSerializer
import com.letvler.nixin.a11y.UiNode
import com.letvler.nixin.capabilities.AppMatcher
import com.letvler.nixin.core.parseObject
import com.letvler.nixin.link.PairingPayload
import com.letvler.nixin.policy.Methods
import com.letvler.nixin.policy.SafetyRules
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.util.Base64

private class FakeNode(
    override val className: String? = "android.widget.TextView",
    override val text: String? = null,
    override val contentDescription: String? = null,
    override val hintText: String? = null,
    override val viewId: String? = null,
    override val bounds: IntArray = intArrayOf(0, 0, 100, 50),
    override val isVisible: Boolean = true,
    override val isClickable: Boolean = false,
    override val isLongClickable: Boolean = false,
    override val isEditable: Boolean = false,
    override val isScrollable: Boolean = false,
    override val isCheckable: Boolean = false,
    override val isChecked: Boolean = false,
    override val isFocused: Boolean = false,
    override val isSelected: Boolean = false,
    override val isEnabled: Boolean = true,
    override val isPassword: Boolean = false,
    override val children: List<UiNode> = emptyList(),
) : UiNode

class ScreenSerializerTest {
    private fun tree() = FakeNode(
        className = "android.widget.FrameLayout", bounds = intArrayOf(0, 0, 1080, 2400),
        children = listOf(
            FakeNode(className = "android.widget.ImageButton", contentDescription = "Navigate up", isClickable = true,
                bounds = intArrayOf(0, 100, 100, 180)),
            // clickable row whose label comes from its children
            FakeNode(className = "android.view.ViewGroup", isClickable = true, bounds = intArrayOf(0, 300, 1080, 450),
                children = listOf(FakeNode(text = "Rahul Sharma", bounds = intArrayOf(120, 310, 600, 360)),
                    FakeNode(text = "See you soon", bounds = intArrayOf(120, 370, 900, 420)))),
            FakeNode(className = "android.widget.EditText", hintText = "Message", isEditable = true, isClickable = true,
                viewId = "com.whatsapp:id/entry", bounds = intArrayOf(40, 2200, 900, 2300)),
            FakeNode(className = "android.widget.EditText", text = "hunter2", isPassword = true, isEditable = true,
                bounds = intArrayOf(40, 1900, 900, 2000)),
            FakeNode(text = "invisible", isVisible = false),
            FakeNode(className = "android.widget.Switch", contentDescription = "Wi-Fi", isCheckable = true, isChecked = true,
                isClickable = true, bounds = intArrayOf(900, 600, 1040, 680)),
            FakeNode(className = "android.view.View", bounds = intArrayOf(0, 700, 10, 710)), // no info, not actionable
        ),
    )

    @Test
    fun `serializes useful nodes compactly`() {
        val els = ScreenSerializer().serialize(tree()).map { it.json }
        assertEquals(listOf(1, 2, 3, 4, 5), els.map { (it["id"] as JsonPrimitive).content.toInt() })
        val back = els[0]
        assertEquals("button", back["role"]!!.jsonPrimitive.content)
        assertEquals("Navigate up", back["desc"]!!.jsonPrimitive.content)
        val row = els[1]
        assertEquals("Rahul Sharma · See you soon", row["text"]!!.jsonPrimitive.content)
        assertEquals("item", row["role"]!!.jsonPrimitive.content)
        val entry = els[2]
        assertEquals("input", entry["role"]!!.jsonPrimitive.content)
        assertEquals("Message", entry["hint"]!!.jsonPrimitive.content)
        assertEquals("entry", entry["res"]!!.jsonPrimitive.content)
        val pwd = els[3]
        assertNull("password text must never be exported", pwd["text"])
        assertTrue((pwd["flags"] as JsonArray).map { it.jsonPrimitive.content }.contains("pwd"))
        val sw = els[4]
        assertEquals("switch", sw["role"]!!.jsonPrimitive.content)
        assertEquals("true", sw["checked"]!!.jsonPrimitive.content)
        assertFalse(els.any { it.toString().contains("invisible") })
        assertFalse(els.any { it.toString().contains("hunter2") })
    }

    @Test
    fun `respects max elements`() {
        val many = FakeNode(className = "android.widget.LinearLayout", bounds = intArrayOf(0, 0, 1080, 2400),
            children = (1..50).map { FakeNode(text = "item $it", bounds = intArrayOf(0, it * 10, 100, it * 10 + 9)) })
        val ser = ScreenSerializer(maxElements = 10)
        assertEquals(10, ser.serialize(many).size)
        assertTrue(ser.truncated)
    }
}

class SafetyRulesTest {
    @Test
    fun `finance and credential apps are blocked`() {
        listOf("com.phonepe.app", "net.one97.paytm", "com.google.android.apps.nbu.paisa.user", "com.sbi.lotusintouch",
            "com.x8bit.bitwarden", "com.google.android.apps.authenticator2", "com.example.mybank", "in.foo.upi.app",
            "com.acme.wallet").forEach { assertTrue(it, SafetyRules.isBlocked(it)) }
        listOf("com.whatsapp", "com.instagram.android", "com.google.android.youtube", "com.android.settings", "com.spotify.music")
            .forEach { assertFalse(it, SafetyRules.isBlocked(it)) }
        assertTrue(SafetyRules.isBlocked("com.foo.bar", setOf("com.foo.bar")))
    }

    @Test
    fun `sensitive labels and fields`() {
        assertTrue(SafetyRules.isSensitiveLabel("Send"))
        assertTrue(SafetyRules.isSensitiveLabel("Place order"))
        assertTrue(SafetyRules.isSensitiveLabel("Pay ₹200"))
        assertFalse(SafetyRules.isSensitiveLabel("Search"))
        assertFalse(SafetyRules.isSensitiveLabel("Settings"))
        assertTrue(SafetyRules.isSensitiveField(false, "Enter OTP", null, null))
        assertTrue(SafetyRules.isSensitiveField(true, null, null, null))
        assertTrue(SafetyRules.isSensitiveField(false, null, "com.bank:id/upi_pin", null))
        assertFalse(SafetyRules.isSensitiveField(false, "Message", "com.whatsapp:id/entry", null))
    }

    @Test
    fun `otp masking`() {
        assertEquals("Your OTP is •••••• for login", SafetyRules.maskOtp("Your OTP is 482913 for login"))
        assertEquals("Meeting at 1530 in room 4", SafetyRules.maskOtp("Meeting at 1530 in room 4"))
    }
}

class MethodsRegistryTest {
    private fun sharedFile(): File {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            val f = File(dir, "shared/protocol/methods.json")
            if (f.exists()) return f
            dir = dir.parentFile
        }
        error("shared/protocol/methods.json not found")
    }

    @Test
    fun `kotlin registry matches the shared protocol file`() {
        val root = parseObject(sharedFile().readText())!!
        val methods = root["methods"] as JsonObject
        val shared = methods.mapValues { (_, v) -> ((v as JsonObject)["risk"] as JsonPrimitive).contentOrNull }
        assertEquals(shared, Methods.RISK)
    }

    @Test
    fun `dispatcher has a handler for every protocol method`() {
        val methods = (parseObject(sharedFile().readText())!!["methods"] as JsonObject).keys
        val dispatcher = File(sharedFile().parentFile.parentFile.parentFile,
            "android/app/src/main/java/com/letvler/nixin/dispatch/Dispatcher.kt").readText()
        val handled = Regex("\"([a-z_]+\\.[a-z_]+)\" to h \\{").findAll(dispatcher).map { it.groupValues[1] }.toSet()
        assertEquals(methods.sorted(), handled.sorted())
    }
}

class PairingPayloadTest {
    private fun uri(json: String) = "nixin://pair?d=" + Base64.getUrlEncoder().withoutPadding().encodeToString(json.toByteArray())
    private val fp = "a".repeat(64)

    @Test
    fun `parses a valid link`() {
        val p = PairingPayload.parse(uri("""{"v":1,"pcId":"pc1","pcName":"Home-PC","endpoints":["wss://192.168.1.20:8765/link","wss://100.101.1.2:8765/link"],"fp":"$fp","token":"tok","exp":9999999999}"""))
        assertEquals("Home-PC", p.pcName)
        assertEquals(2, p.endpoints.size)
        assertFalse(p.expired)
    }

    @Test
    fun `rejects public or insecure endpoints`() {
        assertThrows(IllegalArgumentException::class.java) {
            PairingPayload.parse(uri("""{"pcId":"x","endpoints":["wss://8.8.8.8:8765/link"],"fp":"$fp","token":"t","exp":1}"""))
        }
        assertThrows(IllegalArgumentException::class.java) {
            PairingPayload.parse(uri("""{"pcId":"x","endpoints":["ws://192.168.1.2:8765/link"],"fp":"$fp","token":"t","exp":1}"""))
        }
        assertThrows(IllegalArgumentException::class.java) { PairingPayload.parse("hello") }
    }
}

class AppMatcherTest {
    private val apps = listOf(
        AppMatcher.App("WhatsApp", "com.whatsapp"), AppMatcher.App("YouTube", "com.google.android.youtube"),
        AppMatcher.App("YouTube Music", "com.google.android.apps.youtube.music"), AppMatcher.App("Samsung Notes", "com.samsung.android.app.notes"),
    )

    @Test
    fun matches() {
        assertEquals("com.whatsapp", AppMatcher.best("whatsapp", apps)?.pkg)
        assertEquals("com.whatsapp", AppMatcher.best("whatsap", apps)?.pkg)
        assertEquals("com.google.android.youtube", AppMatcher.best("youtube", apps)?.pkg)
        assertEquals("com.samsung.android.app.notes", AppMatcher.best("notes", apps)?.pkg)
        assertNull(AppMatcher.best("calculator", apps))
        assertNotNull(AppMatcher.best("YouTube Music app", apps))
    }
}
