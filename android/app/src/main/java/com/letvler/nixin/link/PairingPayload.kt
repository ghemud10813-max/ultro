package com.letvler.nixin.link

import com.letvler.nixin.core.arr
import com.letvler.nixin.core.long
import com.letvler.nixin.core.parseObject
import com.letvler.nixin.core.str
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.net.URI
import java.util.Base64

/** Contents of the pairing QR: nixin://pair?d=<base64url(json)> */
data class PairingPayload(
    val pcId: String,
    val pcName: String,
    val endpoints: List<String>,
    val fingerprint: String,
    val token: String,
    val expiresAtEpoch: Long,
) {
    val expired: Boolean get() = System.currentTimeMillis() / 1000 > expiresAtEpoch

    companion object {
        private val HEX64 = Regex("^[0-9a-f]{64}$")

        /** Accepts the nixin:// link, a raw JSON payload, or text containing the link. Throws IllegalArgumentException. */
        fun parse(input: String): PairingPayload {
            val text = input.trim()
            val json = when {
                text.startsWith("{") -> text
                text.contains("d=") -> {
                    val d = text.substringAfter("d=").substringBefore("&").trim()
                    String(Base64.getUrlDecoder().decode(d.replace('+', '-').replace('/', '_').trimEnd('=')))
                }
                else -> throw IllegalArgumentException("Not a Nixin pairing code")
            }
            val o = parseObject(json) ?: throw IllegalArgumentException("Pairing code is not valid JSON")
            val endpoints = o.arr("endpoints")?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.orEmpty()
            val p = PairingPayload(
                pcId = o.str("pcId") ?: throw IllegalArgumentException("pcId missing"),
                pcName = o.str("pcName") ?: "PC",
                endpoints = endpoints,
                fingerprint = (o.str("fp") ?: "").lowercase(),
                token = o.str("token") ?: throw IllegalArgumentException("token missing"),
                expiresAtEpoch = o.long("exp") ?: 0L,
            )
            require(HEX64.matches(p.fingerprint)) { "Certificate fingerprint missing" }
            require(p.endpoints.isNotEmpty()) { "No PC address in pairing code" }
            p.endpoints.forEach { require(isAllowedEndpoint(it)) { "Refusing non-private address: $it" } }
            return p
        }

        /** Only wss:// to private LAN / Tailscale / loopback addresses. */
        fun isAllowedEndpoint(url: String): Boolean {
            val u = runCatching { URI(url) }.getOrNull() ?: return false
            if (u.scheme != "wss") return false
            val host = u.host ?: return false
            val parts = host.split(".").mapNotNull { it.toIntOrNull() }
            if (parts.size != 4) return host == "localhost" || host.endsWith(".ts.net") || host.endsWith(".local")
            val (a, b) = parts
            return a == 10 || a == 127 || (a == 172 && b in 16..31) || (a == 192 && b == 168) || (a == 100 && b in 64..127)
        }
    }
}
