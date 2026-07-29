import java.io.BufferedReader;
import java.io.InputStreamReader;
import org.apache.commons.validator.routines.EmailValidator;
import org.apache.commons.validator.routines.UrlValidator;

/** Reads "url<TAB>value" or "email<TAB>value" lines and prints kind, verdict, value. */
public class Oracle {
  public static void main(String[] args) throws Exception {
    BufferedReader in = new BufferedReader(new InputStreamReader(System.in, "UTF-8"));
    String line;
    while ((line = in.readLine()) != null) {
      if (line.isEmpty()) continue;
      int tab = line.indexOf('\t');
      String kind = line.substring(0, tab);
      String value = line.substring(tab + 1);
      boolean ok;
      if (kind.equals("url")) {
        ok = UrlValidator.getInstance().isValid(value);
      } else {
        ok = EmailValidator.getInstance().isValid(value);
      }
      System.out.println(kind + "\t" + ok + "\t" + value);
    }
  }
}
