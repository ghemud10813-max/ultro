package com.letvler.nixin.link

import okhttp3.OkHttpClient
import java.security.MessageDigest
import java.security.SecureRandom
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/**
 * Trusts exactly one certificate: the PC's self-signed cert whose SHA-256 fingerprint
 * came from the pairing QR. No CA, no domain, no man-in-the-middle on the LAN.
 */
class PinnedTrustManager(private val pinHex: String) : X509TrustManager {
    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        val leaf = chain?.firstOrNull() ?: throw CertificateException("No certificate")
        val fp = MessageDigest.getInstance("SHA-256").digest(leaf.encoded).joinToString("") { "%02x".format(it) }
        if (!MessageDigest.isEqual(fp.toByteArray(), pinHex.lowercase().toByteArray())) {
            throw CertificateException("PC certificate does not match the paired fingerprint")
        }
    }

    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) =
        throw CertificateException("Client certificates are not used")

    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
}

object PinnedTls {
    fun client(pinHex: String): OkHttpClient {
        val tm = PinnedTrustManager(pinHex)
        val ctx = SSLContext.getInstance("TLS")
        ctx.init(null, arrayOf(tm), SecureRandom())
        return OkHttpClient.Builder()
            .sslSocketFactory(ctx.socketFactory, tm)
            // Identity is proven by the pinned certificate, not by hostname (the PC has no domain).
            .hostnameVerifier { _, _ -> true }
            .connectTimeout(6, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.SECONDS)
            .pingInterval(20, TimeUnit.SECONDS)
            .retryOnConnectionFailure(false)
            .build()
    }
}
