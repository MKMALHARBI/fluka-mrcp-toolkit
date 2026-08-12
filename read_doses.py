#!/usr/bin/env python3
"""Turn a FLUKA region-binning result into a per-organ dose table.

    python3 read_doses.py <sex> <usrbin ascii file> [-o out.csv]

INPUT MUST COME FROM usbsuw, NOT FROM THE RAW fort.21.

    printf "run001_fort.21\\n\\nsum\\n" | usbsuw     # merge cycles -> sum.bnn
    printf "sum\\nsum.txt\\n"           | usbrea     # binary -> ascii

The raw <run>001_fort.21 written by rfluka holds the scores only. usbsuw adds a
second array of the same length, the per-bin percentage error, and usbrea then
prints both blocks:

    Data follow in an array A(ir) ...              <- 187 values
    Percentage errors follow in an array A(ir) ... <- 187 errors

Reading the raw file therefore silently discards every uncertainty, so this
script refuses a single-block file.

NORMALISATION. A region binning is normalised per unit primary weight only, NOT
per unit volume; the division is left to the user. For a DOSE binning the bin
value is GeV cm3 g-1 per primary, so

    dose [GeV/g per primary] = bin value / organ volume [cm3]

Checked rather than assumed: sum(bin value * density) reproduces the total
energy deposited per primary in the .out energy balance to five significant
figures, while treating the bin as GeV/g is out by four orders of magnitude.

For an internal source the specific absorbed fraction follows as

    SAF(target <- source) = dose per decay / energy emitted     in kg-1
"""

__version__ = '1.1.0'
import argparse
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_umesh as M                                            # noqa: E402

GEV_J = 1.602176634e-10          # 1 GeV in joules


def read_usrbin_ascii(path):
    """Return (values, percentage errors), each in region order.

    usbrea writes one block per array, each introduced by a line naming it.
    """
    blocks, cur = [], None
    for line in open(path):
        if 'Data follow' in line or 'errors follow' in line:
            cur = []
            blocks.append(cur)
            continue
        if cur is None:
            continue
        if re.match(r'^\s+[-\d]', line) and ('E+' in line or 'E-' in line):
            cur += [float(x) for x in line.split()]
    if not blocks:
        sys.exit(f'{path}: no data block found -- is this a usbrea output?')
    if len(blocks) < 2:
        sys.exit(f'{path}: only one data block, so it carries no uncertainties.\n'
                 f'Merge the cycles with usbsuw first, then run usbrea on that:\n'
                 f'    printf "<run>001_fort.21\\n\\nsum\\n" | usbsuw\n'
                 f'    printf "sum\\nsum.txt\\n" | usbrea')
    return blocks[0], blocks[1]


def load_regions(sex, where=None):
    """The region table: organ ID, volume, mass, ratios.

    It lives in the case directory, written beside the input it belongs to, so
    a case carries the volumes its own doses were divided by. Pass the case
    directory, or a file inside it.
    """
    if where and os.path.isfile(where):
        where = os.path.dirname(where)
    fn = os.path.join(where or M.out_dir(sex), f'{sex}_regions.csv')
    if not os.path.exists(fn):
        sys.exit(f'{fn} not found.\n'
                 f'Generate the case first:  python3 make_examples.py\n'
                 f'(it writes the region table into the case directory).')
    return list(csv.DictReader(open(fn)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('sex', choices=list(M.REFERENCE))
    ap.add_argument('usrbin', help='ASCII from usbrea, run on a usbsuw output')
    ap.add_argument('-o', '--out', help='write the full table here as CSV')
    ap.add_argument('-e', '--energy', type=float, default=1.0e-3,
                    help='emitted energy per primary in GeV (default 1 MeV)')
    ap.add_argument('-n', '--top', type=int, default=15)
    a = ap.parse_args()

    rows = load_regions(a.sex, a.usrbin)
    vals, errs = read_usrbin_ascii(a.usrbin)
    for name, arr in (('values', vals), ('errors', errs)):
        if len(arr) != len(rows):
            sys.exit(f'{len(arr)} {name} but {len(rows)} organs in the region '
                     f'table -- the binning does not cover exactly the organs')

    out = []
    total_gev = 0.0
    for v, e, r in zip(vals, errs, rows):
        vol, rho, m = (float(r['volume_cm3']), float(r['density']),
                       float(r['mass_g']))
        dose_gev_g = v / vol
        total_gev += v * rho
        out.append(dict(
            region=r['region'], organ=r['organ'], mass_g=m,
            dose_Gy_per_primary=dose_gev_g * GEV_J * 1000.0,
            dose_err_Gy=dose_gev_g * GEV_J * 1000.0 * e / 100.0,
            saf_per_kg=dose_gev_g / a.energy * 1000.0,
            saf_err_per_kg=dose_gev_g / a.energy * 1000.0 * e / 100.0,
            error_percent=e,
            fraction=v * rho / a.energy,
        ))

    scored = [o for o in out if o['saf_per_kg'] > 0.0]
    absorbed = total_gev / a.energy
    print(f'{a.sex}: {len(out)} organs, {len(scored)} with a non-zero score')
    print(f'   energy deposited      {total_gev:.4e} GeV per primary')
    print(f'   absorbed fraction     {absorbed:.4f} of {a.energy*1000:.0f} MeV emitted')
    print(f'   (cross-check against the .out energy balance)')
    if scored:
        good = sum(1 for o in scored if o['error_percent'] <= 10.0)
        print(f'   error <= 10 %         {good} of {len(scored)} scored organs')
    print()
    print(f'   {"region":<10} {"organ":<32} {"mass g":>9} '
          f'{"Gy/primary":>12} {"SAF /kg":>10} {"err %":>7}')
    for o in sorted(out, key=lambda o: -o['saf_per_kg'])[:a.top]:
        print(f'   {o["region"]:<10} {o["organ"]:<32} {o["mass_g"]:>9.1f} '
              f'{o["dose_Gy_per_primary"]:>12.3e} {o["saf_per_kg"]:>10.3e} '
              f'{o["error_percent"]:>7.1f}')

    if a.out:
        with open(a.out, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(out[0]))
            w.writeheader()
            w.writerows(out)
        print(f'\n   full table -> {a.out}')


if __name__ == '__main__':
    main()
