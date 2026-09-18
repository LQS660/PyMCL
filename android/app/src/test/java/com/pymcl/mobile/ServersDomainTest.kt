package com.pymcl.mobile

import com.pymcl.mobile.data.Nbt
import com.pymcl.mobile.data.ServerError
import com.pymcl.mobile.data.Servers
import com.pymcl.mobile.model.ServerEntry
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

class ServersDomainTest {
    private lateinit var dir: File

    @Before
    fun setUp() {
        dir = kotlin.io.path.createTempDirectory("pymcl-servers").toFile()
    }

    @After
    fun tearDown() {
        dir.deleteRecursively()
    }

    @Test
    fun splitAddressUsesExplicitPort() {
        assertEquals("mc.example.com" to 19132, Servers.splitAddress("mc.example.com", 19132))
        assertEquals("mc.example.com" to 19132, Servers.splitAddress("mc.example.com", "19132"))
    }

    @Test
    fun splitAddressReadsPortFromText() {
        assertEquals("mc.example.com" to 25566, Servers.splitAddress("mc.example.com:25566"))
    }

    @Test
    fun splitAddressFallsBackToDefaultPort() {
        assertEquals("mc.example.com" to 25565, Servers.splitAddress("mc.example.com"))
        assertEquals("mc.example.com" to 25565, Servers.splitAddress("mc.example.com", "abc"))
        assertEquals("mc.example.com" to 25565, Servers.splitAddress("mc.example.com", 0))
        assertEquals("mc.example.com" to 25565, Servers.splitAddress("mc.example.com", 70000))
    }

    @Test
    fun splitAddressTrimsWhitespace() {
        assertEquals("mc.example.com" to 25565, Servers.splitAddress("  mc.example.com  "))
    }

    @Test
    fun splitAddressKeepsIpv6Literal() {
        val (host, port) = Servers.splitAddress("fe80::1")
        assertEquals("fe80::1", host)
        assertEquals(25565, port)
    }

    @Test
    fun addStoresNormalizedEntry() {
        val row = Servers.add(dir, "  家里的服  ", " mc.example.com ", 25566, " 生存 ")
        assertEquals("家里的服", row.name)
        assertEquals("mc.example.com", row.ip)
        assertEquals(25566, row.port)
        assertEquals("生存", row.description)
        assertEquals(0, row.index)
    }

    @Test
    fun addFallsBackToAddressAsName() {
        val row = Servers.add(dir, "", "mc.example.com")
        assertEquals("mc.example.com", row.name)
    }

    @Test(expected = ServerError::class)
    fun addRejectsBlankAddress() {
        Servers.add(dir, "x", "   ")
    }

    @Test(expected = ServerError::class)
    fun addRejectsBadPort() {
        Servers.add(dir, "x", "mc.example.com", 70000)
    }

    @Test
    fun listReturnsInsertionOrder() {
        Servers.add(dir, "a", "a.example.com")
        Servers.add(dir, "b", "b.example.com")
        Servers.add(dir, "c", "c.example.com")
        assertEquals(listOf("a", "b", "c"), Servers.list(dir).map { it.name })
        assertEquals(listOf(0, 1, 2), Servers.list(dir).map { it.index })
    }

    @Test
    fun updateChangesOnlyGivenFields() {
        Servers.add(dir, "old", "a.example.com", 25565, "desc")
        val row = Servers.update(dir, 0, name = "new")
        assertEquals("new", row.name)
        assertEquals("a.example.com", row.ip)
        assertEquals("desc", Servers.list(dir)[0].description)
    }

    @Test(expected = ServerError::class)
    fun updateRejectsUnknownIndex() {
        Servers.update(dir, 3, name = "x")
    }

    @Test(expected = ServerError::class)
    fun updateRejectsBlankAddress() {
        Servers.add(dir, "a", "a.example.com")
        Servers.update(dir, 0, ip = " ")
    }

    @Test
    fun deleteShiftsRemainingIndexes() {
        Servers.add(dir, "a", "a.example.com")
        Servers.add(dir, "b", "b.example.com")
        Servers.delete(dir, 0)
        val rows = Servers.list(dir)
        assertEquals(1, rows.size)
        assertEquals("b", rows[0].name)
        assertEquals(0, rows[0].index)
    }

    @Test(expected = ServerError::class)
    fun deleteRejectsUnknownIndex() {
        Servers.delete(dir, 0)
    }

    @Test
    fun moveReordersRows() {
        Servers.add(dir, "a", "a.example.com")
        Servers.add(dir, "b", "b.example.com")
        Servers.add(dir, "c", "c.example.com")
        Servers.move(dir, 2, 0)
        assertEquals(listOf("c", "a", "b"), Servers.list(dir).map { it.name })
    }

    @Test
    fun moveClampsTargetIndex() {
        Servers.add(dir, "a", "a.example.com")
        Servers.add(dir, "b", "b.example.com")
        Servers.move(dir, 0, 99)
        assertEquals(listOf("b", "a"), Servers.list(dir).map { it.name })
    }

    @Test
    fun importTextParsesAllThreeShapes() {
        val added = Servers.importText(
            dir,
            """
            # comment
            生存服	mc.a.com:25566
            mc.b.com:25567
            mc.c.com

            """.trimIndent(),
        )
        assertEquals(3, added)
        val rows = Servers.list(dir)
        assertEquals("生存服", rows[0].name)
        assertEquals(25566, rows[0].port)
        assertEquals("mc.b.com", rows[1].name)
        assertEquals(25565, rows[2].port)
    }

    @Test
    fun importTextSkipsDuplicateAddresses() {
        Servers.add(dir, "a", "mc.a.com", 25566)
        val added = Servers.importText(dir, "mc.a.com:25566\nmc.d.com")
        assertEquals(1, added)
        assertEquals(2, Servers.list(dir).size)
    }

    @Test
    fun exportTextRoundTripsThroughImport() {
        Servers.add(dir, "生存服", "mc.a.com", 25566)
        Servers.add(dir, "mc.b.com", "mc.b.com")
        val text = Servers.exportText(dir)
        assertTrue(text.startsWith("# PyMCL 服务器列表导出"))
        assertTrue(text.contains("生存服\tmc.a.com:25566"))
        assertTrue(text.contains("mc.b.com:25565"))

        val other = File(dir, "other").also { it.mkdirs() }
        assertEquals(2, Servers.importText(other, text))
        assertEquals(Servers.list(dir).map { it.ip to it.port }, Servers.list(other).map { it.ip to it.port })
    }

    @Test
    fun importJsonSkipsDuplicatesAndBadRows() {
        val added = Servers.importJson(
            dir,
            """[{"name":"a","ip":"mc.a.com","port":25566},{"ip":""},{"name":"a2","ip":"mc.a.com","port":25566},7]""",
        )
        assertEquals(1, added)
        assertEquals("a", Servers.list(dir)[0].name)
    }

    @Test(expected = ServerError::class)
    fun importJsonRejectsNonArray() {
        Servers.importJson(dir, "{}")
    }

    @Test
    fun exportJsonCarriesDescription() {
        Servers.add(dir, "a", "mc.a.com", 25566, "生存")
        val text = Servers.exportJson(dir)
        assertEquals(1, Servers.importJson(File(dir, "o").also { it.mkdirs() }, text))
        assertTrue(text.contains("生存"))
    }

    @Test
    fun writeAllAlsoWritesGameReadableDat() {
        Servers.add(dir, "生存服", "mc.a.com", 25566)
        val dat = Servers.datFile(dir)
        assertTrue(dat.isFile)
        val root = Nbt.read(dat.readBytes())
        val list = root["servers"] as Nbt.NbtList
        assertEquals(1, list.items.size)
        @Suppress("UNCHECKED_CAST")
        val row = list.items[0] as Map<String, Any>
        assertEquals("生存服", row["name"])
        assertEquals("mc.a.com:25566", row["ip"])
    }

    @Test
    fun datOmitsDefaultPortFromAddress() {
        Servers.add(dir, "a", "mc.a.com")
        val root = Nbt.read(Servers.datFile(dir).readBytes())
        val list = root["servers"] as Nbt.NbtList
        @Suppress("UNCHECKED_CAST")
        val row = list.items[0] as Map<String, Any>
        assertEquals("mc.a.com", row["ip"])
    }

    @Test
    fun datWinsOverJsonButJsonSuppliesDescription() {
        Servers.add(dir, "a", "mc.a.com", 25566, "生存")
        // 手动往 dat 里塞第二条，模拟用户在游戏里加的服务器
        Servers.writeDat(
            Servers.datFile(dir),
            listOf(
                ServerEntry("a", "mc.a.com", 25566),
                ServerEntry("游戏里加的", "mc.z.com", 25565),
            ),
        )
        val rows = Servers.list(dir)
        assertEquals(2, rows.size)
        assertEquals("生存", rows[0].description)
        assertEquals("游戏里加的", rows[1].name)
        assertEquals("", rows[1].description)
    }

    @Test
    fun listFallsBackToJsonWhenDatMissing() {
        Servers.add(dir, "a", "mc.a.com")
        assertTrue(Servers.datFile(dir).delete())
        assertEquals(listOf("a"), Servers.list(dir).map { it.name })
    }

    @Test
    fun listIsEmptyOnFreshDirectory() {
        assertTrue(Servers.list(dir).isEmpty())
    }

    @Test
    fun hiddenFlagSurvivesRoundTrip() {
        Servers.add(dir, "a", "mc.a.com")
        Servers.update(dir, 0, hidden = true)
        assertTrue(Servers.readDat(Servers.datFile(dir))[0].hidden)
        assertFalse(Servers.readJson(Servers.jsonFile(dir)).isEmpty())
    }

    @Test
    fun readDatIgnoresCorruptFile() {
        Servers.datFile(dir).writeBytes(byteArrayOf(9, 9, 9, 9))
        assertTrue(Servers.readDat(Servers.datFile(dir)).isEmpty())
    }

    @Test
    fun readJsonIgnoresCorruptFile() {
        Servers.jsonFile(dir).writeText("not json")
        assertTrue(Servers.readJson(Servers.jsonFile(dir)).isEmpty())
    }

    @Test
    fun addAcceptsAddressWithInlinePort() {
        val row = Servers.add(dir, "", "mc.a.com:25570")
        assertEquals("mc.a.com", row.ip)
        assertEquals(25570, row.port)
        assertNotNull(Servers.list(dir).firstOrNull { it.port == 25570 })
    }
}
