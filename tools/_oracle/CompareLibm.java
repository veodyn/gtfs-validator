import com.google.common.geometry.S2LatLng;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import org.mobilitydata.gtfsvalidator.util.S2Earth;

/**
 * Asks whether the distance upstream reports is a canonical value or a platform-specific one.
 *
 * For each coordinate pair it prints three haversines: the one the validator computes through the
 * S2 library (which calls java.lang.Math), the same formula through Math, and the same formula
 * through StrictMath, which is fdlibm and identical on every JVM and platform.
 *
 * If Math and StrictMath disagree, the digit upstream reports depends on the JVM's intrinsics for
 * sin/cos/asin, and there is no single correct value for a port to reach.
 */
public final class CompareLibm {
  private static final double RADIUS = 6371010.0;
  private static final double TO_RADIANS = Math.PI / 180.0;

  public static void main(String[] args) throws IOException {
    BufferedReader reader =
        new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
    StringBuilder out = new StringBuilder();
    String line;
    while ((line = reader.readLine()) != null) {
      if (line.isEmpty()) {
        continue;
      }
      String[] parts = line.trim().split("\\s+");
      double lat1 = Double.parseDouble(parts[0]);
      double lon1 = Double.parseDouble(parts[1]);
      double lat2 = Double.parseDouble(parts[2]);
      double lon2 = Double.parseDouble(parts[3]);
      double library =
          S2Earth.getDistanceMeters(
              S2LatLng.fromDegrees(lat1, lon1), S2LatLng.fromDegrees(lat2, lon2));
      out.append(Double.toString(library))
          .append(' ')
          .append(Double.toString(withMath(lat1, lon1, lat2, lon2)))
          .append(' ')
          .append(Double.toString(withStrictMath(lat1, lon1, lat2, lon2)))
          .append('\n');
    }
    System.out.print(out);
  }

  private static double withMath(double lat1, double lon1, double lat2, double lon2) {
    double a = lat1 * TO_RADIANS;
    double b = lat2 * TO_RADIANS;
    double dlat = Math.sin(0.5 * (b - a));
    double dlng = Math.sin(0.5 * (lon2 * TO_RADIANS - lon1 * TO_RADIANS));
    double x = dlat * dlat + dlng * dlng * Math.cos(a) * Math.cos(b);
    return 2 * Math.asin(Math.sqrt(Math.min(1.0, x))) * RADIUS;
  }

  private static double withStrictMath(double lat1, double lon1, double lat2, double lon2) {
    double a = lat1 * TO_RADIANS;
    double b = lat2 * TO_RADIANS;
    double dlat = StrictMath.sin(0.5 * (b - a));
    double dlng = StrictMath.sin(0.5 * (lon2 * TO_RADIANS - lon1 * TO_RADIANS));
    double x = dlat * dlat + dlng * dlng * StrictMath.cos(a) * StrictMath.cos(b);
    return 2 * StrictMath.asin(StrictMath.sqrt(Math.min(1.0, x))) * RADIUS;
  }
}
