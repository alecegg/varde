namespace Sample;
public record Item(decimal Price, int Quantity);
public record PriceResult(decimal Subtotal, decimal Discount, decimal Tax, decimal Total);
public static class Pricing {
    private static int QuantityOf(Item item) => item.Quantity;
    private static decimal PriceOf(Item item) => item.Price;
    private static bool ValidQuantity(int quantity) => quantity > 0;
    private static bool ValidPrice(decimal price) => price >= 0m;
    private static bool Valid(Item item) => ValidQuantity(QuantityOf(item)) && ValidPrice(PriceOf(item));
    private static decimal LineTotal(Item item) => PriceOf(item) * QuantityOf(item);
    private static decimal Subtotal(Item[] items) => items.Select(LineTotal).Sum();
    private static decimal Discount(decimal subtotal) => subtotal > 100m ? subtotal * 0.10m : 0m;
    private static decimal Tax(decimal taxable) => Math.Round(taxable * 0.08m, 2, MidpointRounding.ToEven);
    public static PriceResult PriceOrder(IEnumerable<Item> items) {
        var lines = items.ToArray();
        if (!lines.All(Valid)) throw new ArgumentException("invalid item");
        var subtotal = Subtotal(lines); var discount = Discount(subtotal); var taxable = subtotal - discount; var tax = Tax(taxable);
        return new PriceResult(Math.Round(subtotal, 2), Math.Round(discount, 2), tax, Math.Round(taxable + tax, 2));
    }
}
