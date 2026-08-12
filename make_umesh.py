#!/usr/bin/env python3
"""Build the FLUKA inputs for the ICRP-145 adult mesh-type reference phantoms.

    python3 make_umesh.py            writes the region table for each phantom

DATA LOCATION. The ICRP data sits under the work root, where setup_data.py
unpacks it:

    runs/phantom/MRCP_AM/MRCP_AM.ele  .node  _media.dat  _bone.dat  _blood.dat
    runs/phantom/MRCP_AF/MRCP_AF.ele  ...
    runs/phantom/mcnp_tables/mrcp-am.cell  mrcp-am.material  mrcp-af.*

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
files: mrcp-am.material gives one composition and one density per organ ID.
Every organ composition is checked back against the 52 media in media.dat
before anything is written.

ORGAN VOLUME is not read from a table. It is summed over the tetrahedra of the
.ele file, so the mass of a region is the mass of the geometry FLUKA is handed
and a dose is a deposit divided by what actually stopped it. mrcp-am.cell also
tabulates a volume, and for the adults it is the same number; for the ten
paediatric phantoms it is not, for the tissues ICRP cuts into head, trunk, arms
and legs. mesh_volumes() has the measurements.
"""

__version__ = '1.1.0'
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, '.datapath')


OUTCFG = os.path.join(HERE, '.outpath')


def work_root():
    """Where everything generated goes.

    Nothing is written beside the code. The phantom cards, the region tables
    and every case live under one directory, so the toolkit stays exactly as
    it was installed and a whole study can be moved or deleted in one piece.
    Default runs/ next to the toolkit; set_work_root moves it.
    """
    if os.path.exists(OUTCFG):
        p = open(OUTCFG).read().strip()
        if p:
            return p
    return os.path.join(HERE, 'runs')


def set_work_root(path):
    with open(OUTCFG, 'w') as f:
        f.write(os.path.abspath(path))


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
    return os.path.join(work_root(), 'phantom')


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


def alias(sex):
    """The phantom tag as a FLUKA name.

    FLUKA names must begin with a letter, so the paediatric tags rotate the
    sex letter to the front: 00M -> M00. Three characters, since the region
    names append an organ ID of up to five digits to an 8-character limit.
    """
    return sex if sex[0].isalpha() else sex[-1] + sex[:-1]


def phantoms(data=None):
    """Every phantom whose mesh is present, in the order REFERENCE lists them.

    Discovered rather than hardcoded: the adults are Publication 145 and the
    ten children are Publication 156, and more may follow. A phantom counts as
    present when its .ele file is there and its reference masses are known,
    because without those the build cannot be checked.
    """
    root = data or data_dir()
    out = []
    for name in REFERENCE:
        f = os.path.join(root, f'MRCP_{name}', f'MRCP_{name}.ele')
        if os.path.exists(f):
            out.append(name)
    return out


def mesh_dir(sex):
    """Directory holding MRCP_<sex>.ele/.node and the three .dat tables."""
    return os.path.join(data_dir(), f'MRCP_{sex}')


def out_dir(sex):
    """Kept for callers that want a per-phantom scratch area.

    Cases do not use this. Every case is self-contained: make_examples.py
    gives build() its own directory and the region table is written there,
    beside the input it belongs to.
    """
    d = os.path.join(work_root(), sex)
    os.makedirs(d, exist_ok=True)
    return d


# The adults are Publication 145, tables 2.1 and 2.2. The children are
# Publication 156: total body mass and standing height from table 6.1, and
# the marrow masses from table 4.2, organ-only column, which is the blood-free
# mass the ratios in MRCP_*_bone.dat apply to. Newborn standing height is the
# recumbent reference length; the newborn has no inactive marrow at all.
REFERENCE = {
    'AM':  dict(height=176.0, mass=73000.0, rbm=1170.000, ybm=2480.000),
    'AF':  dict(height=163.0, mass=60000.0, rbm= 900.000, ybm=1800.000),
    '00M': dict(height= 51.0, mass= 3500.0, rbm=  50.000, ybm=   0.000),
    '00F': dict(height= 51.0, mass= 3500.0, rbm=  50.000, ybm=   0.000),
    '01M': dict(height= 76.0, mass=10000.0, rbm= 155.548, ybm=  14.452),
    '01F': dict(height= 76.0, mass=10000.0, rbm= 155.548, ybm=  14.452),
    '05M': dict(height=109.0, mass=19000.0, rbm= 374.931, ybm= 125.069),
    '05F': dict(height=109.0, mass=19000.0, rbm= 374.931, ybm= 125.069),
    '10M': dict(height=138.0, mass=32000.0, rbm= 754.144, ybm= 505.856),
    '10F': dict(height=138.0, mass=32000.0, rbm= 754.144, ybm= 505.856),
    '15M': dict(height=167.0, mass=56000.0, rbm=1053.496, ybm=1506.504),
    '15F': dict(height=161.0, mass=53000.0, rbm=1049.098, ybm=1330.902),
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
    """organ ID -> (density g/cm3, volume cm3) as MCNP tabulates them.

    The volume here is the one MCNP normalises its tallies by. It is NOT
    always the volume of the tetrahedra FLUKA transports; see mesh_volumes.
    Only the density is taken from this table for the build.
    """
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


_VOLUMES = {}


def mesh_volumes(sex):
    """organ ID -> volume cm3, summed over the tetrahedra of the .ele file.

    This is the volume of the geometry FLUKA is given, so it is the volume a
    scored energy deposit has to be divided by. It is not read from a table;
    it is the mesh itself, one sixth of the scalar triple product over every
    tetrahedron carrying that organ ID, in the file's own centimetres.

    It is not always what mrcp-*.cell tabulates. Whole-body volume and mass
    agree exactly, and so does every organ that occupies one place in the
    body, but the tissues ICRP subdivides by body region -- muscle, residual
    tissue, skin and the large blood vessels, each cut into head, trunk, arms
    and legs -- are split differently in the two. In the newborn male the arm
    muscle is 69.407 cm3 of tetrahedra against 76.381 cm3 in the table, 9.1 %,
    and the trunk muscle is larger by the same amount of tissue; the ten
    paediatric phantoms all show it, the two adults do not. The published
    Geant4 example output follows the table rather than the mesh it reads,
    so the region boundary moved between the mesh ICRP tabulated and the mesh
    ICRP distributes. Since FLUKA transports the distributed mesh, the mesh
    is what its regions are normalised by. build() prints the disagreement.

    Reading the mesh costs about twenty seconds a phantom, so the answer is
    kept -- selftest.py and the GUI both ask for the same phantom repeatedly.
    """
    if sex in _VOLUMES:
        return _VOLUMES[sex]
    from array import array
    x, y, z = array('d'), array('d'), array('d')
    d = mesh_dir(sex)
    with open(os.path.join(d, f'MRCP_{sex}.node'), encoding='latin-1') as f:
        n = int(f.readline().split()[0])
        for _ in range(n):
            t = f.readline().split()
            x.append(float(t[1]))
            y.append(float(t[2]))
            z.append(float(t[3]))
    vol = {}
    with open(os.path.join(d, f'MRCP_{sex}.ele'), encoding='latin-1') as f:
        m = int(f.readline().split()[0])
        for _ in range(m):
            t = f.readline().split()
            a, b, c, e = int(t[1]), int(t[2]), int(t[3]), int(t[4])
            ax, ay, az = x[a], y[a], z[a]
            bx, by, bz = x[b] - ax, y[b] - ay, z[b] - az
            cx, cy, cz = x[c] - ax, y[c] - ay, z[c] - az
            ex, ey, ez = x[e] - ax, y[e] - ay, z[e] - az
            v = (bx * (cy * ez - cz * ey) + by * (cz * ex - cx * ez)
                 + bz * (cx * ey - cy * ex))
            o = int(t[5])
            vol[o] = vol.get(o, 0.0) + (v if v >= 0.0 else -v)
    _VOLUMES[sex] = {o: v / 6.0 for o, v in vol.items()}
    return _VOLUMES[sex]


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
    vols = mesh_volumes(sex)
    ids = sorted(vols)
    mats = load_materials(sex)
    cells = load_cells(sex)
    media = load_media(sex)
    bone = load_bone(sex)
    blood = load_blood(sex)
    ref = REFERENCE[sex]

    problems, warnings = [], []

    missing = [i for i in ids if i not in mats or i not in cells]
    if missing:
        problems.append(f'no composition/volume for organ IDs {missing}')

    # every organ must match one of the 52 media in media.dat -- this is what
    # ties the MCNP-side organ table back to ICRP's own published media list,
    # and it is also how each organ gets its medium number for the blood ratios
    # Composition decides, density only breaks ties. The two tables round
    # differently: the tongue of the 15-year-old male is 1.05 g/cm3 in
    # .material and 1.051 in media.dat, the same medium printed to different
    # precision, and requiring the densities to agree to 0.0005 rejected it
    # even though every element fraction agreed exactly. The best match is
    # taken rather than the first, so a near-miss cannot win over an exact one.
    medium_of = {}
    for i in ids:
        name, rho, comp = mats[i]
        best, hit = None, None
        for mid, (_, mrho, mcomp) in media.items():
            if set(mcomp) != set(comp):
                continue
            worst = max(abs(mcomp[e] - comp[e]) for e in comp)
            if worst > 1e-3 or abs(mrho - rho) > 2e-3:
                continue
            score = (worst, abs(mrho - rho))
            if best is None or score < best:
                best, hit = score, mid
        if hit is None:
            problems.append(f'organ {i} ({name}) matches no medium in media.dat')
        medium_of[i] = hit
        # ICRP's own two tables disagree slightly for a few organs -- the
        # spinal cord of three paediatric phantoms, by 0.1 to 0.2 %. The mass
        # is built from the .material density, because that is the density the
        # MATERIAL card carries and therefore the one FLUKA transports with,
        # so a small disagreement is noted and not fatal.
        drho = abs(cells[i][0] - rho)
        if drho > 5e-4:
            where = (f'organ {i} ({name}): density {rho} g/cm3 in .material, '
                     f'{cells[i][0]} in .cell ({100 * drho / rho:+.2f} %); '
                     f'the MATERIAL card carries the .material value')
            (warnings if drho <= 0.01 * rho else problems).append(where)

    # Volume is the mesh's own, density the .cell one, which mesh_volumes and
    # the density check above explain. Where the two tables disagree on volume
    # the organ is named, because the disagreement carries straight into dose.
    apart = sorted(((100.0 * (vols[i] - cells[i][1]) / cells[i][1], i)
                    for i in ids if i in cells and cells[i][1] > 0),
                   key=lambda p: -abs(p[0]))
    off = [p for p in apart if abs(p[0]) > 0.5]
    if off:
        both = [i for i in ids if i in cells and cells[i][1] > 0]
        tot = 100.0 * (sum(vols[i] for i in both)
                       - sum(cells[i][1] for i in both)) \
            / sum(cells[i][1] for i in both)
        warnings.append(
            f'{len(off)} pieces of distributed tissues where the mesh and '
            f'mrcp-{sex.lower()}.cell partition the head/trunk/arms/legs '
            f'boundaries differently, worst '
            + ', '.join(f'{i} ({mats[i][0]}) {p:+.2f} %' for p, i in off[:3])
            + f'; whole-body volume agrees to {tot:+.3f} % and masses follow '
              'the mesh, so doses are consistent with the transported '
              'geometry; only these pieces are not comparable against '
              'table-normalised references')

    # masses, and the reference-mass checks that have to pass before writing.
    # the bone ratios are exclusive of blood, so they act on the blood-free mass
    mass = {i: vols[i] * mats[i][1] for i in ids}
    dry = {i: mass[i] * (1.0 - blood.get(medium_of[i], 0.0)) for i in ids}
    total = sum(mass.values())
    rbm = sum(dry[i] * bone[i][0] for i in ids if i in bone)
    ybm = sum(dry[i] * bone[i][1] for i in ids if i in bone)

    def check(label, got, want, frac, floor=1.0):
        tol = max(frac * want, floor)
        if abs(got - want) > tol:
            problems.append(f'{label} {got:.1f} g, ICRP reference {want:.1f} g '
                            f'({100 * (got - want) / want:+.2f} %, limit '
                            f'{100 * frac:.1f} %)')

    # Tolerances measured against all twelve phantoms, not guessed.
    #
    # Total mass is what ICRP guarantees: Publication 156 states the organ
    # masses agree with the reference values within 0.1 %, and the worst seen
    # here is 0.02 %.
    #
    # The marrows are different. They are not segmented organs -- Publication
    # 156 says the microstructures of the skeletal targets "are not modelled
    # explicitly" -- so their mass is derived from the spongiosa mass and the
    # ratios in MRCP_*_bone.dat, and ICRP claims no accuracy for the result.
    # Measured: red marrow agrees to 0.73 % or better everywhere. Inactive
    # marrow agrees to 0.02 % in the adults but runs high in the children, by
    # up to 2.4 % at 15 years. That follows from Publication 156 itself, which
    # says the ACTIVE marrow masses were adjusted to match the reference and
    # says nothing of the inactive, so only the active one was tuned.
    check('total mass', total, ref['mass'], 0.005)
    check('red bone marrow', rbm, ref['rbm'], 0.015)
    check('yellow bone marrow', ybm, ref['ybm'], 0.030)

    for w in warnings:
        print(f'{sex} note: {w}')
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
        cards.append(card('ASSIGNMA', (mat_of[key_of[i]], f'{alias(sex)}{i}')))

    return dict(sex=sex, ids=ids, cards=cards, mats=mats, cells=cells,
                vols=vols,
                bone=bone, blood=blood, medium_of=medium_of, mat_of=mat_of,
                key_of=key_of, mass=mass, dry=dry, total=total, rbm=rbm,
                ybm=ybm, ref=ref)

def build(sex, dest=None, write=True):
    d = assemble(sex)
    if d is None:
        return None
    ids, cards, mats, vols = d['ids'], d['cards'], d['mats'], d['vols']
    bone, blood, medium_of = d['bone'], d['blood'], d['medium_of']
    mat_of, key_of = d['mat_of'], d['key_of']
    mass, dry, total, rbm, ybm, ref = (d['mass'], d['dry'], d['total'],
                                       d['rbm'], d['ybm'], d['ref'])

    if not write:
        # Validation only, and nothing on disk. The path is not built here
        # either: out_dir() creates its directory as a side effect, so asking
        # for it would leave an empty folder behind.
        print(f'{sex}: {len(ids)} organs, {len(mat_of)} materials')
        print(f'   total mass {total/1000:7.2f} kg  (ICRP {ref["mass"]/1000:g})')
        dev = lambda g, w: f'{100 * (g - w) / w:+.2f} %' if w else 'n/a'
        print(f'   red marrow  {rbm:7.1f} g   (ICRP {ref["rbm"]:g}, '
              f'{dev(rbm, ref["rbm"])})')
        print(f'   yellow      {ybm:7.1f} g   (ICRP {ref["ybm"]:g}, '
              f'{dev(ybm, ref["ybm"])})')
        return True
    tbl = os.path.join(dest or out_dir(sex), f'{sex}_regions.csv')
    with open(tbl, 'w', newline='') as f:
        c = csv.writer(f)
        c.writerow(['region', 'organ_id', 'organ', 'material', 'medium',
                    'density', 'volume_cm3', 'mass_g', 'blood_frac', 'blood_g',
                    'bloodfree_g', 'rbm_frac', 'rbm_g', 'ybm_frac', 'ybm_g',
                    'tb_frac', 'tb_g', 'cb_frac', 'cb_g', 'mst_frac', 'mst_g'])
        for i in ids:
            name, rho, _ = mats[i]
            vol = vols[i]
            m, d = mass[i], dry[i]
            bf = blood.get(medium_of[i], 0.0)
            r, y, tb, cb, mst = bone.get(i, (0.0,) * 5)
            c.writerow([f'{alias(sex)}{i}', i, name, mat_of[key_of[i]],
                        medium_of[i],
                        rho, repr(vol), repr(m), bf, repr(m * bf),
                        repr(d),
                        r, repr(d * r), y, repr(d * y), tb, repr(d * tb),
                        cb, repr(d * cb), mst, repr(d * mst)])

    print(f'{sex}: {tbl}')
    print(f'   {len(ids)} organs -> {len(ids)} regions, {len(mat_of)} materials,'
          f' {len(cards)} cards')
    print(f'   total mass {total/1000:7.2f} kg  (ICRP {ref["mass"]/1000:g})')
    dev = lambda g, w: f'{100 * (g - w) / w:+.2f} %' if w else 'n/a'
    print(f'   red marrow  {rbm:7.1f} g   (ICRP {ref["rbm"]:g}, '
          f'{dev(rbm, ref["rbm"])})')
    print(f'   yellow      {ybm:7.1f} g   (ICRP {ref["ybm"]:g}, '
          f'{dev(ybm, ref["ybm"])})')
    return tbl


if __name__ == '__main__':
    names = sys.argv[1:] or phantoms()
    ok = [build(s) for s in names]
    sys.exit(0 if all(ok) else 1)
