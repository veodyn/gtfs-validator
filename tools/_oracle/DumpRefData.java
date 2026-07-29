import com.google.i18n.phonenumbers.PhoneNumberUtil;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.time.ZoneId;
import java.util.Currency;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * Dump the reference sets upstream's field parsers resolve against, and answer language-tag
 * queries.
 *
 * <p>RowParser converts these columns with Currency.getInstance, ZoneId.of and
 * Locale.Builder().setLanguageTag(), so the sets Java actually carries are the contract. Reading
 * them here beats hand-transcribing ISO tables that would drift.
 *
 * <p>Phone lengths are probed rather than read out of libphonenumber's metadata: validatePhoneNumber
 * calls isPossibleNumber, which is a length check, so asking it directly which national-number
 * lengths a region accepts measures exactly the behaviour we must reproduce.
 *
 * <p>Prints currency, zone and phone rows, then reads language tags on stdin.
 */
public class DumpRefData {
  private static final int MAX_PROBE_LENGTH = 17;

  public static void main(String[] args) throws Exception {
    for (Currency currency : Currency.getAvailableCurrencies()) {
      // getDefaultFractionDigits drives invalid_currency_amount: an amount whose
      // decimal scale differs from this is reported. -1 means "no fraction".
      System.out.println(
          "currency\t" + currency.getCurrencyCode() + "\t" + currency.getDefaultFractionDigits());
    }
    for (String zone : ZoneId.getAvailableZoneIds()) {
      System.out.println("zone\t" + zone);
    }

    PhoneNumberUtil phones = PhoneNumberUtil.getInstance();
    Method metadataFor = PhoneNumberUtil.class.getDeclaredMethod("getMetadataForRegion", String.class);
    metadataFor.setAccessible(true);
    for (String region : phones.getSupportedRegions()) {
      // Region-scoped probe: national number only, for numbers with no + prefix.
      System.out.println("phoneRegion\t" + region + "\t" + probeRegion(phones, region));
      // parse() strips an international dialling prefix and a national prefix
      // before measuring, and decides whether to keep the stripped form by
      // comparing lengths. Both prefixes are region metadata rather than
      // something a length probe can reveal, so they are read directly.
      Object metadata = metadataFor.invoke(phones, region);
      Object generalDesc = metadata.getClass().getMethod("getGeneralDesc").invoke(metadata);
      System.out.println(
          "phoneMeta\t"
              + region
              + "\t"
              + phones.getCountryCodeForRegion(region)
              + "\t"
              + call(metadata, "getInternationalPrefix")
              + "\t"
              + call(metadata, "getNationalPrefixForParsing")
              + "\t"
              + call(metadata, "getNationalPrefixTransformRule")
              + "\t"
              + probeStrict(phones, region)
              + "\t"
              + call(generalDesc, "getNationalNumberPattern")
              + "\t"
              + joinInts(generalDesc, "getPossibleLengthList")
              + "\t"
              + joinInts(generalDesc, "getPossibleLengthLocalOnlyList"));
    }
    // parse() resolves an extracted country calling code back to a region before
    // it applies that region's national prefix and length rules, so the + branch
    // needs the same map. 001 marks the non-geographical codes.
    for (int code = 1; code <= 999; code++) {
      String main = phones.getRegionCodeForCountryCode(code);
      if (!main.equals("ZZ")) {
        System.out.println("phoneCodeRegion\t" + code + "\t" + main);
      }
    }
    // Calling-code-scoped probe for +-prefixed numbers, where libphonenumber
    // parses the code from the number and ignores the passed region. ZZ forces
    // that path. Codes are 1 to 3 digits.
    for (int code = 1; code <= 999; code++) {
      String lengths = probePlus(phones, code);
      if (!lengths.isEmpty()) {
        System.out.println("phoneCode\t" + code + "\t" + lengths);
      }
    }

    // The ISO country set decides whether validation runs at all. Upstream skips
    // a phone entirely when its CountryCode is unknown, and CountryCode accepts
    // exactly Locale.getISOCountries() plus the ZZ sentinel. A code that is a real
    // country but carries no libphonenumber metadata (AQ) still validates, and a
    // national number then fails, so this set is not the supported-region set.
    for (String country : Locale.getISOCountries()) {
      System.out.println("isoCountry\t" + country);
    }

    // isPossibleNumber parses before measuring, and parse() first rejects anything
    // that does not match this pattern (NOT_A_NUMBER -> false). Without it a value
    // like "+abc1 202-555-0173" reduces to the digits of a valid number. Read by
    // reflection rather than transcribed: the punctuation class alone spans a
    // dozen Unicode dash and space forms.
    // The same argument applies to the three other patterns parse() runs before it
    // measures anything: the extension pattern alone is several hundred characters
    // of alternation across a dozen languages.
    //
    // The flags travel with each pattern because they are not uniform: only
    // EXTN_PATTERN and VALID_PHONE_NUMBER_PATTERN are case insensitive, so
    // compiling the whole set that way makes SECOND_NUMBER_START_PATTERN's "/x"
    // match "/X", which libphonenumber does not treat as a second number.
    for (String name :
        new String[] {
          "VALID_PHONE_NUMBER_PATTERN",
          "EXTN_PATTERN",
          "VALID_ALPHA_PHONE_PATTERN",
          "SECOND_NUMBER_START_PATTERN"
        }) {
      Field field = PhoneNumberUtil.class.getDeclaredField(name);
      field.setAccessible(true);
      Pattern pattern = (Pattern) field.get(null);
      System.out.println(
          "phonePattern\t" + name + "\t" + pattern.flags() + "\t" + pattern.pattern());
    }
    // normalize() folds a vanity number through this map, and its contents are
    // not what its name suggests: it is the 26 letters plus the *ASCII* digits
    // only, so a fullwidth or Arabic-Indic digit is dropped rather than kept on
    // the alpha path. Reconstructing it from libphonenumber's documented digit
    // set gets that backwards, so it is dumped verbatim.
    Field alphaMap = PhoneNumberUtil.class.getDeclaredField("ALPHA_PHONE_MAPPINGS");
    alphaMap.setAccessible(true);
    for (java.util.Map.Entry<?, ?> entry : ((java.util.Map<?, ?>) alphaMap.get(null)).entrySet()) {
      System.out.println(
          "phoneAlpha\t"
              + String.format("%04X", (int) (Character) entry.getKey())
              + "\t"
              + entry.getValue());
    }

    // The RFC 3966 markers parse() splits a "tel:" URI on, before it checks
    // viability. Dumped rather than transcribed for the same reason as the rest.
    for (String name :
        new String[] {"RFC3966_PREFIX", "RFC3966_PHONE_CONTEXT", "RFC3966_ISDN_SUBADDRESS"}) {
      Field field = PhoneNumberUtil.class.getDeclaredField(name);
      field.setAccessible(true);
      System.out.println("phoneConst\t" + name + "\t" + field.get(null));
    }

    BufferedReader in = new BufferedReader(new InputStreamReader(System.in, "UTF-8"));
    String line;
    while ((line = in.readLine()) != null) {
      boolean ok;
      try {
        new Locale.Builder().setLanguageTag(line).build();
        ok = true;
      } catch (RuntimeException e) {
        ok = false;
      }
      System.out.println("language\t" + ok + "\t" + line);
    }
  }

  /** Read a no-argument metadata getter, turning a null or absent value into "". */
  private static String call(Object metadata, String getter) throws Exception {
    Object value = metadata.getClass().getMethod(getter).invoke(metadata);
    return value == null ? "" : value.toString();
  }

  /** Render a List&lt;Integer&gt; metadata getter as a comma-separated string. */
  private static String joinInts(Object desc, String getter) throws Exception {
    Object value = desc.getClass().getMethod(getter).invoke(desc);
    StringBuilder out = new StringBuilder();
    for (Object n : (java.util.List<?>) value) {
      if (out.length() > 0) out.append(",");
      out.append(n);
    }
    return out.toString();
  }

  /**
   * Lengths that are possible outright, excluding the local-only ones.
   *
   * <p>isPossibleNumber accepts IS_POSSIBLE_LOCAL_ONLY as well, so the probe above cannot tell the
   * two apart. parse() needs the distinction: it keeps a prefix-stripped number only when the
   * stripped form is possible in the strict sense, which is why "17654321" stays 8 digits under US
   * and fails rather than becoming the local-only 7-digit "7654321".
   */
  private static String probeStrict(PhoneNumberUtil phones, String region) {
    StringBuilder lengths = new StringBuilder();
    for (int length = 1; length <= MAX_PROBE_LENGTH; length++) {
      boolean strict;
      try {
        strict =
            phones.isPossibleNumberWithReason(phones.parse("2".repeat(length), region))
                == PhoneNumberUtil.ValidationResult.IS_POSSIBLE;
      } catch (RuntimeException | com.google.i18n.phonenumbers.NumberParseException e) {
        strict = false;
      }
      if (strict) {
        if (lengths.length() > 0) lengths.append(",");
        lengths.append(length);
      }
    }
    return lengths.toString();
  }

  private static String probeRegion(PhoneNumberUtil phones, String region) {
    StringBuilder lengths = new StringBuilder();
    for (int length = 1; length <= MAX_PROBE_LENGTH; length++) {
      boolean possible;
      try {
        possible = phones.isPossibleNumber("2".repeat(length), region);
      } catch (RuntimeException e) {
        possible = false;
      }
      if (possible) {
        if (lengths.length() > 0) lengths.append(",");
        lengths.append(length);
      }
    }
    return lengths.toString();
  }

  private static String probePlus(PhoneNumberUtil phones, int code) {
    StringBuilder lengths = new StringBuilder();
    for (int length = 1; length <= MAX_PROBE_LENGTH; length++) {
      boolean possible;
      try {
        possible = phones.isPossibleNumber("+" + code + "2".repeat(length), "ZZ");
      } catch (RuntimeException e) {
        possible = false;
      }
      if (possible) {
        if (lengths.length() > 0) lengths.append(",");
        lengths.append(length);
      }
    }
    return lengths.toString();
  }
}
