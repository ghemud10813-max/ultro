package com.letvler.nixin.policy

/**
 * The phone's own safety rules. The PC and the LLM cannot turn these off:
 *  - financial / UPI / banking / password-manager / authenticator apps are never observed or touched,
 *  - password and OTP-like fields are never read or typed into,
 *  - taps on "Send / Pay / Delete / Call ..." controls need an explicit confirmation from the PC gate,
 *  - OTP-like codes are masked in notifications.
 */
object SafetyRules {
    val BUILTIN_BLOCKED: Set<String> = setOf(
        // UPI / wallets / payments
        "com.google.android.apps.nbu.paisa.user", "com.phonepe.app", "net.one97.paytm", "in.org.npci.upiapp",
        "com.dreamplug.androidapp", "com.mobikwik_new", "com.freecharge.android", "com.paypal.android.p2pmobile",
        "com.samsung.android.spay", "com.google.android.apps.walletnfcrel", "com.amazon.pay", "com.whatsapp.payments",
        "in.amazon.mShop.android.shopping.pay", "com.myairtelapp.payments", "com.jio.myjio.jiopay",
        // Banks (India + common)
        "com.sbi.lotusintouch", "com.sbi.SBIFreedomPlus", "com.csam.icici.bank.imobile", "com.snapwork.hdfc",
        "com.hdfcbank.payzapp", "com.axis.mobile", "com.msf.kbank.mobile", "com.bankofbaroda.mconnect",
        "com.pnb.pnbone", "com.idfcfirstbank.optimus", "com.yesbank.yesmobile", "com.infrasofttech.indianbank",
        "com.unionbank.ecommerce.mobile.android", "com.canarabank.mobility", "com.fss.idbi", "com.kotak811mobilebankingapp",
        // Investing / crypto
        "com.nextbillion.groww", "com.zerodha.kite3", "in.upstox.pro", "com.paytmmoney", "com.binance.dev",
        "com.wazirx", "com.coinbase.android", "com.angelbroking.angelone",
        // Passwords / authenticators / OTP
        "com.google.android.apps.authenticator2", "com.azure.authenticator", "com.authy.authy",
        "com.onepassword.android", "com.agilebits.onepassword", "com.x8bit.bitwarden", "com.lastpass.lpandroid",
        "com.dashlane", "com.samsung.android.samsungpassautofill", "com.samsung.android.authfw",
        "org.fedorahosted.freeotp", "com.beemdevelopment.aegis", "com.google.android.gms.auth",
        // System surfaces that must never be automated
        "com.android.permissioncontroller", "com.google.android.permissioncontroller",
        "com.android.credentialmanager", "com.google.android.apps.work.clouddpc",
    )

    /** Specific words that mark a finance/credential app anywhere in the package name. */
    private val BLOCKED_ANYWHERE = Regex("(bank|wallet|authenticator|password|paisa|upipay|netbanking)", RegexOption.IGNORE_CASE)

    /** Short words that are only meaningful as a whole package segment (avoid "cupid" ~ "upi"). */
    private val BLOCKED_SEGMENT = Regex("(^|\\.)(upi|pay|payments?|otp|vault|2fa)(\\.|$)", RegexOption.IGNORE_CASE)

    /** Never block these even if they match the keyword pattern. */
    private val ALLOWED_OVERRIDE = setOf("com.whatsapp", "com.whatsapp.w4b", "com.letvler.nixin")

    fun isBlocked(pkg: String?, extra: Set<String> = emptySet()): Boolean {
        if (pkg.isNullOrBlank()) return false
        if (pkg in ALLOWED_OVERRIDE) return false
        if (pkg in BUILTIN_BLOCKED || pkg in extra) return true
        return BLOCKED_ANYWHERE.containsMatchIn(pkg) || BLOCKED_SEGMENT.containsMatchIn(pkg)
    }

    private val SENSITIVE_LABEL = Regex(
        "\\b(send|post|publish|share|pay|payment|buy|purchase|order|place order|checkout|delete|remove|erase|" +
            "transfer|withdraw|donate|subscribe|submit|call|dial|video call|bhej|bhejo|bhejein|reply all|forward|uninstall)\\b",
        RegexOption.IGNORE_CASE,
    )

    /** Labels of controls whose tap can affect other people or money. */
    fun isSensitiveLabel(label: String?): Boolean = !label.isNullOrBlank() && SENSITIVE_LABEL.containsMatchIn(label)

    private val SENSITIVE_FIELD = Regex("(password|passcode|passwd|(?<![a-z])pin(?![a-z])|otp|one.?time|cvv|cvc|card.?number)",
        RegexOption.IGNORE_CASE)

    fun isSensitiveField(isPassword: Boolean, hint: String?, viewId: String?, label: String?): Boolean =
        isPassword || listOf(hint, viewId, label).any { !it.isNullOrBlank() && SENSITIVE_FIELD.containsMatchIn(it) }

    private val OTP_CONTEXT = Regex("(otp|one.?time|verification|verify|code|passcode|pin|login|sign.?in|2fa|security)",
        RegexOption.IGNORE_CASE)
    private val DIGITS = Regex("(?<![\\d])\\d{4,8}(?![\\d])")

    /** Mask OTP-like numbers in notification text. */
    fun maskOtp(text: String?): String? {
        if (text.isNullOrEmpty()) return text
        return if (OTP_CONTEXT.containsMatchIn(text)) DIGITS.replace(text) { "•".repeat(it.value.length) } else text
    }
}
