#!/usr/bin/env python3
"""Turn the ICRP tetrahedral mesh into a voxel label volume, once.

    python3 voxelise.py AM [--mm 2.0]   (default: scaled to phantom height)

Slicing 8.2 million tetrahedra takes about fifteen seconds, which is no use
for scrolling. Voxelising once and caching the result makes every slice a
single array index. The cache is <sex>_<mm>mm.npz beside this script and is
reused until deleted.

Each tetrahedron is dropped into the voxel holding its centroid. Tetrahedra
average about 2 mm across, so at 2 mm a few voxels inside the body catch none;
those are filled from the nearest labelled voxel, which is what the mesh would
have said anyway.
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_umesh as M                                            # noqa: E402

DATA = M.data_dir()
CACHE = M.work_root()          # the cache is generated, so it lives with the rest


def numbers(path):
    with open(path) as f:
        t = f.read()
    c = t.find('#')
    return np.fromstring(t[:c] if c >= 0 else t, sep=' ')


def read_mesh(sex, data=DATA):
    d = os.path.join(data, f'MRCP_{sex}')
    raw = numbers(os.path.join(d, f'MRCP_{sex}.node'))
    n = int(raw[0])
    nodes = raw[4:4 + n * 4].reshape(n, 4)[:, 1:].astype(np.float32)
    raw = numbers(os.path.join(d, f'MRCP_{sex}.ele'))
    m = int(raw[0])
    body = raw[3:3 + m * 6].reshape(m, 6).astype(np.int64)
    return nodes, body[:, 1:5], body[:, 5].astype(np.int32)


def pitch(sex):
    """Grid pitch scaled to the phantom, 2 mm on the 176 cm adult male.

    A fixed pitch renders the 51 cm newborn 3.5x coarser than the adult;
    scaling by reference height gives every phantom the same resolution
    relative to its own anatomy, at about the same voxel count.
    """
    return round(2.0 * M.REFERENCE[sex]['height'] / 176.0, 1)


def build(sex, mm=None, data=DATA, log=print):
    mm = mm or pitch(sex)
    nodes, tets, oid = read_mesh(sex, data)
    log(f'{len(tets):,} tetrahedra, {len(nodes):,} nodes')
    cell = mm / 10.0                    # the mesh is in centimetres
    lo = nodes.min(0) - cell
    hi = nodes.max(0) + cell
    dim = np.ceil((hi - lo) / cell).astype(int) + 1
    log(f'grid {dim[0]} x {dim[1]} x {dim[2]} at {mm} mm')

    # One sample per tetrahedron leaves about a third of the voxels inside the
    # body untouched, because there is roughly one tetrahedron per voxel and
    # they land at random. Sampling each one at several points inside itself
    # covers every voxel it overlaps. Done in chunks: 8 samples over 8.2
    # million tetrahedra is 66 million points.
    grid = np.zeros(tuple(dim), np.int32)
    rng = np.random.default_rng(0)
    vcell = cell ** 3
    a, b, c, d = (nodes[tets[:, i]].astype(np.float64) for i in range(4))
    vol = np.abs(np.einsum('ij,ij->i', b - a, np.cross(c - a, d - a))) / 6.0
    # a tetrahedron bigger than a voxel needs more than one sample to cover
    # every voxel it overlaps; the thigh muscles are meshed far coarser than
    # the organs and are what a fixed count misses
    nsamp = np.clip(np.ceil(vol / vcell * 4.0), 4, 300).astype(np.int32)
    log(f'{nsamp.sum():,} samples for {len(tets):,} tetrahedra')

    step = 300_000
    for s0 in range(0, len(tets), step):
        sl = slice(s0, s0 + step)
        t, o, k = tets[sl], oid[sl], nsamp[sl]
        v = nodes[t]
        rep = np.repeat(np.arange(len(t)), k)
        w = rng.random((len(rep), 4)).astype(np.float32)
        w /= w.sum(1, keepdims=True)
        pts = np.einsum('nj,njc->nc', w, v[rep])
        idx = np.floor((pts - lo) / cell).astype(np.int32)
        np.clip(idx, 0, dim - 1, out=idx)
        grid[idx[:, 0], idx[:, 1], idx[:, 2]] = np.repeat(o, k)
    log(f'{int((grid > 0).sum()):,} voxels labelled by sampling')

    # whatever is still empty inside the body takes the nearest label
    from scipy import ndimage
    lab = grid > 0
    body = ndimage.binary_fill_holes(
        ndimage.binary_closing(lab, ndimage.generate_binary_structure(3, 1),
                               iterations=2))
    holes = body & ~lab
    if holes.any():
        _d, ind = ndimage.distance_transform_edt(~lab, return_indices=True,
                                                 return_distances=True)
        grid[holes] = grid[tuple(ind)][holes]
    log(f'{int(holes.sum()):,} filled, {int((grid > 0).sum()):,} labelled')

    os.makedirs(CACHE, exist_ok=True)
    out = os.path.join(CACHE, f'{sex}_{mm:g}mm.npz')
    np.savez_compressed(out, grid=grid.astype(np.int32), lo=lo, cell=cell)
    log(f'-> {out} ({os.path.getsize(out)/1e6:.0f} MB)')
    return out


def load(sex, mm=None):
    mm = mm or pitch(sex)
    f = os.path.join(CACHE, f'{sex}_{mm:g}mm.npz')
    if not os.path.exists(f):
        return None
    z = np.load(f)
    return z['grid'], z['lo'], float(z['cell'])


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('sex', choices=list(M.REFERENCE))
    ap.add_argument('--mm', type=float, default=None)
    a = ap.parse_args()
    build(a.sex, a.mm)
