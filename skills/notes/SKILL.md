# notes

Read and write text notes. Tier-2 (writes are announced, undoable).

## Permissions

- `fs.read`, `fs.write` — scoped to the notes jail directory only.
  Paths outside the jail (`../`, absolute paths) are denied.

## Evidence

Logs the note path on every write.
