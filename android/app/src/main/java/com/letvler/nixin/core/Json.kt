package com.letvler.nixin.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull

/** Small helpers so protocol code can read loosely-typed JSON without data classes. */
val NixinJson = Json { ignoreUnknownKeys = true; explicitNulls = false }

fun parseObject(text: String): JsonObject? =
    runCatching { NixinJson.parseToJsonElement(text) as? JsonObject }.getOrNull()

fun JsonObject.str(key: String): String? = (this[key] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull
fun JsonObject.int(key: String): Int? = (this[key] as? JsonPrimitive)?.let { it.intOrNull ?: it.doubleOrNull?.toInt() }
fun JsonObject.long(key: String): Long? = (this[key] as? JsonPrimitive)?.longOrNull
fun JsonObject.bool(key: String): Boolean? = (this[key] as? JsonPrimitive)?.booleanOrNull
fun JsonObject.obj(key: String): JsonObject? = this[key] as? JsonObject
fun JsonObject.arr(key: String): JsonArray? = this[key] as? JsonArray

fun JsonObject.reqStr(key: String): String =
    str(key) ?: throw NixinException(ErrorCode.BAD_REQUEST, "missing '$key'")

fun JsonObject.reqInt(key: String): Int =
    int(key) ?: throw NixinException(ErrorCode.BAD_REQUEST, "missing '$key'")

fun JsonObject.reqBool(key: String): Boolean =
    bool(key) ?: throw NixinException(ErrorCode.BAD_REQUEST, "missing '$key'")

/** Build a JsonObject from Kotlin values (String/Number/Boolean/null/Map/List/JsonElement). */
fun jsonOf(vararg pairs: Pair<String, Any?>): JsonObject = JsonObject(pairs.associate { (k, v) -> k to toJson(v) })

fun toJson(v: Any?): JsonElement = when (v) {
    null -> JsonNull
    is JsonElement -> v
    is String -> JsonPrimitive(v)
    is Number -> JsonPrimitive(v)
    is Boolean -> JsonPrimitive(v)
    is Map<*, *> -> JsonObject(v.entries.associate { (k, value) -> k.toString() to toJson(value) })
    is Iterable<*> -> JsonArray(v.map { toJson(it) })
    is Array<*> -> JsonArray(v.map { toJson(it) })
    is IntArray -> JsonArray(v.map { JsonPrimitive(it) })
    else -> JsonPrimitive(v.toString())
}
