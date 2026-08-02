# Common `target_command` Values for Celestial Objects

https://ssd.jpl.nasa.gov/

## Solar System Targets

| Planet         | target_command |
| -------------- | -------------- |
| Sun            | `'10'`         |
| Mercury        | `'199'`        |
| Venus          | `'299'`        |
| Earth (center) | `'399'`        |
| Mars           | `'499'`        |
| Jupiter        | `'599'`        |
| Saturn         | `'699'`        |
| Uranus         | `'799'`        |
| Neptune        | `'899'`        |
| Pluto          | `'999'`        |

---

## Common Satellites

| Satellites | target_command | center  |
| ---------- | -------------- | ------- |
| Moon       | `'301'`        | Earth   |
| Phobos     | `'401'`        | Mars    |
| Deimos     | `'402'`        | Mars    |
| Io         | `'501'`        | Jupiter |
| Europa     | `'502'`        | Jupiter |
| Ganymede   | `'503'`        | Jupiter |
| Callisto   | `'504'`        | Jupiter |
| Titan      | `'606'`        | Saturn  |

---

## Comets

| Comets                | target_command   |
| --------------------- | ---------------- |
| Halley                | `'1P'`           |
| Encke                 | `'2P'`           |
| Hale-Bopp             | `'C/1995 O1'`    |
| NEOWISE               | `'C/2020 F3'`    |
| C/2025 R3 (PanSTARRS) | `'DES=1004093;'` |


* Old comets can be directly accessed with `'1P'`, etc.
* For new comets, you may need to use the `DES` format with the comet's designation (e.g., `'DES=1004093;'` for C/2025 R3).

```text
'DES=xxxxxxx;'
```

---

## ☄️ Asteroids

| Asteroids | target_command |
| --------- | -------------- |
| Ceres     | `'1'`          |
| Pallas    | `'2'`          |
| Vesta     | `'4'`          |
| Eros      | `'433'`        |
| Bennu     | `'101955'`     |
| Apophis   | `'99942'`      |

---

## Human-Made Satellites

| object   | target_command |
| ------ | -------------- |
| ISS    | `'25544'`      |
| Hubble | `'20580'`      |

* Those require Horizons support for TLE
* Sometimes you may need to use different modes (but your current setup should work directly)

---

## Meteor Showers

Meteor showers are **not** Horizons targets. A shower is a debris stream, not a
body, so there is nothing to compute an ephemeris for. These use a separate
provider (`astronomy.meteor_fetcher.MeteorRadiantFetcher`) that computes the
radiant position locally, and a `SHOWER=<IAU code>` command instead.

| Shower                   | target_command | Peak (solar longitude) | Peak ZHR |
| ------------------------ | -------------- | ---------------------- | -------- |
| Quadrantids              | `SHOWER=QUA`   | 283.15 deg (~Jan 3)    | 110      |
| Lyrids                   | `SHOWER=LYR`   | 32.32 deg (~Apr 22)    | 18       |
| eta Aquariids            | `SHOWER=ETA`   | 45.5 deg (~May 6)      | 50       |
| Southern delta Aquariids | `SHOWER=SDA`   | 125.0 deg (~Jul 30)    | 25       |
| Perseids                 | `SHOWER=PER`   | 140.0 deg (~Aug 12)    | 100      |
| Draconids                | `SHOWER=DRA`   | 195.4 deg (~Oct 8)     | 5        |
| Orionids                 | `SHOWER=ORI`   | 208.0 deg (~Oct 21)    | 20       |
| Leonids                  | `SHOWER=LEO`   | 235.27 deg (~Nov 17)   | 15       |
| Geminids                 | `SHOWER=GEM`   | 262.2 deg (~Dec 14)    | 150      |
| Ursids                   | `SHOWER=URS`   | 270.7 deg (~Dec 22)    | 10       |

* Calendar dates are approximate; the solar longitude is the fixed quantity and
  the date it falls on shifts by up to a day across the leap-year cycle. Call
  `MeteorShower.next_peak()` for the exact time in a given year.
* Bare codes and names also resolve, so `SHOWER=PER`, `PER`, and `Perseids` are
  equivalent.
* A shower launcher must set `fetcher_factory=MeteorRadiantFetcher` in its
  `TrackerAppConfig`; a `SHOWER=` command sent to Horizons will not resolve.

```text
SHOWER=<IAU code>
```

Note that the parent bodies **are** valid Horizons targets, but tracking one
tells you nothing about where to watch: 109P/Swift-Tuttle, the Perseids' parent,
is currently far beyond Saturn's orbit while its debris hits the atmosphere
100 km overhead.