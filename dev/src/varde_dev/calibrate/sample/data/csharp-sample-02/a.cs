namespace Sample;
public record Item(decimal Price,int Quantity);
public record PriceResult(decimal Subtotal,decimal Discount,decimal Tax,decimal Total);
public static class Pricing {
 public static PriceResult PriceOrder(IEnumerable<Item> items) {
  var rows=items.ToList();
  if(rows.Exists(x=>x.Price<0m||x.Quantity<1)) throw new ArgumentException("invalid item");
  var subtotal=rows.Sum(x=>x.Price*x.Quantity);
  var discount=subtotal>100m?subtotal*.10m:0m; var net=subtotal-discount;
  var tax=decimal.Round(net*.08m,2,MidpointRounding.ToEven);
  return new(decimal.Round(subtotal,2),decimal.Round(discount,2),tax,decimal.Round(net+tax,2));
 }
}
