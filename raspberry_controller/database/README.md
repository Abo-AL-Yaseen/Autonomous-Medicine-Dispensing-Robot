This SQLite schema and `hospital.db` belong to the legacy Raspberry mission and
navigation implementation. They remain in place for compatibility and are not
the source of truth for scheduled missions.

The RTC-driven `MissionScheduler` and software-only `MissionExecutor` must use
Laravel over HTTP. They must not query this database or copy Laravel mission
records into it.
