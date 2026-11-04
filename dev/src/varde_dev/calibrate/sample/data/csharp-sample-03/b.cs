namespace Sample;
public record Item(decimal Price,int Quantity);
public record PriceResult(decimal Subtotal,decimal Discount,decimal Tax,decimal Total);
public static class Pricing {
 static bool Valid(Item x)=>x.Quantity>0&&x.Price>=decimal.Zero;
 static decimal Extended(Item x)=>x.Price*x.Quantity;
 static decimal Reduction(decimal n)=>n>100m?n*10m/100m:decimal.Zero;
 public static PriceResult PriceOrder(IEnumerable<Item> items) {
  var rows=items.ToArray();
  if(Array.Exists(rows,x=>!Valid(x))) throw new ArgumentException("invalid item");
  var subtotal=rows.Aggregate(decimal.Zero,(sum,x)=>sum+Extended(x)); var discount=Reduction(subtotal);
  var net=subtotal-discount; var tax=decimal.Round(net*0.08m,2,MidpointRounding.ToEven);
  return new(decimal.Round(subtotal,2),decimal.Round(discount,2),tax,decimal.Round(net+tax,2));
 }
}
