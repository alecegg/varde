auto write_encoded_tm_str(OutputIt out, string_view in, const std::locale& loc)
    -> OutputIt {
  if (detail::use_utf8 && loc != get_classic_locale()) {
    // char16_t and char32_t codecvts are broken in MSVC (linkage errors) and
    // gcc-4.
#if FMT_MSC_VERSION != 0 ||  \
    (defined(__GLIBCXX__) && \
     (!defined(_GLIBCXX_USE_DUAL_ABI) || _GLIBCXX_USE_DUAL_ABI == 0))
    // The _GLIBCXX_USE_DUAL_ABI macro is always defined in libstdc++ from gcc-5
    // and newer.
    using code_unit = wchar_t;
#else
    using code_unit = char32_t;
#endif

    using unit_t = codecvt_result<code_unit>;
    unit_t unit;
    write_codecvt(unit, in, loc);
    // In UTF-8 is used one to four one-byte code units.
    auto u =
        to_utf8<code_unit, basic_memory_buffer<char, unit_t::max_size * 4>>();
    if (!u.convert({unit.buf, to_unsigned(unit.end - unit.buf)}))
      FMT_THROW(format_error("failed to format time"));
    return copy<char>(u.c_str(), u.c_str() + u.size(), out);
  }
  return copy<char>(in.data(), in.data() + in.size(), out);
}
