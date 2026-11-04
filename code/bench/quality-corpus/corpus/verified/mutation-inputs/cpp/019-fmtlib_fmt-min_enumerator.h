template <typename E> consteval auto min_enumerator() -> E {
  auto enumerators = std::meta::enumerators_of(^^E);
  if (enumerators.empty()) return E();
  auto min = std::meta::extract<E>(enumerators[0]);
  for (std::meta::info e : enumerators) {
    auto value = std::meta::extract<E>(e);
    if (value < min) min = value;
  }
  return min;
}
