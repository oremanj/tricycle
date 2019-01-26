At least at this early stage in its life, `tricycle` is pretty much "oremanj's bikeshed
of interesting-but-maybe-not-fully-proven Trio ideas". PRs fixing bugs, extending
existing code to be more robust or complete, and/or improving documentation are very welcome,
but if you want to contribute a largish new feature, please raise it on the issue tracker
first so I have a chance to think about whether I want to take on the maintenance
burden or not.

We mostly follow the Trio contributing guide:
    https://trio.readthedocs.io/en/latest/contributing.html
but (this being largely a personal project) contributors will not automatically get commit
bits, and we're trying out some alternative tooling (code formatting with `black` and
enforced static type checking to pass `mypy --strict`) compared to the mainline Trio
projects. `tricycle` anticipates moving to live under the python-trio Github organization
once its scope has stabilized a bit, at which point it will stop being so much of a special
snowflake.
