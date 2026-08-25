FROM ghcr.io/astral-sh/uv:python3.13-alpine AS build
WORKDIR /app
RUN apk add --update --no-cache \
    libjpeg-turbo-dev libpng-dev libwebp-dev zlib-dev
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group build
COPY src src
COPY static static
COPY data data
RUN uv run build /app/www

FROM alpine:3.22 AS goaccess-build
ARG GOACCESS_VERSION=1.11
ARG GOACCESS_SHA256=19f52862eb805bfa2682acc3184e7af09019c00df96a27f400480230b0bcaf73
ADD "https://github.com/allinurl/goaccess/archive/refs/tags/v${GOACCESS_VERSION}.tar.gz" /tmp/goaccess.tar.gz
RUN \
    echo "${GOACCESS_SHA256}  /tmp/goaccess.tar.gz" > /tmp/goaccess.sha256; \
    sha256sum -c /tmp/goaccess.sha256; \
    apk add --no-cache \
        autoconf automake build-base gettext-dev libmaxminddb-dev linux-headers ncurses-dev openssl-dev pkgconf zlib-dev
WORKDIR /src
RUN \
    tar -xzf /tmp/goaccess.tar.gz --strip-components=1; \
    autoreconf -fiv; \
    ./configure --prefix=/usr --enable-utf8 --with-openssl --with-zlib --enable-geoip=mmdb; \
    make -j"$(nproc)"; \
    make DESTDIR=/dist install

FROM alpine:3.22
ARG S6_OVERLAY_VERSION=3.2.1.0
ADD "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz" /tmp
ADD "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-aarch64.tar.xz" /tmp
ADD "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-x86_64.tar.xz" /tmp
ADD "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb" /usr/local/share/GeoIP/GeoLite2-Country.mmdb
RUN \
    sha256sum "/tmp/s6-overlay-noarch.tar.xz"; \
    echo "42e038a9a00fc0fef70bf0bc42f625a9c14f8ecdfe77d4ad93281edf717e10c5  /tmp/s6-overlay-noarch.tar.xz" | sha256sum -c; \
    tar -C / -Jxpf /tmp/s6-overlay-noarch.tar.xz; \
    \
    case "$(uname -m)" in \
        "x86_64") \
            sha256sum "/tmp/s6-overlay-x86_64.tar.xz"; \
            echo "8bcbc2cada58426f976b159dcc4e06cbb1454d5f39252b3bb0c778ccf71c9435  /tmp/s6-overlay-x86_64.tar.xz" | sha256sum -c; \
            tar -C / -Jxpf /tmp/s6-overlay-x86_64.tar.xz; \
            ;; \
        "aarch64") \
            sha256sum "/tmp/s6-overlay-aarch64.tar.xz"; \
            echo "c8fd6b1f0380d399422fc986a1e6799f6a287e2cfa24813ad0b6a4fb4fa755cc  /tmp/s6-overlay-aarch64.tar.xz" | sha256sum -c; \
            tar -C / -Jxpf /tmp/s6-overlay-aarch64.tar.xz; \
            ;; \
        *) \
          echo "Cannot build, missing valid build platform." \
          exit 1; \
    esac; \
    rm -rf "/tmp/*"; \
    apk add --update --no-cache gettext-libs libmaxminddb ncurses-libs nginx nginx-mod-http-brotli openssl tzdata zlib
COPY --from=goaccess-build /dist/usr/bin/goaccess /usr/bin/goaccess
COPY --from=goaccess-build /dist/usr/share /usr/share
COPY --from=build /app/www /var/www/allabiografer.se
COPY etc /etc
COPY init-wrapper /
ENTRYPOINT ["/init-wrapper"]
