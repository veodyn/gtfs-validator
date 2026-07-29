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

Empty as of 2026-07-29.

Measured that day: every field table in `google/transit@HEAD`
(`gtfs/spec/en/reference.md`, 31 file sections) matches
`src/gtfs_validator/data/table_schemas.json` field for field, including the newest
additions (`trips.safe_duration_factor` and `safe_duration_offset` from
transit#598, `agency.cemv_support` from #545, `stops.stop_access` from #515,
`trips.cars_allowed` from #547). The pin at `v8.0.1` is dated 2026-05-12 and the
last substantive spec change landed 2026-04-22, so the jar had absorbed
everything before we pinned it.

The empty state is the expected one. Entries accumulate only between a spec
merge and the upstream release that implements it.
