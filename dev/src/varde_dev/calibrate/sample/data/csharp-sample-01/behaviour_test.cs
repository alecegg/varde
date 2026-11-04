using Sample;

var expected = new PriceResult(120m, 12m, 8.64m, 116.64m);
if (Pricing.PriceOrder([new Item(60m, 2)]) != expected)
{
    throw new Exception("order price, discount, tax, or total differs");
}

try
{
    Pricing.PriceOrder([new Item(10m, 0)]);
}
catch (ArgumentException)
{
    return;
}

throw new Exception("zero quantity must be rejected");
