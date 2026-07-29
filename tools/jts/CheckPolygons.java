import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.List;
import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.GeometryFactory;
import org.locationtech.jts.geom.LinearRing;
import org.locationtech.jts.geom.MultiPolygon;
import org.locationtech.jts.geom.Polygon;
import org.locationtech.jts.operation.valid.IsValidOp;
import org.locationtech.jts.operation.valid.TopologyValidationError;

/**
 * Batch oracle for GeoJsonGeometryValidator's two failure paths.
 *
 * Reads one case per line on stdin and writes one verdict per line, so a whole corpus
 * costs a single JVM start rather than one per shape. This is what lets the Python
 * geometry engine be differentialled against JTS directly instead of through feeds.
 *
 * Input:  name|<polygon>[#<polygon>...]   where a polygon is ring;ring;ring
 *         and a ring is "x,y x,y x,y". The first ring is the shell.
 *         A single polygon reproduces createPolygon; two or more reproduce
 *         createMultiPolygon, including its per-polygon check order.
 * Output: name\tVALID | name\t<errorCode>\t<message> | name\tTHROWS\t<message>
 */
public class CheckPolygons {
  static final GeometryFactory FACTORY = new GeometryFactory();

  static Coordinate[] parseRing(String text) {
    // A ring can legitimately be empty: GeometryFactory accepts an empty LinearRing, and
    // a polygon with an empty shell has its own message.
    if (text.trim().equals("EMPTY")) {
      return new Coordinate[] {};
    }
    String[] points = text.trim().split("\\s+");
    Coordinate[] coordinates = new Coordinate[points.length];
    for (int i = 0; i < points.length; i++) {
      String[] parts = points[i].split(",");
      coordinates[i] = new Coordinate(Double.parseDouble(parts[0]), Double.parseDouble(parts[1]));
    }
    return coordinates;
  }

  /** createPolygon: the shell as a LinearRing, the rest as interior rings. */
  static Polygon parsePolygon(String text) {
    String[] ringTexts = text.split(";");
    LinearRing shell = FACTORY.createLinearRing(parseRing(ringTexts[0]));
    LinearRing[] holes = null;
    if (ringTexts.length > 1) {
      holes = new LinearRing[ringTexts.length - 1];
      for (int i = 1; i < ringTexts.length; i++) {
        holes[i - 1] = FACTORY.createLinearRing(parseRing(ringTexts[i]));
      }
    }
    return FACTORY.createPolygon(shell, holes);
  }

  static String verdict(String body) {
    try {
      String[] polygonTexts = body.split("#");
      if (polygonTexts.length == 1) {
        return report(parsePolygon(polygonTexts[0]));
      }
      // createMultiPolygon builds every polygon first, and upstream bails on the first
      // invalid one, so a member's error is reported before the collection is assembled.
      List<Polygon> polygons = new ArrayList<>();
      for (String polygonText : polygonTexts) {
        Polygon polygon = parsePolygon(polygonText);
        String memberVerdict = report(polygon);
        if (!memberVerdict.equals("VALID")) {
          return memberVerdict;
        }
        polygons.add(polygon);
      }
      MultiPolygon multiPolygon =
          FACTORY.createMultiPolygon(polygons.toArray(new Polygon[0]));
      return report(multiPolygon);
    } catch (IllegalArgumentException exception) {
      return "THROWS\t" + exception.getMessage();
    }
  }

  static String report(org.locationtech.jts.geom.Geometry geometry) {
    if (IsValidOp.isValid(geometry)) {
      return "VALID";
    }
    TopologyValidationError error = new IsValidOp(geometry).getValidationError();
    return error == null ? "VALID" : error.getErrorType() + "\t" + error.getMessage();
  }

  public static void main(String[] args) throws Exception {
    BufferedReader reader = new BufferedReader(new InputStreamReader(System.in));
    String line;
    StringBuilder out = new StringBuilder();
    while ((line = reader.readLine()) != null) {
      if (line.isBlank()) {
        continue;
      }
      int split = line.indexOf('|');
      String name = line.substring(0, split);
      try {
        out.append(name).append('\t').append(verdict(line.substring(split + 1))).append('\n');
      } catch (RuntimeException exception) {
        out.append(name).append("\tERROR\t").append(exception).append('\n');
      }
    }
    System.out.print(out);
  }
}
