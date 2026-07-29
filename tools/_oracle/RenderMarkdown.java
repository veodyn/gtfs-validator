import com.vladsch.flexmark.html.HtmlRenderer;
import com.vladsch.flexmark.parser.Parser;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;

/**
 * Render Markdown to HTML with the flexmark bundled in the pinned jar.
 *
 * `NoticeView.getDescription()` runs each notice's combined documentation through
 * Parser/HtmlRenderer with default options, and the result is dropped into report.html by
 * `th:utext`, unescaped. Reproducing that in Python would mean reimplementing a Markdown
 * renderer and matching it exactly, so it is measured once per notice code at the pin and
 * checked in, the same way jts_messages.json is.
 *
 * Protocol, chosen so a record can hold blank lines and backticks without escaping: the input
 * file is a sequence of records, each opening with a line "###KEY <code>" and running to the
 * next such line. Output repeats the key lines with the rendered HTML between them.
 */
public class RenderMarkdown {
  private static final String KEY = "###KEY ";

  public static void main(String[] args) throws Exception {
    String text = new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8);
    Parser parser = Parser.builder().build();
    HtmlRenderer renderer = HtmlRenderer.builder().build();

    String key = null;
    StringBuilder body = new StringBuilder();
    StringBuilder out = new StringBuilder();
    for (String line : text.split("\n", -1)) {
      if (line.startsWith(KEY)) {
        if (key != null) {
          emit(out, key, renderer.render(parser.parse(trimTrailingNewline(body.toString()))));
        }
        key = line.substring(KEY.length());
        body.setLength(0);
      } else {
        body.append(line).append('\n');
      }
    }
    if (key != null) {
      emit(out, key, renderer.render(parser.parse(trimTrailingNewline(body.toString()))));
    }
    System.out.print(out);
  }

  private static String trimTrailingNewline(String value) {
    return value.endsWith("\n") ? value.substring(0, value.length() - 1) : value;
  }

  /**
   * The separator newline is unconditional. Adding one only when the body lacks it would make
   * flexmark's own trailing newline indistinguishable from the delimiter, and it is not
   * cosmetic: report.html renders "<p >" + description + "</p>", so a lost newline is a byte of
   * difference on every notice block in the page.
   */
  private static void emit(StringBuilder out, String key, String html) {
    out.append(KEY).append(key).append('\n').append(html).append('\n');
  }
}
