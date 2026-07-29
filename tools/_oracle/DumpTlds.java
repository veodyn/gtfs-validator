import java.lang.reflect.Field;
import org.apache.commons.validator.routines.DomainValidator;

/**
 * Dump the TLD tables commons-validator's DomainValidator checks against.
 *
 * <p>UrlValidator and EmailValidator both reject a hostname whose top-level domain is not in these
 * arrays, so a port that skips them accepts domains upstream rejects. The list is whatever shipped
 * in the bundled commons-validator, which is frozen in time; that staleness is the contract, not a
 * bug to correct against today's IANA registry.
 */
public class DumpTlds {
  public static void main(String[] args) throws Exception {
    String[] names = {
      "INFRASTRUCTURE_TLDS", "GENERIC_TLDS", "COUNTRY_CODE_TLDS", "LOCAL_TLDS"
    };
    for (String name : names) {
      Field field = DomainValidator.class.getDeclaredField(name);
      field.setAccessible(true);
      String[] values = (String[]) field.get(null);
      for (String value : values) {
        System.out.println(name + "\t" + value);
      }
    }
  }
}
