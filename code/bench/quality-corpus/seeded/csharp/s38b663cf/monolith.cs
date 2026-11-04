using System.Globalization;
public static class Original
{
 public static decimal SeatPrice(string seatClass)
 {
  string value=seatClass==null?"":seatClass.Trim(); string canonical=value.Equals("Standard",StringComparison.OrdinalIgnoreCase)?"Standard":value.Equals("Premium",StringComparison.OrdinalIgnoreCase)?"Premium":value.Equals("VIP",StringComparison.OrdinalIgnoreCase)?"VIP":"";
  return canonical=="Standard"?50m:canonical=="Premium"?90m:canonical=="VIP"?140m:0m;
 }
 public static decimal CalculateTotal(string seatClass,int quantity)
 {
  string value=seatClass==null?"":seatClass.Trim(); string canonical=value.Equals("Standard",StringComparison.OrdinalIgnoreCase)?"Standard":value.Equals("Premium",StringComparison.OrdinalIgnoreCase)?"Premium":value.Equals("VIP",StringComparison.OrdinalIgnoreCase)?"VIP":"";
  decimal price=canonical=="Standard"?50m:canonical=="Premium"?90m:canonical=="VIP"?140m:0m;
  if(price==0m||quantity<1||quantity>20)return 0m; decimal subtotal=decimal.Round(price*quantity,2,MidpointRounding.AwayFromZero);decimal discount=quantity>=6?decimal.Round(subtotal*.10m,2,MidpointRounding.AwayFromZero):0m;decimal net=subtotal-discount;decimal fee=net<=100?5m:net<=500?10m:20m;decimal tax=decimal.Round((net+fee)*.08m,2,MidpointRounding.AwayFromZero);return decimal.Round(net+fee+tax,2,MidpointRounding.AwayFromZero);
 }
 public static string ProcessLine(string input)
 {
  if(input==null)return "REJECTED: format"; string[] fields=input.Split('|');if(fields.Length!=3)return "REJECTED: format";string name=fields[0].Trim(),value=fields[1].Trim();string canonical=value.Equals("Standard",StringComparison.OrdinalIgnoreCase)?"Standard":value.Equals("Premium",StringComparison.OrdinalIgnoreCase)?"Premium":value.Equals("VIP",StringComparison.OrdinalIgnoreCase)?"VIP":"";if(name.Length==0)return "REJECTED: name";if(canonical.Length==0)return "REJECTED: class";if(!int.TryParse(fields[2].Trim(),NumberStyles.Integer,CultureInfo.InvariantCulture,out int quantity)||quantity<1||quantity>20)return "REJECTED: quantity";decimal price=canonical=="Standard"?50m:canonical=="Premium"?90m:140m;decimal subtotal=decimal.Round(price*quantity,2,MidpointRounding.AwayFromZero);decimal discount=quantity>=6?decimal.Round(subtotal*.10m,2,MidpointRounding.AwayFromZero):0m;decimal net=subtotal-discount;decimal fee=net<=100?5m:net<=500?10m:20m;decimal tax=decimal.Round((net+fee)*.08m,2,MidpointRounding.AwayFromZero);decimal total=decimal.Round(net+fee+tax,2,MidpointRounding.AwayFromZero);return string.Join("\n",new[]{"CONFIRMED: "+name,"Tickets: "+quantity.ToString(CultureInfo.InvariantCulture)+" x "+canonical,"Subtotal: $"+subtotal.ToString("0.00",CultureInfo.InvariantCulture),"Discount: $"+discount.ToString("0.00",CultureInfo.InvariantCulture),"Booking fee: $"+fee.ToString("0.00",CultureInfo.InvariantCulture),"Tax: $"+tax.ToString("0.00",CultureInfo.InvariantCulture),"Total: $"+total.ToString("0.00",CultureInfo.InvariantCulture)});
 }
 public static string ProcessAll(string input)
 {
  if(string.IsNullOrEmpty(input))return string.Empty;var reports=new List<string>();using var reader=new StringReader(input);string? line;while((line=reader.ReadLine())!=null)if(!string.IsNullOrWhiteSpace(line))reports.Add(ProcessLine(line));return string.Join("\n",reports);
 }
}
