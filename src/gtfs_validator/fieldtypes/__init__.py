"""Pure field parsers: string in, value or ParseError out.

No parser constructs a Notice. typing_stage.py owns the mapping from a failed
parse to a notice code, which keeps the FieldType -> code table in one place and
leaves these functions property-testable in isolation.
"""

from gtfs_validator.fieldtypes.scalars import ParseError

__all__ = ["ParseError"]
