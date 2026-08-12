# Requirements

## 1. ICRP-145 phantom data

Not distributed here. ICRP Publication 145 is "Copyright 2020 ICRP … All rights
reserved"; republishing any part of it requires written permission
(annals@icrp.org). Free to access from ICRP since 2023.

| | |
|---|---|
| publication page | https://www.icrp.org/publication.asp?id=ICRP%20Publication%20145 |
| electronic files | https://www.icrp.org/docs/P145%20Electronic%20files.zip |
| size | 1 879 727 107 bytes (1.88 GB) |
| report PDF | https://journals.sagepub.com/doi/pdf/10.1177/ANIB_49_3 |

Both go to tab 1 of `RUNME.py`, one at a time, exactly as downloaded. Nothing
needs unpacking by hand: the toolkit takes the files it needs and puts them
under `runs/phantom`, and remembers where.

    P145 Electronic files.zip        the phantoms, required
    MRCP_GEANT4_lung_airway.zip      the airway model, optional

On the command line the same thing is

```sh
python3 setup_data.py "P145 Electronic files.zip"
python3 setup_data.py MRCP_GEANT4_lung_airway.zip     # optional
python3 setup_data.py --status
```

The `.obj`, `.mtl` and `.pdf` files are visualisation only; the remaining
`MC_examples` zips are Geant4 and PHITS.

`mrcp-am.material` and `mrcp-am.cell` are required. `MRCP_*_media.dat` cannot
substitute: its organ-name column is truncated with `...` for every medium shared
by several organs, so it cannot be inverted into an organ-ID → medium map.

## 2. FLUKA

| | |
|---|---|
| download and licence registration | https://fluka.cern/download |
| version used here | 4-5.2 (2026-05-06) |

`UMESH` and `tetrarndpt` require FLUKA 4.

CERN single-user licence: personal, non-transferable, non-military,
non-commercial, not redistributable. Anything compiled against it, including
`flukamrcp`, cannot be redistributed either.

## 3. Flair (recommended)

| | |
|---|---|
| download | https://cern.ch/flair/download/ |
| version | 3.4-5.4 |
| requires | Python 3.6+, tkinter, Tcl/Tk 8.5+ |

Reads the TetGen mesh natively: opens the `.inp` files, shows the 187 organs in
the geometry viewer, reports region name and material per organ, runs jobs.
Install `flair-geoviewer` alongside it for the 3D view.

```sh
# repository instructions per Ubuntu release (26.04, 24.04, 22.04 LTS) at
# https://cern.ch/flair/download/
sudo apt install flair flair-geoviewer
```

Not required; see README.md §6 for both routes.

## 4. Python

Python 3, checked on 3.13. Standard library only.

## 5. Check

```sh
python3 make_umesh.py
```

Reproduces ICRP's reference masses, and writes nothing if it cannot:

```
AM: 187 organs -> 187 regions, 48 materials
   total mass    73.0 kg  (ICRP 73)
   red marrow     1169 g   (ICRP 1170)
   yellow         2480 g   (ICRP 2480)
AF: ...
   total mass    60.0 kg  (ICRP 60)
   red marrow      899 g   (ICRP 900)
   yellow         1800 g   (ICRP 1800)
```

## Citing

- ICRP, 2020. *Adult mesh-type reference computational phantoms.* ICRP
  Publication 145. Ann. ICRP 49(3).
- FLUKA: cite the reference set at https://fluka.cern/documentation/references
  (required by the licence).
