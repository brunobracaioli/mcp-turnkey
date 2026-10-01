# Why a living template

A template that does not run is not tested, and an untested template drifts away from
what works in production. Servers started by cloning each other prove the point: every
fix found later (405 on GET, 503 on backend failures, httpx logging tokens) spreads
unevenly, if at all.

Here the template is a real server, with an example slice (`items`) against a fictional
API and close to 200 tests covering the full OAuth flow, the consent screen, tenant
isolation and the hardening baseline. The scaffold only renames — it generates no code —
so everything the new project contains has already passed this repository's CI.

The cost is that the template contains a fake domain that must be replaced; the
`SCAFFOLD:` markers and the generated spec make explicit what to swap.

## Why not a framework or a shared library?

A library would let every server pick up fixes with a version bump, but it couples all of
them to one release cycle and hides the OAuth and storage code behind an API you cannot
easily change. The generated server owns all of its code: you can read it, change it and
deploy it on its own schedule. The trade-off is that porting later template improvements
is manual — which is why the lessons are written down in
[`production-lessons.md`](production-lessons.md).
