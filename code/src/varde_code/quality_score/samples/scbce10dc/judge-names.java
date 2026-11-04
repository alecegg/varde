import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.HashMap;
import java.util.Map;

public final class Original {
    private static final BigDecimal ONE_HUNDRED = new BigDecimal("100");
    private static final BigDecimal ORDER_DISCOUNT_RATE = new BigDecimal("0.10");
    private static final BigDecimal TAX_RATE = new BigDecimal("0.0825");

    private static final class InventoryItem {
        String itemName;
        BigDecimal unitPrice;
        int availableStock;
        String itemGroup;

        InventoryItem(String itemName, BigDecimal unitPrice, int availableStock, String itemGroup) {
            this.itemName = itemName;
            this.unitPrice = unitPrice;
            this.availableStock = availableStock;
            this.itemGroup = itemGroup;
        }
    }

    private static String[] splitIntoRows(String multilineValue) {
        return multilineValue == null ? new String[0] : multilineValue.split("\\R", -1);
    }

    private static BigDecimal roundToCents(BigDecimal monetaryValue) {
        return monetaryValue.setScale(2, RoundingMode.HALF_UP);
    }

    private static boolean containsOnlyWholeNumberDigits(String value) {
        return value.matches("[0-9]+");
    }

    public static boolean validate(String inventory, String order) {
        return calculateOrderTotals(inventory, order) != null;
    }

    public static String process(String inventory, String order) {
        BigDecimal[] calculatedAmounts = calculateOrderTotals(inventory, order);
        if (calculatedAmounts == null) return "INVALID";
        return "Subtotal=" + formatMoney(calculatedAmounts[0]) + "; Discount=" + formatMoney(calculatedAmounts[1]) + "; Tax=" + formatMoney(calculatedAmounts[2]) + "; Shipping=" + formatMoney(calculatedAmounts[3]) + "; Total=" + formatMoney(calculatedAmounts[4]);
    }

    public static String report(String inventory, String order) {
        BigDecimal[] calculatedAmounts = calculateOrderTotals(inventory, order);
        if (calculatedAmounts == null) return "INVALID";
        return "Subtotal: " + formatMoney(calculatedAmounts[0]) + "\nDiscount: " + formatMoney(calculatedAmounts[1]) + "\nTax: " + formatMoney(calculatedAmounts[2]) + "\nShipping: " + formatMoney(calculatedAmounts[3]) + "\nTotal: " + formatMoney(calculatedAmounts[4]);
    }

    private static String formatMoney(BigDecimal monetaryValue) {
        return monetaryValue.setScale(2, RoundingMode.HALF_UP).toPlainString();
    }

    private static boolean isBlank(String value) {
        return value.trim().isEmpty();
    }

    private static String trimWhitespace(String value) {
        return value.trim();
    }

    private static boolean isValidAmount(String value) {
        return value.matches("[0-9]+(\\.[0-9]{1,2})?");
    }

    private static BigDecimal calculatePercentageAmount(BigDecimal monetaryValue, String percentageRate) {
        return roundToCents(monetaryValue.multiply(new BigDecimal(percentageRate)));
    }

    private static BigDecimal[] calculateOrderTotals(String inventory, String order) {
        if (inventory == null || order == null) return null;
        Map<String, InventoryItem> inventoryItemsBySku = new HashMap<>();
        for (String untrimmedInventoryRow : splitIntoRows(inventory)) {
            String inventoryRow = trimWhitespace(untrimmedInventoryRow);
            if (isBlank(inventoryRow)) continue;
            String[] inventoryFields = inventoryRow.split("\\|", -1);
            if (inventoryFields.length != 5) return null;
            for (int fieldIndex = 0; fieldIndex < inventoryFields.length; fieldIndex++) {
                inventoryFields[fieldIndex] = trimWhitespace(inventoryFields[fieldIndex]);
            }
            if (inventoryFields[0].isEmpty() || inventoryFields[1].isEmpty() || !isValidAmount(inventoryFields[2]) || !containsOnlyWholeNumberDigits(inventoryFields[3]) || inventoryFields[4].isEmpty()) {
                return null;
            }
            int availableStock;
            try { availableStock = Integer.parseInt(inventoryFields[3]); } catch (RuntimeException exception) { return null; }
            if (availableStock <= 0 || inventoryItemsBySku.containsKey(inventoryFields[0])) {
                if (availableStock <= 0) {
                    return null;
                } else {
                    if (inventoryItemsBySku.containsKey(inventoryFields[0])) return null;
                }
            }
            inventoryItemsBySku.put(inventoryFields[0], new InventoryItem(inventoryFields[1], new BigDecimal(inventoryFields[2]), availableStock, inventoryFields[4]));
        }
        if (inventoryItemsBySku.isEmpty()) return null;
        BigDecimal subtotalBeforeOrderDiscount = BigDecimal.ZERO;
        for (String untrimmedOrderRow : splitIntoRows(order)) {
            String orderRow = trimWhitespace(untrimmedOrderRow);
            if (isBlank(orderRow)) continue;
            String[] orderFields = orderRow.split("\\|", -1);
            if (orderFields.length != 2) return null;
            orderFields[0] = trimWhitespace(orderFields[0]);
            orderFields[1] = trimWhitespace(orderFields[1]);
            if (!containsOnlyWholeNumberDigits(orderFields[1])) return null;
            int requestedQuantity;
            try { requestedQuantity = Integer.parseInt(orderFields[1]); } catch (RuntimeException exception) { return null; }
            InventoryItem inventoryItem = inventoryItemsBySku.get(orderFields[0]);
            if (inventoryItem == null || requestedQuantity <= 0 || requestedQuantity > inventoryItem.availableStock) {
                if (inventoryItem == null) return null;
                else {
                    if (requestedQuantity <= 0) return null;
                    else {
                        if (requestedQuantity > inventoryItem.availableStock) return null;
                    }
                }
            }
            BigDecimal discountedLineAmount = roundToCents(inventoryItem.unitPrice.multiply(BigDecimal.valueOf(requestedQuantity)));
            if (inventoryItem.itemGroup.equals("A")) {
                discountedLineAmount = roundToCents(discountedLineAmount.multiply(new BigDecimal("0.95")));
            }
            subtotalBeforeOrderDiscount = subtotalBeforeOrderDiscount.add(discountedLineAmount);
        }
        if (subtotalBeforeOrderDiscount.signum() < 0) return null;
        subtotalBeforeOrderDiscount = roundToCents(subtotalBeforeOrderDiscount);
        BigDecimal orderDiscountAmount = calculatePercentageAmount(subtotalBeforeOrderDiscount, "0.10");
        BigDecimal amountAfterOrderDiscount = roundToCents(subtotalBeforeOrderDiscount.subtract(orderDiscountAmount));
        BigDecimal taxAmount = calculatePercentageAmount(amountAfterOrderDiscount, "0.0825");
        BigDecimal shippingAmount;
        if (amountAfterOrderDiscount.compareTo(new BigDecimal("100.00")) >= 0) shippingAmount = new BigDecimal("0.00");
        else if (amountAfterOrderDiscount.compareTo(new BigDecimal("50.00")) >= 0) shippingAmount = new BigDecimal("5.00");
        else shippingAmount = new BigDecimal("8.00");
        BigDecimal totalAmount = roundToCents(amountAfterOrderDiscount.add(taxAmount).add(shippingAmount));
        return new BigDecimal[] {subtotalBeforeOrderDiscount, orderDiscountAmount, taxAmount, shippingAmount, totalAmount};
    }
}
