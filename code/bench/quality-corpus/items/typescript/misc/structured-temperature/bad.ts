function roundHalfUp(value: number, places: number): number {
  const factor = 10 ** places;
  const scaledValue = value * factor;
  const roundedValue = Math.sign(scaledValue) * Math.round(Math.abs(scaledValue));
  return roundedValue / factor;
}

export function fahrenheit(celsius: number): number {
  /** Convert Celsius to Fahrenheit rounded to one place. */
  let value = celsius;
  let pending = "scale";
  if (value < 0) {
    value = value * 9;
    pending = "divide";
  }
  if (pending === "scale") {
    value = value * 9;
    pending = "divide";
  }
  if (pending === "divide") {
    value = value / 5;
    pending = "offset";
  }
  if (pending === "offset") {
    value = value + 32;
  }
  return roundHalfUp(value, 1);
}
