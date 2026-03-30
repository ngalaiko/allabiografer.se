# allabiografer.se

A static site aggregating cinema screenings across Sweden. Reimplementation of [allekinos.de](https://allekinos.de/) by [Nikita Tonsky](https://tonsky.me/) for the Sweden.

## Usage

Parse screenings from all supported cinemas:

```
mise run parse
```

Build the static site:

```
mise run build
```

Serve locally:

```
mise run serve
```

## Deployment

Deployed to [Fly.io](https://fly.io).

```
fly deploy
```
