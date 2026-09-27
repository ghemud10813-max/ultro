package com.letvler.nixin.a11y

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo

/** Adapts AccessibilityNodeInfo to the pure [UiNode] interface used by [ScreenSerializer]. */
class AndroidUiNode(val info: AccessibilityNodeInfo) : UiNode {
    override val className: String? get() = info.className?.toString()
    override val text: String? get() = if (info.isShowingHintText) null else info.text?.toString()
    override val contentDescription: String? get() = info.contentDescription?.toString()
    override val hintText: String? get() = info.hintText?.toString()
    override val viewId: String? get() = info.viewIdResourceName
    override val bounds: IntArray by lazy {
        val r = Rect()
        info.getBoundsInScreen(r)
        intArrayOf(r.left, r.top, r.right, r.bottom)
    }
    override val isVisible: Boolean get() = info.isVisibleToUser
    override val isClickable: Boolean get() = info.isClickable
    override val isLongClickable: Boolean get() = info.isLongClickable
    override val isEditable: Boolean get() = info.isEditable
    override val isScrollable: Boolean get() = info.isScrollable
    override val isCheckable: Boolean get() = info.isCheckable
    @Suppress("DEPRECATION") // getChecked() int-state API is 36+ only; the boolean works on every version
    override val isChecked: Boolean get() = info.isChecked
    override val isFocused: Boolean get() = info.isFocused || info.isAccessibilityFocused
    override val isSelected: Boolean get() = info.isSelected
    override val isEnabled: Boolean get() = info.isEnabled
    override val isPassword: Boolean get() = info.isPassword
    override val children: List<UiNode> by lazy {
        (0 until info.childCount).mapNotNull { i -> info.getChild(i)?.let { AndroidUiNode(it) } }
    }
}
