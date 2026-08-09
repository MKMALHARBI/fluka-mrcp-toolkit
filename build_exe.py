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

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, 'flukamrcp')


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


def build(log=print, force=False):
    """Compile and link. Returns (ok, message)."""
    if not force and os.access(EXE, os.X_OK):
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

    work = os.path.join(HERE, '.build')
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    shutil.copy2(src, os.path.join(work, 'mrcp_source.f'))
    log(f'   source: {src}')
    try:
        log('   fff mrcp_source.f')
        r = subprocess.run(['fff', 'mrcp_source.f'], cwd=work,
                           capture_output=True, text=True)
        if r.returncode:
            return False, 'compile failed:\n' + (r.stderr or r.stdout)[-1200:]
        log('   lfluka -m fluka -o flukamrcp mrcp_source.o')
        r = subprocess.run(['lfluka', '-m', 'fluka', '-o', 'flukamrcp',
                            'mrcp_source.o'], cwd=work,
                           capture_output=True, text=True)
        if r.returncode:
            return False, 'link failed:\n' + (r.stderr or r.stdout)[-1200:]
        built = os.path.join(work, 'flukamrcp')
        if not os.path.exists(built):
            return False, 'the link step produced no executable'
        shutil.move(built, EXE)
        os.chmod(EXE, 0o755)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return True, f'built flukamrcp ({os.path.getsize(EXE) / 1e6:.0f} MB)'


def main():
    ok, msg = build(force='--force' in sys.argv)
    print(('ok: ' if ok else 'failed: ') + msg)
    if ok:
        print('The internal-exposure case can now be run.')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
