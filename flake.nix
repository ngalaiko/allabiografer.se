{
  description = "allabiografer.se";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/da6dc0e7b26060f2f71ce3ef7088fb56ee44fa36";

  outputs =
    { nixpkgs, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      server =
        pkgs:
        import ./deploy { inherit pkgs; }
        // {
          # The image for another platform, e.g. Fly's x86_64-linux from a Mac.
          imageFor = system: (import ./deploy { pkgs = nixpkgs.legacyPackages.${system}; }).image;
        };
      # What every task needs; `tools` adds the server and deploy tools.
      python = pkgs: [
        pkgs.uv
        pkgs.python314
      ];
      tools =
        pkgs:
        python pkgs
        ++ [
          pkgs.nodejs
          pkgs.git-lfs
          # The production nginx, for the server and newsletter API tests.
          (server pkgs).openresty
          pkgs.crane
          pkgs.flyctl
          pkgs.gnutar
          pkgs.gzip
        ];
      # Pele renders the trace diagrams to SVG: https://pele.run
      pele =
        pkgs:
        pkgs.fetchzip {
          url = "https://registry.npmjs.org/pele/-/pele-1.13.0.tgz";
          hash = "sha256-1mxtui9HY6TO5Sdpt+DtoTf/O7q8rvcba76Ifg1txBs=";
        };
      # uv runs the locked dependencies on Nix's Python; it never downloads its own.
      env = pkgs: {
        PELE = "${pele pkgs}/dist/pele.js";
        UV_PYTHON = "${pkgs.python314}/bin/python3";
        UV_PYTHON_DOWNLOADS = "never";
        NEWSLETTER_LUA_PATH = "${pkgs.luajitPackages.lua-resty-http}/share/lua/5.1/?.lua;;";
      };
      # Tasks that only run Python (lint, format) skip the server's build.
      light = [
        "lint"
        "format"
      ];
      task =
        pkgs: name: text:
        pkgs.writeShellApplication {
          inherit name;
          runtimeInputs = if builtins.elem name light then python pkgs else tools pkgs;
          runtimeEnv = env pkgs;
          text = ''
            export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
            ${text}
          '';
        };
      apps =
        pkgs:
        builtins.mapAttrs
          (name: text: {
            type = "app";
            program = "${task pkgs name text}/bin/${name}";
          })
          {
            lint = ''uv run --locked --group dev ruff check src tests "$@"'';
            format = ''uv run --locked --group dev ruff format src tests "$@"'';
            test = ''
              uv run --locked --group dev --group parse --group build pytest "$@"
              node --test tests/allabiografer/site/*.test.cjs
            '';
            # Download, read, look up and build the programme, then render it, against data/allabiografer.
            # Flags pass through (--cinema, --fresh, --render-only); --production, the R2 store, runs in CI only.
            run = ''uv run --locked --group parse --group build allabiografer "$@"'';
            # Check the rendered site: published pages resolve, redirects land, links lead somewhere.
            check-site = ''uv run --locked allabiografer-check-site "$@"'';
            # Draw a run, a step (--step) or a film's sources (--film) from the local store as SVG; --open shows it.
            trace = ''uv run --locked allabiografer-trace "$@"'';
            # Adapter fixtures: save <adapter> from the local store, update its rows, or diff the reader.
            fixture = ''uv run --locked --group parse allabiografer-fixture "$@"'';
            # The weekly newsletter: previews, or with --send, PostHog batches (POSTHOG_* variables).
            newsletter = ''uv run --locked allabiografer-newsletter "$@"'';
            serve = ''python3 -m http.server "''${1:-8000}" --bind 127.0.0.1 -d data/allabiografer/www'';
            # Push the server image with data/allabiografer/www as a layer, then deploy it to Fly
            # (FLY_API_TOKEN; FLY_APP, default allabiografer-se). The image is built for Fly's x86_64.
            deploy = ''
              site=$(realpath "''${1:-data/allabiografer/www}")
              [[ -f "$site/index.html" ]] || { echo "No rendered site at $site" >&2; exit 1; }
              app="''${FLY_APP:-allabiografer-se}"
              tag="registry.fly.io/$app:$(date -u +%Y%m%d%H%M%S)"
              work=$(mktemp -d)
              trap 'rm -rf "$work"' EXIT
              # The site layer: /srv/www, readable by the server's user.
              tar -C "$site" --transform 's,^\.,srv/www,' --owner=0 --group=0 --mode=a+rX \
                --sort=name --mtime=@0 -cf "$work/www.tar" .
              # Credentials stay in this process: a throwaway config, not ~/.docker.
              export DOCKER_CONFIG="$work/docker"
              crane auth login registry.fly.io -u x -p "$FLY_API_TOKEN"
              gzip -dc ${(server pkgs).imageFor "x86_64-linux"} > "$work/server.tar"
              crane push "$work/server.tar" "$tag.base"
              crane append --base "$tag.base" --new_layer "$work/www.tar" --new_tag "$tag"
              flyctl deploy --app "$app" --image "$tag" --ha=false --yes
            '';
            # The production nginx, newsletter API included, on data/allabiografer/www at :8080.
            nginx = ''
              SITE_ROOT=$(realpath "''${1:-data/allabiografer/www}") exec ${(server pkgs).serve}/bin/allabiografer-serve
            '';
            # Copy the production store into data/allabiografer, deleting what production lacks.
            # Credentials from R2_* variables, else ~/.config/allabiografer/r2.env.
            pull = ''
              if [[ -z "''${R2_BUCKET:-}" && -f "$HOME/.config/allabiografer/r2.env" ]]; then
                set -a
                # shellcheck disable=SC1091
                . "$HOME/.config/allabiografer/r2.env"
                set +a
              fi
              uv run --locked allabiografer-pull "$@"
            '';
          };
    in
    {
      apps = forAll apps;

      # The production server image, without the site: CI adds the rendered site as a layer.
      packages = forAll (pkgs: {
        image = (server pkgs).image;
        default = (server pkgs).image;
      });

      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = tools pkgs;
          env = env pkgs;
          FONTCONFIG_FILE = pkgs.makeFontsConf { fontDirectories = [ pkgs.dejavu_fonts ]; };
        };
      });
    };
}
