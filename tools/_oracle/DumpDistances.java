import com.google.common.geometry.S2LatLng;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import org.mobilitydata.gtfsvalidator.util.S2Earth;

/**
 * Dumps S2Earth.getDistanceMeters for coordinate pairs, exactly as the validator computes it.
 *
 * Input on stdin: one "lat1 lon1 lat2 lon2" per line, in degrees.
 * Output: one line per input, `Double.toString` of the distance in metres, which is also how
 * Gson renders it into a notice.
 *
 * Run against the pinned jar so the S2 library is the one upstream links, not a rebuild:
 *   javac -cp gtfs-validator.jar -d out DumpDistances.java
 *   java -cp gtfs-validator.jar:out DumpDistances < pairs.txt
 *
 * The point is the last digit. The haversine is a handful of libm calls, and Java's Math.sin is
 * only specified to within 1 ulp of the true result, so whether Python's libm agrees is a
 * measurement rather than a deduction. A 1-ulp difference changes the shortest round-tripping
 * decimal, which is what lands in the report.
 */
public final class DumpDistances {
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
      S2LatLng first = S2LatLng.fromDegrees(Double.parseDouble(parts[0]), Double.parseDouble(parts[1]));
      S2LatLng second =
          S2LatLng.fromDegrees(Double.parseDouble(parts[2]), Double.parseDouble(parts[3]));
      out.append(Double.toString(S2Earth.getDistanceMeters(first, second))).append('\n');
    }
    System.out.print(out);
  }
}
