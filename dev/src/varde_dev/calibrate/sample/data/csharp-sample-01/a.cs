namespace Sample;
public record Item(decimal Price, int Quantity);
public record PriceResult(decimal Subtotal, decimal Discount, decimal Tax, decimal Total);
public static class Pricing {
    public static PriceResult PriceOrder(IEnumerable<Item> items) {
        var lines = items.ToArray();
        if (lines.Any(item => item.Quantity <= 0 || item.Price < 0)) throw new ArgumentException("invalid item");
        var subtotal = lines.Sum(item => item.Price * item.Quantity);
        var discount = subtotal > 100m ? subtotal * 0.10m : 0m;
        var taxable = subtotal - discount;
        var tax = Math.Round(taxable * 0.08m, 2, MidpointRounding.ToEven);
        return new PriceResult(Math.Round(subtotal, 2), Math.Round(discount, 2), tax, Math.Round(taxable + tax, 2));
    }
}
