#!/usr/bin/env python3
"""ICRP-145 target-region doses from a FLUKA per-organ result.

    python3 targets.py AM AM/Internal/MRCP-AM_internal_sum.lis
    python3 targets.py AF AF/Internal/*_sum.lis -o targets.csv
    python3 targets.py --check                 verify the tables against a phantom

An organ dose is not the same thing as a target-region dose. ICRP-145 divides
several organs into depth layers and designates only some of them radiosensitive:
the stomach dose that enters a dose coefficient is the dose to the stem-cell layer
at 60-100 um, organ 7201, not to the whole stomach wall. Scoring every organ
separately, as this toolkit does, leaves that selection to be made afterwards --
which is what this file does.

TARGET REGIONS. Table D.1 of ICRP-145 Annex D, verbatim: target region, acronym,
and the organ IDs it is made of. Where a target spans several organs the dose is
the mass-weighted average.

SKELETAL TARGETS. Red bone marrow and the 50 um endosteal region are not
segmented anywhere in the phantom -- Annex D marks them with footnotes rather
than IDs. Annex H states the method: "absorbed doses to the skeletal target
tissues (RBM and endosteum) were taken as the mass-weighted average of the
regional spongiosa and medullary cavity doses following the same approach used in
Publication 116."

    D_RBM = sum(D_i * m_RBM,i) / sum(m_RBM,i)

The RBM mass fractions are distributed, in MRCP_<sex>_bone.dat, so RBM is
computed here. The endosteum mass fractions are NOT distributed: Bozzato et al
2026 had to derive them from ICRP-110 and ICRP-145 data. Endosteum is therefore
reported only if those weights are supplied with --endosteum-weights; it is not
guessed, and the bone-column MST is not a substitute for it.
"""

__version__ = '1.2.3'
import argparse
import csv
import os
import sys

import read_doses as R
import make_umesh as M

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- ICRP-145 Table D.1, target region -> organ IDs ----------------------
TARGETS = [
    ('Colon', 'Colon wall', [7600, 7601, 7602, 7800, 7801, 7802, 8000, 8001,
                             8002, 8200, 8201, 8202, 8400, 8401, 8402, 8600]),
    ('Colon-stem', 'Stem cells of colon', [7601, 7801, 8001, 8201, 8401]),
    ('RC-wall', 'Right colon wall', [7600, 7601, 7602, 7800, 7801, 7802]),
    ('LC-wall', 'Left colon wall', [8000, 8001, 8002, 8200, 8201, 8202]),
    ('RS-wall', 'Rectosigmoid colon wall', [8400, 8401, 8402, 8600]),
    ('RC-stem', 'Stem cells of right colon', [7601, 7801]),
    ('LC-stem', 'Stem cells of left colon', [8001, 8201]),
    ('RSig-stem', 'Stem cells of rectosigmoid colon', [8401]),
    ('St-wall', 'Stomach wall', [7200, 7201, 7202, 7203]),
    ('St-stem', 'Stem cells of stomach', [7201]),
    ('SI-wall', 'Small intestine wall', [7400, 7401, 7402, 7403]),
    ('SI-stem', 'Stem cells of small intestine', [7401]),
    ('Oesophagus', 'Oesophagus wall', [11000, 11001, 11002]),
    ('Oesophagus-bas', 'Oesophagus basal cells', [11001]),
    ('UB-wall', 'Urinary bladder wall', [13700, 13701]),
    ('UB-basal', 'Urinary bladder basal cells', [13701]),
    ('Skin', 'Skin', [12200, 12201, 12300, 12301, 12400, 12401, 12500, 12501]),
    ('Skin-bas', 'Basal cells of skin', [12201, 12301, 12401, 12501]),
    ('ET', 'ET region', [300, 301, 302, 303, 401, 402, 403, 404, 405]),
    ('ET1-bas', 'Basal cells of anterior nasal passages', [302]),
    ('ET2-bas', 'Basal cells of posterior nasal passages + pharynx', [402]),
    ('Bronch-bas', 'Bronchi basal cells', [804, 805]),
    ('Bronch-sec', 'Bronchi secretory cells', [803, 804]),
    ('Brchiol-sec', 'Bronchiolar secretory cells', [813]),
    ('AI', 'Alveolar-interstitium', [9700, 9900]),
    ('Lungs', 'Lungs', [9700, 9900]),
    ('RLung', 'Right lung lobe', [9900]),
    ('LLung', 'Left lung lobe', [9700]),
    ('Liver', 'Liver', [9500]),
    ('Thyroid', 'Thyroid', [13200]),
    ('Brain', 'Brain', [6100]),
    ('S-glands', 'Salivary glands', [12000, 12100]),
    ('O-mucosa', 'Oral mucosa', [500, 501, 600]),
    ('Tongue', 'Tongue', [500, 13300, 13301]),
    ('Tonsils', 'Tonsils', [13400]),
    ('Adrenals', 'Adrenals', [100, 200]),
    ('RAdrenal', 'Right adrenal gland', [200]),
    ('LAdrenal', 'Left adrenal gland', [100]),
    ('GB-wall', 'Gallbladder wall', [7000]),
    ('Ht-wall', 'Heart wall', [8700]),
    ('Kidneys', 'Kidneys', [8900, 9000, 9100, 9200, 9300, 9400]),
    ('RKidney', 'Right kidney C+M+P', [9200, 9300, 9400]),
    ('LKidney', 'Left kidney C+M+P', [8900, 9000, 9100]),
    ('RKidney-C', 'Right kidney cortex', [9200]),
    ('RKidney-M', 'Right kidney medulla', [9300]),
    ('RKidney-P', 'Right kidney pelvis', [9400]),
    ('LKidney-C', 'Left kidney cortex', [8900]),
    ('LKidney-M', 'Left kidney medulla', [9000]),
    ('LKidney-P', 'Left kidney pelvis', [9100]),
    ('Pancreas', 'Pancreas', [11300]),
    ('Spleen', 'Spleen', [12700]),
    ('Thymus', 'Thymus', [13100]),
    ('Muscle', 'Muscle', [10600, 10700, 10800, 10900]),
    ('LN-Sys', 'Systemic lymph nodes', [10200, 10300, 10400, 10500]),
    ('LN-ET', 'Extrathoracic lymph nodes', [10000]),
    ('LN-Th', 'Thoracic lymph nodes', [10100]),
    ('Breast', 'Breasts', [6200, 6300, 6400, 6500]),
    ('Breast-a', 'Breast adipose', [6200, 6400]),
    ('Breast-g', 'Breast glandular', [6300, 6500]),
    ('RBreast', 'Right breast', [6400, 6500]),
    ('LBreast', 'Left breast', [6200, 6300]),
    ('Ovaries', 'Ovaries', [11100, 11200]),
    ('ROvary', 'Right ovary', [11200]),
    ('LOvary', 'Left ovary', [11100]),
    ('Testes', 'Testes', [12900, 13000]),
    ('Prostate', 'Prostate', [11500]),
    ('Uterus', 'Uterus/cervix', [13900]),
    ('Lens-ent', 'Entire lens of eye', [6600, 6601, 6800, 6801]),
    ('Lens-sen', 'Sensitive lens of eye', [6600, 6800]),
    ('P-gland', 'Pituitary gland', [11400]),
    ('Sp-cord', 'Spinal cord', [12600]),
    ('Ureters', 'Ureters', [13500, 13600]),
    ('Adipose', 'Adipose/residual tissue', [11600, 11700, 11800, 11900]),
]

# Annex D footnote *: organ IDs carrying a red bone marrow fraction
RBM_REGIONS = [1400, 2500, 2700, 2900, 4000, 4200, 4400, 4600, 4800, 5000,
               5200, 5400, 5600]
# Annex D footnote +: organ IDs carrying an endosteum fraction
ENDOSTEUM_REGIONS = [1400, 1500, 1700, 1800, 2000, 2100, 2300, 2500, 2700,
                     2900, 3000, 3200, 3300, 3500, 3600, 3800, 4000, 4200,
                     4400, 4600, 4800, 5000, 5200, 5400, 5600]

# the sub-layer targets, i.e. those whose dose is NOT the whole-organ dose
RADIOSENSITIVE = {'Colon-stem', 'RC-stem', 'LC-stem', 'RSig-stem', 'St-stem',
                  'SI-stem', 'Oesophagus-bas', 'UB-basal', 'Skin-bas',
                  'ET1-bas', 'ET2-bas', 'Bronch-bas', 'Bronch-sec',
                  'Brchiol-sec', 'Lens-sen'}


def load_bone(sex):
    """organ ID -> RBM mass ratio, exclusive of blood (see make_umesh)."""
    fn = os.path.join(M.mesh_dir(sex), f'MRCP_{sex}_bone.dat')
    out = {}
    for line in open(fn, encoding='latin-1'):
        t = line.split()
        if len(t) >= 12 and t[0].isdigit():
            out[int(t[0])] = float(t[-10])       # RBM, exclusive of blood
    return out


def organ_doses(sex, lis):
    """organ ID -> (dose Gy/primary, error %, mass g, blood-free mass g)."""
    vals, errs = R.read_usrbin_ascii(lis)
    rows = R.load_regions(sex, lis)
    if not (len(vals) == len(errs) == len(rows)):
        sys.exit(f'{lis}: {len(vals)} bins against {len(rows)} organs')
    out = {}
    for v, e, r in zip(vals, errs, rows):
        oid = int(r['organ_id'])
        dose = v / float(r['volume_cm3']) * R.GEV_J * 1000.0
        out[oid] = (dose, e, float(r['mass_g']), float(r['bloodfree_g']))
    return out


def weighted(d, ids, weight):
    """Mass-weighted mean dose and its propagated error, over ids.

    Weights are independent of the Monte Carlo, so the error on a weighted mean
    of independent regional doses is the weighted quadrature sum.
    """
    num = den = var = 0.0
    used = []
    for oid in ids:
        if oid not in d:
            continue
        dose, epct, _m, _bf = d[oid]
        w = weight(oid)
        if w <= 0:
            continue
        num += w * dose
        den += w
        var += (w * dose * epct / 100.0) ** 2
        used.append(oid)
    if den <= 0:
        return None
    mean = num / den
    err = (var ** 0.5) / den
    return mean, (100.0 * err / mean if mean else 0.0), den, used


def compute(sex, lis, endo_weights=None):
    d = organ_doses(sex, lis)
    bone = load_bone(sex)
    out = []

    for acr, name, ids in TARGETS:
        present = [o for o in ids if o in d]
        if not present:
            continue                       # sex-specific organ, absent here
        r = weighted(d, present, lambda o: d[o][2])      # mass weighting
        if r is None:
            continue
        mean, epct, mass, used = r
        out.append(dict(target=acr, name=name, kind='sub-layer'
                        if acr in RADIOSENSITIVE else 'organ',
                        organs=' '.join(str(o) for o in used),
                        mass_g=f'{mass:.3f}', dose_Gy=f'{mean:.4e}',
                        err_pct=f'{epct:.2f}'))

    # red bone marrow: mass-weighted over the spongiosa regions, weighted by the
    # RBM mass each one carries (blood-free mass x RBM ratio)
    r = weighted(d, RBM_REGIONS, lambda o: d[o][3] * bone.get(o, 0.0))
    if r:
        mean, epct, mass, used = r
        out.append(dict(target='R-marrow', name='Red (active) marrow',
                        kind='skeletal', organs=f'{len(used)} spongiosa regions',
                        mass_g=f'{mass:.3f}', dose_Gy=f'{mean:.4e}',
                        err_pct=f'{epct:.2f}'))

    if endo_weights:
        r = weighted(d, ENDOSTEUM_REGIONS, lambda o: endo_weights.get(o, 0.0))
        if r:
            mean, epct, mass, used = r
            out.append(dict(target='Endost-BS', name='50 um endosteal region',
                            kind='skeletal',
                            organs=f'{len(used)} skeletal regions',
                            mass_g=f'{mass:.3f}', dose_Gy=f'{mean:.4e}',
                            err_pct=f'{epct:.2f}'))
    return out


def check():
    """Every organ ID in the tables must exist in a phantom, or be explained."""
    listed = {o for _, _, ids in TARGETS for o in ids}
    listed |= set(RBM_REGIONS) | set(ENDOSTEUM_REGIONS)
    have, bad = {}, 0
    names = M.phantoms() or ['AM', 'AF']
    for sex in names:
        have[sex] = set(M.organ_ids(sex))
        bone = load_bone(sex)
        nz = [o for o in RBM_REGIONS if bone.get(o, 0) > 0]
        print(f'{sex}: {len(have[sex])} organs, {len(listed)} referenced by the '
              f'target tables, RBM fraction non-zero in {len(nz)}/'
              f'{len(RBM_REGIONS)} Annex D regions')
        if len(nz) != len(RBM_REGIONS):
            bad += 1

    # An ID absent from every phantom is a fault in the tables; one absent
    # from some is sex-specific anatomy, and now also age-specific.
    per = {s: listed - have[s] for s in names}
    absent_both = sorted(set.intersection(*per.values())) if per else []
    sex_specific = sorted(set.union(*per.values()) - set(absent_both)) if per else []

    if sex_specific:
        print('  sex-specific, expected: ' + ', '.join(map(str, sex_specific)))
    if absent_both:
        print('  ABSENT FROM EVERY PHANTOM: ' + ', '.join(map(str, absent_both)))
        print('    Annex D lists these as target regions but the distributed')
        print('    mesh does not contain them. A target built only from such')
        print('    IDs is skipped rather than reported as zero.')
    return bad


def main():
    ap = argparse.ArgumentParser(
        description='ICRP-145 target-region doses from a FLUKA per-organ result')
    ap.add_argument('sex', nargs='?', choices=list(M.REFERENCE))
    ap.add_argument('usrbin', nargs='?', help='ASCII from usbrea on a usbsuw file')
    ap.add_argument('-o', '--out', help='write the table here as CSV')
    ap.add_argument('--endosteum-weights', metavar='CSV',
                    help='two columns, organ ID and endosteum mass in g; '
                         'ICRP does not distribute these (see the module note)')
    ap.add_argument('--check', action='store_true',
                    help='verify the target tables against both phantoms')
    a = ap.parse_args()

    if a.check:
        return check()
    if not (a.sex and a.usrbin):
        ap.error('give a phantom and a usbrea file, or --check')

    endo = None
    if a.endosteum_weights:
        endo = {}
        for row in csv.reader(open(a.endosteum_weights)):
            if len(row) >= 2 and row[0].strip().isdigit():
                endo[int(row[0])] = float(row[1])

    out = compute(a.sex, a.usrbin, endo)
    print(f'{"target":<16}{"kind":<11}{"mass g":>11}{"Gy/primary":>13}{"err %":>8}  region')
    for o in out:
        print(f'{o["target"]:<16}{o["kind"]:<11}{float(o["mass_g"]):>11.2f}'
              f'{float(o["dose_Gy"]):>13.3e}{float(o["err_pct"]):>8.2f}  {o["name"]}')
    if not endo:
        print('\nEndost-BS not reported: ICRP does not distribute endosteum mass '
              'fractions.\nSupply them with --endosteum-weights to include it.')
    if a.out:
        with open(a.out, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(out[0]))
            w.writeheader()
            w.writerows(out)
        print(f'\n{len(out)} targets -> {a.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
