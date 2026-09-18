package com.pymcl.mobile

import com.pymcl.mobile.data.Nbt
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class NbtCodecTest {
    private fun roundTrip(root: Map<String, Any>): Map<String, Any> = Nbt.read(Nbt.write(root))

    @Test
    fun emptyInputReadsAsEmptyMap() {
        assertTrue(Nbt.read(ByteArray(0)).isEmpty())
    }

    @Test
    fun emptyCompoundRoundTrips() {
        assertTrue(roundTrip(emptyMap()).isEmpty())
    }

    @Test
    fun stringRoundTrips() {
        assertEquals("mc.example.com", roundTrip(mapOf("ip" to "mc.example.com"))["ip"])
    }

    @Test
    fun unicodeStringRoundTrips() {
        assertEquals("生存服 ⛏", roundTrip(mapOf("name" to "生存服 ⛏"))["name"])
    }

    @Test
    fun numericTypesKeepTheirWidth() {
        val out = roundTrip(
            mapOf(
                "b" to 7.toByte(),
                "s" to 300.toShort(),
                "i" to 70000,
                "l" to 5_000_000_000L,
                "f" to 1.5f,
                "d" to 2.25,
            ),
        )
        assertEquals(7.toByte(), out["b"])
        assertEquals(300.toShort(), out["s"])
        assertEquals(70000, out["i"])
        assertEquals(5_000_000_000L, out["l"])
        assertEquals(1.5f, out["f"])
        assertEquals(2.25, out["d"])
    }

    @Test
    fun booleanIsStoredAsByte() {
        assertEquals(1.toByte(), roundTrip(mapOf("hidden" to true))["hidden"])
        assertEquals(0.toByte(), roundTrip(mapOf("hidden" to false))["hidden"])
    }

    @Test
    fun byteArrayRoundTrips() {
        assertArrayEquals(byteArrayOf(1, 2, 3), roundTrip(mapOf("raw" to byteArrayOf(1, 2, 3)))["raw"] as ByteArray)
    }

    @Test
    fun intAndLongArraysRoundTrip() {
        val out = roundTrip(mapOf("ia" to intArrayOf(1, 2), "la" to longArrayOf(3L, 4L)))
        assertArrayEquals(intArrayOf(1, 2), out["ia"] as IntArray)
        assertArrayEquals(longArrayOf(3L, 4L), out["la"] as LongArray)
    }

    @Test
    fun nestedCompoundRoundTrips() {
        val out = roundTrip(mapOf("outer" to linkedMapOf<String, Any>("inner" to "v")))
        @Suppress("UNCHECKED_CAST")
        assertEquals("v", (out["outer"] as Map<String, Any>)["inner"])
    }

    @Test
    fun listOfCompoundsRoundTrips() {
        val items = listOf<Any>(
            linkedMapOf<String, Any>("name" to "a"),
            linkedMapOf<String, Any>("name" to "b"),
        )
        val out = roundTrip(mapOf("servers" to Nbt.NbtList(Nbt.TAG_COMPOUND, items)))
        val list = out["servers"] as Nbt.NbtList
        assertEquals(2, list.items.size)
        assertEquals(Nbt.TAG_COMPOUND, list.elementType)
    }

    @Test
    fun emptyListKeepsItsDeclaredElementType() {
        val out = roundTrip(mapOf("servers" to Nbt.NbtList(Nbt.TAG_COMPOUND, emptyList())))
        val list = out["servers"] as Nbt.NbtList
        assertTrue(list.items.isEmpty())
        assertEquals(Nbt.TAG_COMPOUND, list.elementType)
    }

    @Test
    fun listOfStringsRoundTrips() {
        val out = roundTrip(mapOf("tags" to Nbt.NbtList(Nbt.TAG_STRING, listOf<Any>("a", "b"))))
        assertEquals(listOf("a", "b"), (out["tags"] as Nbt.NbtList).items)
    }

    @Test
    fun keyOrderIsPreserved() {
        val root = linkedMapOf<String, Any>("z" to "1", "a" to "2", "m" to "3")
        assertEquals(listOf("z", "a", "m"), roundTrip(root).keys.toList())
    }

    @Test
    fun rootNameIsWrittenAndSkippedOnRead() {
        val bytes = Nbt.write(mapOf("k" to "v"), rootName = "root")
        assertEquals("v", Nbt.read(bytes)["k"])
    }

    @Test
    fun typeOfCoversSupportedValues() {
        assertEquals(Nbt.TAG_BYTE, Nbt.typeOf(1.toByte()))
        assertEquals(Nbt.TAG_BYTE, Nbt.typeOf(true))
        assertEquals(Nbt.TAG_STRING, Nbt.typeOf("x"))
        assertEquals(Nbt.TAG_LIST, Nbt.typeOf(Nbt.NbtList(Nbt.TAG_STRING, emptyList())))
        assertEquals(Nbt.TAG_COMPOUND, Nbt.typeOf(emptyMap<String, Any>()))
        assertEquals(Nbt.TAG_INT_ARRAY, Nbt.typeOf(intArrayOf()))
    }

    @Test(expected = Nbt.NbtException::class)
    fun unsupportedValueIsRejected() {
        Nbt.write(mapOf("bad" to Any()))
    }

    @Test(expected = Nbt.NbtException::class)
    fun nonCompoundRootIsRejected() {
        Nbt.read(byteArrayOf(Nbt.TAG_STRING.toByte(), 0, 0))
    }

    @Test(expected = Nbt.NbtException::class)
    fun truncatedDataIsRejected() {
        val bytes = Nbt.write(mapOf("k" to "long value here"))
        Nbt.read(bytes.copyOf(bytes.size - 4))
    }
}
