package com.letvler.nixin.link

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.util.Base64

/**
 * Device identity: an EC P-256 key inside the Android Keystore. The private key never
 * leaves secure hardware; the PC only ever sees the public key and signatures.
 */
object KeyManager {
    private const val ALIAS = "nixin_device_key_v1"

    private fun keyStore(): KeyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    private fun ensureKey() {
        val ks = keyStore()
        if (ks.containsAlias(ALIAS)) return
        val kpg = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore")
        kpg.initialize(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
                .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_SHA256)
                .build(),
        )
        kpg.generateKeyPair()
    }

    /** DER X.509 SubjectPublicKeyInfo, base64url without padding. */
    fun publicKeyB64(): String {
        ensureKey()
        val cert = keyStore().getCertificate(ALIAS)
        return b64(cert.publicKey.encoded)
    }

    fun sign(message: String): String {
        ensureKey()
        val key = keyStore().getKey(ALIAS, null) as PrivateKey
        val sig = Signature.getInstance("SHA256withECDSA")
        sig.initSign(key)
        sig.update(message.toByteArray(Charsets.UTF_8))
        return b64(sig.sign())
    }

    /** Forget the key (after unpairing) so a fresh identity is used next time. */
    fun reset() {
        runCatching { keyStore().deleteEntry(ALIAS) }
    }

    private fun b64(bytes: ByteArray): String = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)

    fun pairMessage(pcId: String, nonce: String, token: String, deviceId: String) =
        "nixin-pair\n$pcId\n$nonce\n$token\n$deviceId"

    fun authMessage(pcId: String, nonce: String, deviceId: String) = "nixin-auth\n$pcId\n$nonce\n$deviceId"
}
