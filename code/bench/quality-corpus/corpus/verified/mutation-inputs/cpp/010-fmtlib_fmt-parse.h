FMT_CONSTEXPR auto parse(parse_context<Char>& ctx) -> const Char* {
  auto it = ctx.begin();
  auto end = ctx.end();
  it = specs_.parse(it, end, ctx, ':');
  if (it != end && detail::to_ascii(*it) == 'n') {
    ++it;
    set_brackets({}, {});
    set_separator({});
  }
  if (it != end && *it != '}') report_error("invalid format specifier");
  ctx.advance_to(it);
  detail::for_each(formatters_, detail::parse_empty_specs<Char>{ctx});
  return it;
}
