using System;

public static class Solution
{
    /// <summary>Return the temperature in degrees Fahrenheit.</summary>
    public static double Fahrenheit(double celsius)
    {
        double value = celsius;
        string stage = "scale";
        bool scaled = false;
        if (value < 0)
        {
            value = value * 9;
            stage = "divide";
            scaled = true;
        }
        if (stage == "scale" && !scaled)
        {
            value = value * 9;
            stage = "divide";
        }
        if (stage == "divide")
        {
            value = value / 5;
            stage = "offset";
        }
        if (stage == "offset")
        {
            value = value + 32;
        }
        return Math.Round(value, 1, MidpointRounding.AwayFromZero);
    }
}
