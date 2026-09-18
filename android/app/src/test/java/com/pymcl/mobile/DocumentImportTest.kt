package com.pymcl.mobile

import com.pymcl.mobile.data.DocumentImport
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.nio.file.Files

class DocumentImportTest {
    private fun withCache(test: (File) -> Unit) {
        val dir = Files.createTempDirectory("document-import-test-").toFile()
        try { test(dir) } finally { dir.deleteRecursively() }
    }
    private fun assertClean(cache: File) {
        assertTrue(File(cache, "content-import").listFiles().orEmpty().isEmpty())
    }
    @Test fun preservesNameAndBytesAndClosesStream() = withCache { cache ->
        var closed = false
        val input = object : ByteArrayInputStream(byteArrayOf(1, 2, 3)) {
            override fun close() { closed = true; super.close() }
        }
        val name = DocumentImport.consume(cache, "My Pack.ZIP", listOf("zip"), { input }) {
            assertArrayEquals(byteArrayOf(1, 2, 3), it.readBytes())
            it.name
        }
        assertEquals("My Pack.ZIP", name)
        assertTrue(closed)
        assertClean(cache)
    }
    @Test fun rejectsTraversalAndInvalidExtensionsBeforeOpening() = withCache { cache ->
        for (name in listOf("../x.zip", "..\\x.zip", "C:x.zip", ".", "..", "x.exe", "", "x\u0000.zip")) {
            var opened = false
            assertThrows(IllegalArgumentException::class.java) {
                DocumentImport.consume(cache, name, listOf("zip"), { opened = true; null }) { }
            }
            assertFalse(opened)
        }
        assertClean(cache)
    }
    @Test fun cleansUpWhenProviderCannotOpen() = withCache { cache ->
        assertThrows(IllegalStateException::class.java) {
            DocumentImport.consume(cache, "x.zip", listOf("zip"), { null }) { }
        }
        assertClean(cache)
    }
    @Test fun cleansUpOnReadFailure() = withCache { cache ->
        var closed = false
        val input = object : InputStream() {
            override fun read(): Int = throw IOException("provider disconnected")
            override fun close() { closed = true }
        }
        assertThrows(IOException::class.java) {
            DocumentImport.consume(cache, "x.zip", listOf("zip"), { input }) { fail("must not import") }
        }
        assertTrue(closed)
        assertClean(cache)
    }
    @Test fun cleansUpOnImporterFailure() = withCache { cache ->
        assertThrows(IOException::class.java) {
            DocumentImport.consume(cache, "x.zip", listOf("zip"), { ByteArrayInputStream(byteArrayOf(4)) }) {
                throw IOException("bad archive")
            }
        }
        assertClean(cache)
    }
    @Test fun sameNamesHaveSeparateStagingAndDoNotDeleteExistingCache() = withCache { cache ->
        val existing = File(cache, "same.zip").apply { writeText("keep") }
        DocumentImport.consume(cache, "same.zip", listOf("zip"), { "first".byteInputStream() }) { first ->
            DocumentImport.consume(cache, "same.zip", listOf("zip"), { "second".byteInputStream() }) { second ->
                assertNotEquals(first.parentFile, second.parentFile)
                assertEquals("first", first.readText())
                assertEquals("second", second.readText())
            }
            assertTrue(first.isFile)
        }
        assertEquals("keep", existing.readText())
        assertClean(cache)
    }
}
