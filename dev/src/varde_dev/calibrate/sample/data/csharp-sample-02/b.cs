namespace Sample;
public record Item(decimal Price,int Quantity);
public record PriceResult(decimal Subtotal,decimal Discount,decimal Tax,decimal Total);
public static class Pricing {
 static decimal Line(Item item)=>item.Price*item.Quantity;
 static decimal DiscountFor(decimal total)=>total>100m?total/10m:0m;
 static decimal TaxFor(decimal net)=>decimal.Round(net*8m/100m,2,MidpointRounding.ToEven);
 public static PriceResult PriceOrder(IEnumerable<Item> items) {
  var rows=items.ToArray();
  if(!rows.All(item=>item.Price>=0m&&item.Quantity>0)) throw new ArgumentException("invalid item");
  var subtotal=rows.Select(Line).Sum(); var discount=DiscountFor(subtotal); var net=subtotal-discount; var tax=TaxFor(net);
  return new(decimal.Round(subtotal,2),decimal.Round(discount,2),tax,decimal.Round(net+tax,2));
 }
}
