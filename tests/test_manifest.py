import pytest

from gtfs_validator.loading import RECOMMENDED_COLUMNS
from gtfs_validator.manifest import IMPLEMENTED, UNREACHABLE, load_manifest
from gtfs_validator.notices import Severity


def test_manifest_carries_the_full_upstream_surface():
    """Every upstream code is either implemented or exempted, and the failure names which.

    This was `len(codes) == 176`, which on a pin bump fails with "177 != 176": red,
    but silent about what arrived. Set equality turns the same red build into the
    change list, which is what tools/check_upstream.py hands off to.
    """
    manifest = load_manifest()
    accounted = IMPLEMENTED | set(UNREACHABLE)
    assert manifest.codes - accounted == set(), (
        f"upstream codes neither implemented nor exempted: {sorted(manifest.codes - accounted)}"
    )
    assert accounted - manifest.codes == set(), (
        f"codes we account for that upstream no longer has: {sorted(accounted - manifest.codes)}"
    )
    assert manifest.meta["tag"] == "v8.0.1"


def test_every_implemented_code_exists_upstream():
    manifest = load_manifest()
    unknown = IMPLEMENTED - manifest.codes
    assert unknown == set(), f"codes not in upstream manifest: {sorted(unknown)}"


def test_severities_match_upstream():
    manifest = load_manifest()
    assert manifest.severity_of("empty_file") is Severity.ERROR
    assert manifest.severity_of("unknown_file") is Severity.INFO
    assert manifest.severity_of("empty_row") is Severity.WARNING


def test_context_fields_are_available():
    manifest = load_manifest()
    assert manifest.context_fields_of("invalid_row_length") == {
        "filename": "string",
        "csvRowNumber": "integer",
        "rowLength": "integer",
        "headerCount": "integer",
    }


def test_unknown_code_raises():
    with pytest.raises(KeyError):
        load_manifest().severity_of("no_such_notice")


def test_the_pipeline_wires_no_recommended_columns():
    """`missing_recommended_column` is deprecated upstream and constructed nowhere, so
    the moment this map gains an entry we emit a notice the jar cannot. The emitter in
    csvparse stays, mirroring upstream's declared-but-dead class; this is the wiring
    that keeps it unreachable.
    """
    assert RECOMMENDED_COLUMNS == {}
