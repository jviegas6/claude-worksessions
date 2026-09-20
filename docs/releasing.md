# Releasing

Versions follow [semver](https://semver.org): **major** when an upgrade needs you to do
something (config key renamed, folder layout changed), **minor** for new features,
**patch** for fixes.

1. Update `VERSION` and add a section to `CHANGELOG.md`.
2. Commit, tag, push, release:
   ```sh
   v=$(cat VERSION)
   git commit -am "Release v$v"
   git tag -a "v$v" -m "v$v"
   git push origin main "v$v"
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
