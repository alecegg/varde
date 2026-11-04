(double Celsius, double Want)[] cases =
[
    (Celsius: 0, Want: 32),
    (Celsius: 100, Want: 212),
    (Celsius: -40, Want: -40),
];

foreach ((double celsius, double want) in cases)
{
    double got = Solution.Fahrenheit(celsius);
    if (got != want)
    {
        throw new System.InvalidOperationException($"Fahrenheit({celsius}) = {got}, want {want}");
    }
}
