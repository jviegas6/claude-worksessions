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
git fetch --tags && git checkout v1.1.0     # or: git pull, to follow main
./install.sh
```

`bin/` and `shell/` are symlinked/sourced from the repo, so they change as soon as the
checkout does; skills, `CLAUDE.md` and the yazi config are rendered, so they change when
`install.sh` runs.
