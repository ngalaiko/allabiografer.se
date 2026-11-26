# allabiografer.se

Cinema programmes across Sweden.
Inspired by [allekinos.de](https://allekinos.de/) by [Nikita Tonsky](https://tonsky.me/).

Tools come from Nix; Python dependencies from `uv.lock`.

```sh
nix run .#run       # fetch, parse, merge, enrich and render (store in R2 when R2_* are set)
nix run .#serve     # serve data/allabiografer/www on :8000
nix run .#pull      # copy the R2 store into data/allabiografer
nix run .#push      # copy data/allabiografer into R2
nix run .#newsletter # prepare (or --send) the weekly city editions
nix run .#nginx     # the production server on data/allabiografer/www, :8080
nix run .#deploy    # push the image with the rendered site to Fly (FLY_API_TOKEN)
nix run .#test
nix run .#lint
nix run .#format
nix develop         # shell with uv, Python and Node
```

See [data/allabiografer/README.md](data/allabiografer/README.md) for the registry, pipeline and website.

## Production

- **Store:** the Cloudflare R2 bucket `allabiografer-store` (EU jurisdiction). Pipeline runs read and write it directly.
- **Server:** a Nix-built OpenResty image (`deploy/`) serving `/srv/www` and the newsletter API; Fly app `allabiografer-se`.
- **CI** (`.github/workflows/`):
  - `ci.yml` lints, tests and builds the image;
  - `run.yml` runs the pipeline daily (and re-renders on push) and deploys the site;
  - `newsletter.yml` sends Thursday editions; `newsletter-test.yml` sends one test.
- **Secrets:** `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `TMDB_ACCESS_TOKEN`, `FLY_API_TOKEN`, `POSTHOG_PERSONAL_API_KEY`. **Variables:** `R2_BUCKET`, `R2_JURISDICTION`, `POSTHOG_PROJECT_TOKEN`, `POSTHOG_PROJECT_ID`, `POSTHOG_NEWSLETTER_WORKFLOW`, `POSTHOG_NEWSLETTER_TEST_WORKFLOW`, `NEWSLETTER_ENABLED`.
