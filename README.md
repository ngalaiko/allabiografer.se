# allabiografer.se

Cinema programmes across Sweden.
Inspired by [allekinos.de](https://allekinos.de/) by [Nikita Tonsky](https://tonsky.me/).

Tools come from Nix; Python dependencies from `uv.lock`.

```sh
nix run .#run       # fetch, parse, merge, enrich and render (store in R2 when R2_* are set)
nix run .#serve     # serve data/allabiografer/www on :8000
nix run .#pull      # copy the R2 store into data/allabiografer
nix run .#push      # copy data/allabiografer into R2
nix run .#test
nix run .#lint
nix run .#format
nix develop         # shell with uv, Python and Node
```

See [data/allabiografer/README.md](data/allabiografer/README.md) for the registry, pipeline and website.
