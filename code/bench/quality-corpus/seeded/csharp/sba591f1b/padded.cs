using System.Globalization;
public static class Original
{
    public static string CreateReceipt(string line) => ReceiptWrap1(line);
    public static string CreateReport(IEnumerable<string> lines) => ReportWrap1(lines);
    public static decimal CalculateFee(string vehicleClass, int hours, bool validated) => PriceWrap1(vehicleClass, hours, validated);
    private static string ReceiptFlow(string line) { var p = Parse(line); return Format(p.Name, p.Hours, p.Validated, CalculateFee(p.Name,p.Hours,p.Validated)); }
    private static (string Name,int Hours,bool Validated) Parse(string line) { if (line == null) throw new FormatException(); var f=line.Trim().Split(','); if(f.Length!=3) throw new FormatException(); var n=Normalize(f[0]); int h; if(!int.TryParse(f[1].Trim(),NumberStyles.Integer,CultureInfo.InvariantCulture,out h)||h<1||h>168) throw new FormatException(); var v=f[2].Trim().ToLowerInvariant(); if(v!="true"&&v!="false") throw new FormatException(); try { Rate(n); } catch (ArgumentException) { throw new FormatException(); } return(n,h,v=="true"); }
    private static string Normalize(string s) => (s??"").Trim().ToLowerInvariant();
    private static decimal Rate(string n) => n=="car"?5m:n=="motorcycle"?3m:n=="van"?8m:throw new ArgumentException();
    private static decimal PriceFlow(string n,int h,bool v) { if(h<1||h>168) throw new ArgumentOutOfRangeException(nameof(h)); return Price(RateWrap(NormalizeWrap(n)),h,v); }
    private static decimal Price(decimal r,int h,bool v) { decimal t=0; while(h>0){int b=Math.Min(24,h); t+=Math.Min(BlockWrap(r,b),r*24);h-=b;} if(v)t*=.9m; return Math.Round(t*1.08m,2,MidpointRounding.AwayFromZero); }
    private static decimal Block(decimal r,int h) => h<=2?h*r:h<=5?2*r+(h-2)*r*1.5m:2*r+3*r*1.5m+(h-5)*r*2m;
    private static string Format(string n,int h,bool v,decimal t) => $"Vehicle: {n}\nHours: {h.ToString(CultureInfo.InvariantCulture)}\nValidated: {v.ToString().ToLowerInvariant()}\nTotal: ${t.ToString("F2",CultureInfo.InvariantCulture)}";
    private static string ReportFlow(IEnumerable<string> lines) { if(lines==null) throw new ArgumentNullException(nameof(lines)); var a=new List<string>(); foreach(var x in lines) if(!string.IsNullOrWhiteSpace(x)) a.Add(CreateReceipt(x)); return string.Join("\n",a); }
    private static string ReceiptWrap1(string x)=>ReceiptWrap2(x); private static string ReceiptWrap2(string x)=>ReceiptFlow(x);
    private static string ReportWrap1(IEnumerable<string> x)=>ReportWrap2(x); private static string ReportWrap2(IEnumerable<string> x)=>ReportFlow(x);
    private static decimal PriceWrap1(string n,int h,bool v)=>PriceWrap2(n,h,v); private static decimal PriceWrap2(string n,int h,bool v)=>PriceFlow(n,h,v);
    private static decimal RateWrap(string n)=>Rate(n); private static string NormalizeWrap(string n)=>Normalize(n);
    private static decimal BlockWrap(decimal r,int h)=>Block(r,h);

}