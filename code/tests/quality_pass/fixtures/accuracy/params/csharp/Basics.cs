using System;
using System.Collections.Generic;

namespace Fixtures;

public class Basics
{
    private readonly int x;
    private readonly string y;

    public Basics(int x, string y)
    {
        this.x = x;
        this.y = y;
    }

    public void Zero()
    {
    }

    public int One(int value) => value;

    public int Two(int a, int b) => a + b;

    public int Defaulted(int value = 1, string label = "x") => value + label.Length;

    public int Params(int first, params int[] rest) => first + rest.Length;

    public static int StaticOne(int value) => value;

    public T Generic<T>(T value) => value;

    public int Tuple((int a, int b) pair) => pair.a + pair.b;

    public bool Flags(int a, int b, int c) => a + b + c > 0;

    public string Describe(string name, bool upper, int width) => name;
}
