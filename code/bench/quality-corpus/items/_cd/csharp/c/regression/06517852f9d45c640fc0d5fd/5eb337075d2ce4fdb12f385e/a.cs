#region License
// Copyright (c) 2007 James Newton-King
//
// Permission is hereby granted, free of charge, to any person
// obtaining a copy of this software and associated documentation
// files (the "Software"), to deal in the Software without
// restriction, including without limitation the rights to use,
// copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the
// Software is furnished to do so, subject to the following
// conditions:
//
// The above copyright notice and this permission notice shall be
// included in all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
// EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
// OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
// NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
// HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
// WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
// FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
// OTHER DEALINGS IN THE SOFTWARE.
#endregion

public static string FormatWith(this string format, IFormatProvider provider, object arg0)
        {
            return format.FormatWith(provider, new[] { arg0 });
        }

public static string FormatWith(this string format, IFormatProvider provider, object arg0, object arg1)
        {
            return format.FormatWith(provider, new[] { arg0, arg1 });
        }

public static string FormatWith(this string format, IFormatProvider provider, object arg0, object arg1, object arg2)
        {
            return format.FormatWith(provider, new[] { arg0, arg1, arg2 });
        }

public static string FormatWith(this string format, IFormatProvider provider, params object[] args)
        {
            ValidationUtils.ArgumentNotNull(format, "format");

            return string.Format(provider, format, args);
        }

public static string ToCamelCase(string s)
        {
            if (string.IsNullOrEmpty(s))
                return s;

            if (!char.IsUpper(s[0]))
                return s;

            int length = s.Length;
            char[] chars = s.ToCharArray();
#if !(NETFX_CORE || PORTABLE)
            CultureInfo invariantCulture = CultureInfo.InvariantCulture;
#endif

            for (int i = 0; i < length; i++)
            {
                bool hasNext = (i + 1 < length);
                if (i > 0 && hasNext && !char.IsUpper(chars[i + 1]))
                    break;

#if !(NETFX_CORE || PORTABLE)
                chars[i] = char.ToLower(chars[i], invariantCulture);
#else
                chars[i] = char.ToLower(chars[i]);
#endif
            }

            return new string(chars);
        }

public static bool StartsWith(this string source, char value)
        {
            return (source.Length != 0 && source[0] == value);
        }

public static bool EndsWith(this string source, char value)
        {
            int sourceLen = source.Length;
            return (sourceLen != 0 && source[sourceLen - 1] == value);
        }