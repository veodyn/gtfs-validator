"""FareProductDefaultRiderCategoriesValidator: one product, two default riders.

A fare product priced for two categories that both claim to be the default has no default. The
notice names a **pair** even when there are more: measured on a product with three defaults, where
the jar reports one notice naming the first two in file order.

Three things that do not count, all measured: the same default category listed twice for one product,
because the check is on distinct categories; a category that exists but is not marked default; and a
category whose id appears twice in rider_categories.txt where the **first** row is not the default,
because the index upstream reads keeps the first row.

Gated on rider_categories.txt existing, which is upstream's `shouldCallValidate`.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.javahash import hashmap_order
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import file_rule

CODE = "fare_product_with_multiple_default_rider_categories"
FARE_PRODUCTS = "fare_products.txt"
RIDER_CATEGORIES = "rider_categories.txt"

# GtfsRiderFareCategory.IS_DEFAULT.
IS_DEFAULT = 1
# The notice has room for two, so a third default changes nothing.
PAIR = 2


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    if feed.is_missing(RIDER_CATEGORIES) or feed.dependency_failed(RIDER_CATEGORIES):
        return
    # First row wins for a duplicate rider_category_id, as upstream's single-key index does: a
    # category listed first as non-default and then as default is **not** a default. Collecting
    # every row marked default reported a product the jar accepts, measured.
    categories: dict[str, object] = {}
    for row in feed.rows(RIDER_CATEGORIES):
        category_id = row.get("rider_category_id")
        if category_id is not None:
            categories.setdefault(category_id, row.get("is_default_fare_category"))
    defaults = {category_id for category_id, flag in categories.items() if flag == IS_DEFAULT}
    if not defaults:
        return

    # Per product, the distinct default categories in file order and the row that introduced each.
    found: dict[str, list[tuple[str, int]]] = {}
    for row in feed.rows(FARE_PRODUCTS):
        product_id = row.get("fare_product_id")
        category_id = row.get("rider_category_id")
        if product_id is None or category_id not in defaults:
            continue
        seen = found.setdefault(product_id, [])
        if any(category == category_id for category, _ in seen):
            continue
        seen.append((category_id, row["_row_number"]))

    # HashMap order over the fare product ids: upstream accumulates into HashMaps keyed by product,
    # and above the 1,000-sample cap the order decides which notices survive. Measured on a
    # 1,005-product feed, where file order kept five samples the jar does not.
    for product_id in hashmap_order(found):
        seen = found[product_id]
        if len(seen) < PAIR:
            continue
        (first_category, first_row), (second_category, second_row) = seen[:PAIR]
        yield Notice(
            CODE,
            Severity.ERROR,
            {
                "fareProductId": product_id,
                "csvRowNumber1": first_row,
                "riderCategoryId1": first_category,
                "csvRowNumber2": second_row,
                "riderCategoryId2": second_category,
            },
        )
