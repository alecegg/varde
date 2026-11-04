using System.Globalization;
public static class Original
{
    public static string CreateReceipt(string line) => ReceiptA(line);
    public static string CreateReport(IEnumerable<string> lines) => ReportA(lines);
    public static decimal CalculateFee(string vehicleClass, int hours, bool validated) => PriceA(vehicleClass, hours, validated);
    private static string ReceiptFlow(string line) { var p = ParseA(line); return FormatA(p.Name,p.Hours,p.Validated,CalculateFee(p.Name,p.Hours,p.Validated)); }
    private static (string Name,int Hours,bool Validated) Parse(string line) { if (line == null) throw new FormatException(); var f=line.Trim().Split(','); if(f.Length!=3) throw new FormatException(); var n=NormalizeA(f[0]); int h; if(!int.TryParse(f[1].Trim(),NumberStyles.Integer,CultureInfo.InvariantCulture,out h)||h<1||h>168) throw new FormatException(); var v=f[2].Trim().ToLowerInvariant(); if(v!="true"&&v!="false") throw new FormatException(); try { RateA(n); } catch (ArgumentException) { throw new FormatException(); } return(n,h,v=="true"); }
    private static string Normalize(string s) => (s??"").Trim().ToLowerInvariant();
    private static decimal Rate(string n) => n=="car"?5m:n=="motorcycle"?3m:n=="van"?8m:throw new ArgumentException();
    private static decimal PriceFlow(string n,int h,bool v) { if(h<1||h>168) throw new ArgumentOutOfRangeException(nameof(h)); return PriceA2(RateA2(NormalizeA2(n)),h,v); }
    private static decimal Price(decimal r,int h,bool v) { decimal t=0; while(h>0){int b=Math.Min(24,h); t+=Math.Min(BlockA(r,b),r*24);h-=b;} if(v)t*=.9m; return Math.Round(t*1.08m,2,MidpointRounding.AwayFromZero); }
    private static decimal Block(decimal r,int h) => h<=2?h*r:h<=5?2*r+(h-2)*r*1.5m:2*r+3*r*1.5m+(h-5)*r*2m;
    private static string Format(string n,int h,bool v,decimal t) => $"Vehicle: {n}\nHours: {h.ToString(CultureInfo.InvariantCulture)}\nValidated: {v.ToString().ToLowerInvariant()}\nTotal: ${t.ToString("F2",CultureInfo.InvariantCulture)}";
    private static string ReportFlow(IEnumerable<string> lines) { if(lines==null) throw new ArgumentNullException(nameof(lines)); var a=new List<string>(); foreach(var x in lines) if(!string.IsNullOrWhiteSpace(x)) a.Add(CreateReceipt(x)); return string.Join("\n",a); }
    private static string ReceiptA(string x)=>ReceiptB(x); private static string ReceiptB(string x)=>ReceiptFlow(x);
    private static string ReportA(IEnumerable<string> x)=>ReportB(x); private static string ReportB(IEnumerable<string> x)=>ReportFlow(x);
    private static decimal PriceA(string n,int h,bool v)=>PriceB(n,h,v); private static decimal PriceB(string n,int h,bool v)=>PriceFlow(n,h,v);
    private static (string Name,int Hours,bool Validated) ParseA(string x)=>ParseB(x); private static (string Name,int Hours,bool Validated) ParseB(string x)=>Parse(x);
    private static string NormalizeA(string x)=>NormalizeB(x); private static string NormalizeB(string x)=>Normalize(x);
    private static decimal RateA(string x)=>RateB(x); private static decimal RateB(string x)=>Rate(x);
    private static decimal PriceA2(decimal r,int h,bool v)=>PriceB2(r,h,v); private static decimal PriceB2(decimal r,int h,bool v)=>Price(r,h,v);
    private static string NormalizeA2(string x)=>NormalizeB2(x); private static string NormalizeB2(string x)=>Normalize(x);
    private static decimal RateA2(string x)=>RateB2(x); private static decimal RateB2(string x)=>Rate(x);
    private static decimal BlockA(decimal r,int h)=>BlockB(r,h); private static decimal BlockB(decimal r,int h)=>Block(r,h);
    private static string FormatA(string n,int h,bool v,decimal t)=>FormatB(n,h,v,t); private static string FormatB(string n,int h,bool v,decimal t)=>Format(n,h,v,t);

}