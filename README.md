# A FLUKA toolkit for the ICRP-145 adult mesh phantoms

Build the ICRP Publication 145 adult mesh-type reference computational phantoms
in FLUKA, run them, and reduce the results to organ and target-region doses.

ICRP-145 distributes two exposure examples implemented for **Geant4, MCNP6 and
PHITS**. It distributes none for FLUKA. This toolkit builds the phantoms in
FLUKA, generates those two examples or any case of your own, and reduces the
output to organ and target-region doses.

Bozzato *et al* 2026 (*J. Radiol. Prot.* **46** 011510) implemented these
phantoms in FLUKA first and published fluence-to-effective-dose conversion
coefficients. Their supplementary material is twelve spreadsheets of
coefficients; no code, input files or source routine were released. This is the
runnable part.

Built and tested on FLUKA 4-5.2, gfortran, Linux.

## Easiest way: one window

```sh
python3 RUNME.py
```

Five tabs, in the order they have to happen. Point tab 1 at the ICRP download,
then work left to right. No environment variable, no terminal commands, and the
data location is remembered so tab 1 is done once.

| tab | what it does |
|---|---|
| 1 Data | choose the ICRP zip as downloaded, or a folder; it unpacks the 14 files needed |
| 2 Phantom | builds the FLUKA cards, refusing to write unless the masses match ICRP |
| 3 Case | organ, particle, energy, phantom, exposure; writes the input |
| 4 Run | cycles and cores; runs FLUKA, merges with `usbsuw`, converts |
| 5 Results | dose per organ, or per ICRP-145 target region |

The log pane echoes the equivalent command for everything it does, so a session
in the window can be repeated on the command line.

## The same thing on the command line

| # | run | what it does | produces |
|---|---|---|---|
| 0 | `setup_data.py <zip or folder>` | unpacks the ICRP data and remembers where it is | `phantom/`, `.datapath` |
| 1 | `selftest.py` | checks Python, FLUKA, the data, and that the phantom matches ICRP's reference masses | pass / fail |
| 2 | `make_umesh.py` | builds the phantom: one `MATERIAL` + `COMPOUND` per tissue, one `ASSIGNMA` per organ | the cards, and `AM_regions.csv` / `AF_regions.csv` |
| 3 | `make_examples.py` | writes the FLUKA input for your case | `AM/Internal/MRCP-AM_internal.inp` etc. |
| 4 | `rfluka`, `usbsuw`, `usbrea` | FLUKA's own commands: transport, merge, convert | `*_sum.lis` |
| 5 | `read_doses.py` or `targets.py` | dose per organ, or per ICRP-145 target region | a table, printed or CSV |

Steps 0 to 2 are done once per installation; 3 to 5 are per case. Step 4 is
FLUKA's, not the toolkit's.

Two things that catch people out. **Step 2 writes the region tables** — organ
volumes and masses — that steps 3 and 5 read; skip it and they stop with a
message saying so. And **`usbsuw` is not optional**: the file FLUKA writes
directly holds the scores but no uncertainties.

```sh
python3 setup_data.py ~/Downloads/P145*.zip   # 0  once
python3 selftest.py                           # 1
python3 make_umesh.py                         # 2
python3 make_examples.py                      # 3

cd AM/External                                # 4  FLUKA's own commands
rfluka -N0 -M10 MRCP-AM_external
{ ls *_fort.21; echo; echo MRCP-AM_external_sum; } | usbsuw
printf 'MRCP-AM_external_sum.bnn\nMRCP-AM_external_sum.lis\n\n' | usbrea
cd ../..

python3 targets.py AM AM/External/*_sum.lis   # 5
```

FLUKA is single-threaded; to use more cores, run several `rfluka` processes with
different `RANDOMIZ` seeds in separate directories and merge them all with one
`usbsuw`. `RUNME.py` tab 4 does that for you. The internal case additionally
needs an executable built from FLUKA's own `umesh_source_newgen.f`; see the notes
below.

The phantom data is not included — see `REQUIREMENTS.md`.

## Using it for your own problem

Only step 3 changes.

```sh
python3 make_examples.py --list-organs                   # the 187 organ IDs
python3 make_examples.py --organ 8700                    # heart-wall source
python3 make_examples.py --particle ELECTRON --energy 0.5
python3 make_examples.py --sex AM --case internal
```

The ICRP benchmark inputs are never overwritten: anything non-default is written
to its own directory and flagged as not the benchmark.

Then steps 4 and 5 as before:

```sh
python3 read_doses.py AM AM/Internal/*_sum.lis     # per organ
python3 targets.py   AM AM/Internal/*_sum.lis      # per ICRP target region
```

`read_doses.py` gives all 187 organs. `targets.py` gives the 73 ICRP-145 target
regions — picking the radiosensitive sub-layer where ICRP specifies one, and
computing red bone marrow, which no per-organ result contains.

## Validation

`make_umesh.py` refuses to write anything unless the phantom it has built matches
ICRP's published reference values, and `selftest.py` checks the same:

| | male | ICRP | female | ICRP |
|---|---|---|---|---|
| total mass | 73.0 kg | 73 | 60.0 kg | 60 |
| height, from the mesh | 176.0 cm | 176 | 163.0 cm | 163 |
| red bone marrow | 1169 g | 1170 | 899 g | 900 |
| yellow bone marrow | 2480 g | 2480 | 1800 g | 1800 |
| imported mesh volume vs ICRP organ table | exact | | exact | |

Results from this toolkit have been checked organ by organ against the Geant4,
MCNP6 and PHITS reference results ICRP distributes, at 10 million primaries per
case. **`supplement.pdf`** holds that comparison in full: every organ, both
phantoms, both exposures, each with its uncertainty.

| case | Geant4 | MCNP6 | PHITS |
|---|---|---|---|
| AM internal | 1.0006 | 0.9998 | 1.0019 |
| AM external | 0.9924 | 0.9948 | 0.9929 |
| AF internal | 1.0029 | 0.9996 | 0.9994 |
| AF external | 0.9999 | 1.0062 | 0.9960 |

Median FLUKA / reference dose ratio, over organs where both sides have a
relative error of 10 % or better. Twelve independent comparisons, all within
0.8 % of unity, and the residual per-organ scatter follows the combined
statistical uncertainty rather than showing any systematic difference.

The code that produced that comparison is not part of this toolkit.

## Notes on the implementation

Points that are not in the FLUKA manual and cost time to find.

**Region names.** For a TetGen mesh FLUKA concatenates the `UMESH` SDUM with the
integer organ-ID attribute, no separator: SDUM `AM` and organ 9500 give region
`AM9500`. Names cap at 8 characters and ICRP organ IDs reach 14000, so the SDUM
cannot exceed three characters.

**The internal source.** Sampling a point inside a tetrahedral organ needs
`tetrarndpt`, reachable only from a source routine. Its `SOURCE` SDUM must be the
**bare organ ID** `9500`, not the region name `AM9500` — the lookup is by mesh
group name, which for TetGen is the integer attribute alone. With the wrong value
FLUKA writes one line to the `.log` and carries on, starting every primary at the
origin; the run completes, the energy balance is consistent, and the dose table
is wrong.

**Mesh files.** The `.ele` is named on the line after `UMESH`; the `.node` is
found from its basename and must sit in the same directory. The path must be
**relative** — FLUKA aborts with `Error loading umesh` on an absolute path, at
any length. `make_examples.py` writes a path relative to the case directory, so
the data can sit anywhere without an absolute path ever appearing.

**Materials.** `MATERIAL` WHAT(2) is deprecated and aborts the run. FLUKA
predefines 8 of the 13 elements ICRP uses; P, S, Cl, K and I need their own
cards. `MRCP_*_media.dat` cannot give the organ→medium map — its organ-name
column is truncated with `...` — so the map comes from ICRP's MCNP6 tables and
is cross-checked against the 52 media.

**Bone ratios.** `MRCP_*_bone.dat` lists each ratio twice, exclusive and
inclusive of blood. Only the exclusive ratios against the blood-free mass
reproduce ICRP's reference marrow masses; the inclusive ratios against the full
mass overshoot red marrow by 19 %.

**Comments.** Flair parses a line beginning with `*` immediately followed by a
card name as a *disabled card*, not a comment. `make_umesh.comment()` refuses any
comment whose first word is one of the 136 FLUKA card tags.

**Scoring.** A region binning is normalised per primary weight only, not per unit
volume; the division is left to the user. Verified against the energy balance.
The raw `fort.21` holds scores only — `usbsuw` is what adds the per-bin error
array, so it is not optional.

## Limitations

- **Endosteum is not computed.** ICRP does not distribute endosteum mass
  fractions; supply them with `targets.py --endosteum-weights` if you have them.
- **Organ 813** (`Brchiol-sec`) is listed in ICRP-145 Annex D but exists in
  neither distributed phantom, and none of the three reference implementations
  reports it. `targets.py --check` says so rather than reporting zero.
- Bladder-wall organs 13700 and 13701 were re-divided by ICRP between the 2018
  reference runs and the 2020 one; they are not comparable against MCNP6 and
  PHITS and are marked `geom`.

## Licence

**PolyForm Noncommercial License 1.0.0** — see `LICENCE`.

Free to use, modify and redistribute for any noncommercial purpose: research,
teaching, personal study, and any use by a charity, educational institution,
public research organisation, health or safety body, or government institution,
whatever their funding. Commercial use is not granted; contact the copyright
holder for a commercial licence.

This covers the code and documentation here only — not the ICRP phantom data,
not FLUKA, and not the reference results, none of which are distributed with it.
Those carry their own terms, from their own suppliers. FLUKA's own licence is
also noncommercial.
