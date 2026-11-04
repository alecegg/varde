FMT_FUNC auto write_loc(appender out, loc_value value,
                        const format_specs& specs, locale_ref loc) -> bool {
  auto locale = loc.get<std::locale>();
  // We cannot use the num_put<char> facet because it may produce output in
  // a wrong encoding.
  using facet = format_facet<std::locale>;
  if (std::has_facet<facet>(locale))
    return use_facet<facet>(locale).put(out, value, specs);
  return facet(locale).put(out, value, specs);
}
