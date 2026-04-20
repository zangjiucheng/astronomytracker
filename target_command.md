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