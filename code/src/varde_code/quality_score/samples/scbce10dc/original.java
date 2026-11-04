import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.HashMap;
import java.util.Map;

public final class Original {
    private static final BigDecimal H = new BigDecimal("100");
    private static final BigDecimal T = new BigDecimal("0.10");
    private static final BigDecimal X = new BigDecimal("0.0825");

    private static final class Item {
        String n;
        BigDecimal p;
        int s;
        String g;
        Item(String n, BigDecimal p, int s, String g) {
            this.n = n;
            this.p = p;
            this.s = s;
            this.g = g;
        }
    }

    private static String[] rows(String value) {
        return value == null ? new String[0] : value.split("\\R", -1);
    }

    private static BigDecimal cents(BigDecimal value) {
        return value.setScale(2, RoundingMode.HALF_UP);
    }

    private static boolean whole(String value) {
        return value.matches("[0-9]+");
    }

    public static boolean validate(String inventory, String order) {
        return calculate(inventory, order) != null;
    }

    public static String process(String inventory, String order) {
        BigDecimal[] a = calculate(inventory, order);
        if (a == null) return "INVALID";
        return "Subtotal=" + money(a[0]) + "; Discount=" + money(a[1]) + "; Tax=" + money(a[2]) + "; Shipping=" + money(a[3]) + "; Total=" + money(a[4]);
    }

    public static String report(String inventory, String order) {
        BigDecimal[] a = calculate(inventory, order);
        if (a == null) return "INVALID";
        return "Subtotal: " + money(a[0]) + "\nDiscount: " + money(a[1]) + "\nTax: " + money(a[2]) + "\nShipping: " + money(a[3]) + "\nTotal: " + money(a[4]);
    }

    private static String money(BigDecimal value) {
        return value.setScale(2, RoundingMode.HALF_UP).toPlainString();
    }

    private static boolean blank(String value) {
        return value.trim().isEmpty();
    }

    private static String clean(String value) {
        return value.trim();
    }

    private static boolean amount(String value) {
        return value.matches("[0-9]+(\\.[0-9]{1,2})?");
    }

    private static BigDecimal rate(BigDecimal value, String percent) {
        return cents(value.multiply(new BigDecimal(percent)));
    }

    private static BigDecimal[] calculate(String inventory, String order) {
        if (inventory == null || order == null) return null;
        Map<String, Item> m = new HashMap<>();
        for (String raw : rows(inventory)) {
            String line = clean(raw);
            if (blank(line)) continue;
            String[] f = line.split("\\|", -1);
            if (f.length != 5) return null;
            for (int i=0;i<f.length;i++) {
                f[i]=clean(f[i]);
            }
            if (f[0].isEmpty() || f[1].isEmpty() || !amount(f[2]) || !whole(f[3]) || f[4].isEmpty()) {
                return null;
            }
            int stock;
            try { stock = Integer.parseInt(f[3]); } catch (RuntimeException ex) { return null; }
            if (stock <= 0 || m.containsKey(f[0])) {
                if (stock <= 0) {
                    return null;
                } else {
                    if (m.containsKey(f[0])) return null;
                }
            }
            m.put(f[0], new Item(f[1], new BigDecimal(f[2]), stock, f[4]));
        }
        if (m.isEmpty()) return null;
        BigDecimal sub = BigDecimal.ZERO;
        for (String raw : rows(order)) {
            String line = clean(raw);
            if (blank(line)) continue;
            String[] f = line.split("\\|", -1);
            if (f.length != 2) return null;
            f[0]=clean(f[0]);
            f[1]=clean(f[1]);
            if (!whole(f[1])) return null;
            int q;
            try { q=Integer.parseInt(f[1]); } catch (RuntimeException ex) { return null; }
            Item it=m.get(f[0]);
            if (it == null || q <= 0 || q > it.s) {
                if (it == null) return null;
                else {
                    if (q <= 0) return null;
                    else {
                        if (q > it.s) return null;
                    }
                }
            }
            BigDecimal lineAmount=cents(it.p.multiply(BigDecimal.valueOf(q)));
            if (it.g.equals("A")) {
                lineAmount=cents(lineAmount.multiply(new BigDecimal("0.95")));
            }
            sub=sub.add(lineAmount);
        }
        if (sub.signum() < 0) return null;
        sub=cents(sub);
        BigDecimal discount=rate(sub, "0.10");
        BigDecimal after=cents(sub.subtract(discount));
        BigDecimal tax=rate(after, "0.0825");
        BigDecimal ship;
        if (after.compareTo(new BigDecimal("100.00")) >= 0) ship=new BigDecimal("0.00");
        else if (after.compareTo(new BigDecimal("50.00")) >= 0) ship=new BigDecimal("5.00");
        else ship=new BigDecimal("8.00");
        BigDecimal total=cents(after.add(tax).add(ship));
        return new BigDecimal[] {sub, discount, tax, ship, total};
    }
}
