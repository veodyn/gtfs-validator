import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

/**
 * Dumps java.util.HashMap iteration order for corpora of string keys.
 *
 * Input on stdin: groups of keys, one key per line, groups separated by a line "---".
 * Output on stdout: each group's keySet() iteration order, one key per line, groups
 * separated by "---".
 *
 * This settles the ordering that gtfs_validator.javahash reproduces. Above the 1,000-notice
 * sample cap the order decides which notices survive, so it is part of the contract.
 * Keys are printed escaped so a corpus may contain anything except a newline.
 */
public final class DumpHashOrder {
  public static void main(String[] args) throws IOException {
    BufferedReader reader =
        new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
    StringBuilder out = new StringBuilder();
    Map<String, Integer> map = new HashMap<>();
    boolean first = true;
    String line;
    while ((line = reader.readLine()) != null) {
      if (line.equals("---")) {
        if (!first) {
          out.append("---\n");
        }
        first = false;
        emit(out, map);
        map = new HashMap<>();
        continue;
      }
      map.put(unescape(line.substring(1)), map.size());
    }
    if (!map.isEmpty()) {
      if (!first) {
        out.append("---\n");
      }
      emit(out, map);
    }
    System.out.print(out);
  }

  private static void emit(StringBuilder out, Map<String, Integer> map) {
    for (String key : map.keySet()) {
      // Prefixed, because the empty string is a legal key and an unprefixed one would
      // be a blank line indistinguishable from padding.
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
