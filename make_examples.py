#!/usr/bin/env python3
"""Generate FLUKA exposure inputs for the ICRP-145 adult MRCPs.

    python3 make_examples.py                    ICRP's two benchmark cases
    python3 make_examples.py --organ 8700       a heart-wall source instead
    python3 make_examples.py --particle ELECTRON --energy 0.5
    python3 make_examples.py --list-organs      organ IDs and names
    python3 make_examples.py --help

With no arguments this reproduces the two cases ICRP ships for Geant4, MCNP6 and
PHITS, so the answers are directly comparable across codes:

  internal   1 MeV photons emitted uniformly through the liver, organ 9500
  external   1 MeV photons from an isotropic point source 1 m in front (AP)

Both taken from ICRP's own MCNP6 inputs:
    sdef par=p erg=1 pos=volumer      (internal, homogeneous liver source)
    sdef par=p erg=1 pos=0 -100 0     (external, point source at y = -100 cm)

The liver is ICRP's choice of source organ, not a limitation. Any of the 187
organs works: the organ ID is the SDUM of the SOURCE card and is read at run
time, so one executable serves every organ without recompiling.

Anything other than the ICRP defaults is written to its own directory so the
benchmark inputs are never overwritten.

The materials, the compounds and the per-organ ASSIGNMA cards come from
make_umesh.py, which validates them against ICRP's reference organ masses before
returning anything, so this script cannot emit an input built on tables that
failed their checks.
"""

__version__ = '1.0.0'
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

import make_umesh as M                                        # noqa: E402

# ICRP-145 benchmark specification
ICRP_ORGAN = 9500         # liver, 2360 g male / 1810 g female
ICRP_PARTICLE = 'PHOTON'
ICRP_ENERGY = 1.0         # MeV
ICRP_POS = (0.0, -100.0, 0.0)    # cm, point source 1 m in front
PRIMARIES = 1000000       # x 10 cycles = the 1e7 all three references used

ISOTROPIC = 12566.4       # mrad; anything above 2000*pi tells FLUKA "isotropic"

# Region numbering is fixed by the order the regions are declared: BLKBODY is 1,
# VOID is 2, the mesh cage is 3, and the 187 organs follow in organ-ID order.
FIRST_ORGAN_REGION = 4


def header(f, sex, case, cfg, note):
    w = lambda s: f.write(s + '\n')
    w('TITLE')
    w(f'ICRP-145 {sex} adult MRCP -- {case} exposure, '
      f'{cfg.energy:g} MeV {cfg.particle.lower()}s')
    w(M.comment('..+....1....+....2....+....3....+....4....+....5....+....6....+....7....+....8'))
    for line in note:
        w(M.comment(line))
    return w


def geometry(w, sex, case_dir):
    """GEOBEGIN through GEOEND. Identical for both exposure cases.

    The mesh path is written RELATIVE to the case directory. FLUKA rejects an
    absolute path on the UMESH card -- it aborts with "Error loading umesh" --
    so the path has to be relative however far away the data sits.
    """
    w(M.card('GEOBEGIN', (), 'COMBNAME'))
    # the mesh file is named on the line FOLLOWING the UMESH card; FLUKA finds
    # MRCP_<sex>.node itself from the basename, so it is never mentioned here
    w(M.card('UMESH', (), sex))
    mesh = os.path.join(M.mesh_dir(sex), f'MRCP_{sex}.ele')
    w(os.path.relpath(mesh, case_dir))
    w('    0    0')
    w('SPH blkbody    0.0 0.0 0.0 100000.0')
    w('SPH void       0.0 0.0 0.0 10000.0')
    w('END')
    w('BLKBODY      5 +blkbody -void')
    w(f'VOID         5 +void -{sex}')
    w(f'{sex:<12} 5 +{sex}')
    w('END')
    w(M.card('GEOEND'))


def scoring(w, sex, ids):
    """Per-organ dose, by region binning over every organ.

    Type 12 is the region mesh with track-length apportioning, which converges
    far faster than the step-midpoint algorithm (type 2) for electrons. Region
    binnings are normalised per primary weight only and NOT per unit volume --
    read_doses.py divides by the organ volume.

    The range is given as region NAMES, not numbers. Flair rewrites numeric
    region WHATs into names when it saves an input, and for a UMESH phantom it
    gets them wrong -- 4 and 190 come back as AM11900 and VOID, and the run then
    scores a single empty bin with no error message. Writing the names in the
    first place leaves Flair nothing to convert. FLUKA accepts either form.
    """
    first, last = f'{sex}{ids[0]}', f'{sex}{ids[-1]}'
    w(M.card('USRBIN', (12.0, 'DOSE', -21.0, last, 0.0, 0.0), 'organdose'))
    w(M.card('USRBIN', (first, 0.0, 0.0, 1.0, 1.0, 1.0), '&'))


def tail(w, cfg, d, sex):
    for c in d['cards']:
        w(c)
    w(M.card('ASSIGNMA', ('VACUUM', sex)))
    w(M.card('ASSIGNMA', ('BLCKHOLE', 'BLKBODY')))
    w(M.card('ASSIGNMA', ('VACUUM', 'VOID')))
    scoring(w, sex, d['ids'])
    w(M.card('RANDOMIZ', (1.0, 12345)))
    w(M.card('START', (cfg.primaries,)))
    w(M.card('STOP'))


def case_dir(cfg, kind):
    """Benchmark cases keep their names; anything else gets its own directory."""
    if cfg.is_benchmark:
        return kind, kind.lower()
    tag = f'{kind}_{cfg.organ}_{cfg.particle.lower()}{cfg.energy:g}MeV'
    return tag, tag.lower()


def write_external(sex, d, cfg):
    sub, stem = case_dir(cfg, 'External')
    out = os.path.join(HERE, sex, sub, f'MRCP-{sex}_{stem}.inp')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    x, y, z = cfg.position
    with open(out, 'w') as f:
        w = header(f, sex, 'external', cfg, [
            f'Isotropic point source of {cfg.energy:g} MeV '
            f'{cfg.particle.lower()}s',
            f'at ({x:g}, {y:g}, {z:g}) cm.',
        ])
        w(M.card('GLOBAL', (5000.0,)))
        w(M.card('DEFAULTS', (), 'PRECISIO'))
        w(M.card('BEAM', (M.num(-cfg.energy / 1000.0), 0.0, ISOTROPIC),
                 cfg.particle))
        w(M.card('BEAMPOS', (x, y, z)))
        geometry(w, sex, os.path.dirname(out))
        tail(w, cfg, d, sex)
    return out


def write_internal(sex, d, cfg):
    sub, stem = case_dir(cfg, 'Internal')
    out = os.path.join(HERE, sex, sub, f'MRCP-{sex}_{stem}.inp')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    region = f'{sex}{cfg.organ}'
    name = d['mats'][cfg.organ][0]
    with open(out, 'w') as f:
        w = header(f, sex, 'internal', cfg, [
            f'{cfg.energy:g} MeV {cfg.particle.lower()}s emitted uniformly',
            f'through {name}, organ {cfg.organ}, region {region}.',
            f'The SOURCE SDUM is the organ ID {cfg.organ}, not the region name.',
        ])
        w(M.card('GLOBAL', (5000.0,)))
        w(M.card('DEFAULTS', (), 'PRECISIO'))
        w(M.card('BEAM', (M.num(-cfg.energy / 1000.0),), cfg.particle))
        w(M.card('SOURCE', (1.0,), str(cfg.organ)))
        geometry(w, sex, os.path.dirname(out))
        tail(w, cfg, d, sex)
    return out


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description='Generate FLUKA exposure inputs for the ICRP-145 phantoms. '
                    'With no arguments, reproduces ICRP\'s two benchmark cases.')
    p.add_argument('--organ', type=int, default=ICRP_ORGAN, metavar='ID',
                   help=f'source organ ID for the internal case '
                        f'(default {ICRP_ORGAN}, liver -- ICRP\'s choice)')
    p.add_argument('--particle', default=ICRP_PARTICLE, metavar='NAME',
                   help=f'FLUKA particle name (default {ICRP_PARTICLE})')
    p.add_argument('--energy', type=float, default=ICRP_ENERGY, metavar='MeV',
                   help=f'kinetic energy in MeV (default {ICRP_ENERGY:g})')
    p.add_argument('--position', type=float, nargs=3, default=list(ICRP_POS),
                   metavar=('X', 'Y', 'Z'),
                   help='external point-source position in cm '
                        '(default 0 -100 0, i.e. 1 m in front)')
    p.add_argument('--primaries', type=int, default=PRIMARIES, metavar='N',
                   help=f'primaries per cycle (default {PRIMARIES})')
    p.add_argument('--sex', choices=('AM', 'AF'), action='append',
                   help='phantom to write; repeatable, default both')
    p.add_argument('--case', choices=('internal', 'external', 'both'),
                   default='both', help='which case to write (default both)')
    p.add_argument('--list-organs', action='store_true',
                   help='print the organ IDs and names, then exit')
    a = p.parse_args(argv)
    a.sex = a.sex or ['AM', 'AF']
    a.position = tuple(a.position)
    a.is_benchmark = (a.organ == ICRP_ORGAN and a.particle == ICRP_PARTICLE
                      and a.energy == ICRP_ENERGY and a.position == ICRP_POS)
    return a


def main(argv=None):
    cfg = parse_args(argv)

    if cfg.list_organs:
        d = M.assemble(cfg.sex[0])
        if d is None:
            return 1
        for oid in d['ids']:
            print(f'{oid:>6}  {d["mats"][oid][0]:<44} {d["mass"][oid]:>10.2f} g')
        return 0

    ok = True
    for sex in cfg.sex:
        d = M.assemble(sex)
        if d is None:
            ok = False
            continue
        if cfg.organ not in d['ids']:
            print(f'{sex}: organ {cfg.organ} is not in this phantom '
                  f'(try --list-organs)', file=sys.stderr)
            ok = False
            continue
        n = len(d['ids'])
        first, last = FIRST_ORGAN_REGION, FIRST_ORGAN_REGION + n - 1
        print(f'{sex}: {n} organs, regions {first}-{last}, '
              f'source {d["mats"][cfg.organ][0]} {sex}{cfg.organ} = '
              f'{d["mass"][cfg.organ]:.0f} g'
              + ('' if cfg.is_benchmark else '   [not the ICRP benchmark]'))
        written = []
        if cfg.case in ('external', 'both'):
            written.append(write_external(sex, d, cfg))
        if cfg.case in ('internal', 'both'):
            written.append(write_internal(sex, d, cfg))
        for p in written:
            print(f'   {os.path.relpath(p, HERE)}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
