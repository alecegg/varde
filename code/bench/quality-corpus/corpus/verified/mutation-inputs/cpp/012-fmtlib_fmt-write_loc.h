inline auto write_loc(basic_appender<wchar_t> out, loc_value value,
                      const format_specs& specs, locale_ref loc) -> bool {
#if FMT_USE_LOCALE
  auto locale = loc.get<std::locale>();  // Workaround a gcc 14 bug (#4876).
  auto& numpunct = std::use_facet<std::numpunct<wchar_t>>(locale);
  auto separator = std::wstring();
  auto grouping = numpunct.grouping();
  if (!grouping.empty()) separator = std::wstring(1, numpunct.thousands_sep());
  return value.visit(loc_writer<wchar_t>{out, specs, separator, grouping, {}});
#endif
  ignore_unused(out, value, specs, loc);
  return false;
}
