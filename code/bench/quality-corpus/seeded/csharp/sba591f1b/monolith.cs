using System.Globalization;
public static class Original
{
 public static decimal CalculateFee(string vehicleClass,int hours,bool validated) {
 if(hours<1||hours>168) throw new ArgumentOutOfRangeException(nameof(hours)); var n=(vehicleClass??"").Trim().ToLowerInvariant(); decimal r=n=="car"?5m:n=="motorcycle"?3m:n=="van"?8m:throw new ArgumentException(); decimal total=0m; var left=hours; while(left>0){var count=Math.Min(24,left); decimal amount=count<=2?count*r:count<=5?2m*r+(count-2)*r*1.5m:2m*r+3m*r*1.5m+(count-5)*r*2m; total+=Math.Min(amount,r*24m);left-=count;} if(validated)total*=.9m; return Math.Round(total*1.08m,2,MidpointRounding.AwayFromZero);
 }
 public static string CreateReceipt(string line) {
 if(line==null)throw new FormatException(); var f=line.Trim().Split(','); if(f.Length!=3)throw new FormatException();var n=(f[0]??"").Trim().ToLowerInvariant(); int h;if(!int.TryParse(f[1].Trim(),NumberStyles.Integer,CultureInfo.InvariantCulture,out h)||h<1||h>168)throw new FormatException();var x=f[2].Trim().ToLowerInvariant();if(x!="true"&&x!="false")throw new FormatException();if(n!="car"&&n!="van"&&n!="motorcycle")throw new FormatException();var rate=n=="car"?5m:n=="motorcycle"?3m:8m;decimal total=0;var left=h;while(left>0){var count=Math.Min(24,left);decimal amount=count<=2?count*rate:count<=5?2m*rate+(count-2)*rate*1.5m:2m*rate+3m*rate*1.5m+(count-5)*rate*2m;total+=Math.Min(amount,rate*24m);left-=count;}if(x=="true")total*=.9m;total=Math.Round(total*1.08m,2,MidpointRounding.AwayFromZero);return $"Vehicle: {n}\nHours: {h.ToString(CultureInfo.InvariantCulture)}\nValidated: {x}\nTotal: ${total.ToString("F2",CultureInfo.InvariantCulture)}";
 }
 public static string CreateReport(IEnumerable<string> lines) {if(lines==null)throw new ArgumentNullException(nameof(lines));var result=new List<string>();foreach(var line in lines){if(string.IsNullOrWhiteSpace(line))continue;result.Add(CreateReceipt(line));}return string.Join("\n",result);}
}