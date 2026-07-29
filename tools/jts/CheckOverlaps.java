import java.io.BufferedReader;
import java.io.InputStreamReader;
import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.GeometryFactory;
import org.locationtech.jts.geom.LinearRing;
import org.locationtech.jts.geom.Polygon;

/**
 * Batch oracle for Geometry.overlaps, which is what GtfsGeoJsonFeature.geometryOverlaps calls.
 *
 * OverlappingPickupDropOffZoneValidator asks JTS whether two locations.geojson zones overlap,
 * and JTS means the DE-9IM predicate rather than "intersect": containment is not overlap, a
 * shared edge is not overlap, and two identical polygons do not overlap. Those three are easy
 * to get wrong by reading the name, so the Python port is differentialled against this.
 *
 * Only Polygon is handled, deliberately. Upstream drops every MultiPolygon before the geometry
 * type dispatch, because validateCoordinates indexes to a fixed depth and throws on anything
 * deeper, so a MultiPolygon never reaches a feature and never reaches overlaps().
 *
 * Input:  name|<polygon>#<polygon>   where a polygon is ring;ring;ring
 *         and a ring is "x,y x,y x,y". The first ring is the shell, the rest are holes.
 * Output: name\tTRUE | name\tFALSE | name\tTHROWS\t<message>
 */
public class CheckOverlaps {
  static final GeometryFactory FACTORY = new GeometryFactory();

  static Coordinate[] parseRing(String text) {
    String[] points = text.trim().split("\\s+");
    Coordinate[] coordinates = new Coordinate[points.length];
    for (int i = 0; i < points.length; i++) {
      String[] parts = points[i].split(",");
      coordinates[i] = new Coordinate(Double.parseDouble(parts[0]), Double.parseDouble(parts[1]));
    }
    return coordinates;
  }

  static Polygon parsePolygon(String text) {
    String[] rings = text.split(";");
    LinearRing shell = FACTORY.createLinearRing(parseRing(rings[0]));
    LinearRing[] holes = new LinearRing[rings.length - 1];
    for (int i = 1; i < rings.length; i++) {
      holes[i - 1] = FACTORY.createLinearRing(parseRing(rings[i]));
    }
    return FACTORY.createPolygon(shell, holes);
  }

  public static void main(String[] args) throws Exception {
    BufferedReader reader = new BufferedReader(new InputStreamReader(System.in));
    String line;
    while ((line = reader.readLine()) != null) {
      if (line.isBlank()) {
        continue;
      }
      int bar = line.indexOf('|');
      String name = line.substring(0, bar);
      String[] halves = line.substring(bar + 1).split("#");
      try {
        Polygon first = parsePolygon(halves[0]);
        Polygon second = parsePolygon(halves[1]);
        System.out.println(name + "\t" + (first.overlaps(second) ? "TRUE" : "FALSE"));
      } catch (Exception e) {
        System.out.println(name + "\tTHROWS\t" + e.getMessage());
      }
    }
  }
}
