import com.google.common.geometry.S2;
import com.google.common.geometry.S2EdgeUtil;
import com.google.common.geometry.S2LatLng;
import com.google.common.geometry.S2Point;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import org.mobilitydata.gtfsvalidator.util.S2Earth;

/**
 * Dumps the three S2 edge operations `ShapeToStopMatchingValidator` matches stops with.
 *
 * The four stop-to-shape notice codes each carry the matched location as context, so the last
 * digit of `S2EdgeUtil.getClosestPoint` is part of the contract at parity level C. That point is
 * then converted back to degrees by `new S2LatLng(point)`, which uses atan2 rather than asin, and
 * the distance from the stop to it comes from the `S2Point` overload of `getDistanceMeters`.
 *
 * Input on stdin, one operation per line:
 *
 *   closest XLAT XLON ALAT ALON BLAT BLON   -> matched lat, lng and the distance from X, in metres
 *   interp  T ALAT ALON BLAT BLON           -> the interpolated lat and lng
 *   approx  ALAT ALON BLAT BLON             -> `S2.approxEquals` at its default 1e-15
 *
 * Output: `Double.toString` of each field, space separated, one line per input line. That is the
 * same rendering Gson writes into the report, so a mismatch can be read directly.
 */
public final class DumpEdgeGeometry {

  private static S2Point point(String latitude, String longitude) {
    return S2LatLng.fromDegrees(Double.parseDouble(latitude), Double.parseDouble(longitude))
        .toPoint();
  }

  private static String degrees(S2Point p) {
    S2LatLng latLng = new S2LatLng(p);
    return Double.toString(latLng.latDegrees()) + " " + Double.toString(latLng.lngDegrees());
  }

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
      switch (parts[0]) {
        case "closest":
          {
            S2Point x = point(parts[1], parts[2]);
            S2Point a = point(parts[3], parts[4]);
            S2Point b = point(parts[5], parts[6]);
            S2Point closest = S2EdgeUtil.getClosestPoint(x, a, b);
            out.append(degrees(closest))
                .append(' ')
                .append(Double.toString(S2Earth.getDistanceMeters(x, closest)))
                .append('\n');
            break;
          }
        case "interp":
          {
            double t = Double.parseDouble(parts[1]);
            S2Point a = point(parts[2], parts[3]);
            S2Point b = point(parts[4], parts[5]);
            out.append(degrees(S2EdgeUtil.interpolate(t, a, b))).append('\n');
            break;
          }
        case "approx":
          {
            S2Point a = point(parts[1], parts[2]);
            S2Point b = point(parts[3], parts[4]);
            out.append(S2.approxEquals(a, b) ? "true" : "false").append('\n');
            break;
          }
        default:
          throw new IllegalArgumentException("unknown operation: " + parts[0]);
      }
    }
    System.out.print(out);
  }
}
