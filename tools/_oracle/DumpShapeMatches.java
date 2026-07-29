import com.google.common.geometry.S2LatLng;
import com.google.common.geometry.S2Point;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import org.mobilitydata.gtfsvalidator.util.S2Earth;
import org.mobilitydata.gtfsvalidator.util.shape.ShapePoints;
import org.mobilitydata.gtfsvalidator.util.shape.StopToShapeMatch;

/**
 * Dumps `ShapePoints.matchesFromLocation`, the local-minimum search behind two of the four
 * stop-to-shape codes.
 *
 * The *count* it returns is what `stop_has_too_many_matches_for_shape` reports and compares against
 * its threshold of 20, and it is also the candidate set the assignment search runs over. So the
 * count is a control-flow value, not a reported number: if this port counted differently the
 * difference would show up as a notice appearing or vanishing rather than as a digit. Divergence 12
 * makes that a real risk here, because whether a segment's closest point is nearer than the
 * previous segment's end vertex can turn on the eleventh digit.
 *
 * `ShapePoints` is built directly from its public constructor rather than through
 * `fromGtfsShape`, which would need a loaded feed. The geo distances are accumulated with the same
 * haversine overload `fromGtfsShape` uses, so a match's `geoDistance` is comparable too.
 *
 * Input on stdin, one query per line:
 *
 *   MAXDIST STOPLAT STOPLON LAT1 LON1 LAT2 LON2 ...
 *
 * Output: the match count, then each match as `index:geoDistanceToShape`, space separated.
 */
public final class DumpShapeMatches {

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
      double maxDistance = Double.parseDouble(parts[0]);
      S2Point stop =
          S2LatLng.fromDegrees(Double.parseDouble(parts[1]), Double.parseDouble(parts[2])).toPoint();

      List<ShapePoints.ShapePoint> points = new ArrayList<>();
      double geoDistance = 0.0;
      S2LatLng previous = null;
      for (int index = 3; index + 1 < parts.length; index += 2) {
        S2LatLng current =
            S2LatLng.fromDegrees(
                Double.parseDouble(parts[index]), Double.parseDouble(parts[index + 1]));
        if (previous != null) {
          geoDistance += Math.max(0.0, S2Earth.getDistanceMeters(previous, current));
        }
        points.add(new ShapePoints.ShapePoint(geoDistance, 0.0, current.toPoint()));
        previous = current;
      }

      List<StopToShapeMatch> matches =
          new ShapePoints(points).matchesFromLocation(stop, maxDistance);
      out.append(matches.size());
      for (StopToShapeMatch match : matches) {
        out.append(' ')
            .append(match.getIndex())
            .append(':')
            .append(Double.toString(match.getGeoDistanceToShape()));
      }
      out.append('\n');
    }
    System.out.print(out);
  }
}
