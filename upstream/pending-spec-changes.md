# Pending spec changes

GTFS spec changes that have merged into `google/transit` but that MobilityData
have not yet released. Written by the `upstream-watch` skill when
`tools/check_upstream.py` exits 10.

**Nothing here is work.** Parity is with the pinned jar, not with the spec, so a
merged spec change upstream has not implemented is a fact about the future.
Implementing one early would be a deliberate divergence, and divergences belong
in `known-divergences.md` with a measurement, one at a time. An entry leaves this
file when the release that implements it arrives, at which point the pin bump
carries the actual work.

Format, newest first:

```
## <ISO date recorded> - <subject> (transit#<PR>)
Sha: <commit>
Touches: <tables and fields>
Reads as: <new notice code | schema field only | wording only>
```

---

## 2026-09-29 - shapes.txt is conditionally required, recommended otherwise (transit#660)
Sha: 3c9e7b904b5035349622f03e11851e25c16d1d99
Touches: shapes.txt file presence (Optional -> Conditionally Required: required
when a trip has continuous pickup or drop-off defined in routes.txt or
stop_times.txt, recommended otherwise). No field table changes.
Reads as: new notice code

A file-level presence flip in two halves. The "recommended otherwise" half is
mechanical: an `@Recommended` on the table interface lands in
`table_schemas.json` as `presence: RECOMMENDED` through
`tools/sync_upstream_schemas.py`, and `container.py` already reports every such
absent table as `missing_recommended_file`. The "required when continuous"
half needs a validator upstream has not written, reading
`routes.continuous_pickup`, `routes.continuous_drop_off`,
`stop_times.continuous_pickup` and `stop_times.continuous_drop_off` against
`trips.shape_id`. No code in `canonical_notices.json` covers it today, so when
the release arrives it shows up as a new key under `notices`.

## 2026-09-29 - Update language code reference link (transit#658)
Sha: dacd5537c2cb65ef8172226936816b9d77668529
Touches: the "Language code" field-type definition prose (the BCP 47 reference
URL). No table or field.
Reads as: wording only

## 2026-08-25 - min_transfer_time is conditionally required for timed transfers (transit#640)
Sha: 3215f98f26615f1b925dca1bf2205311b747e308
Touches: transfers.txt, min_transfer_time (Optional -> Conditionally Required,
required when transfer_type is 2)
Reads as: schema field only

A presence flip on one field. When the release arrives it lands in
`table_schemas.json` as `presence: CONDITIONALLY_REQUIRED`, which our loader
treats as inert exactly as upstream does: only `REQUIRED` draws
`missing_required_field` (`typing_checks.py`). Enforcing the actual condition
needs a validator upstream has not written, and no code in
`canonical_notices.json` covers it today.

## Baseline

Measured 2026-07-29: every field table in `google/transit@HEAD`
(`gtfs/spec/en/reference.md`, 31 file sections) matches
`src/gtfs_validator/data/table_schemas.json` field for field, including the newest
additions (`trips.safe_duration_factor` and `safe_duration_offset` from
transit#598, `agency.cemv_support` from #545, `stops.stop_access` from #515,
`trips.cars_allowed` from #547). The pin at `v8.0.1` is dated 2026-05-12 and the
last substantive spec change landed 2026-04-22, so the jar had absorbed
everything before we pinned it.

Entries accumulate only between a spec merge and the upstream release that
implements it.
