package com.letvler.nixin.capabilities

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Rect
import android.net.Uri
import android.os.Bundle
import android.provider.ContactsContract
import android.telephony.SmsManager
import android.view.accessibility.AccessibilityNodeInfo
import com.letvler.nixin.a11y.UiController
import com.letvler.nixin.core.ErrorCode
import com.letvler.nixin.core.bool
import com.letvler.nixin.core.fail
import com.letvler.nixin.core.int
import com.letvler.nixin.core.jsonOf
import com.letvler.nixin.core.reqStr
import kotlinx.coroutines.delay
import kotlinx.serialization.json.JsonObject

/** Contacts, calls, SMS and the WhatsApp send-once workflow. All sends require meta.confirmed (dispatcher). */
class CommControl(private val ctx: Context) {

    private fun granted(p: String) = ctx.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED

    // ------------------------------------------------------------------ contacts
    fun searchContacts(p: JsonObject): JsonObject {
        if (!granted(Manifest.permission.READ_CONTACTS)) fail(ErrorCode.PERM_CONTACTS, "Grant Contacts permission to Nixin")
        val q = p.reqStr("query").trim()
        val limit = (p.int("limit") ?: 5).coerceIn(1, 10)
        val byId = LinkedHashMap<Long, Pair<String, MutableList<Map<String, String>>>>()
        val proj = arrayOf(
            ContactsContract.CommonDataKinds.Phone.CONTACT_ID,
            ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
            ContactsContract.CommonDataKinds.Phone.NUMBER,
            ContactsContract.CommonDataKinds.Phone.TYPE,
            ContactsContract.CommonDataKinds.Phone.LABEL,
        )
        ctx.contentResolver.query(
            ContactsContract.CommonDataKinds.Phone.CONTENT_URI, proj,
            "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} LIKE ?", arrayOf("%$q%"),
            "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} ASC",
        )?.use { c ->
            while (c.moveToNext() && byId.size <= limit * 3) {
                val id = c.getLong(0)
                val name = c.getString(1) ?: continue
                val number = c.getString(2) ?: continue
                val label = ContactsContract.CommonDataKinds.Phone.getTypeLabel(ctx.resources, c.getInt(3), c.getString(4)).toString()
                val entry = byId.getOrPut(id) { name to mutableListOf() }
                val norm = number.filter { it.isDigit() || it == '+' }
                if (entry.second.none { it["number"]!!.filter { ch -> ch.isDigit() || ch == '+' }.takeLast(10) == norm.takeLast(10) }) {
                    entry.second.add(mapOf("number" to number, "label" to label))
                }
            }
        }
        // rank: exact name, then name starting with query, then others
        val ranked = byId.entries.sortedBy { (_, v) ->
            val n = v.first.lowercase()
            when { n == q.lowercase() -> 0; n.startsWith(q.lowercase()) -> 1; else -> 2 }
        }.take(limit)
        return jsonOf("contacts" to ranked.map { (id, v) -> mapOf("id" to id.toString(), "name" to v.first, "numbers" to v.second) })
    }

    // ------------------------------------------------------------------ call / sms
    fun call(p: JsonObject): JsonObject {
        val number = p.reqStr("number")
        val uri = Uri.parse("tel:" + Uri.encode(number))
        return if (granted(Manifest.permission.CALL_PHONE)) {
            if (!Launcher.start(Intent(Intent.ACTION_CALL, uri))) fail(ErrorCode.FAILED, "Could not start the call")
            jsonOf("number" to number, "mode" to "call")
        } else {
            if (!Launcher.start(Intent(Intent.ACTION_DIAL, uri))) fail(ErrorCode.FAILED, "No dialer")
            jsonOf("number" to number, "mode" to "dial")
        }
    }

    fun sms(p: JsonObject): JsonObject {
        val number = p.reqStr("number")
        val text = p.reqStr("text")
        if (!granted(Manifest.permission.SEND_SMS)) {
            val i = Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:" + Uri.encode(number))).putExtra("sms_body", text)
            if (!Launcher.start(i)) fail(ErrorCode.FAILED, "No SMS app")
            return jsonOf("number" to number, "mode" to "composer")
        }
        val sms = ctx.getSystemService(SmsManager::class.java) ?: fail(ErrorCode.UNSUPPORTED, "No SMS on this device")
        val parts = sms.divideMessage(text)
        try {
            sms.sendMultipartTextMessage(number, null, parts, null, null)
        } catch (e: Exception) {
            fail(ErrorCode.UNCERTAIN, "SMS may not have been sent: ${e.message}")
        }
        return jsonOf("number" to number, "mode" to "sent", "parts" to parts.size)
    }

    // ------------------------------------------------------------------ WhatsApp
    /**
     * Send-once workflow:
     *  1. open the chat via WhatsApp's click-to-chat link with the text pre-filled,
     *  2. verify we are in WhatsApp with a composer that holds exactly our text,
     *  3. tap Send exactly once,
     *  4. verify the composer emptied -> "sent"; otherwise "uncertain" (never retried).
     */
    suspend fun whatsapp(p: JsonObject): JsonObject {
        val digits = p.reqStr("number").filter { it.isDigit() }
        val text = p.reqStr("text")
        val send = p.bool("send") ?: true
        val pkg = listOf(if (p.bool("business") == true) "com.whatsapp.w4b" else "com.whatsapp", "com.whatsapp", "com.whatsapp.w4b")
            .firstOrNull { runCatching { ctx.packageManager.getPackageInfo(it, 0) }.isSuccess }
            ?: fail(ErrorCode.APP_NOT_INSTALLED, "WhatsApp is not installed")
        if (digits.length < 8) fail(ErrorCode.BAD_REQUEST, "Invalid phone number")
        val svc = UiController.service()

        val link = "https://api.whatsapp.com/send?phone=$digits&text=${Uri.encode(text)}"
        if (!Launcher.start(Intent(Intent.ACTION_VIEW, Uri.parse(link)).setPackage(pkg))) fail(ErrorCode.FAILED, "Could not open WhatsApp")
        UiController.invalidate()

        // 2. wait for the chat composer
        var entry: AccessibilityNodeInfo? = null
        var sendBtn: AccessibilityNodeInfo? = null
        val start = System.currentTimeMillis()
        while (System.currentTimeMillis() - start < 12_000) {
            delay(400)
            val root = svc.appRoot() ?: continue
            if (root.packageName?.toString() != pkg) continue
            val screenText = UiController.rootText(root).lowercase()
            if ("isn't on whatsapp" in screenText || "not on whatsapp" in screenText || "invalid" in screenText && "url" in screenText) {
                svc.performGlobalAction(android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_BACK)
                fail(ErrorCode.NOT_FOUND, "This number is not on WhatsApp")
            }
            entry = UiController.findById(root, "$pkg:id/entry")
            sendBtn = UiController.findById(root, "$pkg:id/send") ?: UiController.findByDesc(root, "Send")
            if (entry != null && sendBtn != null) break
        }
        if (entry == null) fail(ErrorCode.FAILED, "WhatsApp chat did not open")

        // verify / fix the composer text (never re-type if it already matches)
        val current = if (entry.isShowingHintText) "" else entry.text?.toString().orEmpty()
        if (current.trim() != text.trim()) {
            val args = Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text) }
            entry.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
            delay(300)
            entry.refresh()
            val now = if (entry.isShowingHintText) "" else entry.text?.toString().orEmpty()
            if (now.trim() != text.trim()) fail(ErrorCode.FAILED, "Could not put the exact message in the composer")
            sendBtn = UiController.findById(svc.appRoot(), "$pkg:id/send") ?: UiController.findByDesc(svc.appRoot(), "Send")
        }
        if (!send) return jsonOf("state" to "composer", "verified" to true)
        val btn = sendBtn ?: fail(ErrorCode.FAILED, "Send button not found")

        // 3. tap Send once
        val clicked = btn.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        if (!clicked) {
            val r = Rect()
            btn.getBoundsInScreen(r)
            val path = android.graphics.Path().apply {
                moveTo(r.exactCenterX(), r.exactCenterY())
                lineTo(r.exactCenterX() + 1, r.exactCenterY() + 1)
            }
            if (!UiController.gesture(path, 60)) fail(ErrorCode.FAILED, "Send tap was rejected (nothing sent)")
        }

        // 4. verify
        val t0 = System.currentTimeMillis()
        while (System.currentTimeMillis() - t0 < 4_000) {
            delay(300)
            val e = UiController.findById(svc.appRoot(), "$pkg:id/entry") ?: continue
            val v = if (e.isShowingHintText) "" else e.text?.toString().orEmpty()
            if (v.isBlank()) return jsonOf("state" to "sent", "verified" to true)
        }
        return jsonOf("state" to "uncertain", "verified" to false)
    }
}
