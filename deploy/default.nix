# The production server: OpenResty (nginx with Lua) serving the rendered site from
# /srv/www (SITE_ROOT locally) and the newsletter API. `image` is the server alone; the
# site is added as a layer when deploying, so a render ships without a Nix rebuild.
{ pkgs }:
let
  openresty = pkgs.openresty.overrideAttrs (old: {
    configureFlags = (old.configureFlags or [ ]) ++ [ "--add-module=${pkgs.nginxModules.brotli.src}" ];
    buildInputs = (old.buildInputs or [ ]) ++ [ pkgs.brotli ];
  });
  cacert = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";

  conf = pkgs.runCommand "allabiografer-nginx-conf" { } ''
    cp -r ${./nginx} $out
    chmod -R u+w $out
    substituteInPlace $out/nginx.conf $out/sites-available/* \
      --replace-quiet @openresty@ ${openresty} \
      --replace-quiet @conf@ $out \
      --replace-quiet @cacert@ ${cacert} \
      --replace-quiet @luaPath@ '${pkgs.luajitPackages.lua-resty-http}/share/lua/5.1/?.lua'
  '';

  serve = pkgs.writeShellApplication {
    name = "allabiografer-serve";
    runtimeInputs = [
      openresty
      pkgs.coreutils
      pkgs.gnused
    ];
    text = ''
      root="''${SITE_ROOT:-/srv/www}"
      export NEWSLETTER_CITIES_FILE="''${NEWSLETTER_CITIES_FILE:-$root/i/newsletter-cities.json}"
      work=$(mktemp -d)
      # The configuration names /srv/www; elsewhere, serve a copy pointing at SITE_ROOT.
      if [[ "$root" != /srv/www ]]; then
        cp -r ${conf} "$work/conf"
        chmod -R u+w "$work/conf"
        for file in "$work"/conf/nginx.conf "$work"/conf/sites-available/*; do
          sed "s#/srv/www#$root#g; s#${conf}#$work/conf#g" "$file" > "$file.new"
          mv "$file.new" "$file"
        done
        exec openresty -p "$work" -e stderr -c "$work/conf/nginx.conf" "$@"
      fi
      exec openresty -p "$work" -e stderr -c ${conf}/nginx.conf "$@"
    '';
  };
in
{
  inherit openresty conf serve;

  image = pkgs.dockerTools.buildLayeredImage {
    name = "allabiografer-se";
    tag = "latest";
    contents = [
      pkgs.cacert
      pkgs.tzdata
      pkgs.dockerTools.fakeNss
    ];
    extraCommands = "mkdir -m 1777 tmp && mkdir -p srv/www";
    config = {
      Cmd = [ "${serve}/bin/allabiografer-serve" ];
      ExposedPorts."8080/tcp" = { };
      Env = [
        "TZ=Europe/Stockholm"
        "SSL_CERT_FILE=${cacert}"
      ];
      User = "nobody";
    };
  };
}
