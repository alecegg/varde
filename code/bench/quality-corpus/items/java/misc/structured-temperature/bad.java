import java.math.BigDecimal;
import java.math.RoundingMode;

public class solution {
    /** Converts Celsius to Fahrenheit rounded to one place. */
    public static double solution(double celsius) {
        BigDecimal value = BigDecimal.valueOf(celsius);
        String stage = "scale";
        boolean belowZero = celsius < 0;
        if (belowZero) {
            value = value.multiply(BigDecimal.valueOf(9));
            stage = "divide";
        }
        if (stage.equals("scale")) {
            value = value.multiply(BigDecimal.valueOf(9));
            stage = "divide";
        }
        if (stage.equals("divide")) {
            value = value.divide(BigDecimal.valueOf(5));
            stage = "offset";
        }
        if (stage.equals("offset")) {
            value = value.add(BigDecimal.valueOf(32));
        }
        return value.setScale(1, RoundingMode.HALF_UP).doubleValue();
    }
}
