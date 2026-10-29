{
  description = "Development tools for allabiografer.se";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/da6dc0e7b26060f2f71ce3ef7088fb56ee44fa36";

  outputs =
    { nixpkgs, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
    in
    {
      devShells = nixpkgs.lib.genAttrs systems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              uv
              git-lfs
              mise
              nodejs
              chromium
              openresty
            ];

            NEWSLETTER_LUA_PATH = "${pkgs.luajitPackages.lua-resty-http}/share/lua/5.1/?.lua;${pkgs.luajitPackages.lua-resty-openssl}/share/lua/5.1/?.lua;;";

            # Binary Python wheels (greenlet and curl_cffi) need the C++ runtime.
            LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib ];
            PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH = "${pkgs.chromium}/bin/chromium";
            PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1";
            FONTCONFIG_FILE = pkgs.makeFontsConf {
              fontDirectories = [ pkgs.dejavu_fonts ];
            };
          };
        }
      );
    };
}
