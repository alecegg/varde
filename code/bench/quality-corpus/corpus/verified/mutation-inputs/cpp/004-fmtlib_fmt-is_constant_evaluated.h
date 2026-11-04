constexpr auto is_constant_evaluated(bool default_value = false) noexcept
    -> bool {
// Workaround for incompatibility between clang 14 and libstdc++ consteval-based
// std::is_constant_evaluated: https://github.com/fmtlib/fmt/issues/3247.
#if FMT_CPLUSPLUS >= 202002L && FMT_GLIBCXX_RELEASE >= 12 && \
    (FMT_CLANG_VERSION >= 1400 && FMT_CLANG_VERSION < 1500)
  ignore_unused(default_value);
  return __builtin_is_constant_evaluated();
#elif defined(__cpp_lib_is_constant_evaluated)
  ignore_unused(default_value);
  return std::is_constant_evaluated();
#else
  return default_value;
#endif
}
