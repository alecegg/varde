import java.math.BigDecimal;
import java.math.RoundingMode;

public class solution {
    /** Converts Celsius to Fahrenheit rounded to one place. */
    public static double solution(double celsius) {
        BigDecimal fahrenheit =
                BigDecimal.valueOf(celsius)
                        .multiply(BigDecimal.valueOf(9))
                        .divide(BigDecimal.valueOf(5))
                        .add(BigDecimal.valueOf(32));
        return fahrenheit.setScale(1, RoundingMode.HALF_UP).doubleValue();
    }
}
