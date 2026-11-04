namespace Sample;
public record Item(decimal Price,int Quantity);
public record PriceResult(decimal Subtotal,decimal Discount,decimal Tax,decimal Total);
public static class Pricing {
 public static PriceResult PriceOrder(IEnumerable<Item> items) {
  decimal subtotal=0m;
  foreach(var item in items) {
   if(item.Price<0m||item.Quantity<=0) throw new ArgumentException("invalid item");
   subtotal+=item.Price*item.Quantity;
  }
  var discount=subtotal>100m?subtotal*.10m:0m; var taxable=subtotal-discount;
  var tax=Math.Round(taxable*.08m,2,MidpointRounding.ToEven);
  return new(Math.Round(subtotal,2),Math.Round(discount,2),tax,Math.Round(taxable+tax,2));
 }
}
