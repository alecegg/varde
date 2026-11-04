function roundHalfUp(value: number, places: number): number {
  const factor = 10 ** places;
  const scaledValue = value * factor;
  const roundedValue = Math.sign(scaledValue) * Math.round(Math.abs(scaledValue));
  return roundedValue / factor;
}

export function fahrenheit(celsius: number): number {
  /** Convert Celsius to Fahrenheit rounded to one place. */
  const scaledCelsius = (celsius * 9) / 5;
  return roundHalfUp(scaledCelsius + 32, 1);
}
