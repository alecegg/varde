using System.Globalization;
public static class Original
{
 public static decimal SeatPrice(string seatClass) => A01(seatClass);
 public static decimal CalculateTotal(string seatClass,int quantity) => A02(seatClass,quantity);
 public static string ProcessLine(string input) => A03(input);
 public static string ProcessAll(string input) => A04(input);
 private static decimal A01(string s)=>A05(A06(A07(s)));
 private static decimal A02(string s,int q)=>A08(A09(A01(s),q),q);
 private static string A03(string s)=>A10(A11(s));
 private static string A04(string s)=>A12(A13(s));
 private static decimal A05(string s)=>decimal.Parse(A24(s),CultureInfo.InvariantCulture);
 private static string A06(string s)=>A15(s);
 private static string A07(string s)=>A16(s);
 private static decimal A08(decimal p,int q)=>A17(p,q);
 private static decimal A09(decimal p,int q)=>A18(p,q);
 private static string A10(string s)=>A19(s);
 private static string A11(string s)=>A20(s);
 private static string A12(string s)=>s;
 private static string A13(string s)=>A22(s);
 private static string A14(string s)=>s==null?"":s.Trim();
 private static string A15(string s)=>A23(s);
 private static string A16(string s)=>A23(A14(s));
 private static string A23(string s)=>s.Equals("Standard",StringComparison.OrdinalIgnoreCase)?"Standard":s.Equals("Premium",StringComparison.OrdinalIgnoreCase)?"Premium":s.Equals("VIP",StringComparison.OrdinalIgnoreCase)?"VIP":"";
 private static string A24(string s)=>s=="Standard"?"50":s=="Premium"?"90":s=="VIP"?"140":"0";
 private static decimal A17(decimal p,int q)=>p==0||!A25(q)?0:A27(p,q);
 private static decimal A18(decimal p,int q)=>p;
 private static decimal A26(decimal p,int q)=>A28(p*q);
 private static decimal A27(decimal p,int q){decimal subtotal=A26(p,q),discount=q>=6?A28(subtotal*.10m):0m,net=subtotal-discount,fee=net<=100m?5m:net<=500m?10m:20m,tax=A28((net+fee)*.08m);return A28(net+fee+tax);}
 private static bool A25(int q)=>q>=1&&q<=20;
 private static decimal A28(decimal x)=>decimal.Round(x,2,MidpointRounding.AwayFromZero);
 private static string A19(string s)=>A29(s);
 private static string A20(string s)=>A30(s);
 private static string A21(string s)=>A31(s);
 private static string A22(string s)=>A31(s);
 private static string A29(string s){if(s==null)return A33("format");var f=s.Split('|');if(f.Length!=3)return A33("format");var n=A34(f[0]);var c=A23(A34(f[1]));if(n.Length==0)return A33("name");if(c.Length==0)return A33("class");if(!int.TryParse(A34(f[2]),NumberStyles.Integer,CultureInfo.InvariantCulture,out int q)||!A25(q))return A33("quantity");return A35(n,c,q);}
 private static string A30(string s)=>s;
 private static string A31(string s)=>string.IsNullOrEmpty(s)?"":A36(s);
 private static string A32(string s)=>string.Join("\n",A37(s));
 private static string[] A37(string s){var r=new List<string>();using var rd=new StringReader(s);string? l;while((l=rd.ReadLine())!=null)if(!string.IsNullOrWhiteSpace(l))r.Add(A03(l));return r.ToArray();}
 private static string A36(string s)=>A32(s);
 private static string A33(string s)=>"REJECTED: "+s;
 private static string A34(string s)=>s.Trim();
 private static string A35(string n,string c,int q){decimal sub=A28(decimal.Parse(A24(c),CultureInfo.InvariantCulture)*q),dis=q>=6?A28(sub*.10m):0m,net=sub-dis,fee=net<=100?5:net<=500?10:20,tax=A28((net+fee)*.08m),tot=A28(net+fee+tax);return string.Join("\n",new[]{"CONFIRMED: "+n,"Tickets: "+q.ToString(CultureInfo.InvariantCulture)+" x "+c,A38("Subtotal",sub),A38("Discount",dis),A38("Booking fee",fee),A38("Tax",tax),A38("Total",tot)});}
 private static string A38(string l,decimal x)=>l+": $"+x.ToString("0.00",CultureInfo.InvariantCulture);
}
