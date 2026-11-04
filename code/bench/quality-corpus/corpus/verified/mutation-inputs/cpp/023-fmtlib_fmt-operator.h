void operator()(T value) {
  // MSVC2013 fails to compile separate overloads for bool and Char so use
  // std::is_same instead.
  if (!std::is_same<T, Char>::value) {
    if (value == 0 && this->specs.precision == 0)
      return write_zero_with_zero_precision();
    return write(value);
  }
  format_specs s = this->specs;
  if (s.type() != presentation_type::none &&
      s.type() != presentation_type::chr) {
    return (*this)(static_cast<int>(value));
  }
  s.set_sign(sign::none);
  s.clear_alt();
  s.set_fill(' ');  // Ignore '0' flag for char types.
  // align::numeric needs to be overwritten here since the '0' flag is
  // ignored for non-numeric types
  if (s.align() == align::none || s.align() == align::numeric)
    s.set_align(align::right);
  detail::write<Char>(this->out, static_cast<Char>(value), s);
}
