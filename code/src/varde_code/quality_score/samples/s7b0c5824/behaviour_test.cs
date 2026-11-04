using System.Collections.Generic;
using System;
using System.Globalization;

public static class BehaviourTest
{
    private static int failures;

    public static int Main()
    {
        var a = Original.Process(" A |2|10.00\nB|1|30");
        Check(a.Items.Count == 2, "item count");
        Check(a.Items[0].Sku == "A" && a.Items[1].Sku == "B", "trim and order");
        Check(a.Items[0].LineTotal == 20m && a.Items[1].LineTotal == 30m, "line totals");
        Check(a.Subtotal == 50m && a.Discount == 2.5m, "five percent threshold");
        Check(a.Tax == 3.92m && a.Shipping == 5.95m && a.Total == 57.37m, "tax and shipping");

        var b = Original.Process("X|2|50");
        Check(b.Subtotal == 100m && b.Discount == 10m, "ten percent threshold");
        Check(b.Tax == 7.43m && b.Shipping == 0m && b.Total == 97.43m, "free shipping tier");

        var taxRateEdge = Original.Process("T|1|1.03");
        Check(taxRateEdge.Tax == 0.08m, "tax rate at a rounding-sensitive amount");

        var c = Original.Process("Y|1|10");
        Check(c.Discount == 0m && c.Shipping == 8.95m && c.Total == 19.78m, "lowest shipping tier");
        Check(Original.Report(c) == "Order\nItems: 1\nSubtotal: $10.00\nDiscount: $0.00\nTax: $0.83\nShipping: $8.95\nTotal: $19.78", "report formatting");
        Check(Original.Report(a).Contains("Items: 2", StringComparison.Ordinal), "report item count");

        var d = Original.Process("Q|1|24.99");
        Check(d.Shipping == 8.95m, "below first shipping edge");
        var e = Original.Process("Q|1|25");
        Check(e.Shipping == 5.95m, "first shipping edge");
        var f = Original.Process("Q|1|100");
        Check(f.Shipping == 0m, "second shipping edge");
        var exactFreeShippingEdge = Original.Process("Q|1|78.95");
        Check(exactFreeShippingEdge.Subtotal - exactFreeShippingEdge.Discount == 75m,
            "discounted subtotal at free-shipping edge");
        Check(exactFreeShippingEdge.Shipping == 0m, "free shipping at exact edge");

        var rounding = Original.Process("R|3|0.005");
        Check(rounding.Items[0].UnitPrice == 0.01m, "unit price midpoint rounds away from zero");
        Check(rounding.Items[0].LineTotal == 0.02m && rounding.Subtotal == 0.02m,
            "line total midpoint rounds away from zero");
        var taxMidpoint = Original.Process("M|1|2.00");
        Check(taxMidpoint.Tax == 0.17m, "tax midpoint rounds away from zero");
        var discountMidpoint = Original.Process("D|1|50.10");
        Check(discountMidpoint.Discount == 2.51m, "discount midpoint rounds away from zero");

        CheckThrows<ArgumentException>(() => Original.Process(null!), "null input");
        CheckThrows<ArgumentException>(() => Original.Process(" \n "), "blank input");
        CheckThrows<ArgumentException>(() => Original.Process("A|1"), "wrong field count");
        CheckThrows<ArgumentException>(() => Original.Process("A|1|2|extra"),
            "extra field is rejected");
        CheckThrows<ArgumentException>(() => Original.Process("|1|2"), "empty sku");
        CheckThrows<ArgumentException>(() => Original.Process("A|0|2"), "quantity minimum");
        CheckThrows<ArgumentException>(() => Original.Process("A|101|2"), "quantity maximum");
        CheckThrows<ArgumentException>(() => Original.Process("A|one|2"), "quantity syntax");
        CheckThrows<ArgumentException>(() => Original.Process("A|1|-1"), "negative price");
        CheckThrows<ArgumentException>(() => Original.Process("A|1|10000.01"), "price maximum");
        CheckThrows<ArgumentException>(() => Original.Process("A|1|2\na|1|3"), "duplicate sku");
        CheckThrows<ArgumentNullException>(() => Original.Report(null!), "null report");
        Check(failures == 0, "all checks passed");
        return failures == 0 ? 0 : 1;
    }

    private static void Check(bool value, string name)
    {
        if (!value)
        {
            failures++;
            Console.Error.WriteLine("FAIL: " + name);
        }
    }

    private static void CheckThrows<T>(Action action, string name) where T : Exception
    {
        try { action(); Check(false, name); }
        catch (T) { Check(true, name); }
    }
}
