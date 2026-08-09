#!/usr/bin/env python3
"""Put the ICRP-145 data where the toolkit can use it.

    python3 setup_data.py ~/Downloads/P145*.zip     unpack the ICRP download
    python3 setup_data.py /some/folder              use a folder already unpacked
    python3 setup_data.py --status                  what is found, and where

Takes the archive exactly as downloaded from ICRP and extracts the eleven files
the toolkit needs -- nothing else, so about 1.3 GB instead of 2.7 GB. Four of
those files live inside a second archive nested in the first.

The location is remembered in .datapath, so it need only be given once and no
environment variable has to be set.
"""

__version__ = '1.1.0'

import argparse
import os
import re
import shutil
import sys
import zipfile

import make_umesh as M

HERE = os.path.dirname(os.path.abspath(__file__))

MESH = ['.ele', '.node', '_media.dat', '_bone.dat', '_blood.dat']
TABLES = ['cell', 'material']


def needed(root):
    """Every file the toolkit needs, and whether it is present under root."""
    out = []
    for sex in ('AM', 'AF'):
        for suf in MESH:
            out.append((os.path.join(root, f'MRCP_{sex}', f'MRCP_{sex}{suf}'),
                        f'MRCP_{sex}{suf}'))
        for t in TABLES:
            out.append((os.path.join(root, 'mcnp_tables', f'mrcp-{sex.lower()}.{t}'),
                        f'mrcp-{sex.lower()}.{t}'))
    return out


def status(root):
    have = [(p, n) for p, n in needed(root) if os.path.exists(p)]
    miss = [(p, n) for p, n in needed(root) if not os.path.exists(p)]
    return have, miss


def from_folder(src, root, log=print):
    """Copy or link the needed files out of an already-unpacked folder."""
    index = {}
    for dirpath, _dirs, files in os.walk(src, followlinks=True):
        for f in files:
            index.setdefault(f, os.path.join(dirpath, f))
    found = 0
    for dest, name in needed(root):
        if os.path.exists(dest):
            found += 1
            continue
        src_file = index.get(name)
        if not src_file:
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src_file, dest)
        log(f'   copied {name}')
        found += 1
    return found


def from_zip(zpath, root, log=print):
    """Extract the needed members from the ICRP download.

    The mesh and the .dat tables sit in Phantom_data/. The four organ tables are
    inside MC_examples/MRCP_MCNP6.zip, a second archive within the first, so it
    is streamed out and read without ever being written to disk whole.
    """
    want_mesh = {f'MRCP_{s}{suf}' for s in ('AM', 'AF') for suf in MESH}
    want_tab = {f'mrcp-{s}.{t}' for s in ('am', 'af') for t in TABLES}
    n = 0
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        for member in names:
            base = os.path.basename(member)
            if base in want_mesh:
                sex = 'AM' if '_AM' in base else 'AF'
                dest = os.path.join(root, f'MRCP_{sex}', base)
                if os.path.exists(dest):
                    n += 1
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                log(f'   extracting {base} ...')
                with z.open(member) as src, open(dest, 'wb') as out:
                    shutil.copyfileobj(src, out, 1024 * 1024)
                n += 1

        inner = next((m for m in names
                      if os.path.basename(m).upper() == 'MRCP_MCNP6.ZIP'), None)
        if inner and any(not os.path.exists(p) for p, nm in needed(root)
                         if nm in want_tab):
            log('   opening the MCNP6 archive for the organ tables ...')
            import io
            with z.open(inner) as f:
                blob = io.BytesIO(f.read())
            with zipfile.ZipFile(blob) as z2:
                for m2 in z2.namelist():
                    b2 = os.path.basename(m2)
                    if b2 in want_tab:
                        dest = os.path.join(root, 'mcnp_tables', b2)
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        with z2.open(m2) as src, open(dest, 'wb') as out:
                            shutil.copyfileobj(src, out)
                        log(f'   extracted {b2}')
    return n


def setup(source, root=None, log=print):
    """Make the data usable, from a zip or a folder. Returns (ok, message)."""
    root = root or os.path.join(HERE, 'phantom')
    os.makedirs(root, exist_ok=True)
    if source:
        if os.path.isdir(source):
            have, _ = status(source)
            if not status(source)[1]:           # already in the right shape
                M.set_data_dir(source)
                M._refresh()
                return True, f'using the data already in {source}'
            log(f'looking through {source} ...')
            from_folder(source, root, log)
        elif zipfile.is_zipfile(source):
            log(f'reading {os.path.basename(source)} ...')
            from_zip(source, root, log)
        else:
            return False, f'{source} is neither a folder nor a zip archive'
    have, miss = status(root)
    if miss:
        return False, (f'{len(miss)} of {len(needed(root))} files still missing, first '
                       f'{os.path.basename(miss[0][1])}')
    M.set_data_dir(root)
    M._refresh()
    return True, f'all {len(needed(root))} files present in {root}'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('source', nargs='?',
                    help='the ICRP zip as downloaded, or a folder holding it')
    ap.add_argument('--into', help='where to put it (default ./phantom)')
    ap.add_argument('--status', action='store_true')
    a = ap.parse_args()

    if a.status:
        root = M.data_dir()
        have, miss = status(root)
        print(f'data location: {root}')
        print(f'  {len(have)} of {len(needed(root))} files present')
        for _p, n in miss:
            print(f'  missing: {n}')
        return 0 if not miss else 1

    if not a.source:
        ap.error('give the ICRP zip or a folder, or use --status')
    ok, msg = setup(a.source, a.into)
    print(('ok: ' if ok else 'failed: ') + msg)
    if ok:
        print('Remembered. No environment variable is needed.')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
