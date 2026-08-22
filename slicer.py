#!/usr/bin/env python3
"""Slice viewer for the ICRP-145 phantoms: anatomy, airways and dose.

    python3 slicer.py AM
    python3 slicer.py AM --lis path/to/..._sum.lis --regions path/to/AM_regions.csv

Scroll through the body a slab at a time. Choose the orientation, the slab
thickness, and which of the three layers to draw. Nothing here belongs to the
toolkit; it reads the same ICRP files and, if given one, a FLUKA result.

    arrow keys / mouse wheel   move through the slices
    the sliders                position and slab thickness
    the radio buttons          axial, coronal or sagittal
    the check buttons          anatomy, airways, dose

Anatomy is the voxelised mesh, one colour per organ. Dose replaces those
colours with the organ dose from the result file. Airways are the branches
crossing the slab, drawn over whatever is beneath.
"""
import argparse
import csv
import math
import os
import sys

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, RadioButtons, CheckButtons
from matplotlib.collections import LineCollection

import voxelise as V

HERE = os.path.dirname(os.path.abspath(__file__))
GEV_J = 1.602176634e-10
AXES = {'axial': 2, 'coronal': 1, 'sagittal': 0}
LABEL = {2: ('x (cm)', 'y (cm)'), 1: ('x (cm)', 'z (cm)'), 0: ('y (cm)', 'z (cm)')}


def organ_colours(ids, seed=3):
    rng = np.random.default_rng(seed)
    cols = plt.get_cmap('turbo')(rng.permutation(np.linspace(.03, .97, len(ids))))
    lut = np.zeros((int(ids.max()) + 1, 4), np.float32)
    lut[ids] = cols
    return lut


def read_airway(sex, data):
    d = os.path.join(data, f'MRCP_{sex}')
    f = os.path.join(d, f'MRCP_{sex}.lung')
    if not os.path.exists(f):
        return None, None
    rows = [l.split() for l in open(f) if l.split()]
    pos = np.array([[float(v) for v in r[1:4]] for r in rows], np.float32)
    ex = np.array([int(r[4]) for r in rows]).astype(bool)
    seg = np.array([(i // 2, i, int(math.log2(i)))
                    for i in range(2, len(rows)) if ex[i]], np.int32)
    return pos, seg


def read_dose(lis, regions):
    """organ ID -> dose in Gy per primary, from a FLUKA region binning.

    usbrea puts a couple of remarks between "Data follow" and the numbers,
    for instance that the binning is track-length, so a non-numeric line is
    only the end of the block once numbers have started. The first block is
    the values; a second block of percentage errors follows and is not read
    here.
    """
    if not (lis and regions):
        return None
    vals, started, block = [], False, False
    for line in open(lis):
        if 'Data follow' in line:
            block = True
            continue
        if not block:
            continue
        f = line.split()
        try:
            row = [float(x) for x in f]
        except ValueError:
            if started:
                break
            continue
        if not row:
            if started:
                break
            continue
        vals += row
        started = True
    rows = list(csv.DictReader(open(regions)))
    if len(vals) < len(rows):
        print(f'{lis}: {len(vals)} values for {len(rows)} organs', file=sys.stderr)
        return None
    return {int(r['organ_id']): v / float(r['volume_cm3']) * GEV_J * 1000.0
            for v, r in zip(vals, rows)}


class Viewer:
    def __init__(self, sex, mm, data, lis, regions):
        mm = mm or V.pitch(sex)
        got = V.load(sex, mm)
        if got is None:
            print(f'building the {mm} mm voxel cache, once ...')
            V.build(sex, mm, data)
            got = V.load(sex, mm)
        self.grid, self.lo, self.cell = got
        self.sex = sex
        self.ids = np.unique(self.grid)
        self.ids = self.ids[self.ids > 0]
        self.lut = organ_colours(self.ids)
        self.pos, self.seg = read_airway(sex, data)
        self.dose = read_dose(lis, regions)
        self.dlut = None
        if self.dose:
            d = np.array([self.dose.get(int(o), 0.0) for o in self.ids])
            good = d > 0
            # An external field gives most organs a similar dose, and one or
            # two outliers otherwise take the whole colour range. Clipping to
            # the 2nd and 98th percentiles spreads the bulk out; the extremes
            # saturate rather than flatten everything else.
            ld = np.log10(d[good])
            lo_, hi_ = np.percentile(ld, [2, 98])
            if hi_ - lo_ < 0.3:
                lo_, hi_ = ld.min(), ld.max()
            f = np.zeros(len(d))
            f[good] = np.clip((np.log10(d[good]) - lo_) / max(hi_ - lo_, 1e-9), 0, 1)
            self.dlut = np.zeros((int(self.ids.max()) + 1, 4), np.float32)
            self.dlut[self.ids] = plt.get_cmap('inferno')(f)
            self.drange = (10 ** lo_, 10 ** hi_)
            print(f'dose {d[good].min():.3e} to {d[good].max():.3e} Gy/primary, '
                  f'colour scale {self.drange[0]:.2e} to {self.drange[1]:.2e}')

        self.axis = 2
        self.thick = 2.0                      # mm
        self.build_ui()

    # ---------------------------------------------------------------- slab
    def slab(self):
        ax = self.axis
        n = self.grid.shape[ax]
        c = int(self.pos_slider.val)
        h = max(1, int(round(self.thick / (self.cell * 10))))
        a, b = max(0, c - h // 2), min(n, c + max(1, h - h // 2))
        sl = [slice(None)] * 3
        sl[ax] = slice(a, b)
        block = self.grid[tuple(sl)]
        # the organ seen most often through the slab
        flat = np.moveaxis(block, ax, 0).reshape(b - a, -1)
        if b - a == 1:
            lab = flat[0]
        else:
            lab = np.zeros(flat.shape[1], np.int32)
            nz = (flat > 0)
            first = np.argmax(nz, 0)
            has = nz.any(0)
            lab[has] = flat[first[has], np.arange(flat.shape[1])[has]]
        shape = [s for i, s in enumerate(self.grid.shape) if i != ax]
        return lab.reshape(shape), (a + b) / 2.0

    def extent(self):
        keep = [i for i in range(3) if i != self.axis]
        e = []
        for i in keep:
            e += [self.lo[i], self.lo[i] + self.grid.shape[i] * self.cell]
        return [e[0], e[1], e[2], e[3]]

    def draw(self, _=None):
        lab, mid = self.slab()
        show = {t.get_text(): s for t, s in zip(self.check.labels,
                                                self.check.get_status())}
        on = bool(show.get('dose')) and self.dlut is not None
        lut = self.dlut if on else self.lut
        self.cax.set_visible(on)
        rgba = lut[np.clip(lab, 0, len(lut) - 1)]
        if not show.get('anatomy') and not show.get('dose'):
            rgba[:] = 0
        rgba[lab == 0] = (1, 1, 1, 1)
        self.im.set_data(np.transpose(rgba, (1, 0, 2)))
        self.im.set_extent(self.extent())

        for c in list(self.ax.collections):
            c.remove()
        if show.get('airways') and self.seg is not None:
            z = self.lo[self.axis] + mid * self.cell
            half = self.thick / 20.0                       # mm -> cm, half slab
            p1 = self.pos[self.seg[:, 0]]
            p2 = self.pos[self.seg[:, 1]]
            keep = [i for i in range(3) if i != self.axis]
            hit = (np.minimum(p1[:, self.axis], p2[:, self.axis]) <= z + half) & \
                  (np.maximum(p1[:, self.axis], p2[:, self.axis]) >= z - half)
            if hit.any():
                segs = np.stack([p1[hit][:, keep], p2[hit][:, keep]], 1)
                gen = self.seg[hit, 2]
                cols = plt.get_cmap('cool')(gen / 16.0)
                self.ax.add_collection(LineCollection(segs, colors=cols,
                                                      linewidths=.8))
        xl, yl = LABEL[self.axis]
        self.ax.set_xlabel(xl); self.ax.set_ylabel(yl)
        self.ax.set_title(f'{self.sex}  {self.name}  '
                          f'{self.lo[self.axis] + mid * self.cell:+.1f} cm  '
                          f'slab {self.thick:.0f} mm', loc='left')
        self.fig.canvas.draw_idle()

    # ------------------------------------------------------------------ ui
    def build_ui(self):
        self.fig, self.ax = plt.subplots(figsize=(8.5, 8))
        plt.subplots_adjust(left=.28, bottom=.12)
        self.name = 'axial'
        self.im = self.ax.imshow(np.zeros((2, 2, 4)), origin='lower',
                                 interpolation='nearest', aspect='equal')
        n = self.grid.shape[self.axis]
        axp = plt.axes([.28, .05, .62, .03])
        self.pos_slider = Slider(axp, 'slice', 0, n - 1, valinit=n // 2,
                                 valstep=1)
        axt = plt.axes([.28, .01, .62, .03])
        self.th_slider = Slider(axt, 'slab mm', 2, 100, valinit=2, valstep=2)
        axr = plt.axes([.02, .70, .20, .16])
        self.radio = RadioButtons(axr, ('axial', 'coronal', 'sagittal'))
        axc = plt.axes([.02, .50, .20, .16])
        self.check = CheckButtons(axc, ('anatomy', 'airways', 'dose'),
                                  (True, True, self.dlut is not None))
        self.cax = plt.axes([.92, .30, .02, .40])
        self.cax.set_visible(False)
        if self.dlut is not None:
            import matplotlib.colors as mc
            sm = plt.cm.ScalarMappable(
                cmap='inferno',
                norm=mc.LogNorm(vmin=self.drange[0], vmax=self.drange[1]))
            self.fig.colorbar(sm, cax=self.cax, label='Gy per primary')
        self.pos_slider.on_changed(self.draw)
        self.th_slider.on_changed(self.set_thick)
        self.radio.on_clicked(self.set_axis)
        self.check.on_clicked(self.draw)
        self.fig.canvas.mpl_connect('scroll_event', self.scroll)
        self.fig.canvas.mpl_connect('key_press_event', self.key)
        self.draw()

    def set_thick(self, v):
        self.thick = float(v)
        self.draw()

    def set_axis(self, name):
        self.name = name
        self.axis = AXES[name]
        n = self.grid.shape[self.axis]
        self.pos_slider.valmax = n - 1
        self.pos_slider.ax.set_xlim(0, n - 1)
        self.pos_slider.set_val(min(self.pos_slider.val, n - 1))
        self.draw()

    def step(self, d):
        self.pos_slider.set_val(int(np.clip(self.pos_slider.val + d, 0,
                                            self.grid.shape[self.axis] - 1)))

    def scroll(self, e):
        self.step(1 if e.button == 'up' else -1)

    def key(self, e):
        if e.key in ('up', 'right'):
            self.step(1)
        elif e.key in ('down', 'left'):
            self.step(-1)
        elif e.key == 'pageup':
            self.step(10)
        elif e.key == 'pagedown':
            self.step(-10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('sex', nargs='?', default='AM', choices=list(V.M.REFERENCE))
    ap.add_argument('--mm', type=float, default=None)
    ap.add_argument('--data', default=V.DATA)
    ap.add_argument('--lis', help='a FLUKA organ-dose result')
    ap.add_argument('--regions', help='the matching <sex>_regions.csv')
    a = ap.parse_args()
    v = Viewer(a.sex, a.mm, a.data, a.lis, a.regions)
    plt.show()


if __name__ == '__main__':
    main()
