package com.letvler.nixin.capabilities

/** Fuzzy "open <name>" matching against installed app labels (pure logic). */
object AppMatcher {
    data class App(val label: String, val pkg: String)

    private fun norm(s: String) = s.lowercase().replace(Regex("[^a-z0-9 ]"), " ").replace(Regex("\\s+"), " ").trim()

    fun best(name: String, apps: List<App>): App? {
        val n = norm(name).removeSuffix(" app").trim()
        if (n.isEmpty()) return null
        apps.firstOrNull { norm(it.label) == n }?.let { return it }
        apps.firstOrNull { it.pkg.equals(name.trim(), ignoreCase = true) }?.let { return it }
        var best: App? = null
        var bestScore = 0.0
        for (a in apps) {
            val l = norm(a.label)
            if (l.isEmpty()) continue
            var s = similarity(n, l)
            if (l.startsWith(n) || n.startsWith(l)) s = maxOf(s, 0.86)
            if (l.split(" ").contains(n)) s = maxOf(s, 0.84)
            if (s > bestScore) {
                bestScore = s
                best = a
            }
        }
        return if (bestScore >= 0.8) best else null
    }

    /** Normalised Levenshtein similarity in [0,1]. */
    fun similarity(a: String, b: String): Double {
        if (a == b) return 1.0
        if (a.isEmpty() || b.isEmpty()) return 0.0
        val prev = IntArray(b.length + 1) { it }
        val cur = IntArray(b.length + 1)
        for (i in 1..a.length) {
            cur[0] = i
            for (j in 1..b.length) {
                val cost = if (a[i - 1] == b[j - 1]) 0 else 1
                cur[j] = minOf(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
            }
            System.arraycopy(cur, 0, prev, 0, cur.size)
        }
        return 1.0 - prev[b.length].toDouble() / maxOf(a.length, b.length)
    }
}
