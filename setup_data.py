#!/usr/bin/env python3
"""Put the ICRP-145 data where the toolkit can use it.

    python3 setup_data.py ~/Downloads/P145*.zip     unpack the ICRP download
    python3 setup_data.py --status                  what is found, and where

Takes the archive exactly as downloaded from ICRP and extracts the eleven files
the toolkit needs -- nothing else, so about 1.3 GB instead of 2.7 GB. Four of
those files live inside a second archive nested in the first.

The location is remembered in .datapath, so it need only be given once and no
environment variable has to be set.
"""

__version__ = '1.2.3'

import argparse
import os
import shutil
import sys
import zipfile

import make_umesh as M

HERE = os.path.dirname(os.path.abspath(__file__))

MESH = ['.ele', '.node', '_media.dat', '_bone.dat', '_blood.dat']
TABLES = ['cell', 'material']

# The bronchial airway model. ICRP ships it in a second archive,
# MRCP_GEANT4_lung_airway.zip, not in the electronic files. It is optional:
# without it everything works except the airway scoring.
AIRWAY = ['.lung', '.lungDiam', '.lungvol']


def wanted(root):
    """The phantoms to look for: every one whose reference masses are known."""
    return list(M.REFERENCE)


def needed(root, names=None):
    """Every file the toolkit needs for the phantoms present in the archive.

    An archive holds either the two adults of Publication 145 or the ten
    children of Publication 156, so the caller passes the names it found and
    only those are required. With no names given, every phantom is listed,
    which is what --status wants.
    """
    out = []
    for sex in (names if names is not None else wanted(root)):
        for suf in MESH:
            out.append((os.path.join(root, f'MRCP_{sex}', f'MRCP_{sex}{suf}'),
                        f'MRCP_{sex}{suf}'))
        for t in TABLES:
            out.append((os.path.join(root, 'mcnp_tables',
                                     f'mrcp-{sex.lower()}.{t}'),
                        f'mrcp-{sex.lower()}.{t}'))
    return out


def present(root):
    """Phantoms that are fully installed under root."""
    return [s for s in wanted(root)
            if all(os.path.exists(p) for p, _ in needed(root, [s]))]


def airway_files(root, names=None):
    """The optional airway files, and whether each is present."""
    return [(os.path.join(root, f'MRCP_{s}', f'MRCP_{s}{e}'), f'MRCP_{s}{e}')
            for s in (names if names is not None else present(root))
            for e in AIRWAY]


def have_airway(root, names=None):
    f = airway_files(root, names)
    return bool(f) and all(os.path.exists(p) for p, _ in f)


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


def phantom_of(base):
    """Which phantom a file belongs to, from its name.

    The archives are not consistent: the mesh is MRCP_10M.ele, the organ table
    is mrcp-10m.cell, and the airway file is MRCP-10F.lung with a hyphen where
    the adults used an underscore. Matching on the phantom code rather than the
    whole filename copes with all three.
    """
    up = base.upper()
    for name in M.REFERENCE:
        if f'MRCP_{name}' in up or f'MRCP-{name}' in up:
            return name
    return None


def from_zip(zpath, root, log=print):
    """Extract what the toolkit needs from the ICRP download.

    The mesh and the .dat tables sit in Phantom_data/. The organ tables are
    inside MC_examples/MRCP_MCNP6.zip and the airway model inside
    MC_examples/MRCP_GEANT4_lung_airway.zip, both archives within the first,
    streamed out and read without ever being written to disk whole.

    Publication 145 holds the two adults and Publication 156 the ten children;
    the same code reads either, taking whichever phantoms it finds.
    """
    mesh_suf = {s.upper(): s for s in MESH}
    air_suf = {s.upper(): s for s in AIRWAY}
    tab_suf = {t.upper(): t for t in TABLES}
    n, found = 0, set()

    def take(src_zip, member, base, sub):
        dest = os.path.join(root, sub, base)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(dest):
            return False
        log(f'   extracting {base} ...' if sub != 'mcnp_tables'
            else f'   extracted {base}')
        with src_zip.open(member) as src, open(dest, 'wb') as out:
            shutil.copyfileobj(src, out, 1024 * 1024)
        return True

    def suffix_of(base, suffixes):
        up = base.upper()
        for suf in suffixes:
            if up.endswith(suf):
                return suf
        return None

    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        for member in names:
            base = os.path.basename(member)
            name = phantom_of(base)
            if not name:
                continue
            suf = suffix_of(base, mesh_suf)
            if suf and 'PHANTOM_DATA' in member.upper():
                take(z, member, f'MRCP_{name}{mesh_suf[suf]}', f'MRCP_{name}')
                found.add(name)
                n += 1

        # the organ tables, and the airway model, each in a nested archive
        for inner_name, suffixes, sub_of in (
                ('MRCP_MCNP6.ZIP', tab_suf, lambda nm: 'mcnp_tables'),
                ('MRCP_GEANT4_LUNG_AIRWAY.ZIP', air_suf,
                 lambda nm: f'MRCP_{nm}')):
            inner = next((m for m in names
                          if os.path.basename(m).upper() == inner_name), None)
            if not inner:
                continue
            log(f'   opening {os.path.basename(inner)} ...')
            import io
            with z.open(inner) as f:
                blob = io.BytesIO(f.read())
            with zipfile.ZipFile(blob) as z2:
                for m2 in z2.namelist():
                    b2 = os.path.basename(m2)
                    nm = phantom_of(b2)
                    if not nm or not suffix_of(b2, suffixes):
                        continue
                    suf = suffix_of(b2, suffixes)
                    if suffixes is tab_suf:
                        out_name = f'mrcp-{nm.lower()}.{suffixes[suf]}'
                    else:
                        out_name = f'MRCP_{nm}{suffixes[suf]}'
                    take(z2, m2, out_name, sub_of(nm))
    return n


def setup(source, root=None, log=print):
    """Make the data usable, from a zip or a folder. Returns (ok, message)."""
    # under the work root, never beside the code: this is 900 MB and
    # the toolkit must stay as it was installed
    root = root or os.path.join(M.work_root(), 'phantom')
    os.makedirs(root, exist_ok=True)
    if source:
        if os.path.isdir(source):
            log(f'copying from {source} ...')
            from_folder(source, root, log)
        elif zipfile.is_zipfile(source):
            log(f'reading {os.path.basename(source)} ...')
            from_zip(source, root, log)
        else:
            return False, (f'{os.path.basename(source)} is neither a zip '
                           f'archive nor a folder. Give the archive exactly '
                           f'as downloaded from ICRP, or a folder it was '
                           f'unpacked into.')
    # Completeness is per phantom, not over the whole catalogue: an archive
    # holds the two adults or the ten children, and having one publication is
    # not a broken install.
    ok = present(root)
    if not ok:
        _have, miss = status(root)
        return False, (f'no complete phantom in {root}; first missing file is '
                       f'{os.path.basename(miss[0][1])}')
    M.set_data_dir(root)
    M._refresh()
    air = [s for s in ok if have_airway(root, [s])]
    msg = f'{len(ok)} phantom(s) in {root}: ' + ' '.join(ok)
    if air:
        msg += f'\n   airway model for: ' + ' '.join(air)
    return True, msg


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('source', nargs='?',
                    help='P145 Electronic files.zip, exactly as downloaded')
    ap.add_argument('--into', help='where to put it (default ./phantom)')
    ap.add_argument('--status', action='store_true')
    a = ap.parse_args()

    if a.status:
        root = M.data_dir()
        ok = present(root)
        print(f'data location: {root}')
        if not ok:
            print('  no phantom installed')
            return 1
        for s in ok:
            air = 'with airway model' if have_airway(root, [s]) else 'no airway model'
            print(f'  {s:4s} {len(needed(root, [s]))} files, {air}')
        partial = [s for s in wanted(root) if s not in ok and any(
            os.path.exists(p) for p, _ in needed(root, [s]))]
        for s in partial:
            print(f'  {s:4s} incomplete')
        return 0

    if not a.source:
        ap.error('give the ICRP zip, or use --status')
    ok, msg = setup(a.source, a.into)
    print(('ok: ' if ok else 'failed: ') + msg)
    if ok:
        print('Remembered. No environment variable is needed.')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
