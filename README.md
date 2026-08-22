# A FLUKA toolkit for the ICRP mesh-type reference phantoms

Build the ICRP mesh-type reference computational phantoms — the two adults of
Publication 145 and the ten children of Publication 156 — in FLUKA, run them,
and reduce the results to organ and target-region doses.

ICRP distributes two exposure examples implemented for **Geant4, MCNP6 and
PHITS**. It distributes none for FLUKA. This toolkit builds all twelve
phantoms in FLUKA, generates those two examples or any case of your own, and
reduces the output to organ and target-region doses.

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

Six tabs, in the order they have to happen. Point tab 1 at the ICRP download
— the P145 zip, the P156 zip, or both — then work left to right. No
environment variable, no terminal commands, and the data location is
remembered so tab 1 is done once per archive.

| tab | what it does |
|---|---|
| 1 Data | choose an ICRP zip as downloaded, or a folder; it unpacks the files needed |
| 2 Phantom | builds the FLUKA cards, refusing to write unless the masses match ICRP |
| 3 Case | organ, particle, energy, phantom, exposure, physics; writes the input. Offers the phantoms built on tab 2 |
| 4 Run | cycles and cores; runs FLUKA, merges with `usbsuw`, converts |
| 5 Results | dose per organ or per ICRP target region; CSV export at 1, 2 or 3 sigma |
| 6 View | slices through anatomy, airways and dose; merges raw cycles when needed |

The log pane echoes the equivalent command for everything it does, so a session
in the window can be repeated on the command line.

## The same thing on the command line

| # | run | what it does | produces |
|---|---|---|---|
| 0 | `setup_data.py <zip or folder>` | unpacks the ICRP data (P145, P156 or both) and remembers where it is | `phantom/`, `.datapath` |
| 1 | `selftest.py` | checks Python, FLUKA, the data, every phantom's masses and decks; `--fluka` adds short transport runs and staged failures, `--transport` runs every phantom through FLUKA | pass / fail |
| 2 | `make_umesh.py` | builds the phantom: one `MATERIAL` + `COMPOUND` per tissue, one `ASSIGNMA` per organ | the cards, and `<phantom>_regions.csv` |
| 3 | `make_examples.py` | writes the FLUKA input for your case | `runs/AM_internal_9500_photon1MeV/…inp` etc. |
| 4 | `rfluka`, `usbsuw`, `usbrea` | FLUKA's own commands: transport, merge, convert | `*_sum.lis` |
| 5 | `read_doses.py` or `targets.py` | dose per organ, or per ICRP-145 target region | a table, printed or CSV |

Steps 0 to 2 are done once per installation; 3 to 5 are per case. Step 4 is
FLUKA's, not the toolkit's.

Two things that catch people out. **Step 2 writes the region tables** — organ
volumes and masses — that steps 3 and 5 read; skip it and they stop with a
message saying so. And **`usbsuw` is not optional**: the file FLUKA writes
directly holds the scores but no uncertainties.

```sh
python3 setup_data.py ~/Downloads/P145*.zip   # 0  once per archive
python3 setup_data.py ~/Downloads/P156*.zip
python3 selftest.py                           # 1
python3 make_umesh.py                         # 2
python3 make_examples.py                      # 3

cd runs/AM_external_photon1MeV                # 4  FLUKA's own commands
rfluka -N0 -M10 AM_external_photon1MeV
{ ls *_fort.21; echo; echo AM_external_photon1MeV_sum; } | usbsuw
printf 'AM_external_photon1MeV_sum.bnn\nAM_external_photon1MeV_sum.lis\n\n' | usbrea
cd ../..

python3 targets.py AM runs/AM_external_photon1MeV/*_sum.lis   # 5
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
python3 make_examples.py --list-organs                   # organ IDs (187 adult, up to 241 child)
python3 make_examples.py --organ 8700                    # heart-wall source
python3 make_examples.py --particle ELECTRON --energy 0.5
python3 make_examples.py --sex 00M --case internal       # any of the 12 phantoms
```

The ICRP benchmark inputs are never overwritten: anything non-default is written
to its own directory and flagged as not the benchmark.

Then steps 4 and 5 as before:

```sh
python3 read_doses.py AM AM/Internal/*_sum.lis     # per organ
python3 targets.py   AM AM/Internal/*_sum.lis      # per ICRP target region
```

`read_doses.py` gives every organ of the phantom. `targets.py` gives the 73 ICRP-145 target
regions — picking the radiosensitive sub-layer where ICRP specifies one, and
computing red bone marrow, which no per-organ result contains.

## Transport physics

Every input defaults to `DEFAULTS PRECISIO`: coupled electron–photon
transport with a 100 keV electron and positron transport cutoff, and single
Coulomb scattering substituted for the Molière condensed-history multiple
scattering at every boundary crossing. In a phantom of
millions of tetrahedra a shower electron crosses a boundary every fraction of
a millimetre, so that substitution — one single-scattering treatment per
crossing — dominates the electromagnetic transport cost. Two faster settings
exist, on tab 3 of `RUNME.py` or on the command line; each writes two cards
after `DEFAULTS` and changes nothing else in the input.

```sh
python3 make_examples.py --physics fast
python3 make_examples.py --physics custom --ecut 0.15
```

**`fast`** raises the electron and positron transport threshold to 0.35 MeV
(`EMFCUT`; the production thresholds follow the transport cut) and restores
the condensed-history default at boundaries (`MULSOPT`). An electron below
threshold is not transported: its kinetic energy is deposited at its point of
creation. The continuous-slowing-down-approximation (CSDA) range at
0.35 MeV in soft tissue is about 1 mm, so for
scoring volumes large against a millimetre the displacement of the deposition
site is negligible and, under charged-particle equilibrium, the local deposit
is the correct expectation value — the kerma approximation, restricted to
sub-threshold electrons. The same threshold expressed as a range is a 1 mm
production range cut in soft tissue.
Measured on the AF internal benchmark against `PRECISIO`, per-organ doses
agree within counting statistics and the CPU time per primary falls from
63.7 to 41.2 ms. Harder cuts gain nothing further: with electron transport
suppressed entirely the time per primary is unchanged, the remainder being
geometry navigation through the mesh.

**`custom`** writes the same two cards with a threshold of your choosing.
Choose it so the CSDA range at the cut is small against the thinnest
structure scored: in soft tissue, roughly 0.14 mm at 0.1 MeV, 1 mm at
0.35 MeV, 4 mm at 1 MeV.

**Not recommended** wherever local deposition is a poor model of the
transport it replaces:

- **Electron, positron and beta-emitting sources.** The threshold terminates
  the primaries themselves; any part of the spectrum below the cut deposits
  at the emission point, suppressing the cross-dose to neighbouring regions
  entirely.
- **Targets thinner than the residual range.** The airway epithelial layers
  (micrometres), the skin target layer and the lens of the eye receive their
  dose from electrons slowing down across them; displacing the deposition
  site by up to a millimetre biases these doses by construction. The GUI
  warns if fast or custom physics is combined with airway scoring or a
  charged-particle source.
- **Photon energies above a few MeV.** The secondary-electron range grows to
  centimetres, charged-particle equilibrium fails at organ boundaries, and
  the local-deposition error grows with energy.
- **Heavy charged particles.** The primaries are unaffected by these cards,
  but delta-ray transport above the cut is not; keep `precision` when scoring
  micrometre targets around an alpha or ion source.
- **Reference results.** Anything intended for comparison against other
  codes or publication should state, and use, the precision treatment.

A fast or custom case is written to its own directory (`..._fast`,
`..._ecut0.15MeV`) and flagged as not the benchmark, so the ICRP benchmark
inputs are never overwritten.

## Validation

`make_umesh.py` refuses to write anything unless the phantom it has built matches
ICRP's published reference values — the same gates run for all twelve phantoms
against each one's own Publication 145 or 156 reference masses — and
`selftest.py` checks the same:

| | male | ICRP | female | ICRP |
|---|---|---|---|---|
| total mass | 73.0 kg | 73 | 60.0 kg | 60 |
| height, from the mesh | 176.0 cm | 176 | 163.0 cm | 163 |
| red bone marrow | 1169 g | 1170 | 899 g | 900 |
| yellow bone marrow | 2480 g | 2480 | 1800 g | 1800 |
| imported mesh volume vs ICRP organ table | exact | | exact | |

Organ volume is summed over the tetrahedra of the `.ele` file, not read from
`mrcp-*.cell`, so a dose is a deposit divided by the mass of the geometry FLUKA
was handed. For the two adults the two agree. For the ten children of
Publication 156 they do not: whole-body volume and mass agree exactly, and so
does every organ that sits in one place, but the tissues ICRP cuts into head,
trunk, arms and legs — muscle, residual tissue, skin, the large vessels — are
divided differently in the mesh and in the table, by 9 % of the newborn's arm
muscle and 72 % of the ten-year-old's sensitive trunk skin. `make_umesh.py`
names the affected organs as it builds each phantom.

Results from this toolkit have been checked organ by organ against the Geant4,
MCNP6 and PHITS reference results ICRP distributes, at 10 million primaries per
case. **`supplement.pdf`** holds that comparison in full: every organ, all
twelve phantoms, both exposures, each with its uncertainty.

| case | Geant4 | MCNP6 | PHITS |
|---|---|---|---|
| AM internal | 1.0021 | 1.0006 | 1.0025 |
| AM external | 0.9925 | 0.9948 | 0.9928 |
| AF internal | 1.0029 | 0.9996 | 0.9994 |
| AF external | 0.9999 | 1.0062 | 0.9959 |

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
cannot exceed three characters. Names must also begin with a letter — Flair
refuses digit-first names even though the FLUKA executable accepts them — so
the paediatric tags are aliased with the sex letter rotated to the front:
`00M` becomes `M00`, region `M009500`.

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
is cross-checked against the 52 media. The density carried is the media
(Annex B) value; where the per-organ table prints it to fewer digits (the 15M
tongue, 1.05 vs 1.051), the build notes the difference and carries the media
figure.

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
- **Target 813** (`Brchiol-sec`) in ICRP-145 Annex D belongs to the auxiliary
  lung-airway model (Table C.1, IDs 810-815), not to the tetrahedral mesh: no
  tetrahedron carries that attribute and none of the three reference
  implementations, which transport the mesh alone, reports it. The airway
  scoring option computes the bronchiolar layers; `targets.py --check` reports
  813 as absent from the mesh rather than reporting zero.
- Bladder-wall organs 13700 and 13701 were re-divided between the 2018
  reference runs and the 2020 one; they are comparable only against Geant4,
  which derives from the same division as the distributed data, and are
  marked `geom` for the other two.

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
