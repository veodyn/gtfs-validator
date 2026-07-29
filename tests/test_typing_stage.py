from gtfs_validator.notices import Notice, NoticeContainer, Severity
from gtfs_validator.schema import Field, FieldType, Presence, TableSchema
from gtfs_validator.typing_stage import type_row


def schema_with(*fields, filename="test.txt", primary_key=()):
    return TableSchema(filename, Presence.OPTIONAL, primary_key, fields)


def codes(notices):
    return [n.code for g in notices.grouped().values() for n in g]


def only(notices, code):
    return next(n for g in notices.grouped().values() for n in g if n.code == code)


def test_parse_failure_reports_and_excludes_the_row():
    # CsvFileLoader excludes a row that produced an ERROR-severity notice: it is
    # not stored, indexed, or entity-validated. type_row signals that by returning
    # None. The parse notice still fires.
    schema = schema_with(Field("when", FieldType.DATE, Presence.OPTIONAL))
    notices = NoticeContainer()
    typed = type_row(schema, {"_row_number": 2, "when": "nonsense"}, notices)
    assert typed is None
    assert codes(notices) == ["invalid_date"]


def test_clean_row_is_returned_for_storage():
    schema = schema_with(Field("when", FieldType.DATE, Presence.OPTIONAL))
    notices = NoticeContainer()
    typed = type_row(schema, {"_row_number": 2, "when": "20260130"}, notices)
    assert typed == {"_row_number": 2, "when": (2026, 1, 30)}
    assert codes(notices) == []


def test_parse_failure_context_carries_the_raw_value():
    schema = schema_with(Field("colour", FieldType.COLOR, Presence.OPTIONAL))
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 7, "colour": "ZZZ"}, notices)
    assert only(notices, "invalid_color").context == {
        "filename": "test.txt",
        "csvRowNumber": 7,
        "fieldName": "colour",
        "fieldValue": "ZZZ",
    }


def test_missing_required_field_excludes_the_row():
    # missing_required_field is ERROR, so the row is excluded like any other
    # error row.
    schema = schema_with(Field("stop_id", FieldType.ID, Presence.REQUIRED))
    notices = NoticeContainer()
    typed = type_row(schema, {"_row_number": 5, "stop_id": ""}, notices)
    assert typed is None
    assert codes(notices) == ["missing_required_field"]


def test_missing_recommended_field_is_a_warning():
    schema = schema_with(Field("note", FieldType.TEXT, Presence.RECOMMENDED))
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 5, "note": ""}, notices)
    assert codes(notices) == ["missing_recommended_field"]


def test_an_absent_column_is_not_a_missing_field_on_every_row():
    # Measured against the jar: a required column missing from the header draws
    # missing_required_column once in stage 2 and nothing here. Upstream's loader
    # never asks for a column it could not find, so reporting per row would
    # inflate the count by the length of the table.
    schema = schema_with(Field("stop_id", FieldType.ID, Presence.REQUIRED))
    notices = NoticeContainer()
    typed = type_row(schema, {"_row_number": 2}, notices)
    assert codes(notices) == []
    assert typed["stop_id"] is None


def test_conditionally_required_does_not_fire_missing_required():
    # @ConditionallyRequired is a marker upstream; the condition is a named rule.
    schema = schema_with(Field("stop_id", FieldType.ID, Presence.CONDITIONALLY_REQUIRED))
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 5, "stop_id": ""}, notices)
    assert codes(notices) == []


def test_enum_out_of_range_folds_to_unrecognized():
    # A WARNING, so the row survives, but the stored value is the enum's
    # UNRECOGNIZED number rather than the raw integer: upstream stores the enum,
    # and EnumGenerator gives UNRECOGNIZED min(values) - 1. The notice still
    # reports the raw value. Measured: a calendar monday of 2 folds to -1, and
    # weeklyPatternFromMTWTFSS masks with 1, so -1 sets the bit that 2 clears and
    # the jar expands the service and reports expired_calendar for it.
    schema = schema_with(
        Field("route_type", FieldType.ENUM, Presence.OPTIONAL, enum_values=(0, 1, 2, 3))
    )
    notices = NoticeContainer()
    typed = type_row(schema, {"_row_number": 2, "route_type": "99"}, notices)
    assert codes(notices) == ["unexpected_enum_value"]
    assert (
        notices.grouped()[Notice("unexpected_enum_value", Severity.WARNING).mapping_key][0].context[
            "fieldValue"
        ]
        == 99
    )
    assert typed["route_type"] == -1


def test_unrecognized_is_minus_one_even_for_an_enum_starting_at_one():
    # getMinUnrecognizedValue initialises its accumulator to zero and then takes
    # the minimum against each declared value, so it is min(0, *values) - 1. For
    # every GTFS enum, whose values are non-negative, that is -1. An earlier
    # reading of this dropped the zero and folded exception_type to 0.
    schema = schema_with(
        Field("exception_type", FieldType.ENUM, Presence.OPTIONAL, enum_values=(1, 2))
    )
    notices = NoticeContainer()
    typed = type_row(schema, {"_row_number": 2, "exception_type": "7"}, notices)
    assert typed["exception_type"] == -1


def test_enum_that_is_not_an_integer_is_a_parse_failure():
    schema = schema_with(Field("route_type", FieldType.ENUM, Presence.OPTIONAL, enum_values=(0, 1)))
    notices = NoticeContainer()
    typed = type_row(schema, {"_row_number": 2, "route_type": "bus"}, notices)
    assert codes(notices) == ["invalid_integer"]
    assert typed is None


def test_latitude_out_of_range_reports_and_excludes_the_row():
    # number_out_of_range is emitted while loading the field, so it is an ERROR
    # in the row's notices and the row is excluded, matching asLatitude.
    schema = schema_with(Field("stop_lat", FieldType.LATITUDE, Presence.OPTIONAL))
    notices = NoticeContainer()
    typed = type_row(schema, {"_row_number": 2, "stop_lat": "91.0"}, notices)
    assert only(notices, "number_out_of_range").context["fieldType"] == (
        "latitude within [-90, 90]"
    )
    assert typed is None


def test_bounds_are_reported_with_upstreams_wording():
    schema = schema_with(
        Field("count", FieldType.INTEGER, Presence.OPTIONAL, bounds="NON_NEGATIVE")
    )
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 2, "count": "-1"}, notices)
    assert only(notices, "number_out_of_range").context["fieldType"] == ("non-negative integer")


def test_non_ascii_uses_columnname_not_fieldname():
    # The canonical context for this one notice keys the column as columnName.
    schema = schema_with(Field("stop_id", FieldType.ID, Presence.OPTIONAL))
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 2, "stop_id": "café"}, notices)
    context = only(notices, "non_ascii_or_non_printable_char").context
    assert context["columnName"] == "stop_id"
    assert "fieldName" not in context


def test_replacement_character_is_an_error():
    # The canonical manifest defines invalid_character as ERROR, not WARNING.
    schema = schema_with(Field("stop_name", FieldType.TEXT, Presence.OPTIONAL))
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 2, "stop_name": "Caf�"}, notices)
    notice = only(notices, "invalid_character")
    assert notice.severity is Severity.ERROR


def test_whitespace_notice_only_fires_for_declared_columns():
    # Regression against plan 1, which fired this for every column in the file.
    # Upstream calls the field validator only for columns the schema declares.
    schema = schema_with(Field("stop_id", FieldType.ID, Presence.OPTIONAL))
    notices = NoticeContainer()
    typed = type_row(schema, {"_row_number": 2, "stop_id": " S1 ", "extra_col": " x "}, notices)
    assert codes(notices) == ["leading_or_trailing_whitespaces"]
    assert typed["stop_id"] == "S1"


def test_newline_in_value_is_reported():
    schema = schema_with(Field("stop_name", FieldType.TEXT, Presence.OPTIONAL))
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 2, "stop_name": "a\nb"}, notices)
    assert "new_line_in_value" in codes(notices)


def test_mixed_case_fires_on_all_lowercase_multiword_values():
    schema = schema_with(Field("stop_name", FieldType.TEXT, Presence.OPTIONAL, mixed_case=True))
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 2, "stop_name": "main street station"}, notices)
    assert codes(notices) == ["mixed_case_recommended_field"]


def test_mixed_case_fires_on_a_single_lowercase_word():
    schema = schema_with(Field("stop_name", FieldType.TEXT, Presence.OPTIONAL, mixed_case=True))
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 2, "stop_name": "station"}, notices)
    assert codes(notices) == ["mixed_case_recommended_field"]


def test_mixed_case_stays_quiet_on_a_properly_cased_value():
    schema = schema_with(Field("stop_name", FieldType.TEXT, Presence.OPTIONAL, mixed_case=True))
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 2, "stop_name": "Main Street Station"}, notices)
    assert codes(notices) == []


def test_mixed_case_ignores_tokens_with_digits_and_single_letters():
    # Upstream skips tokens of length 1 or containing a digit, then requires at
    # least two surviving tokens before it can complain.
    schema = schema_with(Field("stop_name", FieldType.TEXT, Presence.OPTIONAL, mixed_case=True))
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 2, "stop_name": "A 42 st"}, notices)
    assert codes(notices) == []


def test_range_notice_renders_times_and_carries_entity_id():
    schema = schema_with(
        Field("id", FieldType.ID, Presence.REQUIRED),
        Field("start", FieldType.TIME, Presence.OPTIONAL, end_range=("end", False)),
        Field("end", FieldType.TIME, Presence.OPTIONAL),
        primary_key=("id",),
    )
    notices = NoticeContainer()
    type_row(
        schema,
        {"_row_number": 2, "id": "A", "start": "25:30:00", "end": "09:00:00"},
        notices,
    )
    context = only(notices, "start_and_end_range_out_of_order").context
    # entityId is the single-column primary key; values render via the Java
    # type's toString, so a stored seconds count comes back as HH:MM:SS.
    assert context["entityId"] == "A"
    assert context["startValue"] == "25:30:00"
    assert context["endValue"] == "09:00:00"


def test_range_notice_on_composite_key_table_omits_entity_id():
    schema = schema_with(
        Field("a", FieldType.ID, Presence.REQUIRED),
        Field("b", FieldType.INTEGER, Presence.REQUIRED),
        Field("start", FieldType.TIME, Presence.OPTIONAL, end_range=("end", False)),
        Field("end", FieldType.TIME, Presence.OPTIONAL),
        primary_key=("a", "b"),
    )
    notices = NoticeContainer()
    type_row(
        schema,
        {"_row_number": 2, "a": "X", "b": "1", "start": "10:00:00", "end": "09:00:00"},
        notices,
    )
    assert "entityId" not in only(notices, "start_and_end_range_out_of_order").context


def test_range_equal_uses_the_rendered_value():
    schema = schema_with(
        Field("start", FieldType.TIME, Presence.OPTIONAL, end_range=("end", False)),
        Field("end", FieldType.TIME, Presence.OPTIONAL),
    )
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 3, "start": "10:00:00", "end": "10:00:00"}, notices)
    context = only(notices, "start_and_end_range_equal").context
    assert context["value"] == "10:00:00"


def test_equal_range_is_silent_when_allow_equal_is_set():
    schema = schema_with(
        Field("start", FieldType.TIME, Presence.OPTIONAL, end_range=("end", True)),
        Field("end", FieldType.TIME, Presence.OPTIONAL),
    )
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 2, "start": "10:00:00", "end": "10:00:00"}, notices)
    assert codes(notices) == []


def test_url_and_email_and_timezone_reach_their_notices():
    schema = schema_with(
        Field("site", FieldType.URL, Presence.OPTIONAL),
        Field("mail", FieldType.EMAIL, Presence.OPTIONAL),
        Field("tz", FieldType.TIMEZONE, Presence.OPTIONAL),
    )
    notices = NoticeContainer()
    type_row(
        schema,
        {"_row_number": 2, "site": "not-a-url", "mail": "nope", "tz": "Mars/Olympus"},
        notices,
    )
    assert set(codes(notices)) == {"invalid_url", "invalid_email", "invalid_timezone"}


def test_phone_is_silent_without_a_country_code():
    schema = schema_with(Field("phone", FieldType.PHONE_NUMBER, Presence.OPTIONAL))
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 2, "phone": "123"}, notices)
    assert codes(notices) == []


def test_phone_fires_once_a_country_code_is_supplied():
    schema = schema_with(Field("phone", FieldType.PHONE_NUMBER, Presence.OPTIONAL))
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 2, "phone": "123"}, notices, country_code="US")
    assert codes(notices) == ["invalid_phone_number"]


def test_mixed_case_measures_a_token_in_utf16_units():
    # "Longer than a character" is String.length(), so a single astral lowercase
    # letter is two units and is considered rather than skipped. Measured: the jar
    # reports mixed_case_recommended_field for a route_desc of one Deseret small
    # letter, which len() sees as one character.
    from gtfs_validator.typing_checks import is_mixed_case

    deseret_small = "\U00010428"
    assert not is_mixed_case(deseret_small)
    assert is_mixed_case("a")


def test_mixed_case_fires_when_a_value_starts_with_digits():
    """Measured on real feeds: the jar reports `33DP`, `172CS` and `110ATH` as route_short_name.

    Upstream splits with `value.split("[^\\p{L}]+")`, and digits are non-letters, so a value
    beginning with them yields a **leading empty token** that Java's split keeps. The empty token is
    not of length 1 and holds no digit, so it counts toward `noNumberTokensCount`, which reaches two
    on a single all-caps word and reports. Reading the tokens as "runs of letters" instead loses that
    token and misses the notice on eight of the fifty feeds in the real corpus.
    """
    schema = schema_with(Field("name", FieldType.TEXT, Presence.OPTIONAL, mixed_case=True))
    for value in ("33DP", "172CS", "110ATH"):
        notices = NoticeContainer()
        type_row(schema, {"_row_number": 2, "name": value}, notices)
        assert codes(notices) == ["mixed_case_recommended_field"], value


def test_mixed_case_counts_the_empty_token_before_a_digit_run():
    """Measured on `913-CI`: the jar reports the stop_name `43e BIMA`.

    Tokens are `["", "e", "BIMA"]`. The single-letter `e` is skipped, so only the empty token and
    `BIMA` count, and two is enough. Requiring tokens longer than one character would leave the count
    at one and stay silent.
    """
    schema = schema_with(Field("name", FieldType.TEXT, Presence.OPTIONAL, mixed_case=True))
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 2, "name": "43e BIMA"}, notices)
    assert codes(notices) == ["mixed_case_recommended_field"]


def test_mixed_case_stays_quiet_when_a_digit_run_precedes_a_mixed_case_word():
    """The negative that keeps the fix honest: one properly cased word is still enough.

    `33Dp` tokens are `["", "Dp"]`, so the count reaches two, but `Dp` mixes cases and
    `hasMixedCaseToken` suppresses the notice.
    """
    schema = schema_with(Field("name", FieldType.TEXT, Presence.OPTIONAL, mixed_case=True))
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 2, "name": "33Dp"}, notices)
    assert codes(notices) == []


def test_mixed_case_stays_quiet_on_a_value_that_is_only_digits():
    """`"123".split("[^\\p{L}]+")` is an empty array in Java, not `[""]`, so nothing is counted."""
    schema = schema_with(Field("name", FieldType.TEXT, Presence.OPTIONAL, mixed_case=True))
    notices = NoticeContainer()
    type_row(schema, {"_row_number": 2, "name": "123"}, notices)
    assert codes(notices) == []
