// net48 编译期 polyfill：让 LangVersion=latest 的 record/init/required 语法可用，
// 并补齐 net48 缺失的少量 BCL API。这些类型只在本程序集内可见。

using System.Collections.Generic;
using System.IO;

namespace System.Runtime.CompilerServices
{
    internal static class IsExternalInit { }

    [AttributeUsage(AttributeTargets.Class | AttributeTargets.Struct | AttributeTargets.Property | AttributeTargets.Field, AllowMultiple = false, Inherited = false)]
    internal sealed class RequiredMemberAttribute : Attribute { }

    [AttributeUsage(AttributeTargets.All, AllowMultiple = false, Inherited = false)]
    internal sealed class CompilerFeatureRequiredAttribute : Attribute
    {
        public CompilerFeatureRequiredAttribute(string featureName) => FeatureName = featureName;

        public string FeatureName { get; }

        public bool IsOptional { get; init; }
    }
}

namespace PyMCL
{
    /// <summary>net48 没有 Math.Clamp：IComparable 泛型等价实现，int/double 调用点语义不变。</summary>
    internal static class Clamp
    {
        public static T Of<T>(T value, T min, T max) where T : IComparable<T>
        {
            if (value.CompareTo(min) < 0) return min;
            if (value.CompareTo(max) > 0) return max;
            return value;
        }
    }

    internal static class PyPath
    {
        /// <summary>net48 没有 Path.GetRelativePath：同盘且在其前缀下才返回相对路径，否则退回原样（调用方只做展示）。</summary>
        public static string GetRelativePath(string relativeTo, string path)
        {
            try
            {
                var baseDir = Path.GetFullPath(relativeTo);
                if (!baseDir.EndsWith(Path.DirectorySeparatorChar.ToString(), StringComparison.Ordinal))
                    baseDir += Path.DirectorySeparatorChar;
                var full = Path.GetFullPath(path);
                return full.StartsWith(baseDir, StringComparison.OrdinalIgnoreCase)
                    ? full.Substring(baseDir.Length)
                    : path;
            }
            catch { return path; }
        }
    }

    /// <summary>net48 缺失的 BCL 扩展（CollectionExtensions / string 的 char 重载等）。</summary>
    internal static class BclExtensions
    {
        public static V GetValueOrDefault<K, V>(this IReadOnlyDictionary<K, V> dict, K key) =>
            dict.TryGetValue(key, out var v) ? v : default;

        public static V GetValueOrDefault<K, V>(this IReadOnlyDictionary<K, V> dict, K key, V fallback) =>
            dict.TryGetValue(key, out var v) ? v : fallback;

        public static void Deconstruct<K, V>(this KeyValuePair<K, V> kv, out K key, out V value)
        {
            key = kv.Key;
            value = kv.Value;
        }

        public static bool TryAdd<K, V>(this Dictionary<K, V> dict, K key, V value)
        {
            if (dict.ContainsKey(key)) return false;
            dict.Add(key, value);
            return true;
        }

        public static bool Contains(this string s, string value, StringComparison comparison) =>
            s.IndexOf(value, comparison) >= 0;

        public static bool Contains(this string s, char c) => s.IndexOf(c) >= 0;

        public static bool StartsWith(this string s, char c) => s.Length > 0 && s[0] == c;

        public static bool EndsWith(this string s, char c) => s.Length > 0 && s[s.Length - 1] == c;
    }
}
