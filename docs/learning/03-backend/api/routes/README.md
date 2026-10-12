# One lesson per route module

`backend/api/routes/` has nine modules. Each lesson below says what the module does, shows the request and the
response of every route in it with calls that were really made on 2026-10-12, then how to change it safely and what
breaks if you get it wrong. Read [the API README](../README.md) first for the rules they all share.

| Module | Lesson | In one line |
|---|---|---|
| `sources.py` | [sources](sources.md) | import a picture, list, read and serve it, recycle, restore, delete for good |
| `processing.py` | [processing](processing.md) | ask for a picture to be processed, watch the run, cancel it, retry it |
| `jobs.py` | [jobs](jobs.md) | the scheduling view of the same work |
| `memory.py` | [memory](memory.md) | read-only views of identities and the faces in a picture or identity |
| `people.py` | [people](people.md) | name an identity, rename, link and unlink, forget a person |
| `corrections.py` | [corrections](corrections.md) | confirm, move or separate a face; place the faces recognition declined |
| `identity_changes.py` | [identity changes](identity-changes.md) | merge identities, split faces off, forget an identity |
| `search.py` | [search](search.md) | find people, identities, pictures and appearances by name |
| `face_search.py` | [face search](face-search.md) | search the memory with a picture, saving nothing |

The shape of every lesson is the same:

1. what the module does and why; 2. where it lives (the use cases it calls); 3. the routes, with request and
response; 4. **Try it** (verified calls); 5. **Change it** (a mutation that a named test catches); 6. **Break it on
purpose** (the errors you get); 7. exercises with answers; 8. related files.

To call the examples you need a running backend with a few processed pictures:
[start-here 07](../../../00-start-here/07-run-it-and-see-it-work.md) and [call the API](../01-call-the-api.md) set up
the shell variables `$B` (the base URL), `$H` (the auth header), `$J` (the JSON content type) and the helper `j`
that the commands use.

Back to the [API README](../README.md).
