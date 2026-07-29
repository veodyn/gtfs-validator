import com.google.common.collect.ArrayListMultimap;
import com.google.common.collect.ListMultimap;
import com.google.common.collect.Multimaps;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

/**
 * Dumps key iteration order for `Multimaps.asMap(ArrayListMultimap.create())`.
 *
 * The generated table containers build their indexes with `ArrayListMultimap.create()`, which
 * pre-sizes its backing map for Guava's default of 12 expected keys: `Maps.capacity(12)` is 17,
 * and HashMap rounds an initial capacity up to a power of two, so the table starts at 32 buckets.
 * A plain `new HashMap<>()` starts at 16. The two therefore disagree on iteration order until
 * enough insertions bring them to the same capacity, which is why a probe with a thousand keys
 * cannot tell them apart and one with five can.
 *
 * Input and output use the same line format as DumpHashOrder: one key per line prefixed with K
 * and escaped, groups separated by "---". Keys may contain spaces, so an unescaped
 * space-separated line would not survive them.
 */
public final class DumpMultimapOrder {
  public static void main(String[] args) throws IOException {
    BufferedReader reader =
        new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
    StringBuilder out = new StringBuilder();
    ListMultimap<String, String> multimap = ArrayListMultimap.create();
    boolean first = true;
    String line;
    while ((line = reader.readLine()) != null) {
      if (line.equals("---")) {
        if (!first) {
          out.append("---\n");
        }
        first = false;
        emit(out, multimap);
        multimap = ArrayListMultimap.create();
        continue;
      }
      multimap.put(unescape(line.substring(1)), "v");
    }
    if (!multimap.isEmpty()) {
      if (!first) {
        out.append("---\n");
      }
      emit(out, multimap);
    }
    System.out.print(out);
  }

  private static void emit(StringBuilder out, ListMultimap<String, String> multimap) {
    for (String key : Multimaps.asMap(multimap).keySet()) {
      out.append('K').append(escape(key)).append('\n');
    }
  }

  private static String escape(String value) {
    StringBuilder builder = new StringBuilder();
    for (int index = 0; index < value.length(); index++) {
      char unit = value.charAt(index);
      if (unit == '\\') {
        builder.append("\\\\");
      } else if (unit < 0x20 || unit > 0x7e) {
        builder.append(String.format("\\u%04x", (int) unit));
      } else {
        builder.append(unit);
      }
    }
    return builder.toString();
  }

  private static String unescape(String value) {
    StringBuilder builder = new StringBuilder();
    int index = 0;
    while (index < value.length()) {
      char unit = value.charAt(index);
      if (unit == '\\' && index + 1 < value.length() && value.charAt(index + 1) == 'u') {
        builder.append((char) Integer.parseInt(value.substring(index + 2, index + 6), 16));
        index += 6;
      } else if (unit == '\\' && index + 1 < value.length() && value.charAt(index + 1) == '\\') {
        builder.append('\\');
        index += 2;
      } else {
        builder.append(unit);
        index += 1;
      }
    }
    return builder.toString();
  }
}
