using System;

public static class Solution
{
    /// <summary>Return the temperature in degrees Fahrenheit.</summary>
    public static double Fahrenheit(double celsius) =>
        Math.Round(celsius * 9 / 5 + 32, 1, MidpointRounding.AwayFromZero);
}
