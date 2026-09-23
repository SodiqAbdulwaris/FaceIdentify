| Failure | Consequence |
|---|---|
| App force-killed | Resume from committed checkpoint |
| Windows/power loss | Same recovery path |
| GPU OOM | Adapt batch/resources → retry |
| RAM pressure | Shrink queues/prefetch, throttle background |
| Disk low/full | Safely pause storage-producing jobs |
| Decoder error | Retry/skip/fail according to source error |
| DB write fails | Work unit not committed |
| Face crop missing | Regenerate if valid source survives |
| Thumbnail missing | Regenerate |
| Original media missing unexpectedly | Source integrity failure |
| Qdrant unavailable | Authoritative memory survives; visual retrieval degraded |
| Qdrant corrupted | Rebuild |
| Stale Qdrant metadata | Authoritative resolution corrects/filters |
| Training crash | Production model unaffected |
| Candidate evaluation fails | Candidate not promoted |
| Rebuild crash | Existing active version remains usable |
| Merge/split crash after DB commit | Authoritative state survives; derived state rebuilt |
| Forget cleanup interrupted | Forgotten Person remains logically unavailable |
| Permanent-delete cleanup interrupted | Deleted evidence remains logically invalid |