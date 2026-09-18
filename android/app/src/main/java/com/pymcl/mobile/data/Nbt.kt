package com.pymcl.mobile.data

import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.EOFException

/**
 * 够用就好的 NBT 编解码，只为了读写 `servers.dat`。
 *
 * 游戏只认 servers.dat，不认我们写的 servers.json——只写 json 的话界面上加得进、
 * 进游戏多人列表却是空的（桌面端踩过，见 mclauncher/servers.py 顶部注释）。
 * servers.dat 是**未压缩**的 NBT（跟 gzip 的 level.dat 不一样），所以这里不做 gzip。
 */
object Nbt {
    const val TAG_END = 0
    const val TAG_BYTE = 1
    const val TAG_SHORT = 2
    const val TAG_INT = 3
    const val TAG_LONG = 4
    const val TAG_FLOAT = 5
    const val TAG_DOUBLE = 6
    const val TAG_BYTE_ARRAY = 7
    const val TAG_STRING = 8
    const val TAG_LIST = 9
    const val TAG_COMPOUND = 10
    const val TAG_INT_ARRAY = 11
    const val TAG_LONG_ARRAY = 12

    class NbtException(message: String) : RuntimeException(message)

    /** 一个 TAG_List：元素类型要记住，空表写回去也得带上原来的类型。 */
    data class NbtList(val elementType: Int, val items: List<Any>)

    fun read(bytes: ByteArray): Map<String, Any> {
        if (bytes.isEmpty()) return emptyMap()
        val input = DataInputStream(bytes.inputStream())
        try {
            val type = input.read()
            if (type != TAG_COMPOUND) throw NbtException("根标签不是 TAG_Compound: $type")
            input.readUTF()
            @Suppress("UNCHECKED_CAST")
            return readPayload(input, TAG_COMPOUND) as Map<String, Any>
        } catch (e: EOFException) {
            throw NbtException("NBT 数据截断")
        }
    }

    fun write(root: Map<String, Any>, rootName: String = ""): ByteArray {
        val buffer = ByteArrayOutputStream()
        val out = DataOutputStream(buffer)
        out.writeByte(TAG_COMPOUND)
        out.writeUTF(rootName)
        writePayload(out, root)
        out.flush()
        return buffer.toByteArray()
    }

    private fun readPayload(input: DataInputStream, type: Int): Any = when (type) {
        TAG_BYTE -> input.readByte()
        TAG_SHORT -> input.readShort()
        TAG_INT -> input.readInt()
        TAG_LONG -> input.readLong()
        TAG_FLOAT -> input.readFloat()
        TAG_DOUBLE -> input.readDouble()
        TAG_BYTE_ARRAY -> ByteArray(input.readInt()).also { input.readFully(it) }
        TAG_STRING -> input.readUTF()
        TAG_LIST -> {
            val elem = input.read()
            val size = input.readInt()
            val items = ArrayList<Any>(maxOf(size, 0))
            if (size > 0 && elem != TAG_END) {
                repeat(size) { items += readPayload(input, elem) }
            }
            NbtList(elem, items)
        }
        TAG_COMPOUND -> {
            val map = LinkedHashMap<String, Any>()
            while (true) {
                val child = input.read()
                if (child <= TAG_END) break
                val name = input.readUTF()
                map[name] = readPayload(input, child)
            }
            map
        }
        TAG_INT_ARRAY -> IntArray(input.readInt()) { input.readInt() }
        TAG_LONG_ARRAY -> LongArray(input.readInt()) { input.readLong() }
        else -> throw NbtException("未知标签类型: $type")
    }

    internal fun typeOf(value: Any): Int = when (value) {
        is Byte -> TAG_BYTE
        is Boolean -> TAG_BYTE
        is Short -> TAG_SHORT
        is Int -> TAG_INT
        is Long -> TAG_LONG
        is Float -> TAG_FLOAT
        is Double -> TAG_DOUBLE
        is ByteArray -> TAG_BYTE_ARRAY
        is String -> TAG_STRING
        is NbtList -> TAG_LIST
        is Map<*, *> -> TAG_COMPOUND
        is IntArray -> TAG_INT_ARRAY
        is LongArray -> TAG_LONG_ARRAY
        else -> throw NbtException("不支持的值类型: ${value.javaClass.name}")
    }

    private fun writePayload(out: DataOutputStream, value: Any) {
        when (value) {
            is Boolean -> out.writeByte(if (value) 1 else 0)
            is Byte -> out.writeByte(value.toInt())
            is Short -> out.writeShort(value.toInt())
            is Int -> out.writeInt(value)
            is Long -> out.writeLong(value)
            is Float -> out.writeFloat(value)
            is Double -> out.writeDouble(value)
            is ByteArray -> {
                out.writeInt(value.size)
                out.write(value)
            }
            is String -> out.writeUTF(value)
            is NbtList -> {
                val elem = if (value.items.isEmpty()) value.elementType else typeOf(value.items[0])
                out.writeByte(elem)
                out.writeInt(value.items.size)
                value.items.forEach { writePayload(out, it) }
            }
            is Map<*, *> -> {
                value.forEach { (key, child) ->
                    if (key !is String || child == null) return@forEach
                    out.writeByte(typeOf(child))
                    out.writeUTF(key)
                    writePayload(out, child)
                }
                out.writeByte(TAG_END)
            }
            is IntArray -> {
                out.writeInt(value.size)
                value.forEach { out.writeInt(it) }
            }
            is LongArray -> {
                out.writeInt(value.size)
                value.forEach { out.writeLong(it) }
            }
            else -> throw NbtException("不支持的值类型: ${value.javaClass.name}")
        }
    }
}
