#!/usr/bin/env python3
"""Check an installation before committing to a long run.

    python3 selftest.py            everything that needs no transport
    python3 selftest.py --fluka    also run FLUKA on a tiny case (a few minutes)

Every check is against a value ICRP publishes, not against a value stored here,
so a pass means the phantom data was read correctly rather than that the code is
self-consistent.
"""

__version__ = '1.1.0'
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
    import build_exe as B
    if os.access(B.EXE, os.X_OK):
        return True, 'flukamrcp built'
    src = B.source_file()
    if not src:
        return None, 'FLUKA not found; needed only for the internal case'
    return None, 'not built yet -- run: python3 build_exe.py'


def c_data():
    import make_umesh as M
    missing = []
    for sex in ('AM', 'AF'):
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
    for sex in ('AM', 'AF'):
        d = M.assemble(sex)
        if d is None:
            return False, f'{sex}: validation failed, see the message above'
        ref = M.REFERENCE[sex]
        for label, got, want, tol in (
                ('mass', d['total'], ref['mass'], 0.005 * ref['mass']),
                ('RBM', d['rbm'], ref['rbm'], 0.02 * ref['rbm']),
                ('YBM', d['ybm'], ref['ybm'], 0.02 * ref['ybm'])):
            if abs(got - want) > tol:
                return False, f'{sex} {label}: {got:.1f} vs ICRP {want:.1f}'
        out.append(f'{sex} {d["total"]/1000:.1f} kg, RBM {d["rbm"]:.0f} g')
    return True, '; '.join(out)


def c_organ_count():
    import make_umesh as M
    n = [len(M.assemble(s)['ids']) for s in ('AM', 'AF')]
    return n == [187, 187], f'{n[0]} and {n[1]} organs'


def c_targets():
    import targets as T
    import make_umesh as M
    listed = {o for _, _, ids in T.TARGETS for o in ids}
    have = set(M.organ_ids('AM')) | set(M.organ_ids('AF'))
    absent = sorted(listed - have)
    # 813 is listed in ICRP-145 Annex D but is in neither distributed phantom
    return absent == [813], (f'{len(T.TARGETS)} targets; absent from both '
                             f'phantoms: {absent}')


def c_rbm_weights():
    import targets as T
    for sex in ('AM', 'AF'):
        bone = T.load_bone(sex)
        if any(bone.get(o, 0) <= 0 for o in T.RBM_REGIONS):
            return False, f'{sex}: an Annex D spongiosa region has no RBM fraction'
    return True, f'{len(T.RBM_REGIONS)} spongiosa regions, both phantoms'


def c_generate():
    """make_examples writes a deck, and it has the cards it should."""
    import make_examples as X
    import make_umesh as M
    d = M.assemble('AM')
    if d is None:
        return None, 'phantom data not validated'
    tmp = tempfile.mkdtemp()
    try:
        old, X.HERE = X.HERE, tmp
        cfg = X.parse_args(['--sex', 'AM', '--case', 'internal'])
        p = X.write_internal('AM', d, cfg)
        text = open(p).read()
        X.HERE = old
        for want in ('UMESH', 'SOURCE', 'USRBIN', 'ASSIGNMA', 'GEOEND'):
            if f'\n{want}' not in '\n' + text:
                return False, f'generated deck has no {want} card'
        n = text.count('\nASSIGNMA')
        return n >= 187, f'{n} ASSIGNMA cards'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def c_comment_guard():
    """A comment must never be able to parse as a disabled FLUKA card."""
    import make_umesh as M
    try:
        M.comment('SOURCE SDUM is 9500')
    except ValueError:
        return True, f'{len(M.CARD_TAGS)} card tags guarded'
    return False, 'the guard did not fire on a comment starting with SOURCE'


def c_fluka_run():
    """One short run, to prove the mesh loads and energy is deposited."""
    import make_examples as X
    import make_umesh as M
    if not shutil.which('rfluka'):
        return None, 'rfluka not on PATH'
    d = M.assemble('AM')
    if d is None:
        return None, 'phantom data not validated'
    tmp = tempfile.mkdtemp()
    try:
        old, X.HERE = X.HERE, tmp
        cfg = X.parse_args(['--sex', 'AM', '--case', 'external',
                            '--primaries', '2000'])
        p = X.write_external('AM', d, cfg)
        X.HERE = old
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
        for line in txt.splitlines():
            if 'GeV electro' in line:
                frac = float(line.split()[0])
                return frac > 0, f'{frac:.3e} GeV/primary deposited'
        return False, 'no energy balance in the .out'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fluka', action='store_true',
                    help='also run FLUKA on a tiny case')
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
        check('187 organs per phantom', c_organ_count)
        print('tables')
        check('target regions resolve to real organs', c_targets)
        check('red marrow weights present', c_rbm_weights)
        print('input generation')
        check('a deck is written with the right cards', c_generate)
        check('comment guard fires', c_comment_guard)
        if a.fluka:
            print('transport')
            check('FLUKA runs and deposits energy', c_fluka_run)

    n_fail = sum(1 for s, _, _ in results if s == FAIL)
    n_skip = sum(1 for s, _, _ in results if s == SKIP)
    n_pass = sum(1 for s, _, _ in results if s == PASS)
    print(f'\n{n_pass} passed, {n_fail} failed, {n_skip} skipped')
    if not a.fluka:
        print('Transport was not exercised. Run with --fluka to include it.')
    return 1 if n_fail else 0


if __name__ == '__main__':
    sys.exit(main())
