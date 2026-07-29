import com.google.i18n.phonenumbers.PhoneNumberUtil;
import java.io.BufferedReader;
import java.io.InputStreamReader;

/**
 * Reads "region<TAB>value" lines and prints region, verdict, value.
 *
 * <p>The call is the one DefaultFieldValidator.validatePhoneNumber makes:
 * PhoneNumberUtil.getInstance().isPossibleNumber(phoneNumber, countryCode). The country-code
 * unknown gate that guards it upstream is deliberately not reproduced here, so the fixture records
 * the raw libphonenumber verdict and the port's own gate stays visible in the port.
 */
public class PhoneOracle {
  public static void main(String[] args) throws Exception {
    BufferedReader in = new BufferedReader(new InputStreamReader(System.in, "UTF-8"));
    PhoneNumberUtil phones = PhoneNumberUtil.getInstance();
    String line;
    while ((line = in.readLine()) != null) {
      if (line.isEmpty()) continue;
      int tab = line.indexOf('\t');
      String region = line.substring(0, tab);
      String value = line.substring(tab + 1);
      boolean ok;
      try {
        ok = phones.isPossibleNumber(value, region);
      } catch (RuntimeException e) {
        ok = false;
      }
      System.out.println(region + "\t" + ok + "\t" + value);
    }
  }
}
