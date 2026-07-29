import com.google.common.hash.HashFunction;
import com.google.common.hash.Hasher;
import com.google.common.hash.Hashing;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

/**
 * Dumps Guava's `farmHashFingerprint64` for two kinds of input.
 *
 * `StopTimeTravelSpeedValidator` groups trips by this fingerprint and iterates the resulting
 * multimap, so the fingerprint decides which notices survive the 1,000-sample cap. Reproducing it
 * needs both halves checked: the hash over a byte string, and the byte stream Guava's `Hasher`
 * builds from `putInt` and `putUnencodedChars`.
 *
 * Two modes, chosen by the first argument:
 *
 * - `bytes`: each line is hex, and the output is the fingerprint of those bytes.
 * - `trip`: each line is a trip, `routeId|stopId,arrival,departure;stopId,arrival,departure...`,
 *   fed through the same `Hasher` calls the validator makes. Ids are hex-encoded so that a
 *   separator inside one cannot be confused for a real one.
 *
 * Output is one signed decimal long per line, as `Long` holds it and as the multimap keys it.
 */
public final class DumpFarmHash {
  public static void main(String[] args) throws IOException {
    String mode = args.length > 0 ? args[0] : "bytes";
    HashFunction function = Hashing.farmHashFingerprint64();
    BufferedReader reader =
        new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
    StringBuilder out = new StringBuilder();
    String line;
    while ((line = reader.readLine()) != null) {
      long value = mode.equals("trip") ? hashTrip(function, line) : function.hashBytes(decode(line)).asLong();
      out.append(value).append('\n');
    }
    System.out.print(out);
  }

  /** The `TripAndStopTimes.tripFprint()` call sequence, verbatim. */
  private static long hashTrip(HashFunction function, String line) {
    String[] halves = line.split("\\|", -1);
    String routeId = text(halves[0]);
    String[] stopTimes = halves[1].isEmpty() ? new String[0] : halves[1].split(";", -1);
    Hasher hasher =
        function
            .newHasher()
            .putInt(routeId.length())
            .putUnencodedChars(routeId)
            .putInt(stopTimes.length);
    for (String stopTime : stopTimes) {
      String[] fields = stopTime.split(",", -1);
      String stopId = text(fields[0]);
      hasher
          .putInt(stopId.length())
          .putUnencodedChars(stopId)
          .putInt(Integer.parseInt(fields[1]))
          .putInt(Integer.parseInt(fields[2]));
    }
    return hasher.hash().asLong();
  }

  private static String text(String hex) {
    return new String(decode(hex), StandardCharsets.UTF_8);
  }

  private static byte[] decode(String hex) {
    byte[] bytes = new byte[hex.length() / 2];
    for (int index = 0; index < bytes.length; index++) {
      bytes[index] = (byte) Integer.parseInt(hex.substring(index * 2, index * 2 + 2), 16);
    }
    return bytes;
  }
}
