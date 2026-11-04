import java.math.BigInteger;
import java.util.*;

public class behaviour_test {
    static solution.RawItem i(String s, int q, String p) { return new solution.RawItem(s, q, p); }
    static solution.Request r(List<solution.RawItem> xs, String t, String c, String g) { return new solution.Request(xs,t,c,g); }
    static solution.Request r(solution.RawItem... xs) { return r(List.of(xs),"basic","","EU"); }

    public static void main(String[] args) {
        check(r(List.of(i(" ab-12 ",2,"10.00"),i("CD-34",1,"5.50")),"Silver","","us"), new solution.Quote(List.of(new solution.Line("AB-12",2,1000,2000),new solution.Line("CD-34",1,550,550)),2550,128,0,500,170,3092,List.of("tier","tax")));
        check(r(List.of(i("X1X",10,"20.00")),"gold","pct10","EU"), new solution.Quote(List.of(new solution.Line("X1X",10,2000,20000)),20000,2000,1800,0,3240,19440,List.of("tier","coupon","free-shipping","tax")));
        check(r(List.of(i("aaa",3,"1.00"),i("AAA",4,"1")),"basic","FIXED5","ASIA"), new solution.Quote(List.of(new solution.Line("AAA",7,100,700)),700,0,500,1200,20,1420,List.of("coupon","tax")));
        check(r(List.of(i("ZZZ",1,"0.01")),"silver"," freeship ","EU"), new solution.Quote(List.of(new solution.Line("ZZZ",1,1,1)),1,0,0,0,0,1,List.of("free-shipping")));
        check(r(List.of(i("RND",1,"2.50")),"basic","","US"), new solution.Quote(List.of(new solution.Line("RND",1,250,250)),250,0,0,500,18,768,List.of("tax")));
        check(r(List.of(i("CAP",1,"3.00")),"basic","FIXED500","US"), new solution.Quote(List.of(new solution.Line("CAP",1,300,300)),300,0,300,500,0,500,List.of("coupon")));
        String[] bad = {"0","0.00","1.234","abc","","1234567","1000000",".50",".5","1.","+1","-1"," 1","1 ","1 0","1,5","1a","1e3"};
        for (String p : bad) check(r(i("ABC",1,p)), new solution.QuoteError("BAD_PRICE",0));
        String[] coupons = {"PCT0","PCT51","PCT07","FIXED0","FIXED501","FIXED05","PCT","PCTX","FIXED1A","PCT-5","PCT5.0","FIXED 5","OTHER"};
        for (String c : coupons) check(r(List.of(i("ABC",1,"1")),"basic",c,"EU"),new solution.QuoteError("BAD_COUPON",null));
        check(r(), new solution.QuoteError("EMPTY_ORDER",null));
        check(r(i("a",1,"1")),new solution.QuoteError("BAD_SKU",0));
        for(String sku:List.of("AB","ABCDEFGHIJKLM","AB_","AB ","ÄBC")) check(r(i(sku,1,"1")),new solution.QuoteError("BAD_SKU",0));
        check(r(i("ABC",0,"1")),new solution.QuoteError("BAD_QTY",0));
        for(int qty:List.of(-1,1001)) check(r(i("ABC",qty,"1")),new solution.QuoteError("BAD_QTY",0));
        check(r(i("ABC",1,"1"),i("abc",1,"2")),new solution.QuoteError("PRICE_CONFLICT",1));
        check(r(i("ABC",600,"1"),i("abc",500,"1.0")),new solution.QuoteError("BAD_QTY",1));
        check(r(i("ABC",500,"1"),i("abc",501,"1.00")),new solution.QuoteError("BAD_QTY",1));
        check(r(i("ABC",1000,"1"),i("abc",1,"1.00")),new solution.QuoteError("BAD_QTY",1));
        check(r(i("ABC",600,"1"),i("abc",500,"2")),new solution.QuoteError("PRICE_CONFLICT",1));
        check(r(List.of(i("ABC",1,"1")),"bad","PCT0","MARS"),new solution.QuoteError("BAD_TIER",null));
        check(r(List.of(i("ABC",1,"1")),"basic","PCT0","MARS"),new solution.QuoteError("BAD_COUPON",null));
        check(r(List.of(i("ABC",1,"1")),"basic","","MARS"),new solution.QuoteError("BAD_REGION",null));
        check(r(List.of(i("ABC",1,"1")),"bad","","EU"),new solution.QuoteError("BAD_TIER",null));
        List<solution.RawItem> tooMany=new ArrayList<>(); for(int n=0;n<51;n++)tooMany.add(i("ABC",1,"1")); check(r(tooMany,"bad","","EU"),new solution.QuoteError("TOO_MANY_ITEMS",null));
        check(r(List.of(i("ABC",1,"1"),i("BAD",0,"bad"),i("BAD",1,"1")),"basic","","EU"),new solution.QuoteError("BAD_QTY",1));
        check(r(List.of(i("ABC",1,"1"),i("abc",1,"2"),i("bad",0,"1")),"basic","","EU"),new solution.QuoteError("BAD_QTY",2));
        check(r(i("ABC",1,"1"),i("abc",0,"2")),new solution.QuoteError("BAD_QTY",1));
        check(r(List.of(i("ABC",1,"1")),"bad","PCT0","MARS"),new solution.QuoteError("BAD_TIER",null));
        check(r(List.of(i("ABC",1,"1"),i("abc",1,"2")),"bad","PCT0","MARS"),new solution.QuoteError("PRICE_CONFLICT",1));
        check(r(List.of(i("ABC",1,"1")),"basic","","EU"),oracle(r(List.of(i("ABC",1,"1")),"basic","","EU")));
        for (int[] pair : List.of(new int[]{500,500}, new int[]{999,1})) check(r(i("ABC",pair[0],"1"),i("abc",pair[1],"1.00")),oracle(r(i("ABC",pair[0],"1"),i("abc",pair[1],"1.00"))));
        for(String region:List.of("EU","US","ASIA")){long threshold=region.equals("EU")?10000:region.equals("US")?7500:15000;for(long amount:new long[]{threshold-1,threshold}){String price=(amount/100)+"."+String.format("%02d",amount%100);solution.Request q=r(List.of(i("EDGE",1,price)),"basic","",region);check(q,oracle(q));}}
        for (String region : List.of("EU","US","ASIA")) { long threshold=region.equals("EU")?10000:region.equals("US")?7500:15000; long amount=threshold*112/100; String price=(amount/100)+"."+String.format("%02d",amount%100); solution.Request q=r(List.of(i("EDGE",1,price)),"gold","PCT10",region); check(q,oracle(q)); }
        solution.Request sorted=r(List.of(i("a1x",1,"1"),i("A-1",1,"1"),i("A01",1,"1"),i("A1X",1,"1")),"basic","","EU"); check(sorted,oracle(sorted));
        List<solution.RawItem> fifty=new ArrayList<>(); for(int n=0;n<50;n++)fifty.add(i(String.format("S%02d",n),n+1,"1.25")); solution.Request many=r(fifty,"gold","PCT7","ASIA");check(many,oracle(many));
        maximumCases();
        randomCases();
    }

    static void check(solution.Request input, Object expected) {
        Object got = solution.solution(input);
        if (!expected.equals(got)) throw new AssertionError(input + " expected=" + expected + " got=" + got);
    }
    static long rh(long n, long d) { return new BigInteger(Long.toString(n)).multiply(BigInteger.TWO).add(BigInteger.valueOf(d)).divide(BigInteger.valueOf(2*d)).longValueExact(); }
    static Object oracle(solution.Request q) {
        if(q.items().isEmpty()) return new solution.QuoteError("EMPTY_ORDER",null);
        if(q.items().size()>50) return new solution.QuoteError("TOO_MANY_ITEMS",null);
        TreeMap<String,long[]> m=new TreeMap<>(); int ix=0;
        for(var raw:q.items()) { String sku=raw.sku().strip().toUpperCase(Locale.ROOT), p=raw.price();
            if(!sku.matches("[A-Z0-9-]{3,12}")) return new solution.QuoteError("BAD_SKU",ix);
            if(raw.qty()<1||raw.qty()>1000) return new solution.QuoteError("BAD_QTY",ix);
            if(!p.matches("[0-9]{1,6}(\\.[0-9]{1,2})?")) return new solution.QuoteError("BAD_PRICE",ix);
            String[] a=p.split("\\.",-1); long cents=Long.parseLong(a[0])*100+(a.length==1?0:Long.parseLong((a[1]+"00").substring(0,2)));
            if(cents==0) return new solution.QuoteError("BAD_PRICE",ix);
            ix++; }
        ix=0;
        for(var raw:q.items()) { String sku=raw.sku().strip().toUpperCase(Locale.ROOT), p=raw.price();
            String[] a=p.split("\\.",-1); long cents=Long.parseLong(a[0])*100+(a.length==1?0:Long.parseLong((a[1]+"00").substring(0,2)));
            long[] old=m.get(sku); if(old==null)m.put(sku,new long[]{raw.qty(),cents}); else {if(old[1]!=cents)return new solution.QuoteError("PRICE_CONFLICT",ix); old[0]+=raw.qty();if(old[0]>1000)return new solution.QuoteError("BAD_QTY",ix);} ix++; }
        String tier=q.tier().strip().toLowerCase(Locale.ROOT), coupon=q.coupon().strip().toUpperCase(Locale.ROOT), region=q.region().strip().toUpperCase(Locale.ROOT);
        if(!List.of("basic","silver","gold").contains(tier))return new solution.QuoteError("BAD_TIER",null);
        if(!coupon.isEmpty()&&!coupon.matches("(?:PCT(?:[1-9]|[1-4][0-9]|50)|FIXED(?:[1-9]|[1-9][0-9]|[1-4][0-9]{2}|500)|FREESHIP)"))return new solution.QuoteError("BAD_COUPON",null);
        if(!List.of("EU","US","ASIA").contains(region))return new solution.QuoteError("BAD_REGION",null);
        List<solution.Line> lines=new ArrayList<>(); long sub=0; for(var e:m.entrySet()){long[]v=e.getValue();long line=v[0]*v[1]; sub+=line;lines.add(new solution.Line(e.getKey(),(int)v[0],v[1],line));}
        long td=rh(sub*(tier.equals("gold")?1000:tier.equals("silver")?500:0),10000), net1=sub-td;
        long cd=coupon.startsWith("PCT")?rh(net1*Long.parseLong(coupon.substring(3)),100):coupon.startsWith("FIXED")?Math.min(net1,Long.parseLong(coupon.substring(5))*100):0;
        long net=net1-cd, threshold=region.equals("EU")?10000:region.equals("US")?7500:15000, ship=coupon.equals("FREESHIP")||net>=threshold?0:region.equals("EU")?800:region.equals("US")?500:1200;
        long tax=rh(net*(region.equals("EU")?2000:region.equals("US")?700:1000),10000); List<String> applied=new ArrayList<>(); if(td>0)applied.add("tier");if(cd>0)applied.add("coupon");if(ship==0)applied.add("free-shipping");if(tax>0)applied.add("tax");
        return new solution.Quote(lines,sub,td,cd,ship,tax,net+ship+tax,applied);
    }
    static final String[] VALID_SKUS = {"A-1", "A1B", "X9-Y", "SKU-7", "ABC", "Q-42", "A01"};
    static final String[] BAD_SKUS = {"AB", "AB_", "AB ", "ABCDEFGHIJKLM", "\u00c4BC", ""};
    static final int[] VALID_QTYS = {1, 2, 3, 7, 50, 499, 500, 501, 999, 1000};
    static final int[] BAD_QTYS = {-1, 0, 1001, 5000};
    static final String[] VALID_PRICES = {"0.01", "0.05", "0.10", "0.5", "1", "1.25", "12.34",
            "75.00", "100.00", "150.00", "999999.99"};
    static final String[] BAD_PRICES = {"0", "0.00", "1.234", "abc", "", ".5", "1.", "1234567",
            "1 0"};
    static final String[] VALID_TIERS = {"basic", "silver", "gold", "Silver", "GOLD", " Basic "};
    static final String[] BAD_TIERS = {"platinum", "", "golds"};
    static final String[] VALID_REGIONS = {"EU", "US", "ASIA", "eu", "Us", " asia "};
    static final String[] BAD_REGIONS = {"MARS", "", "europe"};
    static final String[] VALID_COUPONS = {"", "PCT1", "PCT10", "PCT50", "FIXED1", "FIXED99",
            "FIXED500", "FREESHIP", "pct10", " freeship ", "FIXED5"};
    static final String[] BAD_COUPONS = {"PCT0", "PCT51", "FIXED0", "FIXED501", "OTHER"};

    static String mixed(SplittableRandom g, String[] good, String[] bad) {
        return g.nextInt(1000) < 985 ? good[g.nextInt(good.length)] : bad[g.nextInt(bad.length)];
    }

    static int mixedQty(SplittableRandom g) {
        return g.nextInt(1000) < 985 ? VALID_QTYS[g.nextInt(VALID_QTYS.length)]
                : BAD_QTYS[g.nextInt(BAD_QTYS.length)];
    }

    static List<solution.RawItem> mixedItems(SplittableRandom g) {
        List<solution.RawItem> xs = new ArrayList<>();
        int size = g.nextInt(1, 5);
        String sharedPrice = mixed(g, VALID_PRICES, BAD_PRICES);
        boolean samePrice = g.nextInt(100) < 50;
        for (int j = 0; j < size; j++) {
            String price = samePrice ? sharedPrice : mixed(g, VALID_PRICES, BAD_PRICES);
            xs.add(i(mixed(g, VALID_SKUS, BAD_SKUS), mixedQty(g), price));
        }
        if (g.nextInt(100) < 25) {
            int[][] pairs = {{500, 500}, {500, 501}, {1000, 1}, {999, 1}, {400, 600}, {250, 750}};
            int[] pair = pairs[g.nextInt(pairs.length)];
            String sku = VALID_SKUS[g.nextInt(VALID_SKUS.length)];
            String price = VALID_PRICES[g.nextInt(VALID_PRICES.length)];
            String other = g.nextInt(100) < 30 ? VALID_PRICES[g.nextInt(VALID_PRICES.length)] : price;
            xs.add(i(sku, pair[0], price));
            xs.add(i(sku.toLowerCase(Locale.ROOT), pair[1], other));
        }
        return xs;
    }

    static void randomCases() {
        SplittableRandom g = new SplittableRandom(20261017);
        Map<String, Integer> promos = new TreeMap<>(), errors = new TreeMap<>();
        Set<String> tiers = new TreeSet<>(), regions = new TreeSet<>();
        int valid = 0;
        for (int n = 0; n < 4000; n++) {
            String tier = mixed(g, VALID_TIERS, BAD_TIERS);
            String coupon = mixed(g, VALID_COUPONS, BAD_COUPONS);
            String region = mixed(g, VALID_REGIONS, BAD_REGIONS);
            solution.Request q = r(mixedItems(g), tier, coupon, region);
            Object want = oracle(q);
            if (want instanceof solution.Quote) {
                valid++;
                tiers.add(tier.strip().toLowerCase(Locale.ROOT));
                regions.add(region.strip().toUpperCase(Locale.ROOT));
                String code = coupon.strip().toUpperCase(Locale.ROOT);
                promos.merge(code.startsWith("PCT") ? "percent"
                        : code.startsWith("FIXED") ? "fixed"
                        : code.equals("FREESHIP") ? "freeship" : "none", 1, Integer::sum);
            } else {
                errors.merge(((solution.QuoteError) want).error(), 1, Integer::sum);
            }
            check(q, want);
        }
        if (valid < 2000) throw new AssertionError("random loop valid=" + valid + " under half");
        if (!tiers.containsAll(List.of("basic", "silver", "gold")))
            throw new AssertionError("random tiers too narrow: " + tiers);
        if (!regions.containsAll(List.of("EU", "US", "ASIA")))
            throw new AssertionError("random regions too narrow: " + regions);
        if (!promos.keySet().containsAll(List.of("none", "percent", "fixed", "freeship")))
            throw new AssertionError("random coupons too narrow: " + promos);
        for (String code : List.of("BAD_SKU", "BAD_QTY", "BAD_PRICE", "PRICE_CONFLICT", "BAD_TIER",
                "BAD_COUPON", "BAD_REGION")) {
            if (!errors.containsKey(code))
                throw new AssertionError("random loop never produced " + code + ": " + errors);
        }
        System.out.println("random requests=4000 valid=" + valid + " invalid=" + (4000 - valid)
                + " tiers=" + tiers + " regions=" + regions + " promos=" + promos
                + " errors=" + errors);
    }

    static void maximumCases() { for(String tier:List.of("basic","silver","gold")) for(String region:List.of("EU","US","ASIA")){List<solution.RawItem> xs=new ArrayList<>();for(int n=0;n<50;n++)xs.add(i(String.format("S%02d",49-n),1000,"999999.99"));solution.Request q=r(xs,tier,"",""+region);check(q,oracle(q));} }
}
