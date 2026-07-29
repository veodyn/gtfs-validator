import java.util.Locale;
import java.util.TreeSet;

/**
 * Dump every language subtag the JDK knows, with the display name Locale.getDisplayLanguage
 * gives for it.
 *
 * `summary.feedInfo["Feed Language"]` upstream is `info.feedLang().getDisplayLanguage()`, a
 * no-argument call, so the JVM's *default display locale* decides the answer. Measured on the
 * pinned jar against one feed carrying `feed_lang=en`: "English" by default, "anglais" under
 * -Duser.language=fr, and the Japanese for English under -Duser.language=ja. That is a property
 * of the host, not of the feed, so this dump fixes the display locale to Locale.US and
 * gtfs-validator reports the same string everywhere, which is a deliberate difference.
 *
 * Both the two- and three-letter forms are emitted, because feed_lang takes a BCP-47 tag and
 * "eng" is as legal as "en".
 */
public class DumpDisplayLanguages {
  public static void main(String[] args) {
    Locale display = Locale.US;
    TreeSet<String> subtags = new TreeSet<>();

    for (String code : Locale.getISOLanguages()) {
      subtags.add(code);
      String iso3 = new Locale(code).getISO3Language();
      if (!iso3.isEmpty()) {
        subtags.add(iso3);
      }
    }
    for (Locale available : Locale.getAvailableLocales()) {
      if (!available.getLanguage().isEmpty()) {
        subtags.add(available.getLanguage());
      }
    }

    for (String subtag : subtags) {
      Locale locale = new Locale.Builder().setLanguage(subtag).build();
      System.out.println(subtag + "\t" + locale.getDisplayLanguage(display));
    }
  }
}
