# Recovery guide

Use this guide after a recording interruption or application failure. Preserve evidence first;
do not delete, remux, transcode, or overwrite authoritative media while investigating.

1. Stop any active recording safely from the GUI if it is still available. Do not force-stop unless
   safe stop is no longer possible.
2. Record the observed time, worker status, camera connection state, and any UI error. Keep the
   session `session.json`, `events.jsonl`, `recovery.json`, and recorder log with the media.
3. In the Library, inspect the session gaps and validation state. Re-verify a completed segment
   before relying on it. A quarantined or interrupted-unverified item must remain quarantined.
4. If the camera was disconnected, reconnect the same physical device and allow recovery to resolve
   the configured `/dev/v4l/by-id/...-video-index0` identity. Do not replace it with a transient
   `/dev/videoN` path or a different camera without an explicit setup change.
5. If the microphone is unavailable, restore the configured explicit Pulse source. Do not rely on
   the desktop default source.
6. For an archive interruption, leave the source untouched. Reopen the Archive page and use its
   durable queue/recovery state; never publish a partial output as an archive.
7. Under storage pressure, use the storage dashboard and its audit trail. Do not manually delete
   protected, current, partial, quarantined, or interrupted-unverified media to restart capture.
8. If recovery cannot establish a known-good state, preserve the directory and diagnostics and
   report the exact gap/error rather than claiming continuity.

For a package problem, do not uninstall while a recording is active. The package intentionally
preserves user configuration, catalogue, cache, and media on removal; retain those paths for
inspection before reinstalling.
