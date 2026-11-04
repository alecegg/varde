public final class BehaviourTest {
    private static int failures;

    private static void check(boolean condition, String label) {
        if (!condition) {
            failures++;
            System.out.println("FAIL: " + label);
        }
    }

    public static void main(String[] args) {
        String inv = "p1|Pear|10.00|20|A\np2|Milk|20.00|10|B\np3|Rice|60.00|5|C";
        check(Original.validate(inv, "p1|2\np2|1"), "valid input");
        check(!Original.validate(inv, "p9|1"), "unknown sku");
        check(!Original.validate(inv, "p1|21"), "insufficient stock");
        check(!Original.validate(inv + "\np1|3", "p1|1"), "duplicate inventory sku");
        check(!Original.validate(inv, "p1|0"), "zero quantity");
        check(!Original.validate(inv, "p1|-2"), "negative quantity");
        check(!Original.validate(inv, "p1|1|x"), "extra order field");
        check(!Original.validate("p1|Pear|1.001|2|A", "p1|1"), "excess precision");
        check(!Original.validate("p1|Pear|-1.00|2|A", "p1|1"), "negative price");
        check(!Original.validate("p1|Pear|1.00|0|A", "p1|1"), "zero stock");
        check(Original.validate(inv, "  p1|1  \n\n p2|1 "), "trim and blank rows");
        check(Original.process(inv, "p1|2\np2|1").equals("Subtotal=39.00; Discount=3.90; Tax=2.90; Shipping=8.00; Total=46.00"), "group and order discounts");
        check(Original.process(inv, "p2|5").equals("Subtotal=100.00; Discount=10.00; Tax=7.43; Shipping=5.00; Total=102.43"), "discounted free shipping threshold");
        check(Original.process(inv, "p2|3").equals("Subtotal=60.00; Discount=6.00; Tax=4.46; Shipping=5.00; Total=63.46"), "middle shipping tier");
        check(Original.process(inv, "p2|2").equals("Subtotal=40.00; Discount=4.00; Tax=2.97; Shipping=8.00; Total=46.97"), "lower shipping tier");
        check(Original.process(inv, "p1|1").equals("Subtotal=9.50; Discount=0.95; Tax=0.71; Shipping=8.00; Total=17.26"), "group discount line rounding");
        check(Original.process(inv, "p9|1").equals("INVALID"), "invalid process output");
        check(Original.report(inv, "p2|5").equals("Subtotal: 100.00\nDiscount: 10.00\nTax: 7.43\nShipping: 5.00\nTotal: 102.43"), "report labels and ordering");
        check(Original.report(inv, "p9|1").equals("INVALID"), "invalid report output");
        if (failures > 0) System.exit(1);
        System.out.println("All checks passed");
    }
}
