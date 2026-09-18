package com.pymcl.mobile

import com.pymcl.mobile.data.Playtime
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

class PlaytimeDomainTest {
    private lateinit var root: File

    @Before
    fun setUp() {
        root = kotlin.io.path.createTempDirectory("pymcl-playtime").toFile()
    }

    @After
    fun tearDown() {
        root.deleteRecursively()
    }

    @Test
    fun loadIsEmptyWithoutFile() {
        assertTrue(Playtime.load(root).isEmpty())
    }

    @Test
    fun loadIgnoresCorruptFile() {
        Playtime.file(root).writeText("not json")
        assertTrue(Playtime.load(root).isEmpty())
    }

    @Test
    fun recordCreatesInstanceRow() {
        val stat = Playtime.record(root, "default", "1.20.1", 600, now = 1000)
        assertEquals(600L, stat.total)
        assertEquals(600L, stat.versions["1.20.1"])
        assertEquals(1, stat.sessions.size)
        assertEquals(400L, stat.sessions[0].start)
    }

    @Test
    fun recordAccumulatesPerVersion() {
        Playtime.record(root, "default", "1.20.1", 600, now = 1000)
        Playtime.record(root, "default", "1.20.1", 300, now = 2000)
        Playtime.record(root, "default", "1.21", 120, now = 3000)
        val stat = Playtime.get(root, "default")
        assertEquals(1020L, stat.total)
        assertEquals(900L, stat.versions["1.20.1"])
        assertEquals(120L, stat.versions["1.21"])
        assertEquals(3, stat.sessions.size)
    }

    @Test
    fun recordIgnoresNonPositiveDuration() {
        Playtime.record(root, "default", "1.20.1", 0)
        Playtime.record(root, "default", "1.20.1", -5)
        assertTrue(Playtime.load(root).isEmpty())
    }

    @Test
    fun recordKeepsInstancesApart() {
        Playtime.record(root, "a", "1.20.1", 60, now = 100)
        Playtime.record(root, "b", "1.20.1", 90, now = 200)
        assertEquals(60L, Playtime.get(root, "a").total)
        assertEquals(90L, Playtime.get(root, "b").total)
    }

    @Test
    fun sessionsAreCappedAtMax() {
        repeat(Playtime.MAX_SESSIONS + 12) {
            Playtime.record(root, "default", "1.20.1", 1, now = 1000L + it)
        }
        val stat = Playtime.get(root, "default")
        assertEquals(Playtime.MAX_SESSIONS, stat.sessions.size)
        assertEquals((Playtime.MAX_SESSIONS + 12).toLong(), stat.total)
    }

    @Test
    fun getReturnsEmptyStatForUnknownInstance() {
        Playtime.record(root, "a", "1.20.1", 60)
        val stat = Playtime.get(root, "nope")
        assertEquals(0L, stat.total)
        assertTrue(stat.versions.isEmpty())
    }

    @Test
    fun totalOfSumsAllInstances() {
        Playtime.record(root, "a", "1.20.1", 60, now = 100)
        Playtime.record(root, "b", "1.21", 40, now = 200)
        assertEquals(100L, Playtime.totalOf(Playtime.load(root)))
    }

    @Test
    fun totalOfIsZeroWhenEmpty() {
        assertEquals(0L, Playtime.totalOf(emptyMap()))
    }

    @Test
    fun clearAllWipesEveryInstance() {
        Playtime.record(root, "a", "1.20.1", 60, now = 100)
        Playtime.record(root, "b", "1.21", 40, now = 200)
        Playtime.clear(root)
        assertTrue(Playtime.load(root).isEmpty())
    }

    @Test
    fun clearOneInstanceLeavesOthers() {
        Playtime.record(root, "a", "1.20.1", 60, now = 100)
        Playtime.record(root, "b", "1.21", 40, now = 200)
        Playtime.clear(root, "a")
        assertEquals(setOf("b"), Playtime.load(root).keys)
    }

    @Test
    fun clearOneVersionRecomputesTotalFromSessions() {
        Playtime.record(root, "a", "1.20.1", 60, now = 100)
        Playtime.record(root, "a", "1.21", 40, now = 200)
        Playtime.clear(root, "a", "1.20.1")
        val stat = Playtime.get(root, "a")
        assertEquals(40L, stat.total)
        assertEquals(setOf("1.21"), stat.versions.keys)
        assertEquals(1, stat.sessions.size)
    }

    @Test
    fun clearUnknownInstanceIsNoOp() {
        Playtime.record(root, "a", "1.20.1", 60, now = 100)
        Playtime.clear(root, "nope")
        assertEquals(60L, Playtime.get(root, "a").total)
    }

    @Test
    fun saveAndLoadRoundTrip() {
        Playtime.record(root, "a", "1.20.1", 61, now = 100)
        val before = Playtime.load(root)
        Playtime.save(root, before)
        assertEquals(before, Playtime.load(root))
    }

    @Test
    fun fileNameMatchesDesktop() {
        assertEquals("playtime.json", Playtime.FILE_NAME)
        assertTrue(Playtime.file(root).path.endsWith("playtime.json"))
    }

    @Test
    fun formatUsesHoursWhenLongEnough() {
        assertEquals("1 小时 1 分钟", Playtime.format(3660))
        assertEquals("2 小时 0 分钟", Playtime.format(7200))
    }

    @Test
    fun formatUsesMinutesAndSeconds() {
        assertEquals("1 分钟 5 秒", Playtime.format(65))
        assertEquals("45 秒", Playtime.format(45))
    }

    @Test
    fun formatClampsNegative() {
        assertEquals("0 秒", Playtime.format(-10))
    }

    @Test
    fun trackerRecordsElapsedSeconds() {
        var clock = 1_000L
        val tracker = Playtime.Tracker(root, "a", "1.20.1") { clock }
        tracker.start()
        clock += 125
        assertEquals(125L, tracker.stop())
        assertEquals(125L, Playtime.get(root, "a").total)
    }

    @Test
    fun trackerWithoutStartRecordsNothing() {
        val tracker = Playtime.Tracker(root, "a", "1.20.1") { 5 }
        assertEquals(0L, tracker.stop())
        assertTrue(Playtime.load(root).isEmpty())
    }

    @Test
    fun trackerIgnoresZeroLengthSession() {
        var clock = 1_000L
        val tracker = Playtime.Tracker(root, "a", "1.20.1") { clock }
        tracker.start()
        assertEquals(0L, tracker.stop())
        assertTrue(Playtime.load(root).isEmpty())
    }

    @Test
    fun trackerDoesNotDoubleCountAfterStop() {
        var clock = 1_000L
        val tracker = Playtime.Tracker(root, "a", "1.20.1") { clock }
        tracker.start()
        clock += 30
        tracker.stop()
        clock += 30
        assertEquals(0L, tracker.stop())
        assertEquals(30L, Playtime.get(root, "a").total)
    }
}
