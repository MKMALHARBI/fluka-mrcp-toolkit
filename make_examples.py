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

__version__ = '1.2.0'
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

import make_umesh as M
from make_umesh import mesh_dir                                        # noqa: E402

# ICRP-145 benchmark specification
ICRP_ORGAN = 9500         # liver, 2360 g male / 1810 g female
ICRP_PARTICLE = 'PHOTON'
ICRP_ENERGY = 1.0         # MeV
ICRP_POS = (0.0, -100.0, 0.0)    # cm, point source 1 m in front
PRIMARIES = 1000000       # x 10 cycles = the 1e7 all three references used

# The fast electron cut. 0.35 MeV is the production threshold of a 1 mm
# range cut in soft tissue; the residual range, about 1 mm, is below any
# whole organ. Cutting harder gains nothing: the remaining run time is mesh
# navigation, not electron transport.
FAST_ECUT = 0.35

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


def physics(w, cfg):
    """DEFAULTS, plus the two electron cards of the fast and custom modes.

    Electrons below the cut deposit where they stand, so the cut only suits
    structures larger than its range. Production thresholds follow the
    transport cut by default and are not set separately. MULSOPT takes back
    the single Coulomb scattering at boundaries that PRECISIO turns on --
    one single-scattering treatment per tetrahedron crossing is what makes
    a mesh phantom expensive.
    """
    w(M.card('DEFAULTS', (), 'PRECISIO'))
    if cfg.physics == 'full':
        return
    cut = FAST_ECUT if cfg.physics == 'fast' else cfg.ecut
    w(M.card('EMFCUT', (M.num(-cut / 1000.0), '3.3333E-5', 0.0,
                        'BLKBODY', '@LASTREG', 1.0)))
    w(M.card('MULSOPT', (0.0, 0.0, 0.0, -1.0, -1.0, 0.0), 'GLOBEMF'))


def geometry(w, sex, case_dir):
    """GEOBEGIN through GEOEND. Identical for both exposure cases.

    The mesh path is written RELATIVE to the case directory. FLUKA rejects an
    absolute path on the UMESH card -- it aborts with "Error loading umesh" --
    so the path has to be relative however far away the data sits.
    """
    a = M.alias(sex)
    w(M.card('GEOBEGIN', (), 'COMBNAME'))
    # the mesh file is named on the line FOLLOWING the UMESH card; FLUKA finds
    # MRCP_<sex>.node itself from the basename, so it is never mentioned here
    w(M.card('UMESH', (), a))
    mesh = os.path.join(M.mesh_dir(sex), f'MRCP_{sex}.ele')
    w(os.path.relpath(mesh, case_dir))
    w('    0    0')
    w('SPH blkbody    0.0 0.0 0.0 100000.0')
    w('SPH void       0.0 0.0 0.0 10000.0')
    w('END')
    w('BLKBODY      5 +blkbody -void')
    w(f'VOID         5 +void -{a}')
    w(f'{a:<12} 5 +{a}')
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
    first, last = f'{M.alias(sex)}{ids[0]}', f'{M.alias(sex)}{ids[-1]}'
    w(M.card('USRBIN', (12.0, 'DOSE', -21.0, last, 0.0, 0.0), 'organdose'))
    w(M.card('USRBIN', (first, 0.0, 0.0, 1.0, 1.0, 1.0), '&'))


def write_stem(out_path, sex):
    """Tell the airway routines where the ICRP files are.

    MUSRBR reads this one line at the first energy deposit. A file rather than
    an environment variable, so nothing has to be set before a run; the path is
    relative to the case directory for the same reason the mesh path is.
    """
    d = os.path.dirname(out_path)
    stem = os.path.relpath(os.path.join(mesh_dir(sex), f'MRCP_{sex}'), d)
    with open(os.path.join(d, 'airway.stem'), 'w') as f:
        f.write(stem + '\n')
    return stem


README_EXE = """\
{title}

Everything this case needs is in this directory. Build the executable first:
it is not written with the input.

    python3 build_exe.py {case}

or press Build flukamrcp on tab 4 of RUNME.py. It is compiled from your own
FLUKA installation and is not redistributable.


FLAIR

    open {inp}
    go to the Run tab
    set Executable to flukamrcp in this directory: click the folder icon
    next to the Exe field and pick it, or type ./flukamrcp
    set the number of cycles, then Start

    Raise the attach timeout in Preferences before starting. The mesh takes
    a while to load and Flair gives up waiting on the run and reports it as
    failed while FLUKA is still working. A high value costs nothing.

Flair merges the cycles itself; the result is the .bnn it writes beside
the input.


TERMINAL

    rfluka -N0 -M5 -e ./flukamrcp {stem}

        -N0 -M5   run cycles 1 to 5. Five or more gives a usable error;
                  each cycle is an independent batch.
        -e        the executable, needed because this case uses a FLUKA
                  user routine. Do not omit it: FLUKA does not stop, it
                  silently runs its default beam source from the origin
                  and every dose is wrong.

    ls *_fort.2? | usbsuw

        Merges the cycles and works out the error on every bin. The
        fort.2? files hold scores only, so this step is what produces the
        uncertainties. It asks for an output name; give {stem}_sum.

    usbrea

        Turns {stem}_sum.bnn into text. It asks for the input and output
        names; give {stem}_sum.bnn and {stem}_sum.lis.

Then read the doses with

    python3 read_doses.py {sex} {stem}_sum.lis
    python3 targets.py    {sex} {stem}_sum.lis
{stem_note}\
"""

README_NOEXE = """\
{title}

Everything this case needs is in this directory. No executable is required:
this case uses no FLUKA user routine.


FLAIR

    open {inp}
    go to the Run tab, leave Executable empty
    set the number of cycles, then Start


TERMINAL

    rfluka -N0 -M5 {stem}

        -N0 -M5   run cycles 1 to 5. Five or more gives a usable error;
                  each cycle is an independent batch.

    ls *_fort.2? | usbsuw

        Merges the cycles and works out the error on every bin. The
        fort.2? files hold scores only, so this step is what produces the
        uncertainties. It asks for an output name; give {stem}_sum.

    usbrea

        Turns {stem}_sum.bnn into text. It asks for the input and output
        names; give {stem}_sum.bnn and {stem}_sum.lis.

Then read the doses with

    python3 read_doses.py {sex} {stem}_sum.lis
    python3 targets.py    {sex} {stem}_sum.lis
"""


def write_readme(out_path, sex, cfg, kind, needs_exe):
    """A note in the case directory saying how to run it without the toolkit.

    Flair and the terminal need different things: Flair wants the executable
    picked in the Run tab, the terminal wants it after -e, and a case with no
    user routine needs neither. One template each, so nothing tells the reader
    to do a step that does not apply.
    """
    d = os.path.dirname(out_path)
    stem = os.path.basename(out_path)[:-4]
    title = (f'ICRP-145 {sex} phantom, {kind.lower()} exposure, '
             f'{cfg.energy:g} MeV {cfg.particle.lower()}s')
    if kind == 'Internal':
        title += f', source in organ {cfg.organ}'
    note = ('\nairway.stem tells the scoring routines where the ICRP airway\n'
            'files are. Keep it beside the input.\n'
            if getattr(cfg, 'airway', False) else '')
    tmpl = README_EXE if needs_exe else README_NOEXE
    with open(os.path.join(d, 'README.txt'), 'w') as f:
        f.write(tmpl.format(title=title, inp=os.path.basename(out_path),
                            stem=stem, sex=sex, case=os.path.basename(d),
                            stem_note=note))


def airway_scoring(w):
    """Dose in the bronchial airway epithelium.

    ICRP distributes the airway tree apart from the mesh, because layers a few
    micrometres thick cannot be tetrahedra. Geant4 overlays them as a parallel
    world; FLUKA has none, so nothing is added to the geometry. A type 8 binning
    asks MUSRBR for the epithelial layer and LUSRBL for the region, both worked
    out from the deposit position at scoring time.

    On the continuation card WHAT(4) and WHAT(5) are bin WIDTHS, not bin
    counts. The limits are the integers themselves, not half-integers around
    them: FLUKA rounds the range outward, so 0.5 to 10.5 yields eleven bins
    with a dead one on the end, while 1 to 10 yields the ten layers exactly.
    """
    w(M.comment('airway epithelium: layer from MUSRBR, region from LUSRBL'))
    w(M.card('USRBIN', (8.0, 'DOSE', -22.0, 10.0, 2.0, 1.0), 'airway'))
    w(M.card('USRBIN', (1.0, 1.0, 0.0, 1.0, 1.0, 1.0), '&'))


def tail(w, cfg, d, sex):
    for c in d['cards']:
        w(c)
    w(M.card('ASSIGNMA', ('VACUUM', M.alias(sex))))
    w(M.card('ASSIGNMA', ('BLCKHOLE', 'BLKBODY')))
    w(M.card('ASSIGNMA', ('VACUUM', 'VOID')))
    scoring(w, sex, d['ids'])
    if getattr(cfg, 'airway', False):
        airway_scoring(w)
    w(M.card('RANDOMIZ', (1.0, 12345)))
    w(M.card('START', (cfg.primaries,)))
    w(M.card('STOP'))


def case_dir(sex, cfg, kind):
    """One self-contained directory per case, under the work root.

    The name carries everything that makes the case what it is, so changing
    the phantom, the organ, the particle or the energy gives a new directory
    rather than overwriting an old one. The source organ appears only for
    internal exposures, since an external source does not have one.
    """
    bits = [sex, kind.lower()]
    if kind == 'Internal':
        bits.append(str(cfg.organ))
    bits.append(f'{cfg.particle.lower()}{cfg.energy:g}MeV')
    if cfg.physics != 'full':
        bits.append('fast' if cfg.physics == 'fast'
                    else f'ecut{cfg.ecut:g}MeV')
    if getattr(cfg, 'airway', False):
        bits.append('airway')
    tag = '_'.join(bits)
    return os.path.join(M.work_root(), tag), tag


def write_external(sex, d, cfg):
    sub, stem = case_dir(sex, cfg, 'External')
    out = os.path.join(sub, f'{stem}.inp')
    os.makedirs(sub, exist_ok=True)
    M.build(sex, dest=sub)          # the region table belongs with its case
    x, y, z = cfg.position
    with open(out, 'w') as f:
        w = header(f, sex, 'external', cfg, [
            f'Isotropic point source of {cfg.energy:g} MeV '
            f'{cfg.particle.lower()}s',
            f'at ({x:g}, {y:g}, {z:g}) cm.',
        ])
        w(M.card('GLOBAL', (5000.0,)))
        physics(w, cfg)
        w(M.card('BEAM', (M.num(-cfg.energy / 1000.0), 0.0, ISOTROPIC),
                 cfg.particle))
        w(M.card('BEAMPOS', (x, y, z)))
        geometry(w, sex, os.path.dirname(out))
        tail(w, cfg, d, sex)
    if getattr(cfg, 'airway', False):
        write_stem(out, sex)
    write_readme(out, sex, cfg, 'External', getattr(cfg, 'airway', False))
    return out


def write_internal(sex, d, cfg):
    sub, stem = case_dir(sex, cfg, 'Internal')
    out = os.path.join(sub, f'{stem}.inp')
    os.makedirs(sub, exist_ok=True)
    M.build(sex, dest=sub)          # the region table belongs with its case
    region = f'{M.alias(sex)}{cfg.organ}'
    name = d['mats'][cfg.organ][0]
    with open(out, 'w') as f:
        w = header(f, sex, 'internal', cfg, [
            f'{cfg.energy:g} MeV {cfg.particle.lower()}s emitted uniformly',
            f'through {name}, organ {cfg.organ}, region {region}.',
            f'The SOURCE SDUM is the organ ID {cfg.organ}, not the region name.',
        ])
        w(M.card('GLOBAL', (5000.0,)))
        physics(w, cfg)
        w(M.card('BEAM', (M.num(-cfg.energy / 1000.0),), cfg.particle))
        w(M.card('SOURCE', (1.0,), str(cfg.organ)))
        geometry(w, sex, os.path.dirname(out))
        tail(w, cfg, d, sex)
    if getattr(cfg, 'airway', False):
        write_stem(out, sex)
    write_readme(out, sex, cfg, 'Internal', True)
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
    p.add_argument('--airway', action='store_true',
                   help='also score the bronchial airway epithelium '
                        '(needs MRCP_<sex>.lung and .lungDiam)')
    p.add_argument('--primaries', type=int, default=PRIMARIES, metavar='N',
                   help=f'primaries per cycle (default {PRIMARIES})')
    p.add_argument('--physics', choices=('full', 'fast', 'custom'),
                   default='full',
                   help='full = PRECISIO throughout (default); fast = '
                        f'electrons below {FAST_ECUT:g} MeV deposit locally '
                        'and single scattering at boundaries is off, for '
                        'photon organ doses; custom = the same cards with '
                        'the cut given by --ecut')
    p.add_argument('--ecut', type=float, metavar='MeV',
                   help='electron cut for --physics custom')
    p.add_argument('--sex', choices=list(M.REFERENCE), action='append',
                   help='phantom to write; repeatable, default both')
    p.add_argument('--case', choices=('internal', 'external', 'both'),
                   default='both', help='which case to write (default both)')
    p.add_argument('--list-organs', action='store_true',
                   help='print the organ IDs and names, then exit')
    a = p.parse_args(argv)
    if a.energy <= 0:
        p.error('--energy must be positive (MeV); a negative WHAT(1) on '
                'BEAM would be read as momentum, not energy')
    if a.primaries <= 0:
        p.error('--primaries must be positive')
    if a.physics == 'custom':
        if a.ecut is None or a.ecut <= 0:
            p.error('--physics custom needs --ecut > 0')
    elif a.ecut is not None:
        p.error('--ecut only applies to --physics custom')
    a.sex = a.sex or M.phantoms()
    a.position = tuple(a.position)
    a.is_benchmark = (a.organ == ICRP_ORGAN and a.particle == ICRP_PARTICLE
                      and a.energy == ICRP_ENERGY and a.position == ICRP_POS
                      and a.physics == 'full')
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
              f'source {d["mats"][cfg.organ][0]} {M.alias(sex)}{cfg.organ} = '
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
