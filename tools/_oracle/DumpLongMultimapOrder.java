import com.google.common.collect.ArrayListMultimap;
import com.google.common.collect.ListMultimap;
import com.google.common.collect.Multimaps;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

/**
 * Dumps key iteration order for a `Long`-keyed `ArrayListMultimap`.
 *
 * `StopTimeTravelSpeedValidator` groups trips under a 64-bit fingerprint, so its table is keyed by
 * `Long` rather than by `String`. Two things differ from DumpMultimapOrder and both change the
 * order: `Long.hashCode` folds the two halves of the value together, and a bin deep enough to
 * treeify orders its nodes by `Long.compareTo`, which is numeric. A port that treats a non-string
 * key as non-comparable agrees with this until a bucket treeifies and then does not.
 *
 * Input is one decimal signed long per line, groups separated by "---". Output is the same.
 */
public final class DumpLongMultimapOrder {
  public static void main(String[] args) throws IOException {
    BufferedReader reader =
        new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
    StringBuilder out = new StringBuilder();
    ListMultimap<Long, String> multimap = ArrayListMultimap.create();
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
      multimap.put(Long.parseLong(line), "v");
    }
    if (!multimap.isEmpty()) {
      if (!first) {
        out.append("---\n");
      }
      emit(out, multimap);
    }
    System.out.print(out);
  }

  private static void emit(StringBuilder out, ListMultimap<Long, String> multimap) {
    for (Long key : Multimaps.asMap(multimap).keySet()) {
      out.append(key).append('\n');
    }
  }
}
