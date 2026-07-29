import com.google.common.geometry.S2LatLng;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import org.mobilitydata.gtfsvalidator.util.S2Earth;

/**
 * Dumps `S2Earth.getDistanceMeters(S2Point, S2Point)`, the other overload.
 *
 * `S2Earth` has two `getDistanceMeters` methods and they are different formulas. The `S2LatLng`
 * one takes the haversine. This one converts each coordinate to a unit vector with
 * `S2LatLng.toPoint()` and takes `atan2(|a x b|, a . b)`. `TransferDistanceValidator` calls
 * `.toPoint()` and so reaches this one, which is why porting the haversine alone would have put
 * a wrong number in every transfer-distance notice.
 *
 * Input on stdin: one "lat1 lon1 lat2 lon2" per line, in degrees. Output: `Double.toString` of
 * the distance in metres, one per line, which is also how Gson renders it.
 */
public final class DumpPointDistances {
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
      S2LatLng first =
          S2LatLng.fromDegrees(Double.parseDouble(parts[0]), Double.parseDouble(parts[1]));
      S2LatLng second =
          S2LatLng.fromDegrees(Double.parseDouble(parts[2]), Double.parseDouble(parts[3]));
      out.append(Double.toString(S2Earth.getDistanceMeters(first.toPoint(), second.toPoint())))
          .append('\n');
    }
    System.out.print(out);
  }
}
