#!/usr/bin/env python3
"""Build the FLUKA executable the internal-exposure case needs.

    python3 build_exe.py

Starting a particle at a random point inside a tetrahedral organ needs FLUKA's
tetrarndpt subroutine, reachable only from a source routine. FLUKA ships one
that already does this, at

    $FLUKA/examples/umesh/umesh_source_newgen.f

and it works unmodified: the organ and the mesh index both come from the SOURCE
card at run time, so one executable serves any organ and either phantom.

This compiles that file from your own FLUKA installation and leaves the result
here as flukamrcp. Nothing of CERN's is shipped with the toolkit: the source is
read from your installation and the executable stays on your machine, which is
what the FLUKA licence requires.
"""

__version__ = '1.1.0'

import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_umesh as M                                            # noqa: E402

# One executable per case, beside the input it runs. A case then carries
# everything it needs and can be moved, archived or handed on whole.
EXE = os.path.join(M.work_root(), 'flukamrcp')


def exe_for(case_dir):
    return os.path.join(case_dir, 'flukamrcp')


def fluka_root():
    """The FLUKA installation: $FLUKA, $FLUPRO, or wherever rfluka lives."""
    for var in ('FLUKA', 'FLUPRO'):
        p = os.environ.get(var)
        if p and os.path.isdir(p):
            return p
    r = shutil.which('rfluka')
    if r:
        return os.path.dirname(os.path.dirname(os.path.realpath(r)))
    return None


def source_file(root=None):
    root = root or fluka_root()
    if not root:
        return None
    p = os.path.join(root, 'examples', 'umesh', 'umesh_source_newgen.f')
    return p if os.path.exists(p) else None


def build(log=print, force=False, dest=None):
    """Compile and link. Returns (ok, message)."""
    exe = dest and exe_for(dest) or EXE
    if not force and os.access(exe, os.X_OK):
        return True, 'flukamrcp is already built'
    root = fluka_root()
    if not root:
        return False, ('FLUKA not found. Put rfluka on PATH, or set FLUKA to '
                       'the installation directory.')
    src = source_file(root)
    if not src:
        return False, (f'{root}/examples/umesh/umesh_source_newgen.f not found. '
                       f'It ships with FLUKA 4; check the installation.')
    for tool in ('fff', 'lfluka'):
        if not shutil.which(tool):
            return False, f'{tool} is not on PATH; it lives in $FLUKA/bin'

    os.makedirs(os.path.dirname(exe), exist_ok=True)
    work = os.path.join(M.work_root(), '.build')
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    shutil.copy2(src, os.path.join(work, 'mrcp_source.f'))
    log(f'   source: {src}')
    # The airway routines are ours and are always linked in. They cost nothing
    # unless an input asks for a type 8 binning, and linking them here means one
    # executable serves both plain and airway cases.
    extra = [f for f in ('airway.f', 'musrbr.f', 'lusrbl.f')
             if os.path.exists(os.path.join(HERE, f))]
    for f in extra + (['airway.inc'] if os.path.exists(
            os.path.join(HERE, 'airway.inc')) else []):
        shutil.copy2(os.path.join(HERE, f), os.path.join(work, f))
    try:
        objs = []
        for f in ['mrcp_source.f'] + extra:
            log(f'   fff {f}')
            r = subprocess.run(['fff', f], cwd=work,
                               capture_output=True, text=True)
            if r.returncode:
                return False, (f'compile failed on {f}:\n'
                               + (r.stderr or r.stdout)[-1200:])
            objs.append(f[:-2] + '.o')
        log('   lfluka -m fluka -o flukamrcp ' + ' '.join(objs))
        r = subprocess.run(['lfluka', '-m', 'fluka', '-o', 'flukamrcp'] + objs,
                           cwd=work, capture_output=True, text=True)
        if r.returncode:
            return False, 'link failed:\n' + (r.stderr or r.stdout)[-1200:]
        built = os.path.join(work, 'flukamrcp')
        if not os.path.exists(built):
            return False, 'the link step produced no executable'
        shutil.move(built, exe)
        os.chmod(exe, 0o755)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return True, f'built flukamrcp ({os.path.getsize(exe) / 1e6:.0f} MB)'


def needs_exe(case_dir):
    """True if this case has a source routine or an airway binning."""
    inp = glob.glob(os.path.join(case_dir, '*.inp'))
    if not inp:
        return False
    text = open(inp[0]).read()
    return '\nSOURCE' in '\n' + text or 'airway' in text


def main():
    """Build into the case directories given, or into every case that needs one.

    The executable belongs to the case, so there is never a shared copy that a
    case might or might not match.
    """
    force = '--force' in sys.argv
    dests = [a for a in sys.argv[1:] if not a.startswith('-')]
    if not dests:
        dests = [d for d in sorted(glob.glob(os.path.join(M.work_root(), '*')))
                 if os.path.isdir(d) and needs_exe(d)]
        if not dests:
            print('no case needs an executable; generate one with '
                  'make_examples.py first')
            return 1
    rc = 0
    for d in dests:
        ok, msg = build(force=force, dest=d)
        print(f'{os.path.relpath(d, M.work_root())}: '
              + ('ok: ' if ok else 'failed: ') + msg)
        rc |= 0 if ok else 1
    return rc


if __name__ == '__main__':
    sys.exit(main())
