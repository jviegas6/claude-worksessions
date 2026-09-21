# Releasing

Versions follow [semver](https://semver.org): **major** when an upgrade needs you to do
something (config key renamed, folder layout changed), **minor** for new features,
**patch** for fixes.

Nothing is pushed to `main` directly — every change, releases included, goes through a
pull request, and the `tests` workflow must pass (it fails if coverage of `bin/` drops
below 95%).

1. On a branch, update `VERSION` and add a section to `CHANGELOG.md` alongside the change.
2. Run the tests, push the branch and open a pull request:
   ```sh
   .venv/bin/pytest                 # python3 -m venv .venv && .venv/bin/pip install pytest pytest-cov
   git push -u origin HEAD
   gh pr create --fill
   ```
3. Once it is merged, tag the merge commit and release it:
   ```sh
   git switch main && git pull
   v=$(cat VERSION)
   git tag -a "v$v" -m "v$v"
   git push origin "v$v"
   gh release create "v$v" --title "v$v" --notes-file <(awk "/^## \\[$v\\]/{f=1;next} /^## \\[/{f=0} f" CHANGELOG.md)
   ```

Upgrading an installed copy:

```sh
cd ~/Repos/claude-worksessions
./install.sh --update           # newest release, then re-install
./install.sh --update v1.1.0    # a specific release (this is also how you roll back)
./install.sh --edge             # follow main instead of the releases
```

`--update` fetches, refuses to move if the checkout has local changes, checks out the
target, prints the changelog entries you gained, and then runs the normal install so the
skills, `CLAUDE.md` and the yazi files are re-rendered. It never touches `_config/`, your
work folders, the profiles or their history. A normal run prints a one-line notice when
a newer release exists (it fetches at most once a day).

`bin/` and `shell/` are symlinked/sourced from the repo, so they change as soon as the
checkout does; skills, `CLAUDE.md` and the yazi config are rendered, so they change when
`install.sh` runs.
