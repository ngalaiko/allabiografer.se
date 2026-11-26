# allabiografer.se

Cinema programmes across Sweden.
Inspired by [allekinos.de](https://allekinos.de/) by [Nikita Tonsky](https://tonsky.me/).

Tools come from Nix; Python dependencies from `uv.lock`.

```sh
nix run .#run       # fetch, parse, merge, enrich and render
nix run .#serve     # serve data/allabiografer/www on :8000
nix run .#test
nix run .#lint
nix run .#format
nix develop         # shell with uv, Python and Node
```

See [data/allabiografer/README.md](data/allabiografer/README.md) for the registry, pipeline and website.
