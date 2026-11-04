static int convert_c_format_args(
    fmt::basic_format_arg<fmt::format_context>* format_args,
    const fmt_arg* args, size_t num_args) {
  if (num_args > max_c_format_args) return fmt_error_invalid_arg;

  for (size_t i = 0; i < num_args; ++i) {
    switch (args[i].type) {
    case fmt_int:    format_args[i] = args[i].value.int_value; break;
    case fmt_uint:   format_args[i] = args[i].value.uint_value; break;
    case fmt_bool:   format_args[i] = args[i].value.bool_value; break;
    case fmt_char:   format_args[i] = args[i].value.char_value; break;
    case fmt_float:  format_args[i] = args[i].value.float_value; break;
    case fmt_double: format_args[i] = args[i].value.double_value; break;
    case fmt_long_double:
      format_args[i] = args[i].value.long_double_value;
      break;
    case fmt_cstring: format_args[i] = args[i].value.cstring; break;
    case fmt_pointer: format_args[i] = args[i].value.pointer; break;
    default:          return fmt_error_invalid_arg;
    }
  }
  return 0;
}
