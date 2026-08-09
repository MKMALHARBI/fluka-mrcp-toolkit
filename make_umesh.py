#!/usr/bin/env python3
"""Build the FLUKA inputs for the ICRP-145 adult mesh-type reference phantoms.

    python3 make_umesh.py            writes AM/AM.inp and AF/AF.inp plus their
                                     region tables

DATA LOCATION. ICRP data is expected under ./phantom :

    phantom/MRCP_AM/MRCP_AM.ele  .node  _media.dat  _bone.dat  _blood.dat
    phantom/MRCP_AF/MRCP_AF.ele  ...
    phantom/mcnp_tables/mrcp-am.cell  mrcp-am.material  mrcp-af.*

Set MRCP_DATA to override.

FLUKA reads the TetGen mesh directly through a UMESH card, so the 8.2 M / 8.6 M
tetrahedra are never converted -- MRCP_AM.ele is named on the line following the
card and the matching .node file is picked up automatically from the basename.

REGION NAMES. For a TetGen mesh FLUKA concatenates the UMESH SDUM with the
integer organ-ID attribute of the tetrahedron, with no separator. SDUM 'AM' and organ ID 14000 therefore give
region AM14000. Region names are capped at 8 characters and ICRP organ IDs run
to 5 digits, so the SDUM cannot be longer than three.

WHERE THE ORGAN DATA COMES FROM. MRCP_*_media.dat lists the 52 media with their
compositions and densities, but its organ-name column is truncated with '...'
for every medium shared by several organs, so it cannot be inverted to an
organ-ID -> medium map. ICRP ships that map explicitly in the MCNP6 example
files: mrcp-am.material gives one composition per organ ID and mrcp-am.cell
gives that organ's density and volume. Every organ composition is checked back
against the 52 media in media.dat before anything is written.
"""

__version__ = '1.1.0'
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, '.datapath')


def data_dir():
    """Where the ICRP data is, in order of precedence.

    1. MRCP_DATA in the environment, for a one-off run
    2. the path remembered in .datapath, written by RUNME.py
    3. ./phantom, the default place to unpack the download

    A remembered path means neither the GUI nor the command line needs an
    environment variable set.
    """
    env = os.environ.get('MRCP_DATA')
    if env:
        return env
    if os.path.exists(CONFIG):
        p = open(CONFIG).read().strip()
        if p and os.path.isdir(p):
            return p
    return os.path.join(HERE, 'phantom')


def set_data_dir(path):
    """Remember where the data is, so it need only be said once."""
    open(CONFIG, 'w').write(os.path.abspath(path))


DATA = data_dir()
TABLES = os.path.join(DATA, 'mcnp_tables')


def _refresh():
    """Re-read the data location after it has been changed at run time."""
    global DATA, TABLES
    DATA = data_dir()
    TABLES = os.path.join(DATA, 'mcnp_tables')
    return DATA


def mesh_dir(sex):
    """Directory holding MRCP_<sex>.ele/.node and the three .dat tables."""
    return os.path.join(data_dir(), f'MRCP_{sex}')


def out_dir(sex):
    """Output directory for this phantom."""
    d = os.path.join(HERE, sex)
    os.makedirs(d, exist_ok=True)
    return d


# Table 2.1 / 2.2, ICRP Publication 145
REFERENCE = {
    'AM': dict(height=176.0, mass=73000.0, rbm=1170.0, ybm=2480.0),
    'AF': dict(height=163.0, mass=60000.0, rbm=900.0, ybm=1800.0),
}

# MCNP ZAID -> (symbol, Z, FLUKA material name)
ELEMENTS = {
    1000: ('H', 1, 'HYDROGEN'), 6000: ('C', 6, 'CARBON'),
    7000: ('N', 7, 'NITROGEN'), 8000: ('O', 8, 'OXYGEN'),
    11000: ('Na', 11, 'SODIUM'), 12000: ('Mg', 12, 'MAGNESIU'),
    15000: ('P', 15, 'PHOSPHO'), 16000: ('S', 16, 'SULFUR'),
    17000: ('Cl', 17, 'CHLORINE'), 19000: ('K', 19, 'POTASSIU'),
    20000: ('Ca', 20, 'CALCIUM'), 26000: ('Fe', 26, 'IRON'),
    53000: ('I', 53, 'IODINE'),
}
# the five FLUKA does not predefine; Z and density only, because WHAT(2), the
# atomic weight, is deprecated on MATERIAL and aborts the run in MATCRD
EXTRA = {'PHOSPHO': (15, 2.20), 'SULFUR': (16, 2.00), 'CHLORINE': (17, 2.9947e-3),
         'POTASSIU': (19, 0.862), 'IODINE': (53, 4.93)}


# ---------------------------------------------------------------- readers

def load_materials(sex):
    """organ ID -> (organ name, density g/cm3, {element symbol: mass fraction}).

    Each 'm<id>' card is preceded by a comment line carrying the organ name and
    the density, which is the only place the name is given per organ ID.
    """
    fn = os.path.join(data_dir(), 'mcnp_tables', f'mrcp-{sex.lower()}.material')
    out, name, rho, cur = {}, None, None, None
    for line in open(fn, encoding='latin-1'):
        t = line.split()
        if not t:
            continue
        if t[0].upper() == 'C':
            m = re.match(r'C\s+(\S+)\s+([\d.]+)\s+g/cm3', line.strip())
            if m:
                name, rho = m.group(1), float(m.group(2))
            continue
        if re.match(r'^m\d+$', t[0]):
            cur = int(t[0][1:])
            out[cur] = (name, rho, {})
            continue
        if cur is not None and t[0].isdigit():
            sym = ELEMENTS[int(t[0])][0]
            out[cur][2][sym] = abs(float(t[1]))
    return out


def load_cells(sex):
    """organ ID -> (density g/cm3, volume cm3)."""
    fn = os.path.join(data_dir(), 'mcnp_tables', f'mrcp-{sex.lower()}.cell')
    out = {}
    for line in open(fn, encoding='latin-1'):
        m = re.match(r'\s*\d+\s+(\d+)\s+(-[\d.]+).*vol=([\d.eE+-]+)', line)
        if m:
            out[int(m.group(1))] = (-float(m.group(2)), float(m.group(3)))
    return out


def load_media(sex):
    """medium number -> (name, density, {element symbol: mass fraction}).

    Two header rows: atomic numbers, then element symbols followed by the word
    'density'. The atomic-number row fixes how many trailing tokens on each data
    row are percentages, the last token being the density.
    """
    fn = os.path.join(mesh_dir(sex), f'MRCP_{sex}_media.dat')
    lines = [l.rstrip('\r\n') for l in open(fn, encoding='latin-1')]
    znums = [t for t in lines[0].split() if t.isdigit()]
    ne = len(znums)
    syms = [ELEMENTS[int(z) * 1000][0] for z in znums]
    out = {}
    for l in lines[3:]:
        t = l.split()
        if len(t) < ne + 3 or not t[0].isdigit():
            continue
        vals = [float(x) for x in t[-(ne + 1):]]
        comp = {s: v / 100.0 for s, v in zip(syms, vals[:ne]) if v > 0}
        out[int(t[0])] = (' '.join(t[1:-(ne + 1)]), vals[-1], comp)
    return out


def load_bone(sex):
    """organ ID -> (RBM, YBM, TB, CB, MST) mass ratios, EXCLUSIVE of blood.

    The file tabulates each ratio twice, exclusive then inclusive of blood
    content. Only one pairing reproduces ICRP's reference marrow masses, and it
    is the exclusive ratios applied to the blood-free organ mass, i.e.
    mass * (1 - blood ratio). That gives 1169/2480 g male and 899/1800 g female
    against reference 1170/2480 and 900/1800. The inclusive ratios against the
    full mass overshoot red marrow by 19 %.

    Red bone marrow is not a segmented organ in ICRP-145 -- the skeletal targets
    are 'included implicitly in the spongiosa and medullary cavity' and the
    micron-scale structures are not modelled. Marrow mass per region has to come
    from these ratios. Marrow DOSE additionally needs the ICRP-116 Annex E/F
    response functions.
    """
    fn = os.path.join(mesh_dir(sex), f'MRCP_{sex}_bone.dat')
    out = {}
    for line in open(fn, encoding='latin-1'):
        t = line.split()
        if len(t) < 12 or not t[0].isdigit():
            continue
        out[int(t[0])] = tuple(float(x) for x in t[-10:-5])
    return out


def load_blood(sex):
    """medium number -> blood mass ratio of that tissue."""
    fn = os.path.join(mesh_dir(sex), f'MRCP_{sex}_blood.dat')
    out = {}
    for line in open(fn, encoding='latin-1'):
        t = line.split()
        if len(t) == 2 and t[0].isdigit():
            out[int(t[0])] = float(t[1])
    return out


def organ_ids(sex):
    """The distinct organ-ID attributes actually present in the .ele file."""
    fn = os.path.join(mesh_dir(sex), f'MRCP_{sex}.ele')
    seen = set()
    with open(fn, 'rb') as f:
        f.readline()
        for line in f:
            if line[:1] in (b'#', b''):
                continue
            p = line.rsplit(maxsplit=1)
            if p:
                seen.add(int(p[-1]))
    return sorted(seen)


# ---------------------------------------------------------------- cards

def card(tag, w=(), sdum=''):
    """An 80-column FLUKA card: 8-char tag, six 10-char WHATs, 10-char SDUM."""
    s = f'{tag:<10}' + ''.join(f'{x:>10}' for x in list(w)[:6])
    return (s.ljust(70)[:70] + f'{sdum:<10}').rstrip()


# Flair parses a line beginning with '*' immediately followed by a card name as
# a DISABLED CARD, not a comment: '*SOURCE SDUM is ...' shows up in the input
# editor as a greyed-out SOURCE card with the prose chopped into WHAT fields.
# Card tags below are Flair's own list from db/fluka.ini plus their 8-character
# FLUKA truncations.
CARD_TAGS = frozenset("""
    ARB ASSIGNMA ASSIGNMAT AUTOIMBS AUXSCORE BAMJET BEAM BEAMAXES BEAMPOS
    BIASING BME BOX COMPOUND CORRFACT CRYSTAL DCYSCORE DCYTIMES DEFAULTS
    DELTARAY DETECT DETGEB DISCARD DPM-PARA DPMJET ELCFIELD ELL EMF
    EMF-BIAS EMFCUT EMFFIX EMFFLUO EMFRAY END EVENTBIN EVENTDAT EVENTYPE
    EVXTEST EXPTRANS FIXED FLUKAFIX FREE GCR-SPE GEOBEGIN GEOEND GLOBAL
    HI-PROPE IONFLUCT IONTRANS IRRPROFI LAM-BIAS LATTICE LATTSNGL
    LOW-BIAS LOW-DOWN LOW-MAT LOW-NEUT LOW-PWXS MAT-PROP MATERIAL
    MCSTHRES MGNCREAT MGNCREATE MGNDATA MGNFIELD MULSOPT MUPHOTON OPEN
    OPT-PROD OPT-PROP PAIRBREM PART-THR PART-THRES PHOTONUC PHYSICS PLA
    PLOTGEOM POLARIZA PROFILE QUA RAD-BIOL RADDECAY RANDOMIZ RANDOMIZE
    RAW RCC REC REGION RESNUCLE RESNUCLEI ROT-DEFI ROT-DEFINI ROTPRBIN
    RPP RQMD SCORE SOURCE SPECSOUR SPH SPOTBEAM SPOTDIR SPOTPOS SPOTTRAN
    START STEPSIZE STERNHEI STERNHEIME STOP SYRASTEP TCQUENCH THRESHOL
    THRESHOLD TIME-CUT TITLE TPSSCORE TRC TRX TRY TRZ UMESH USERDUMP
    USERWEIG USERWEIGHT USRBDX USRBIN USRCOLL USRGCALL USRICALL USROCALL
    USRTRACK USRYIELD VOXELS WED WW-FACTO WW-FACTOR WW-PROFI WW-PROFILE
    WW-THRES WW-THRESH XCC XEC XRAYREFL XYP XZP YCC YEC YZP ZCC ZEC
""".split())


def comment(text):
    """A '*' comment line whose first word is guaranteed not to be a card tag."""
    first = text.split()[0].strip(':,.;') if text.split() else ''
    if first.upper() in CARD_TAGS:
        raise ValueError(f'comment would parse as a disabled {first.upper()} '
                         f'card in Flair; reword it: {text!r}')
    return '*' + text


def num(x, width=10):
    """Fixed-width numeric field that never overflows its column."""
    for fmt in ('%.6g', '%.5g', '%.4g', '%.3g'):
        s = fmt % x
        if len(s) <= width:
            return s
    return ('%.2g' % x)[:width]


# ---------------------------------------------------------------- build

def assemble(sex):
    """Read every ICRP table, cross-check them, and return the FLUKA cards.

    Returns None, having printed why, if any consistency or reference-mass
    check fails -- nothing downstream should write an input from bad data.
    """
    ids = organ_ids(sex)
    mats = load_materials(sex)
    cells = load_cells(sex)
    media = load_media(sex)
    bone = load_bone(sex)
    blood = load_blood(sex)
    ref = REFERENCE[sex]

    problems = []

    missing = [i for i in ids if i not in mats or i not in cells]
    if missing:
        problems.append(f'no composition/volume for organ IDs {missing}')

    # every organ must match one of the 52 media in media.dat -- this is what
    # ties the MCNP-side organ table back to ICRP's own published media list,
    # and it is also how each organ gets its medium number for the blood ratios
    medium_of = {}
    for i in ids:
        name, rho, comp = mats[i]
        hit = None
        for mid, (_, mrho, mcomp) in media.items():
            if abs(mrho - rho) > 5e-4:
                continue
            if set(mcomp) != set(comp):
                continue
            if all(abs(mcomp[e] - comp[e]) <= 1e-3 for e in comp):
                hit = mid
                break
        if hit is None:
            problems.append(f'organ {i} ({name}) matches no medium in media.dat')
        medium_of[i] = hit
        if abs(cells[i][0] - rho) > 5e-4:
            problems.append(f'organ {i} ({name}) density {rho} in .material '
                            f'but {cells[i][0]} in .cell')

    # masses, and the reference-mass checks that have to pass before writing.
    # the bone ratios are exclusive of blood, so they act on the blood-free mass
    mass = {i: cells[i][1] * cells[i][0] for i in ids}
    dry = {i: mass[i] * (1.0 - blood.get(medium_of[i], 0.0)) for i in ids}
    total = sum(mass.values())
    rbm = sum(dry[i] * bone[i][0] for i in ids if i in bone)
    ybm = sum(dry[i] * bone[i][1] for i in ids if i in bone)

    def check(label, got, want, tol):
        if abs(got - want) > tol:
            problems.append(f'{label} {got:.1f} g, ICRP reference {want:.1f} g')

    check('total mass', total, ref['mass'], 0.005 * ref['mass'])
    check('red bone marrow', rbm, ref['rbm'], 0.02 * ref['rbm'])
    check('yellow bone marrow', ybm, ref['ybm'], 0.02 * ref['ybm'])

    if problems:
        print(f'{sex}: NOT WRITTEN', file=sys.stderr)
        for p in problems:
            print(f'   {p}', file=sys.stderr)
        return None

    # one FLUKA material per distinct (composition, density); many organs share
    key_of, mat_of = {}, {}
    for i in ids:
        name, rho, comp = mats[i]
        k = (tuple(sorted(comp.items())), round(rho, 4))
        key_of[i] = k
        mat_of.setdefault(k, None)
    for n, k in enumerate(sorted(mat_of, key=lambda k: (k[1], k[0])), 1):
        mat_of[k] = f'TIS{n:03d}'

    cards = [card('MATERIAL', (z, '', num(r)), nm) for nm, (z, r) in EXTRA.items()]
    for k in sorted(mat_of, key=lambda k: mat_of[k]):
        comp, rho = k
        nm = mat_of[k]
        cards.append(card('MATERIAL', ('', '', num(rho)), nm))
        frac = [(v, ELEMENTS[[z for z, e in ELEMENTS.items()
                              if e[0] == s][0]][2]) for s, v in comp]
        tot = sum(v for v, _ in frac)
        for j in range(0, len(frac), 3):
            w = []
            for v, en in frac[j:j + 3]:
                w += [num(-v / tot), en]
            cards.append(card('COMPOUND', w, nm))
    for i in ids:
        cards.append(card('ASSIGNMA', (mat_of[key_of[i]], f'{sex}{i}')))

    return dict(sex=sex, ids=ids, cards=cards, mats=mats, cells=cells,
                bone=bone, blood=blood, medium_of=medium_of, mat_of=mat_of,
                key_of=key_of, mass=mass, dry=dry, total=total, rbm=rbm,
                ybm=ybm, ref=ref)

def build(sex):
    d = assemble(sex)
    if d is None:
        return None
    ids, cards, mats, cells = d['ids'], d['cards'], d['mats'], d['cells']
    bone, blood, medium_of = d['bone'], d['blood'], d['medium_of']
    mat_of, key_of = d['mat_of'], d['key_of']
    mass, dry, total, rbm, ybm, ref = (d['mass'], d['dry'], d['total'],
                                       d['rbm'], d['ybm'], d['ref'])

    out = os.path.join(out_dir(sex), f'{sex}.inp')
    with open(out, 'w') as f:
        w = lambda s: f.write(s + '\n')
        w('TITLE')
        w(f'ICRP-145 {sex} adult mesh-type reference computational phantom')
        w(comment('..+....1....+....2....+....3....+....4....+....5....+....6....+....7....+....8'))
        w(comment(f'{len(ids)} organs, {ref["height"]:.0f} cm, {ref["mass"]/1000:.0f} kg'))
        w(comment('A region name is the UMESH SDUM plus the organ ID, e.g. %s100.' % sex))
        w(card('GLOBAL', (5000.0,)))
        w(card('DEFAULTS', (), 'PRECISIO'))
        w(card('BEAM', (-1.0e-4,), 'PHOTON'))
        w(card('BEAMPOS', (0.0, -100.0, 0.0, 0.0, 1.0)))
        w(card('GEOBEGIN', (), 'COMBNAME'))
        w(card('UMESH', (), sex))
        # relative to the output directory: FLUKA rejects an absolute path
        # on the UMESH card, so this must stay relative wherever DATA is
        w(os.path.relpath(os.path.join(mesh_dir(sex), f'MRCP_{sex}.ele'),
                          out_dir(sex)))
        w('    0    0')
        w('SPH blkbody    0.0 0.0 0.0 100000.0')
        w('SPH void       0.0 0.0 0.0 10000.0')
        w('END')
        w(f'BLKBODY      5 +blkbody -void')
        w(f'VOID         5 +void -{sex}')
        w(f'{sex:<12} 5 +{sex}')
        w('END')
        w(card('GEOEND'))
        for c in cards:
            w(c)
        w(card('ASSIGNMA', ('VACUUM', sex)))
        w(card('ASSIGNMA', ('BLCKHOLE', 'BLKBODY')))
        w(card('ASSIGNMA', ('VACUUM', 'VOID')))
        w(card('SCORE', ('ENERGY',)))
        w(card('RANDOMIZ', (1.0, 12345)))
        w(card('START', (100000,)))
        w(card('STOP'))

    # Volumes and masses are written at full precision. A fixed number of
    # decimals costs significant figures on the smallest organs -- at six
    # decimals a 0.025 g organ keeps only five -- and those are exactly the
    # organs whose dose is divided by the volume written here.
    tbl = os.path.join(out_dir(sex), f'{sex}_regions.csv')
    with open(tbl, 'w', newline='') as f:
        c = csv.writer(f)
        c.writerow(['region', 'organ_id', 'organ', 'material', 'medium',
                    'density', 'volume_cm3', 'mass_g', 'blood_frac', 'blood_g',
                    'bloodfree_g', 'rbm_frac', 'rbm_g', 'ybm_frac', 'ybm_g',
                    'tb_frac', 'tb_g', 'cb_frac', 'cb_g', 'mst_frac', 'mst_g'])
        for i in ids:
            name, rho, _ = mats[i]
            vol = cells[i][1]
            m, d = mass[i], dry[i]
            bf = blood.get(medium_of[i], 0.0)
            r, y, tb, cb, mst = bone.get(i, (0.0,) * 5)
            c.writerow([f'{sex}{i}', i, name, mat_of[key_of[i]], medium_of[i],
                        rho, repr(vol), repr(m), bf, repr(m * bf),
                        repr(d),
                        r, repr(d * r), y, repr(d * y), tb, repr(d * tb),
                        cb, repr(d * cb), mst, repr(d * mst)])

    print(f'{sex}: {out}')
    print(f'   {len(ids)} organs -> {len(ids)} regions, {len(mat_of)} materials,'
          f' {len(cards)} cards')
    print(f'   region table -> {os.path.basename(tbl)}')
    print(f'   total mass {total/1000:7.1f} kg  (ICRP {ref["mass"]/1000:.0f})')
    print(f'   red marrow  {rbm:7.0f} g   (ICRP {ref["rbm"]:.0f})')
    print(f'   yellow      {ybm:7.0f} g   (ICRP {ref["ybm"]:.0f})')
    return out


if __name__ == '__main__':
    ok = [build(s) for s in ('AM', 'AF')]
    sys.exit(0 if all(ok) else 1)
