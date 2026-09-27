package com.letvler.nixin.a11y

import com.letvler.nixin.core.toJson
import kotlinx.serialization.json.JsonObject

/** Read-only view of a UI node, so the serializer is pure Kotlin and unit-testable. */
interface UiNode {
    val className: String?
    val text: String?
    val contentDescription: String?
    val hintText: String?
    val viewId: String?
    /** [left, top, right, bottom] in screen pixels */
    val bounds: IntArray
    val isVisible: Boolean
    val isClickable: Boolean
    val isLongClickable: Boolean
    val isEditable: Boolean
    val isScrollable: Boolean
    val isCheckable: Boolean
    val isChecked: Boolean
    val isFocused: Boolean
    val isSelected: Boolean
    val isEnabled: Boolean
    val isPassword: Boolean
    val children: List<UiNode>
}

data class SerializedElement<T>(val id: Int, val node: T, val json: JsonObject)

/**
 * Converts a UI tree into a compact element list:
 *  - keeps visible nodes that have text or can be acted on,
 *  - folds the text of plain child labels into their clickable parent (one row = one element),
 *  - never exposes password text, trims long text,
 *  - assigns snapshot-scoped ids 1..n.
 */
class ScreenSerializer(
    private val maxElements: Int = 150,
    private val maxText: Int = 120,
    private val screenWidth: Int = 10_000,
    private val screenHeight: Int = 10_000,
) {
    var truncated = false
        private set

    fun <T : UiNode> serialize(root: T?): List<SerializedElement<T>> {
        truncated = false
        val out = ArrayList<SerializedElement<T>>()
        if (root != null) walk(root, out, 0)
        return out
    }

    @Suppress("UNCHECKED_CAST")
    private fun <T : UiNode> walk(node: T, out: MutableList<SerializedElement<T>>, depth: Int) {
        if (depth > 60) return
        if (!node.isVisible) return
        val b = node.bounds
        if (b.size != 4 || b[2] <= b[0] || b[3] <= b[1]) {
            node.children.forEach { walk(it as T, out, depth + 1) }
            return
        }
        if (b[2] <= 0 || b[3] <= 0 || b[0] >= screenWidth || b[1] >= screenHeight) return

        val actionable = node.isClickable || node.isLongClickable || node.isEditable || node.isScrollable || node.isCheckable
        val ownText = clean(if (node.isPassword) null else node.text)
        val desc = clean(node.contentDescription)
        var label = ownText
        var folded = false
        if (actionable && label == null && desc == null && !node.isEditable) {
            val childText = collectText(node, 0).joinToString(" · ").take(maxText).ifBlank { null }
            if (childText != null) {
                label = childText
                folded = true
            }
        }
        val hasInfo = label != null || desc != null || (node.isEditable && node.hintText != null)
        if (actionable || hasInfo) {
            if (out.size >= maxElements) {
                truncated = true
                return
            }
            out.add(SerializedElement(out.size + 1, node, toElement(out.size + 1, node, label, desc)))
        }
        if (folded) {
            // children already summarised; still descend for nested actionable controls
            node.children.forEach { walkActionableOnly(it as T, out, depth + 1) }
        } else {
            node.children.forEach { walk(it as T, out, depth + 1) }
        }
    }

    @Suppress("UNCHECKED_CAST")
    private fun <T : UiNode> walkActionableOnly(node: T, out: MutableList<SerializedElement<T>>, depth: Int) {
        if (depth > 60 || !node.isVisible) return
        val actionable = node.isClickable || node.isLongClickable || node.isEditable || node.isScrollable || node.isCheckable
        if (actionable) {
            walk(node, out, depth)
            return
        }
        node.children.forEach { walkActionableOnly(it as T, out, depth + 1) }
    }

    private fun collectText(node: UiNode, depth: Int): List<String> {
        if (depth > 6 || !node.isVisible) return emptyList()
        val res = ArrayList<String>()
        if (depth > 0 && (node.isClickable || node.isEditable)) return res // separate element
        clean(if (node.isPassword) null else node.text)?.let { res.add(it) }
        if (depth > 0 && node.text == null) clean(node.contentDescription)?.let { res.add(it) }
        node.children.forEach { res.addAll(collectText(it, depth + 1)) }
        return res.distinct()
    }

    private fun clean(s: CharSequence?): String? {
        if (s == null) return null
        val t = s.toString().replace(Regex("\\s+"), " ").trim()
        if (t.isEmpty()) return null
        return if (t.length > maxText) t.take(maxText - 1) + "…" else t
    }

    private fun toElement(id: Int, n: UiNode, label: String?, desc: String?): JsonObject {
        val flags = ArrayList<String>(6)
        if (n.isClickable) flags.add("click")
        if (n.isLongClickable) flags.add("long")
        if (n.isEditable) flags.add("edit")
        if (n.isScrollable) flags.add("scroll")
        if (n.isFocused) flags.add("focus")
        if (n.isSelected) flags.add("sel")
        if (!n.isEnabled) flags.add("off")
        if (n.isPassword) flags.add("pwd")
        val m = LinkedHashMap<String, Any?>()
        m["id"] = id
        m["role"] = roleOf(n)
        if (label != null) m["text"] = label
        if (desc != null && desc != label) m["desc"] = desc
        if (n.isEditable && label == null) clean(n.hintText)?.let { m["hint"] = it }
        n.viewId?.substringAfter(":id/", "")?.takeIf { it.isNotEmpty() }?.let { m["res"] = it }
        m["b"] = listOf(n.bounds[0], n.bounds[1], n.bounds[2], n.bounds[3])
        m["flags"] = flags
        if (n.isCheckable) m["checked"] = n.isChecked
        @Suppress("UNCHECKED_CAST")
        return toJson(m) as JsonObject
    }

    companion object {
        fun roleOf(n: UiNode): String {
            val c = n.className?.substringAfterLast('.')?.lowercase() ?: ""
            return when {
                n.isEditable || c.contains("edittext") || c.contains("textfield") -> "input"
                c.contains("switch") || c.contains("toggle") -> "switch"
                c.contains("checkbox") -> "checkbox"
                c.contains("radiobutton") -> "radio"
                c.contains("imagebutton") || c.contains("button") -> "button"
                c.contains("seekbar") || c.contains("slider") -> "slider"
                c.contains("spinner") -> "dropdown"
                c.contains("tab") -> "tab"
                c.contains("webview") -> "web"
                c.contains("recyclerview") || c.contains("listview") || c.contains("scrollview") ||
                    c.contains("gridview") || c.contains("viewpager") || (n.isScrollable && !n.isClickable) -> "list"
                c.contains("image") -> if (n.isClickable) "button" else "image"
                c.contains("textview") || c == "text" -> if (n.isClickable) "button" else "text"
                n.isCheckable -> "checkbox"
                n.isClickable -> "item"
                else -> "text"
            }
        }
    }
}
