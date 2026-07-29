"""Java Locale semantics for the rules that compare language tags.

`RowParser.parseLocale` builds the value with `new Locale.Builder().setLanguageTag(tag)`, so
equality is `Locale.equals`. What a *notice* reports depends on the rule: some carry
`Locale.getLanguage()` and some `Locale.toLanguageTag()`, which disagree about how much of the tag
survives. Neither is string comparison, and neither is derivable from the other. Every line below was oracled from the pinned JDK 17 with

    new Locale.Builder().setLanguageTag(tag).build()  ->  getLanguage(), toLanguageTag()

rather than read off the javadoc. The corpus is 31 tags, and the size matters: a first pass of 17
reported zero mismatches while two behaviours were still wrong, so the tags below are the ones that
have actually been checked rather than the ones that came to mind.

- **Case is normalised, except in a variant.** `EN` equals `en`, and `en-us` equals
  `en-US`, but `en-US-posix` and `en-US-POSIX` are *different* locales. Lowercasing the
  whole tag silences a notice the jar emits.
- **Region matters to equality, and whether it reaches the report depends on the rule.**
  `inconsistent_agency_lang` reports `Locale.getLanguage()`, so `en-US` against `en` draws a notice
  whose two values are both `en`. `feed_info_lang_and_agency_lang_mismatch` reports
  `Locale.toLanguageTag()` and says `en-US` against `en`. Two identical values in one notice is
  correct output for the first rule and would be wrong for the second, so this module exposes both
  spellings rather than picking one.
- **An extlang replaces the language.** `zh-cmn` *is* `cmn`, and `zh-cmn-Hant` is `cmn-Hant`. The
  primary subtag disappears, so comparing the tags as written reports a mismatch between a language
  and itself.
- **`und` disappears when only private use is left.** `und-x-private` is `x-private`, while
  `und-US` and a bare `und` keep theirs.
- **Grandfathered tags are aliases.** `i-klingon` *is* `tlh`, `no-bok` is `nb`,
  `art-lojban` is `jbo`. Comparing them literally reports a mismatch between a
  language and itself, and `language_of("i-klingon")` is `tlh`, not `i`.
- **`und` has no language.** It reports as `""`.
- **Legacy ISO remapping does not apply.** `he`, `id` and `yi` report as themselves,
  not `iw`, `in` and `ji`: `useOldISOCodes` is off by default from JDK 17 on.
"""

from __future__ import annotations

# Every grandfathered tag in the RFC 5646 registry, mapped to what the JDK makes of
# it: (getLanguage(), toLanguageTag()). Both columns are needed, because the canonical
# tag sometimes keeps the original as a private-use suffix while the language does not.
# Keys are lowercased; the lookup lowercases too, since the tags are case insensitive.
_GRANDFATHERED = {
    "en-gb-oed": ("en", "en-GB-x-oed"),
    "i-ami": ("ami", "ami"),
    "i-bnn": ("bnn", "bnn"),
    "i-default": ("en", "en-x-i-default"),
    "i-enochian": ("", "x-i-enochian"),
    "i-hak": ("hak", "hak"),
    "i-klingon": ("tlh", "tlh"),
    "i-lux": ("lb", "lb"),
    "i-mingo": ("see", "see-x-i-mingo"),
    "i-navajo": ("nv", "nv"),
    "i-pwn": ("pwn", "pwn"),
    "i-tao": ("tao", "tao"),
    "i-tay": ("tay", "tay"),
    "i-tsu": ("tsu", "tsu"),
    "sgn-be-fr": ("sfb", "sfb"),
    "sgn-be-nl": ("vgt", "vgt"),
    "sgn-ch-de": ("sgg", "sgg"),
    "art-lojban": ("jbo", "jbo"),
    "cel-gaulish": ("xtg", "xtg-x-cel-gaulish"),
    "no-bok": ("nb", "nb"),
    "no-nyn": ("nn", "nn"),
    "zh-guoyu": ("cmn", "cmn"),
    "zh-hakka": ("hak", "hak"),
    "zh-min": ("nan", "nan-x-zh-min"),
    "zh-min-nan": ("nan", "nan"),
    "zh-xiang": ("hsn", "hsn"),
}

# "und" is the explicit undetermined language, and Locale holds it as no language.
UNDETERMINED = "und"

# Subtag shapes from BCP 47. The Builder normalises case by position, not by content.
_SCRIPT_LENGTH = 4
_REGION_ALPHA_LENGTH = 2
_REGION_DIGIT_LENGTH = 3
_SINGLETON_LENGTH = 1
_UNICODE_KEY_LENGTH = 2
_EXTLANG_LENGTH = 3
_PRIVATE_USE = "x"


def language_of(tag: str) -> str:
    """`Locale.getLanguage()`: the language subtag, lowercased.

    `zh-Hant-TW` reports `zh` and `und` reports `""`, both measured. A grandfathered
    tag reports its replacement's language, so `i-klingon` is `tlh`.
    """
    if not tag:
        return ""
    alias = _GRANDFATHERED.get(tag.lower())
    if alias is not None:
        return alias[0]
    key = canonical(tag)
    # canonical() has already promoted an extlang and dropped a private-use-only `und`, so the
    # language is its first subtag, if any survived.
    if not key or key[0] == UNDETERMINED or key[0] == _PRIVATE_USE:
        return ""
    return key[0]


def language_tag(tag: str) -> str:
    """`Locale.toLanguageTag()`: the canonical spelling, region and all.

    Not the same as `language_of`, and two rules want different ones:
    `inconsistent_agency_lang` reports `getLanguage()` and so says `en` for `en-US`, while
    `feed_info_lang_and_agency_lang_mismatch` reports `toLanguageTag()` and says `en-US`. Both
    measured on the jar, on a 31-tag corpus that includes the grandfathered aliases, `und`,
    extlangs and private use.
    """
    return "-".join(canonical(tag))


def canonical(tag: str) -> tuple[str, ...]:
    """A key equal for exactly the tags `Locale.equals` treats as one locale."""
    if not tag:
        return ()
    alias = _GRANDFATHERED.get(tag.lower())
    if alias is not None:
        # Recurse on the replacement rather than returning it raw, so the two spellings
        # of one locale ("i-klingon" and "tlh") produce the identical key.
        return canonical(alias[1])
    parts = tag.split("-")
    # A tag that is only private use has `x` where a language would be, and everything after it
    # belongs to that section in order. Treating `x` as the language made `x-b-a` into `x-a-b`,
    # which the jar treats as a different locale.
    if parts[0].lower() == _PRIVATE_USE:
        return tuple(part.lower() for part in parts)
    head: list[str] = [parts[0].lower()]
    rest = parts[1:]
    # An extlang in second position replaces the primary language: `zh-cmn` is `cmn`. BCP 47 allows
    # up to three, and Java keeps **only the first**, discarding the rest: `zh-cmn-yue` is `cmn` and
    # `zh-min-nan-Hant` is `min-Hant`. Measured; treating the second as a variant kept it.
    if rest and len(rest[0]) == _EXTLANG_LENGTH and rest[0].isalpha():
        head = [rest[0].lower()]
        rest = rest[1:]
        while rest and len(rest[0]) == _EXTLANG_LENGTH and rest[0].isalpha():
            rest = rest[1:]
    sections: list[list[str]] = []
    for index, part in enumerate(rest):
        if sections and sections[-1][0] == _PRIVATE_USE:
            # Everything after `x-` is private use, including one-character subtags, which would
            # otherwise each look like a new singleton: `und-x-a-b` is one section, not three.
            sections[-1].extend(subtag.lower() for subtag in rest[index:])
            break
        if len(part) == _SINGLETON_LENGTH:
            # A singleton opens an extension section running to the next singleton.
            sections.append([part.lower()])
            continue
        if sections:
            sections[-1].append(part.lower())
        elif len(part) == _SCRIPT_LENGTH and part.isalpha():
            head.append(part.title())
        elif (len(part) == _REGION_ALPHA_LENGTH and part.isalpha()) or (
            len(part) == _REGION_DIGIT_LENGTH and part.isdigit()
        ):
            head.append(part.upper())
        else:
            # A variant, kept verbatim: `en-US-posix` and `en-US-POSIX` are two
            # locales, measured, so folding case here would merge them.
            head.append(part)
    # Private use sorts last whatever its singleton would suggest, because Java appends it after
    # every other extension.
    # A repeated singleton keeps the **first** section and discards the later one, measured on
    # `en-a-foo-a-bar`, which the jar renders as `en-a-foo`.
    first_of_each: dict[str, list[str]] = {}
    for section in sections:
        first_of_each.setdefault(section[0], section)
    # Private use sorts last whatever its singleton would suggest, because Java appends it after
    # every other extension.
    ordered = [
        part
        for section in sorted(
            (_canonical_section(s) for s in first_of_each.values()),
            key=lambda section: (section[0] == _PRIVATE_USE, section),
        )
        for part in section
    ]
    # `und` is dropped when nothing but private use follows it: `und-x-private` is `x-private`,
    # while `und-US` and a bare `und` keep theirs. Measured.
    if head == [UNDETERMINED] and ordered and ordered[0] == _PRIVATE_USE:
        head = []
    return (*head, *ordered)


def _canonical_section(section: list[str]) -> tuple[str, ...]:
    """One extension section, with its Unicode keywords sorted and attributes de-duplicated.

    The `u` extension holds attributes then key-type keywords, and the Builder keeps the keywords in
    a sorted map, so `en-u-ca-buddhist-nu-thai` and `en-u-nu-thai-ca-buddhist` are one locale.
    Attributes go into a *set*, so `en-u-abc-abc` is `en-u-abc`. Both measured.

    Private use and the other singletons carry ordered subtags and are left as written: `x-b-a` stays
    `x-b-a`, and sorting it made it equal to `x-a-b`, which the jar treats as different.
    """
    singleton, subtags = section[0], section[1:]
    if singleton != "u":
        return tuple(section)
    attributes: list[str] = []
    keywords: list[list[str]] = []
    for subtag in subtags:
        if len(subtag) == _UNICODE_KEY_LENGTH:
            keywords.append([subtag])
        elif keywords:
            keywords[-1].append(subtag)
        elif subtag not in attributes:
            attributes.append(subtag)
    flattened = [part for keyword in sorted(keywords) for part in keyword]
    return (singleton, *sorted(attributes), *flattened)
