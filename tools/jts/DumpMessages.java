import java.util.LinkedHashMap;
import java.util.Map;
import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.GeometryFactory;
import org.locationtech.jts.geom.LinearRing;
import org.locationtech.jts.geom.Polygon;
import org.locationtech.jts.operation.valid.IsValidOp;
import org.locationtech.jts.operation.valid.TopologyValidationError;

/**
 * Dumps every message GeoJsonGeometryValidator can put in an invalid_geometry notice.
 *
 * Two sources: TopologyValidationError.getMessage() for a geometry JTS parses but rejects,
 * and IllegalArgumentException.getMessage() for one GeometryFactory refuses to build.
 * Both are read out of the pinned jar rather than transcribed.
 */
public class DumpMessages {
  static final GeometryFactory FACTORY = new GeometryFactory();

  static Coordinate at(double x, double y) {
    return new Coordinate(x, y);
  }

  static LinearRing ring(Coordinate... coordinates) {
    return FACTORY.createLinearRing(coordinates);
  }

  public static void main(String[] args) {
    Map<String, String> errors = new LinkedHashMap<>();
    // The error-code table itself, so the names and their wording come from the jar.
    for (int code = 0; code <= 12; code++) {
      try {
        errors.put("code_" + code, new TopologyValidationError(code).getMessage());
      } catch (RuntimeException exception) {
        errors.put("code_" + code, "UNAVAILABLE");
      }
    }

    Map<String, String> cases = new LinkedHashMap<>();
    // A geometry JTS builds and then judges invalid: the error carries the message.
    record Case(String name, java.util.function.Supplier<Polygon> build) {}
    Case[] polygons = {
      new Case("invalid_coordinate", () -> FACTORY.createPolygon(ring(
          at(Double.NaN, 0), at(1, 0), at(1, 1), at(Double.NaN, 0)))),
      new Case("too_few_distinct_points", () -> FACTORY.createPolygon(ring(
          at(0, 0), at(1, 1), at(1, 1), at(0, 0)))),
      new Case("ring_self_intersection", () -> FACTORY.createPolygon(ring(
          at(0, 0), at(2, 2), at(2, 0), at(0, 2), at(0, 0)))),
      new Case("hole_outside_shell", () -> FACTORY.createPolygon(
          ring(at(0, 0), at(4, 0), at(4, 4), at(0, 4), at(0, 0)),
          new LinearRing[] {ring(at(10, 10), at(11, 10), at(11, 11), at(10, 10))})),
      new Case("nested_holes", () -> FACTORY.createPolygon(
          ring(at(0, 0), at(10, 0), at(10, 10), at(0, 10), at(0, 0)),
          new LinearRing[] {
            ring(at(1, 1), at(8, 1), at(8, 8), at(1, 8), at(1, 1)),
            ring(at(2, 2), at(7, 2), at(7, 7), at(2, 7), at(2, 2)),
          })),
      new Case("disconnected_interior", () -> FACTORY.createPolygon(
          ring(at(0, 0), at(10, 0), at(10, 10), at(0, 10), at(0, 0)),
          new LinearRing[] {
            ring(at(0, 0), at(5, 0), at(5, 10), at(0, 10), at(0, 0)),
            ring(at(5, 0), at(10, 0), at(10, 10), at(5, 10), at(5, 0)),
          })),
      new Case("self_intersection", () -> FACTORY.createPolygon(
          ring(at(0, 0), at(10, 0), at(10, 10), at(0, 10), at(0, 0)),
          new LinearRing[] {
            ring(at(1, 1), at(9, 1), at(9, 9), at(1, 9), at(1, 1)),
            ring(at(2, 2), at(8, 2), at(8, 8), at(2, 8), at(2, 2)),
          })),
    };
    for (Case polygonCase : polygons) {
      try {
        Polygon polygon = polygonCase.build().get();
        TopologyValidationError error = new IsValidOp(polygon).getValidationError();
        cases.put(polygonCase.name(),
            error == null ? "VALID" : error.getErrorType() + "\t" + error.getMessage());
      } catch (IllegalArgumentException exception) {
        cases.put(polygonCase.name(), "THROWS\t" + exception.getMessage());
      }
    }

    Map<String, String> thrown = new LinkedHashMap<>();
    // Geometries GeometryFactory refuses outright. The notice then carries the
    // exception's message instead of a TopologyValidationError's.
    Map<String, Coordinate[]> refused = new LinkedHashMap<>();
    refused.put("unclosed_ring", new Coordinate[] {at(0, 0), at(1, 0), at(1, 1), at(0, 1)});
    refused.put("three_points", new Coordinate[] {at(0, 0), at(1, 0), at(0, 0)});
    refused.put("two_points", new Coordinate[] {at(0, 0), at(0, 0)});
    refused.put("one_point", new Coordinate[] {at(0, 0)});
    refused.put("empty", new Coordinate[] {});
    // A shell that is empty while a hole is not has its own wording, and it is the one
    // message that is not about a single ring, so it cannot come from the loop below.
    try {
      FACTORY.createPolygon(
          ring(),
          new LinearRing[] {ring(at(2, 2), at(3, 2), at(2, 2))});
      thrown.put("shell_empty_holes_not", "ACCEPTED");
    } catch (IllegalArgumentException exception) {
      thrown.put("shell_empty_holes_not", exception.getMessage());
    }
    for (Map.Entry<String, Coordinate[]> entry : refused.entrySet()) {
      try {
        FACTORY.createPolygon(FACTORY.createLinearRing(entry.getValue()));
        thrown.put(entry.getKey(), "ACCEPTED");
      } catch (IllegalArgumentException exception) {
        thrown.put(entry.getKey(), exception.getMessage());
      }
    }

    print("error_messages", errors);
    print("validation_cases", cases);
    print("construction_errors", thrown);
  }

  static void print(String section, Map<String, String> values) {
    System.out.println("### " + section);
    for (Map.Entry<String, String> entry : values.entrySet()) {
      System.out.println(entry.getKey() + "\t" + entry.getValue());
    }
  }
}
