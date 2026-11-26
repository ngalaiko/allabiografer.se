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
      tools = pkgs: [
        pkgs.uv
        pkgs.python314
        pkgs.nodejs
        pkgs.git-lfs
      ];
      # uv runs the locked dependencies on Nix's Python; it never downloads its own.
      env = pkgs: {
        UV_PYTHON = "${pkgs.python314}/bin/python3";
        UV_PYTHON_DOWNLOADS = "never";
      };
      task =
        pkgs: name: text:
        pkgs.writeShellApplication {
          inherit name;
          runtimeInputs = tools pkgs;
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
            # Fetch, parse, merge, enrich and render; flags pass through (--cinema, --fresh, --render-only).
            # With R2_BUCKET (and R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY) set, the
            # store is the bucket; otherwise data/allabiografer.
            run = ''uv run --locked --group parse --group build allabiografer "$@"'';
            serve = ''python3 -m http.server "''${1:-8000}" --bind 127.0.0.1 -d data/allabiografer/www'';
            # Mirror R2 and data/allabiografer; deletes what the source lacks, refuses a source without a run.
            pull = ''uv run --locked allabiografer-sync pull "$@"'';
            push = ''uv run --locked allabiografer-sync push "$@"'';
          };
    in
    {
      apps = forAll apps;


      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = tools pkgs;
          env = env pkgs;
          FONTCONFIG_FILE = pkgs.makeFontsConf { fontDirectories = [ pkgs.dejavu_fonts ]; };
        };
      });
    };
}
