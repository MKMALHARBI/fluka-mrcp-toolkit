#!/usr/bin/env python3
"""Check an installation before committing to a long run.

    python3 selftest.py            everything that needs no transport
    python3 selftest.py --fluka    also run FLUKA on a tiny case (a few minutes)

Every check is against a value ICRP publishes, not against a value stored here,
so a pass means the phantom data was read correctly rather than that the code is
self-consistent.
"""

__version__ = '1.2.1'
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PASS, FAIL, SKIP = 'pass', 'FAIL', 'skip'
results = []

# assemble() reads the whole mesh, so several checks sharing a phantom must
# not each pay for it
ASSEMBLED = {}


def assemble(sex):
    if sex not in ASSEMBLED:
        import make_umesh as M
        ASSEMBLED[sex] = M.assemble(sex)
    return ASSEMBLED[sex]


def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:                                    # noqa: BLE001
        ok, detail = False, f'{type(e).__name__}: {e}'
    results.append((PASS if ok is True else SKIP if ok is None else FAIL,
                    name, detail))
    tag = {True: PASS, None: SKIP}.get(ok, FAIL)
    print(f'  [{tag:>4}] {name}' + (f' -- {detail}' if detail else ''))
    return ok


# ---------------------------------------------------------------- checks

def c_python():
    v = sys.version_info
    return v >= (3, 8), f'Python {v.major}.{v.minor}.{v.micro}'


def c_fluka():
    exe = shutil.which('rfluka')
    return bool(exe), exe or 'rfluka not on PATH -- see REQUIREMENTS.md section 2'


def c_source_routine():
    """The internal case needs an executable built from FLUKA's own file."""
    import glob
    import build_exe as B
    import make_umesh as M
    # the executable belongs to the case, so look in the case directories
    built = [d for d in glob.glob(os.path.join(M.work_root(), '*'))
             if os.path.isdir(d) and os.access(B.exe_for(d), os.X_OK)]
    if built:
        return True, f'flukamrcp built in {len(built)} case director' + \
            ('y' if len(built) == 1 else 'ies')
    src = B.source_file()
    if not src:
        return None, 'FLUKA not found; needed only for the internal case'
    return None, ('not built yet -- it is built per case, by RUNME tab 4 '
                  'or python3 build_exe.py')


def c_data():
    import make_umesh as M
    missing = []
    for sex in M.phantoms():
        for f in (f'MRCP_{sex}.ele', f'MRCP_{sex}.node', f'MRCP_{sex}_media.dat',
                  f'MRCP_{sex}_bone.dat', f'MRCP_{sex}_blood.dat'):
            if not os.path.exists(os.path.join(M.mesh_dir(sex), f)):
                missing.append(f'{sex}/{f}')
        for f in (f'mrcp-{sex.lower()}.cell', f'mrcp-{sex.lower()}.material'):
            if not os.path.exists(os.path.join(M.TABLES, f)):
                missing.append(f)
    if missing:
        return False, f'{len(missing)} file(s) missing, first {missing[0]}'
    return True, f'in {os.path.relpath(M.DATA, HERE)}'


def c_reference_masses():
    """The whole phantom build, checked against ICRP's published masses."""
    import make_umesh as M
    out = []
    for sex in M.phantoms():
        d = assemble(sex)
        if d is None:
            return False, f'{sex}: validation failed, see the message above'
        ref = M.REFERENCE[sex]
        # same tolerances as make_umesh.assemble, and for the same reasons:
        # ICRP guarantees the organ masses, derives the marrows, and adjusted
        # only the active one. Worst measured is the 15-year-old female,
        # +2.39 % inactive marrow.
        for label, got, want, tol in (
                ('mass', d['total'], ref['mass'], 0.005 * ref['mass']),
                ('RBM', d['rbm'], ref['rbm'], 0.015 * ref['rbm']),
                ('YBM', d['ybm'], ref['ybm'], 0.030 * ref['ybm'])):
            if abs(got - want) > tol:
                return False, f'{sex} {label}: {got:.1f} vs ICRP {want:.1f}'
        out.append(f'{sex} {d["total"]/1000:.1f} kg, RBM {d["rbm"]:.0f} g')
    return True, '; '.join(out)


# Organ counts as distributed. The two adults of Publication 145 carry 187;
# the ten children of Publication 156 carry more, and more the older they are,
# because the paediatric series segments organs the adults leave in residual
# tissue. Counted from the .ele attributes of each phantom, not assumed.
ORGANS = {'AM': 187, 'AF': 187, '00M': 202, '00F': 202, '01M': 211,
          '01F': 211, '05M': 220, '05F': 220, '10M': 241, '10F': 241,
          '15M': 230, '15F': 230}


def c_organ_count():
    import make_umesh as M
    wrong = []
    for s in M.phantoms():
        n = len(assemble(s)['ids'])
        if n != ORGANS.get(s):
            wrong.append(f'{s} {n}, expected {ORGANS.get(s)}')
    if wrong:
        return False, '; '.join(wrong)
    return True, ', '.join(f'{s} {ORGANS[s]}' for s in M.phantoms())


def c_targets():
    import targets as T
    import make_umesh as M
    if not {'AM', 'AF'} <= set(M.phantoms()):
        return None, 'needs both adults installed'
    listed = {o for _, _, ids in T.TARGETS for o in ids}
    have = set(M.organ_ids('AM')) | set(M.organ_ids('AF'))
    absent = sorted(listed - have)
    # 813 is listed in ICRP-145 Annex D but is in neither distributed phantom
    return absent == [813], (f'{len(T.TARGETS)} targets; absent from both '
                             f'phantoms: {absent}')


def c_rbm_weights():
    import targets as T
    import make_umesh as M
    names = M.phantoms()
    for sex in names:
        bone = T.load_bone(sex)
        if any(bone.get(o, 0) <= 0 for o in T.RBM_REGIONS):
            return False, f'{sex}: an Annex D spongiosa region has no RBM fraction'
    return True, f'{len(T.RBM_REGIONS)} spongiosa regions, {len(names)} phantoms'


def write_deck(sex, case, extra=()):
    """One deck in a scratch directory: (path, text). Caller removes it.

    The work root is redirected for the duration, so a test never writes
    into the user's runs/.
    """
    import make_examples as X
    import make_umesh as M
    d = assemble(sex)
    if d is None:
        return None, None, None
    tmp = tempfile.mkdtemp()
    old, M.work_root = M.work_root, lambda: tmp
    try:
        cfg = X.parse_args(['--sex', sex, '--case', case, *extra])
        p = (X.write_internal if case == 'internal'
             else X.write_external)(sex, d, cfg)
    finally:
        M.work_root = old
    return tmp, p, open(p).read()


def c_generate():
    """make_examples writes a deck, and it has the cards it should."""
    import make_umesh as M
    sex = M.phantoms()[0]
    tmp, _p, text = write_deck(sex, 'internal')
    if tmp is None:
        return None, 'phantom data not validated'
    try:
        for want in ('UMESH', 'SOURCE', 'USRBIN', 'ASSIGNMA', 'GEOEND'):
            if f'\n{want}' not in '\n' + text:
                return False, f'generated deck has no {want} card'
        n = text.count('\nASSIGNMA')
        return n >= 187, f'{sex}: {n} ASSIGNMA cards'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def c_decks():
    """Every installed phantom writes a deck whose names FLUKA will accept.

    Read back, not trusted: every ASSIGNMA region, the UMESH SDUM, the mesh
    path, the SOURCE SDUM and the scoring range are checked against what
    UMESH will generate at run time -- 8 characters, letter first, alias
    plus organ ID. This is the check that would have caught the paediatric
    naming failure.
    """
    import re
    import make_umesh as M
    bad = []
    for sex in M.phantoms():
        d = assemble(sex)
        if d is None:
            bad.append(f'{sex}: data not validated')
            continue
        a = M.alias(sex)
        tmp, p, text = write_deck(sex, 'internal')
        try:
            case = os.path.dirname(p)
            names = re.findall(r'^ASSIGNMA\s+\S+\s+(\S+)', text, re.M)
            organs = {n for n in names if n.startswith(a) and n != a}
            wanted = {f'{a}{i}' for i in d['ids']}
            if organs != wanted:
                bad.append(f'{sex}: ASSIGNMA regions do not match the '
                           f'{len(d["ids"])} organs')
            illegal = [n for n in names
                       if len(n) > 8 or not n[0].isalpha()]
            if illegal:
                bad.append(f'{sex}: illegal FLUKA name {illegal[0]}')
            lines = text.splitlines()
            k = next(i for i, l in enumerate(lines) if l.startswith('UMESH'))
            sdum, mesh = lines[k].split()[-1], lines[k + 1]
            if sdum != a or len(sdum) > 3 or not sdum[0].isalpha():
                bad.append(f'{sex}: UMESH SDUM {sdum!r}')
            if os.path.isabs(mesh) or \
                    not os.path.exists(os.path.join(case, mesh)):
                bad.append(f'{sex}: mesh path does not resolve: {mesh}')
            src = next(l for l in lines if l.startswith('SOURCE'))
            if not src.split()[-1].isdigit():
                bad.append(f'{sex}: SOURCE SDUM is not a bare organ ID')
            if f'{a}{d["ids"][0]}' not in text or \
                    f'{a}{d["ids"][-1]}' not in text:
                bad.append(f'{sex}: scoring range does not span the organs')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if bad:
        return False, '; '.join(bad[:3])
    return True, f'{len(M.phantoms())} phantoms, every name checked'


def c_misuse():
    """Wrong usage must be refused with a message, never half-work.

    Each case is something a user has actually done or plausibly will:
    a nonexistent source organ, the --ecut/--physics combinations, a data
    path that is not the ICRP archive, and a deck for a phantom whose data
    is absent.
    """
    import io
    import contextlib
    import make_examples as X
    import make_umesh as M
    import setup_data as D

    def argv_fails(argv):
        try:
            with contextlib.redirect_stderr(io.StringIO()), \
                 contextlib.redirect_stdout(io.StringIO()):
                code = X.main(argv)
        except SystemExit as e:
            return e.code not in (0, None)
        return code not in (0, None)

    sex = M.phantoms()[0]
    if not argv_fails(['--sex', sex, '--organ', '99999',
                       '--case', 'internal']):
        return False, 'a nonexistent organ was accepted'
    if not argv_fails(['--sex', sex, '--case', 'external', '--energy', '0']):
        return False, 'zero energy was accepted'
    if not argv_fails(['--sex', sex, '--case', 'external', '--energy', '-5']):
        return False, 'negative energy was accepted (momentum, silently)'
    if not argv_fails(['--sex', sex, '--case', 'external',
                       '--primaries', '-100']):
        return False, 'negative primaries were accepted'
    if not argv_fails(['--physics', 'custom']):
        return False, '--physics custom without --ecut was accepted'
    if not argv_fails(['--ecut', '0.5']):
        return False, '--ecut without --physics custom was accepted'
    if not argv_fails(['--physics', 'custom', '--ecut', '-1',
                       '--case', 'external', '--sex', sex]):
        return False, 'a negative electron cut was accepted'

    tmp = tempfile.mkdtemp()
    try:
        junk = os.path.join(tmp, 'not_the_icrp.zip')
        import zipfile
        with zipfile.ZipFile(junk, 'w') as z:
            z.writestr('readme.txt', 'nothing useful')
        ok, _msg = D.setup(junk, root=os.path.join(tmp, 'out'),
                           log=lambda *a: None)
        if ok:
            return False, 'a zip with no phantom data was accepted'
        try:
            if M.assemble('XX') is not None:
                return False, 'an unknown phantom assembled'
        except Exception:                                     # noqa: BLE001
            pass      # refusing by exception is acceptable for a bad name
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return True, 'wrong organ, wrong flags, wrong zip, wrong phantom refused'


def c_comment_guard():
    """A comment must never be able to parse as a disabled FLUKA card."""
    import make_umesh as M
    try:
        M.comment('SOURCE SDUM is 9500')
    except ValueError:
        return True, f'{len(M.CARD_TAGS)} card tags guarded'
    return False, 'the guard did not fire on a comment starting with SOURCE'


def transport_one(sex, primaries):
    """A short external run: (ok, detail). External needs no executable but
    still loads the mesh, generates every region, and exercises the scoring
    names, which is where a bad deck fails."""
    tmp, p, _text = write_deck(sex, 'external',
                               ('--primaries', str(primaries)))
    if tmp is None:
        return None, 'phantom data not validated'
    try:
        run = os.path.dirname(p)
        # make_examples already wrote a path relative to this case directory,
        # and it must stay relative: FLUKA rejects an absolute mesh path
        r = subprocess.run(['rfluka', '-N0', '-M1', os.path.basename(p)[:-4]],
                           cwd=run, capture_output=True, text=True, timeout=1800)
        out = os.path.join(run, os.path.basename(p)[:-4] + '001.out')
        if not os.path.exists(out):
            return False, 'no .out produced; ' + (r.stdout or '')[-160:]
        txt = open(out, errors='replace').read()
        if 'Error loading umesh' in txt:
            return False, 'FLUKA could not load the mesh'
        if 'Invalid region' in txt or 'invalid token' in txt.lower():
            return False, 'FLUKA rejected a region name'
        for line in txt.splitlines():
            if 'GeV electro' in line:
                frac = float(line.split()[0])
                return frac > 0, f'{frac:.3e} GeV/primary deposited'
        return False, 'no energy balance in the .out'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def c_fluka_run():
    """One short run, to prove the mesh loads and energy is deposited."""
    import make_umesh as M
    if not shutil.which('rfluka'):
        return None, 'rfluka not on PATH'
    sex = M.phantoms()[0]
    ok, detail = transport_one(sex, 2000)
    return ok, f'{sex}: {detail}'


def merged_peak(run, n, sex):
    """(region, organ, share) of the highest-energy organ, or None."""
    import read_doses as R
    if not os.path.exists(os.path.join(run, n + '001_fort.21')):
        return None
    subprocess.run(['usbsuw'], cwd=run, text=True, capture_output=True,
                   input=f'{n}001_fort.21\n\n{n}_sum\n')
    subprocess.run(['usbrea'], cwd=run, text=True, capture_output=True,
                   input=f'{n}_sum.bnn\n{n}_sum.lis\n\n')
    lis = os.path.join(run, n + '_sum.lis')
    if not os.path.exists(lis):
        return None
    vals, _e = R.read_usrbin_ascii(lis)
    rows = R.load_regions(sex, run)
    best = max(zip(vals, rows), key=lambda t: t[0])
    return best[1]['region'], best[1]['organ'], best[0] / (sum(vals) or 1.0)


def c_internal_run():
    """The whole internal chain: deck, executable, transport, merged doses.

    The pass criterion is that the source organ receives more energy than
    any other -- the one check that catches a wrong SOURCE SDUM, which
    otherwise runs silently with every primary at the origin.
    """
    import make_examples as X
    import make_umesh as M
    import read_doses as R
    import build_exe as B
    if not shutil.which('rfluka'):
        return None, 'rfluka not on PATH'
    sex = M.phantoms()[0]
    tmp, p, _text = write_deck(sex, 'internal', ('--primaries', '2000'))
    if tmp is None:
        return None, 'phantom data not validated'
    try:
        run = os.path.dirname(p)
        n = os.path.basename(p)[:-4]
        ok, msg = B.build(log=lambda *a: None, dest=run)
        if not ok:
            return None, f'flukamrcp not built: {msg}'
        r = subprocess.run(['rfluka', '-e', './flukamrcp', '-N0', '-M1', n],
                           cwd=run, capture_output=True, text=True,
                           timeout=1800)
        got = merged_peak(run, n, sex)
        if got is None:
            return False, 'no merged result; ' + (r.stdout or '')[-120:]
        region, organ, share = got
        okd = region.endswith(str(X.ICRP_ORGAN))
        return okd, (f'{sex}: top energy in {organ} '
                     f'({100 * share:.0f} % of total)')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def c_sabotage():
    """Deliberately broken runs must fail visibly, not produce numbers.

    Two classics: the internal case run without its executable, and a
    SOURCE SDUM carrying the region name instead of the bare organ ID --
    the one FLUKA accepts silently, which the source-organ energy check
    of c_internal_run exists to catch. Both are staged here and both must
    be caught.
    """
    import make_umesh as M
    if not shutil.which('rfluka'):
        return None, 'rfluka not on PATH'
    sex = M.phantoms()[0]

    # Forgotten -e: FLUKA does NOT stop -- its default source runs a beam
    # from the origin and every dose is wrong. The energy-peak check is
    # what catches it, so here it must see the peak away from the source.
    tmp, p, _text = write_deck(sex, 'internal', ('--primaries', '2000'))
    try:
        run = os.path.dirname(p)
        n = os.path.basename(p)[:-4]
        subprocess.run(['rfluka', '-N0', '-M1', n], cwd=run,
                       capture_output=True, text=True, timeout=1800)
        got = merged_peak(run, n, sex)
        if got is not None:
            import make_examples as X
            if got[0].endswith(str(X.ICRP_ORGAN)):
                return False, ('a run without the executable still peaked '
                               'in the source organ -- undetectable')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # wrong SDUM: runs, but the source-organ check must see the peak move
    import make_examples as X
    import read_doses as R
    import build_exe as B
    tmp, p, text = write_deck(sex, 'internal', ('--primaries', '2000'))
    try:
        run = os.path.dirname(p)
        n = os.path.basename(p)[:-4]
        a = M.alias(sex)
        lines = text.splitlines()
        k = next((i for i, l in enumerate(lines)
                  if l.startswith('SOURCE')), None)
        if k is None:
            return False, 'could not stage the wrong SDUM'
        lines[k] = M.card('SOURCE', (1.0,), f'{a}{X.ICRP_ORGAN}')
        open(p, 'w').write('\n'.join(lines) + '\n')
        ok, msg = B.build(log=lambda *_a: None, dest=run)
        if not ok:
            return None, f'flukamrcp not built: {msg}'
        subprocess.run(['rfluka', '-e', './flukamrcp', '-N0', '-M1', n],
                       cwd=run, capture_output=True, text=True, timeout=1800)
        got = merged_peak(run, n, sex)
        if got is None:
            return True, 'no-exe caught; wrong SDUM produced no scores'
        region, organ, _share = got
        caught = not region.endswith(str(X.ICRP_ORGAN))
        return caught, (f'no-exe and wrong-SDUM both move the peak '
                        f'(to {organ}) -- the energy check catches them'
                        if caught else
                        'wrong SDUM still peaked in the source organ')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def c_transport_all():
    """Every installed phantom through FLUKA once. About a minute each."""
    import make_umesh as M
    if not shutil.which('rfluka'):
        return None, 'rfluka not on PATH'
    for sex in M.phantoms():
        ok, detail = transport_one(sex, 1000)
        if ok is not True:
            return ok, f'{sex}: {detail}'
        print(f'         {sex}: {detail}')
    return True, f'{len(M.phantoms())} phantoms transported'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fluka', action='store_true',
                    help='also run FLUKA on a tiny case')
    ap.add_argument('--transport', action='store_true',
                    help='run FLUKA once per installed phantom '
                         '(about a minute each)')
    a = ap.parse_args()

    print('environment')
    check('Python 3.8 or newer', c_python)
    check('FLUKA on PATH', c_fluka)
    check('source-routine executable', c_source_routine)
    print('phantom data')
    ok = check('ICRP files present', c_data)
    if ok:
        print('phantom construction')
        check('reference masses reproduced', c_reference_masses)
        check('organ count per phantom', c_organ_count)
        print('tables')
        check('target regions resolve to real organs', c_targets)
        check('red marrow weights present', c_rbm_weights)
        print('input generation')
        check('a deck is written with the right cards', c_generate)
        check('every phantom writes a legal deck', c_decks)
        check('wrong usage is refused', c_misuse)
        check('comment guard fires', c_comment_guard)
        if a.fluka or a.transport:
            print('transport')
        if a.fluka:
            check('FLUKA runs and deposits energy', c_fluka_run)
            check('internal source lands in the source organ', c_internal_run)
            check('sabotaged runs are caught', c_sabotage)
        if a.transport:
            check('every phantom transports', c_transport_all)

    n_fail = sum(1 for s, _, _ in results if s == FAIL)
    n_skip = sum(1 for s, _, _ in results if s == SKIP)
    n_pass = sum(1 for s, _, _ in results if s == PASS)
    print(f'\n{n_pass} passed, {n_fail} failed, {n_skip} skipped')
    if not a.fluka:
        print('Transport was not exercised. Run with --fluka to include it.')
    return 1 if n_fail else 0


if __name__ == '__main__':
    sys.exit(main())
