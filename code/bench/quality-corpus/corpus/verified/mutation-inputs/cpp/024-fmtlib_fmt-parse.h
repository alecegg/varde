FMT_CONSTEXPR auto parse(parse_context<Char>& ctx) -> const Char* {
  auto it = ctx.begin();
  auto end = ctx.end();
  detail::maybe_set_debug_format(underlying_, true);
  if (it == end) return underlying_.parse(ctx);

  it = specs_.parse(it, end, ctx, ':');
  if (it == end) {
    ctx.advance_to(it);
    return underlying_.parse(ctx);
  }

  switch (detail::to_ascii(*it)) {
  case 'n':
    set_brackets({}, {});
    ++it;
    break;
  case '?':
    is_debug = true;
    set_brackets({}, {});
    ++it;
    if (it == end || *it != 's') report_error("invalid format specifier");
    FMT_FALLTHROUGH;
  case 's':
    if (!std::is_same<T, Char>::value)
      report_error("invalid format specifier");
    if (!is_debug) {
      set_brackets(detail::string_literal<Char, '"'>{},
                   detail::string_literal<Char, '"'>{});
      set_separator({});
      detail::maybe_set_debug_format(underlying_, false);
    }
    ++it;
    return it;
  }

  if (it != end && *it != '}') {
    if (*it != ':') report_error("invalid format specifier");
    detail::maybe_set_debug_format(underlying_, false);
    ++it;
  }

  ctx.advance_to(it);
  return underlying_.parse(ctx);
}
