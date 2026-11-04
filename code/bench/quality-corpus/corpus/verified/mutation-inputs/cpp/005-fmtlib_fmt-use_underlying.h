consteval auto use_underlying() -> bool {
  if constexpr (std::is_enum<U>::value) {
    // The annotations specify different representations. Reporting this here
    // gives a better diagnostic than an ambiguous formatter specialization.
    static_assert(!is_annotated<as_underlying_t, U>() ||
                      !is_annotated<as_identifiers_t, U>(),
                  "fmt::as_underlying and fmt::as_identifiers are mutually "
                  "exclusive");
    return is_annotated<as_underlying_t, U>();
  } else {
    return false;
  }
}
