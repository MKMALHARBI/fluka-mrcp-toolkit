#!/usr/bin/env python3
"""The toolkit in one window.

    python3 RUNME.py

    1  Data      point at the ICRP download
    2  Phantom   build the FLUKA cards
    3  Case      organ, particle, energy, phantom
    4  Run       transport, merge, convert
    5  Results   organ and target-region doses

Jobs run on a background thread. The log echoes the equivalent command line.
"""

__version__ = '1.2.2'

import glob
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)   # imports resolve here; output goes to M.work_root()
sys.path.insert(0, HERE)

import make_umesh as M                                        # noqa: E402
import make_examples as X                                     # noqa: E402
import setup_data as D                                        # noqa: E402
import build_exe as B                                         # noqa: E402
import targets as T                                           # noqa: E402
import read_doses as R                                        # noqa: E402

# FLUKA's complete particle table, manual section 5.1, in id order -6 to 62,
# plus ISOTOPE (a BEAM SDUM, not an id). This is every particle name FLUKA
# defines. Ids from @LASTPAR up are generalised scoring quantities and are
# not valid on a BEAM card; RAY is a pseudoparticle. Neither is offered.
PARTICLES = [
    '4-HELIUM', '3-HELIUM', 'TRITON', 'DEUTERON', 'HEAVYION', 'OPTIPHOT',
    'PROTON', 'APROTON', 'ELECTRON', 'POSITRON', 'NEUTRIE', 'ANEUTRIE',
    'PHOTON', 'NEUTRON', 'ANEUTRON', 'MUON+', 'MUON-', 'KAONLONG',
    'PION+', 'PION-', 'KAON+', 'KAON-', 'LAMBDA', 'ALAMBDA', 'KAONSHRT',
    'SIGMA-', 'SIGMA+', 'SIGMAZER', 'PIZERO', 'KAONZERO', 'AKAONZER',
    'NEUTRIM', 'ANEUTRIM', 'ASIGMA-', 'ASIGMAZE', 'ASIGMA+', 'XSIZERO',
    'AXSIZERO', 'XSI-', 'AXSI+', 'OMEGA-', 'AOMEGA+', 'TAU+', 'TAU-',
    'NEUTRIT', 'ANEUTRIT', 'D+', 'D-', 'D0', 'D0BAR', 'DS+', 'DS-',
    'LAMBDAC+', 'XSIC+', 'XSIC0', 'XSIPC+', 'XSIPC0', 'OMEGAC0',
    'ALAMBDC-', 'AXSIC-', 'AXSIC0', 'AXSIPC-', 'AXSIPC0', 'AOMEGAC0',
    'ISOTOPE']

COMMON = ['PHOTON', 'ELECTRON', 'POSITRON', 'NEUTRON', 'PROTON', '4-HELIUM',
          'DEUTERON', 'TRITON', '3-HELIUM', 'MUON+', 'MUON-', 'ISOTOPE']


def particle_names():
    head = [p for p in COMMON if p in PARTICLES]
    return head + [p for p in PARTICLES if p not in head]


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.ui = queue.Queue()   # callables to run on the UI thread
        self.busy = False
        self.alive = True
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.organs = {}
        self.built = self.load_built()
        root.title(f'ICRP-145 phantoms in FLUKA  -  toolkit {__version__}')
        root.geometry('900x680')

        top = ttk.Frame(root, padding=(10, 8, 10, 0))
        top.pack(fill='x')
        self.where = tk.StringVar()
        ttk.Label(top, textvariable=self.where, foreground='#555').pack(side='left')

        self.nb = ttk.Notebook(root)
        self.nb.pack(fill='both', expand=True, padx=10, pady=8)
        self.tabs = {}
        for i, name in enumerate(('1  Data', '2  Phantom', '3  Case',
                                  '4  Run', '5  Results', '6  View')):
            f = ttk.Frame(self.nb, padding=12)
            self.nb.add(f, text=name)
            self.tabs[i] = f

        self.build_data(self.tabs[0])
        self.build_phantom(self.tabs[1])
        self.build_case(self.tabs[2])
        self.build_run(self.tabs[3])
        self.build_results(self.tabs[4])
        self.build_view(self.tabs[5])

        ttk.Label(root, text='Log', foreground='#555').pack(anchor='w', padx=12)
        self.out = scrolledtext.ScrolledText(root, height=11, wrap='word')
        self.out.pack(fill='both', expand=False, padx=10, pady=(0, 10))

        self.refresh_where()
        if self.offered_sexes():
            self.load_organs()
        self.fill_cases()
        self.fill_results()
        self.nb.bind('<<NotebookTabChanged>>', self.on_tab)
        self.poll()

    def close(self):
        """Stop scheduling callbacks before the window goes away."""
        self.alive = False
        self.root.destroy()

    # -------------------------------------------------------------- helpers
    def log(self, msg=''):
        self.q.put(msg)

    def poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self.out.insert('end', str(msg) + '\n')
                self.out.see('end')
        except queue.Empty:
            pass
        try:
            while True:
                fn = self.ui.get_nowait()
                try:
                    fn()
                except Exception as e:                        # noqa: BLE001
                    self.log(f'ui update failed: {type(e).__name__}: {e}')
        except queue.Empty:
            pass
        if self.alive:
            self.root.after(120, self.poll)

    def work(self, fn, done=None):
        """Run fn in a thread; done() runs back on the UI thread afterwards."""
        if self.busy:
            messagebox.showinfo('Busy', 'Something is already running.')
            return
        self.busy = True

        def wrap():
            try:
                fn()
            except Exception as e:                            # noqa: BLE001
                self.log(f'failed: {type(e).__name__}: {e}')
            finally:
                self.busy = False
                if done and self.alive:
                    # via the queue, not root.after: Tk is not thread-safe
                    # and an after() from a worker thread can silently vanish
                    self.ui.put(done)
        threading.Thread(target=wrap, daemon=True).start()

    def on_tab(self, _e=None):
        """Lists reflect the disk, so remake them when their tab is opened."""
        i = self.nb.index('current')
        if i == 3:
            self.fill_cases()
        elif i == 4:
            self.fill_results()
        elif i == 5:
            self.fill_view()

    def refresh_where(self):
        d = M.data_dir()
        have, miss = D.status(d)
        ok = not miss
        self.where.set(f'data: {d}   ({len(have)}/{len(have)+len(miss)} files'
                       + ('' if ok else ', incomplete') + ')')
        self.data_ok = ok
        return ok

    # -------------------------------------------------------------- 1 data
    def build_data(self, f):
        ttk.Label(f, text='ICRP Publication 145 data',
                  font=('', 11, 'bold')).pack(anchor='w')
        ttk.Label(f, justify='left', foreground='#555', text=(
            'Download the ICRP-145 adult mesh-type reference computational '
            'phantoms:\n'
            'https://www.icrp.org/publication.asp?id=ICRP%20Publication%20145\n\n'
            'Give P145 Electronic files.zip as downloaded. Everything is taken '
            'from it,\nincluding the airway model.')
                  ).pack(anchor='w', pady=(4, 10))
        row = ttk.Frame(f)
        row.pack(fill='x')
        self.src = tk.StringVar()
        ttk.Entry(row, textvariable=self.src).pack(side='left', fill='x',
                                                   expand=True)
        ttk.Button(row, text='Choose the zip...',
                   command=self.pick_zip).pack(side='left', padx=4)
        b = ttk.Frame(f)
        b.pack(fill='x', pady=10)
        ttk.Button(b, text='Set up the data', command=self.do_setup).pack(side='left')
        ttk.Button(b, text='Check what is there',
                   command=self.do_status).pack(side='left', padx=6)

    def pick_zip(self):
        p = filedialog.askopenfilename(title='The ICRP Publication 145 download',
                                       filetypes=[('Zip archive', '*.zip'),
                                                  ('All files', '*')])
        if p:
            self.src.set(p)


    def do_status(self):
        d = M.data_dir()
        have, miss = D.status(d)
        self.log(f'\n$ python3 setup_data.py --status')
        self.log(f'  data location: {d}')
        self.log(f'  {len(have)} of {len(have)+len(miss)} files present')
        for _p, n in miss:
            self.log(f'  missing: {n}')
        self.refresh_where()

    def do_setup(self):
        src = self.src.get().strip()
        if not src:
            messagebox.showinfo('Nothing chosen',
                                'Choose the ICRP zip or a folder first.')
            return
        self.log(f'\n$ python3 setup_data.py "{src}"')
        self.log('  a few minutes for the zip')

        def job():
            ok, msg = D.setup(src, log=self.log)
            self.log(('  ok: ' if ok else '  failed: ') + msg)
        self.work(job, done=self.after_setup)

    def after_setup(self):
        # phantoms and airway files may have just arrived
        self.phantoms = self.phantom_list()
        self.build_box['values'] = [n for n, _ in self.phantoms]
        self.refresh_case_phantoms()
        self.check_airway()
        if self.refresh_where():
            self.log('  ready')
            self.nb.select(1)

    # ----------------------------------------------------------- 2 phantom
    # ICRP 145 gives the two adults, ICRP 156 the ten children. The list is
    # built from the phantoms actually installed, so the dropdown shows what
    # can be built and nothing else.
    AGE = {'AM': 'Adult', 'AF': 'Adult', '00': 'Newborn', '01': '1 year',
           '05': '5 years', '10': '10 years', '15': '15 years'}

    @staticmethod
    def phantom_label(name):
        if name in ('AM', 'AF'):
            return 'Adult ' + ('male' if name == 'AM' else 'female')
        return f"{App.AGE.get(name[:2], name[:2])} " \
               f"{'male' if name.endswith('M') else 'female'}"

    def phantom_list(self):
        got = M.phantoms()
        return [('All', 'all')] + [(self.phantom_label(n), n) for n in got]

    def build_phantom(self, f):
        ttk.Label(f, text='Build the phantom',
                  font=('', 11, 'bold')).pack(anchor='w')
        ttk.Label(f, justify='left', foreground='#555', text=(
            'Checks the phantom against ICRP: 73.0 and 60.0 kg, red marrow 1170 '
            'and 900 g.\nThe cards and the region table are written into each '
            'case on tab 3.')).pack(anchor='w', pady=(4, 10))
        p = ttk.Frame(f)
        p.pack(anchor='w', pady=(0, 10))
        ttk.Label(p, text='Phantom').pack(side='left', padx=(0, 8))
        self.phantoms = self.phantom_list()
        self.build_sex = tk.StringVar(value=self.phantoms[0][0])
        self.build_box = ttk.Combobox(p, textvariable=self.build_sex,
                                      state='readonly', width=18,
                                      values=[n for n, _ in self.phantoms])
        self.build_box.pack(side='left')
        ttk.Button(f, text='Build', command=self.do_build).pack(anchor='w')

    def do_build(self):
        # gate on the phantom being built, not on every file of every
        # phantom: a complete P156 install must not be blocked by an
        # absent P145 one, or the other way round
        self.refresh_where()
        pick = dict(self.phantoms).get(self.build_sex.get(), 'all')
        got = M.phantoms()
        sexes = tuple(got) if pick == 'all' else \
            (pick,) if pick in got else ()
        if not sexes:
            messagebox.showwarning(
                'No data', 'That phantom is not installed -- set its '
                'archive up on tab 1 first.')
            return
        self.log(f'\n$ python3 make_umesh.py --check' +
                 ('' if pick == 'all' else f'   ({pick} only)'))

        def job():
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                good = [s for s in sexes if M.build(s, write=False)]
            for line in buf.getvalue().splitlines():
                self.log('  ' + line)
            self.built.update(good)
            if good:
                self.save_built()
            self.log('  matches ICRP.' if len(good) == len(sexes)
                     else '  FAILED -- see above')
        self.work(job, done=lambda: (self.refresh_case_phantoms(),
                                     self.load_organs(), self.nb.select(2)))

    # -------------------------------------------------------------- 3 case
    def build_case(self, f):
        ttk.Label(f, text='Case', font=('', 11, 'bold')).grid(
            row=0, column=0, columnspan=3, sticky='w')
        r = 1

        def row(label, w, hint=''):
            nonlocal r
            ttk.Label(f, text=label).grid(row=r, column=0, sticky='w', pady=3)
            w.grid(row=r, column=1, sticky='ew', pady=3)
            if hint:
                ttk.Label(f, text=hint, foreground='#666').grid(
                    row=r, column=2, sticky='w', padx=8)
            r += 1
        f.columnconfigure(1, weight=1)

        self.sex = tk.StringVar(value='all')
        self.case_box = ttk.Combobox(f, textvariable=self.sex, state='readonly',
                                     values=self.case_phantoms())
        row('Phantom', self.case_box)
        self.case_box.bind('<<ComboboxSelected>>', lambda _e: self.fill_organs())
        self.case = tk.StringVar(value='both')
        row('Exposure', ttk.Combobox(f, textvariable=self.case, state='readonly',
            values=['both', 'internal  source inside an organ',
                    'external  point source outside the body']))
        self.organ = tk.StringVar()
        self.organ_box = ttk.Combobox(f, textvariable=self.organ, state='readonly')
        row('Source organ', self.organ_box, 'internal only')
        self.particle = tk.StringVar(value=X.ICRP_PARTICLE)
        row('Particle', ttk.Combobox(f, textvariable=self.particle,
            state='readonly', values=particle_names()))
        self.energy = tk.StringVar(value=f'{X.ICRP_ENERGY:g}')
        row('Energy (MeV)', ttk.Entry(f, textvariable=self.energy))
        pos = ttk.Frame(f)
        self.px = tk.StringVar(value='0')
        self.py = tk.StringVar(value='-100')
        self.pz = tk.StringVar(value='0')
        for i, (lab, v) in enumerate((('x', self.px), ('y', self.py), ('z', self.pz))):
            ttk.Label(pos, text=lab).grid(row=0, column=2*i, padx=(0 if i == 0 else 8, 2))
            ttk.Entry(pos, textvariable=v, width=9).grid(row=0, column=2*i+1)
        row('Beam position (cm)', pos, 'external only')
        self.primaries = tk.StringVar(value=str(X.PRIMARIES))
        row('Primaries per cycle', ttk.Entry(f, textvariable=self.primaries))

        self.physics = tk.StringVar(value=self.PHYSICS[0])
        self.physics_box = ttk.Combobox(f, textvariable=self.physics,
                                        state='readonly', values=self.PHYSICS)
        row('Physics', self.physics_box)
        self.physics_box.bind('<<ComboboxSelected>>',
                              lambda _e: self.physics_hint())
        self.ecut = tk.StringVar(value=f'{X.FAST_ECUT:g}')
        self.ecut_entry = ttk.Entry(f, textvariable=self.ecut, width=8)
        row('Electron cut (MeV)', self.ecut_entry, 'custom physics only')
        self.phys_text = ttk.Label(f, justify='left', foreground='#666',
                                   wraplength=760)
        self.phys_text.grid(row=r, column=0, columnspan=3, sticky='w',
                            pady=(0, 4))
        r += 1
        self.physics_hint()

        # The airway epithelium is not a second phantom: the mesh and every
        # geometry card are the same. It is scoring, added as a USRBIN of type
        # 8 whose bin is worked out at each energy deposit, so it belongs here
        # and not in the phantom list. It is also independent of the exposure,
        # which is why it is its own row rather than more entries in that one.
        self.scoring = tk.StringVar(value=self.SCORING[0])
        self.scoring_box = ttk.Combobox(f, textvariable=self.scoring,
                                        state='readonly', values=self.SCORING)
        self.scoring_hint = ttk.Label(f, text='', foreground='#666')
        row('Scoring', self.scoring_box)
        self.scoring_hint.grid(row=r - 1, column=2, sticky='w', padx=8)
        self.check_airway()

        b = ttk.Frame(f)
        b.grid(row=r, column=0, columnspan=3, sticky='w', pady=10)
        ttk.Button(b, text='ICRP benchmark defaults',
                   command=self.reset_case).pack(side='left')
        ttk.Button(b, text='Write the input',
                   command=self.do_generate).pack(side='left', padx=8)

    def load_organs(self):
        def job():
            for sex in self.offered_sexes():
                if sex in self.organs:
                    continue
                d = M.assemble(sex)
                if d is None:
                    continue
                self.organs[sex] = [
                    (o, f'{o:<6} {d["mats"][o][0]}   ({d["mass"][o]:.0f} g)')
                    for o in d['ids']]
            self.ui.put(self.fill_organs)
        self.work(job)

    def fill_organs(self):
        sex = self.case_sex()
        first = (M.phantoms() or ['AM'])[0]
        items = self.organs.get(sex) or self.organs.get(first) or []
        self.organ_box['values'] = [t for _, t in items]
        if items and self.organ.get() not in self.organ_box['values']:
            self.organ.set(next((t for o, t in items if o == X.ICRP_ORGAN),
                                items[0][1]))

    def built_marker(self):
        return os.path.join(M.work_root(), '.built')

    def load_built(self):
        try:
            return {s for s in open(self.built_marker()).read().split()
                    if s in M.REFERENCE}
        except OSError:
            return set()

    def save_built(self):
        with open(self.built_marker(), 'w') as f:
            f.write('\n'.join(sorted(self.built)) + '\n')

    def offered_sexes(self):
        """Phantoms the case tab may write: checked on tab 2 this session,
        or already holding a written case (which required the same check)."""
        have = set(self.built)
        for d, _n in self.cases():
            s = os.path.basename(d).split('_')[0]
            if s in M.REFERENCE:
                have.add(s)
        return [n for n in M.phantoms() if n in have]

    def case_phantoms(self):
        """The Phantom dropdown on the case tab: name, description, mass."""
        got = self.offered_sexes()
        out = ['all'] if got else []
        for n in got:
            r = M.REFERENCE[n]
            out.append(f'{n}  {self.phantom_label(n).lower()}, '
                       f'{r["mass"] / 1000:g} kg')
        return out

    def refresh_case_phantoms(self):
        vals = self.case_phantoms()
        self.case_box['values'] = vals
        if self.sex.get() not in vals:
            self.sex.set(vals[0] if vals else '')

    def case_sex(self):
        """The phantom chosen on the case tab, or the first offered."""
        v = self.sex.get()
        if v and v != 'all':
            return v.split()[0]
        return (self.offered_sexes() or M.phantoms() or ['AM'])[0]

    SCORING = ['organ dose only',
               'organ dose + airway epithelium']

    PHYSICS = ['precision  PRECISIO reference transport',
               'fast x1.5  local deposition below 0.35 MeV',
               'custom     user-defined electron cutoff']

    PHYS_TEXT = {
        'precision':
            'PRECISIO defaults: coupled electron-photon transport with a '
            '100 keV electron transport cutoff and single Coulomb scattering '
            'in place of condensed-history multiple scattering at every '
            'tetrahedron boundary. Required for charged-particle and '
            'radionuclide sources, for the airway epithelium, skin and '
            'eye-lens targets, and for reference results.',
        'fast':
            'Fast means one approximation: electrons and positrons below '
            '0.35 MeV are not transported. Their kinetic energy is scored '
            'where they are created, which moves it by at most the '
            'continuous-slowing-down-approximation (CSDA) range at the cut '
            '-- about 1 mm in soft tissue -- and condensed-history multiple '
            'scattering replaces single scattering at tetrahedron '
            'boundaries. Measured on the AF internal benchmark, the time '
            'per primary falls from 63.7 to 41.2 ms (x1.5) and photon organ '
            'doses agree with precision within counting statistics. Invalid '
            'for charged-particle primaries and for targets comparable to '
            'or thinner than the residual range: airway epithelium, skin, '
            'eye lens.',
        'custom':
            'The same two cards with a user-defined threshold. Choose it so '
            'the continuous-slowing-down-approximation (CSDA) range at the '
            'cutoff is small against the thinnest scored structure: in soft '
            'tissue ~0.14 mm at 0.1 MeV, ~1 mm at 0.35 MeV, ~4 mm at '
            '1 MeV.'}

    def physics_hint(self):
        mode = self.physics.get().split()[0]
        self.phys_text.configure(text=self.PHYS_TEXT[mode])
        self.ecut_entry.configure(
            state='normal' if mode == 'custom' else 'disabled')

    def check_airway(self):
        """The airway files come from a different ICRP archive to the mesh.

        MRCP_GEANT4_lung_airway.zip carries .lung and .lungDiam; the archive the
        toolkit normally unpacks does not. Without them the option cannot work,
        so it is disabled rather than left to fail at run time.
        """
        got = M.phantoms()
        missing = [s for s in got
                   if not os.path.exists(os.path.join(M.mesh_dir(s),
                                                      f'MRCP_{s}.lung'))]
        if not got:
            missing = ['none installed']
        if missing:
            self.scoring.set(self.SCORING[0])
            self.scoring_box['values'] = self.SCORING[:1]
            self.scoring_hint.configure(
                text='airway model not found -- set the data up on tab 1')
        else:
            self.scoring_box['values'] = self.SCORING
            self.scoring_hint.configure(text='ICRP-145 BB and bb target layers')

    def reset_case(self):
        self.scoring.set(self.SCORING[0])
        self.physics.set(self.PHYSICS[0])
        self.ecut.set(f'{X.FAST_ECUT:g}')
        self.physics_hint()
        self.sex.set('all'); self.case.set('both')
        self.particle.set(X.ICRP_PARTICLE)
        self.energy.set(f'{X.ICRP_ENERGY:g}')
        self.px.set('0'); self.py.set('-100'); self.pz.set('0')
        self.primaries.set(str(X.PRIMARIES))
        self.fill_organs()

    def case_argv(self):
        a = []
        if self.sex.get() not in ('', 'all'):
            a += ['--sex', self.case_sex()]
        else:
            # 'all' means all phantoms offered on this tab, not all installed
            for s in self.offered_sexes():
                a += ['--sex', s]
        if self.case.get() != 'both':
            a += ['--case', self.case.get().split()[0]]
        oid = int(self.organ.get().split()[0]) if self.organ.get() else X.ICRP_ORGAN
        if oid != X.ICRP_ORGAN:
            a += ['--organ', str(oid)]
        if self.particle.get() != X.ICRP_PARTICLE:
            a += ['--particle', self.particle.get()]
        if self.energy.get() != f'{X.ICRP_ENERGY:g}':
            a += ['--energy', self.energy.get()]
        if (self.px.get(), self.py.get(), self.pz.get()) != ('0', '-100', '0'):
            a += ['--position', self.px.get(), self.py.get(), self.pz.get()]
        if self.primaries.get() != str(X.PRIMARIES):
            a += ['--primaries', self.primaries.get()]
        mode = self.physics.get().split()[0]
        if mode != 'precision':
            a += ['--physics', mode]
            if mode == 'custom':
                a += ['--ecut', self.ecut.get()]
        if self.scoring.get() == self.SCORING[1]:
            a += ['--airway']
        return a

    def do_generate(self):
        if not self.offered_sexes():
            messagebox.showinfo('No phantom', 'Build a phantom on tab 2 first.')
            return
        mode = self.physics.get().split()[0]
        if mode != 'precision' and (self.particle.get() != 'PHOTON'
                               or self.scoring.get() == self.SCORING[1]):
            if not messagebox.askyesno(
                    'Fast physics',
                    'Sub-threshold electrons deposit locally: a '
                    'charged-particle source spectrum is truncated at the '
                    'cutoff, and the micrometre airway layers are thin '
                    'against the ~1 mm residual range, so their doses are '
                    'biased by construction.\n\nWrite the input anyway?'):
                return
        argv = self.case_argv()
        self.log('\n$ python3 make_examples.py ' + ' '.join(argv))

        def job():
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                X.main(argv)
            for line in buf.getvalue().splitlines():
                self.log('  ' + line)
        self.work(job, done=lambda: (self.fill_cases(), self.nb.select(3)))

    # --------------------------------------------------------------- 4 run
    def build_run(self, f):
        ttk.Label(f, text='Run FLUKA', font=('', 11, 'bold')).pack(anchor='w')
        ttk.Label(f, justify='left', foreground='#555', text=(
            'Cores are separate FLUKA processes; more cores than cycles sit '
            'idle.')).pack(anchor='w', pady=(4, 8))
        row = ttk.Frame(f)
        row.pack(fill='x')
        ttk.Label(row, text='Cycles').pack(side='left')
        self.cycles = tk.StringVar(value='5')
        ttk.Entry(row, textvariable=self.cycles, width=6).pack(side='left', padx=4)
        ttk.Label(row, text='5+ recommended',
                  foreground='#666').pack(side='left', padx=(0, 20))
        ttk.Label(row, text='Cores').pack(side='left')
        self.jobs = tk.StringVar(value='1')
        ttk.Entry(row, textvariable=self.jobs, width=6).pack(side='left', padx=4)
        ttk.Label(f, text='Cases found:').pack(anchor='w', pady=(10, 2))
        self.caselist = tk.Listbox(f, height=6, selectmode='extended')
        self.caselist.pack(fill='both', expand=True)
        b = ttk.Frame(f)
        b.pack(fill='x', pady=8)
        ttk.Button(b, text='Refresh', command=self.fill_cases).pack(side='left')
        ttk.Button(b, text='Build flukamrcp',
                   command=self.do_build_exe).pack(side='left', padx=8)

        # Nothing here is required: the inputs are ordinary FLUKA inputs and
        # can be run by hand, on a cluster, or from Flair. Say where they are
        # and what the command is, so the toolkit is not a dependency.
        self.where_run = ttk.Label(f, justify='left', foreground='#555')
        self.where_run.pack(anchor='w', pady=(6, 0))
        self.show_run_path()
        ttk.Button(b, text='Run selected (or all)',
                   command=self.do_run).pack(side='left', padx=8)
        self.prog = ttk.Progressbar(f, mode='indeterminate')
        self.prog.pack(fill='x')

    def do_build_exe(self):
        """Build the executable into every selected case."""
        sel = self.selected()
        self.log('\n$ python3 build_exe.py')

        def job():
            for d, _n in sel:
                self.log(f'  {os.path.relpath(d, M.work_root())}:')
                self.log('    ' + B.build(log=self.log, dest=d)[1])
        self.work(job)

    def selected(self):
        """The cases ticked in the list, or all of them if none are."""
        allc = self.cases()
        return [allc[i] for i in self.caselist.curselection()] or allc

    def cases(self):
        """Every case under the work root, as (directory, run name).

        Directories are absolute so rfluka, usbsuw and usbrea can be given a
        cwd regardless of where the toolkit itself sits.
        """
        root = M.work_root()
        return [(os.path.dirname(p), os.path.basename(p)[:-4])
                for p in sorted(glob.glob(os.path.join(root, '*', '*.inp')))
                if os.path.basename(os.path.dirname(p)) != 'phantom']

    def show_run_path(self):
        """Where the cases are, and how to run one without the toolkit.

        Written relative to the work root so it reads the same on any machine.
        """
        self.where_run.configure(text=(
            'To run in Flair or from a terminal, press Build flukamrcp first: '
            'internal and\nairway cases need it and it is not written with the '
            'input. Then from the case\ndirectory:\n'
            '   rfluka -N0 -M5 -e ./flukamrcp <name>\n'
            '   ls *_fort.2? | usbsuw   then usbrea\n'
            'An organ-dose-only external case needs no -e and no executable.'))

    def fill_cases(self):
        self.caselist.delete(0, 'end')
        for d, n in self.cases():
            done = ' - done' if glob.glob(os.path.join(d, '*_sum.lis')) else ''
            self.caselist.insert('end',
                                 os.path.relpath(d, M.work_root()) + done)

    def do_run(self):
        sel = self.selected()
        if not sel:
            messagebox.showinfo('Nothing to run', 'Write an input on tab 3 first.')
            return
        if not shutil.which('rfluka'):
            messagebox.showerror('No FLUKA', 'rfluka is not on PATH.')
            return
        try:
            cyc, jobs = int(self.cycles.get()), max(1, int(self.jobs.get()))
        except ValueError:
            messagebox.showerror('Bad number', 'Cycles and cores must be whole numbers.')
            return
        self.prog.start(12)

        def job():
            for d, n in sel:
                self.log(f'\n--- {d}: {cyc} cycles on {jobs} core(s)')
                if glob.glob(os.path.join(d, '*_sum.lis')):
                    self.log('  already done, skipping')
                    continue
                if self.transport(d, n, cyc, jobs):
                    self.log('  FAILED')
        self.work(job, done=lambda: (self.prog.stop(), self.fill_cases(),
                                     self.fill_results(), self.nb.select(4)))

    def transport(self, d, name, cycles, jobs):
        # the executable belongs to the case, so the case is self-contained
        exe = B.exe_for(d)
        text = open(os.path.join(d, name + '.inp')).read()
        needs = '\nSOURCE' in '\n' + text or '\nUSRBIN' in text and 'airway' in text
        if needs and not os.access(exe, os.X_OK):
            self.log('  this case needs flukamrcp; building it from your FLUKA')
            ok, msg = B.build(log=self.log, dest=d)
            self.log('  ' + msg)
            if not ok:
                return 1
        e = ['-e', exe] if needs else []
        per = [cycles // jobs + (1 if w < cycles % jobs else 0) for w in range(jobs)]
        procs, wdirs = [], []
        for w, ncyc in enumerate(per, start=1):
            if not ncyc:
                continue
            wd = os.path.join(d, f'w{w:02d}')
            os.makedirs(wd, exist_ok=True)
            wdirs.append(wd)
            src = open(os.path.join(d, name + '.inp')).read().splitlines()
            with open(os.path.join(wd, name + '.inp'), 'w') as fh:
                for line in src:
                    if line.startswith('RANDOMIZ'):
                        fh.write(f'{"RANDOMIZ":<10}{"1.0":>10}{10000+w*7919:>10}\n')
                    elif line.startswith('../'):
                        fh.write('../' + line + '\n')
                    else:
                        fh.write(line + '\n')
            procs.append(subprocess.Popen(
                ['rfluka', *e, '-N0', f'-M{ncyc}', name], cwd=wd,
                stdout=open(os.path.join(wd, 'rfluka.log'), 'w'),
                stderr=subprocess.STDOUT))
        self.log(f'  {len(procs)} process(es) started')
        bad = sum(1 for p in procs if p.wait() != 0)
        fort = sorted(glob.glob(os.path.join(d, 'w[0-9][0-9]', '*_fort.21')))
        if bad or len(fort) != cycles:
            self.log(f'  {len(fort)}/{cycles} cycles; see {d}/w*/rfluka.log')
            return 1
        self.log('  merging with usbsuw')
        rel = '\n'.join(os.path.relpath(x, d) for x in fort)
        subprocess.run(['usbsuw'], cwd=d, input=rel + f'\n\n{name}_sum\n',
                       text=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        subprocess.run(['usbrea'], cwd=d, text=True,
                       input=f'{name}_sum.bnn\n{name}_sum.lis\n\n',
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not os.path.exists(os.path.join(d, name + '_sum.lis')):
            self.log('  usbsuw/usbrea produced no _sum.lis')
            return 1
        for wd in wdirs:
            shutil.rmtree(wd, ignore_errors=True)
        self.log('  done')
        return 0

    # ----------------------------------------------------------- 5 results
    def build_results(self, f):
        ttk.Label(f, text='Doses', font=('', 11, 'bold')).pack(anchor='w')
        row = ttk.Frame(f)
        row.pack(fill='x', pady=6)
        ttk.Label(row, text='Case').pack(side='left')
        self.rcase = tk.StringVar()
        self.rbox = ttk.Combobox(row, textvariable=self.rcase, state='readonly',
                                 width=40)
        self.rbox.pack(side='left', padx=6)
        ttk.Button(row, text='Target regions',
                   command=lambda: self.show(True)).pack(side='left')
        ttk.Button(row, text='Every organ',
                   command=lambda: self.show(False)).pack(side='left', padx=6)
        ttk.Label(row, text='sigma').pack(side='left', padx=(12, 2))
        self.sigma = tk.StringVar(value='1')
        ttk.Combobox(row, textvariable=self.sigma, state='readonly', width=3,
                     values=['1', '2', '3']).pack(side='left')
        ttk.Button(row, text='Save CSV...',
                   command=self.save_csv).pack(side='left', padx=6)
        cols = ('name', 'mass', 'dose', 'err')
        self.tree = ttk.Treeview(f, columns=cols, show='headings')
        for c, t, w in zip(cols, ('region', 'mass (g)', 'Gy per primary',
                                  'error %'), (300, 100, 150, 90)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor='w' if c == 'name' else 'e')
        self.tree.pack(fill='both', expand=True)

    def fill_results(self):
        done = [d for d, _n in self.cases()
                if glob.glob(os.path.join(d, '*_sum.lis'))]
        self._results = {os.path.relpath(d, M.work_root()): d for d in done}
        vals = list(self._results)
        self.rbox['values'] = vals
        if vals and self.rcase.get() not in vals:
            self.rcase.set(vals[0])

    def show(self, as_targets):
        d = getattr(self, '_results', {}).get(self.rcase.get())
        if not d:
            messagebox.showinfo('No result', 'No merged result yet.')
            return
        lis = glob.glob(os.path.join(d, '*_sum.lis'))[0]
        sex = os.path.basename(d).split('_')[0]
        self.tree.delete(*self.tree.get_children())
        out = []
        if as_targets:
            self.log(f'\n$ python3 targets.py {sex} {lis}')
            for o in T.compute(sex, lis):
                out.append(dict(id=o['target'], name=o['name'],
                                mass_g=float(o['mass_g']),
                                dose_Gy=float(o['dose_Gy']),
                                err_pct=float(o['err_pct'])))
        else:
            self.log(f'\n$ python3 read_doses.py {sex} {lis}')
            vals, errs = R.read_usrbin_ascii(lis)
            rows = R.load_regions(sex, lis)
            for v, e, r in zip(vals, errs, rows):
                dose = v / float(r['volume_cm3']) * R.GEV_J * 1000.0
                out.append(dict(id=r['region'], name=r['organ'],
                                mass_g=float(r['mass_g']),
                                dose_Gy=dose, err_pct=float(e)))
        for o in out:
            self.tree.insert('', 'end', values=(
                f'{o["id"]}  {o["name"]}', f'{o["mass_g"]:.2f}',
                f'{o["dose_Gy"]:.4e}', f'{o["err_pct"]:.2f}'))
        self._csv = dict(rows=out, sex=sex,
                         case=self.rcase.get(),
                         view='targets' if as_targets else 'organs')

    def save_csv(self):
        """The shown table as CSV, errors scaled to the chosen sigma level.

        usbsuw reports the 1-sigma standard error of the cycle mean; k sigma
        is that value times k, both as a percentage and in Gy.
        """
        got = getattr(self, '_csv', None)
        if not got:
            messagebox.showinfo('Nothing shown',
                                'Show Target regions or Every organ first.')
            return
        k = int(self.sigma.get())
        p = filedialog.asksaveasfilename(
            defaultextension='.csv', filetypes=[('CSV', '*.csv')],
            initialfile=f'{got["case"]}_{got["view"]}_{k}sigma.csv')
        if not p:
            return
        import csv as csvmod
        with open(p, 'w', newline='') as f:
            c = csvmod.writer(f)
            c.writerow([f'# case {got["case"]}  phantom {got["sex"]}  '
                        f'{got["view"]}  uncertainties at {k} sigma'])
            c.writerow(['id', 'name', 'mass_g', 'dose_Gy_per_primary',
                        f'uncertainty_pct_{k}sigma',
                        f'uncertainty_Gy_{k}sigma'])
            for o in got['rows']:
                c.writerow([o['id'], o['name'], f'{o["mass_g"]:.4f}',
                            f'{o["dose_Gy"]:.6e}',
                            f'{k * o["err_pct"]:.3f}',
                            f'{k * o["err_pct"] / 100.0 * o["dose_Gy"]:.3e}'])
        self.log(f'\n  wrote {p}  ({len(got["rows"])} rows, {k} sigma)')


    # ----------------------------------------------------------- 6 view
    def build_view(self, f):
        ttk.Label(f, text='View a case', font=('', 11, 'bold')).pack(anchor='w')
        ttk.Label(f, justify='left', foreground='#555', text=(
            'Slice through the phantom: anatomy, airways and dose, in any '
            'combination.\nOnly cases that have been run can show dose.')
                  ).pack(anchor='w', pady=(4, 8))
        ttk.Label(f, text='Case:').pack(anchor='w')
        self.viewlist = tk.Listbox(f, height=6, exportselection=False)
        self.viewlist.pack(fill='both', expand=True)
        b = ttk.Frame(f)
        b.pack(fill='x', pady=8)
        ttk.Button(b, text='Refresh', command=self.fill_view).pack(side='left')
        ttk.Button(b, text='Process results',
                   command=self.do_prepare_view).pack(side='left', padx=8)
        ttk.Button(b, text='Open the viewer',
                   command=self.do_open_view).pack(side='left')
        self.view_hint = ttk.Label(f, justify='left', foreground='#666')
        self.view_hint.pack(anchor='w')
        self.fill_view()

    def view_cases(self):
        """(directory, run name, has result) for every case."""
        out = []
        for d, n in self.cases():
            lis = glob.glob(os.path.join(d, '*_sum.lis'))
            raw = glob.glob(os.path.join(d, '*_fort.21'))
            out.append((d, n, lis[0] if lis else None, bool(raw)))
        return out

    def fill_view(self):
        self.viewlist.delete(0, 'end')
        self._view = self.view_cases()
        for d, _n, lis, raw in self._view:
            state = 'ready' if lis else ('needs processing' if raw else 'not run')
            self.viewlist.insert('end',
                                 f'{os.path.relpath(d, M.work_root())}  -  {state}')
        if self._view:
            self.viewlist.selection_set(0)
        self.view_hint.configure(text='')

    def view_pick(self):
        sel = self.viewlist.curselection()
        if not sel:
            messagebox.showinfo('No case', 'Choose a case first.')
            return None
        return self._view[sel[0]]

    def do_prepare_view(self):
        """Merge the cycles and convert to text, and build the voxel cache.

        usbsuw is what produces the per-bin errors, and usbrea is what makes a
        file anything can read; the viewer needs both. The voxel cache takes
        about a minute and is then reused by every case of that phantom.
        """
        got = self.view_pick()
        if not got:
            return
        d, name, lis, raw = got
        sex = os.path.basename(d).split('_')[0]

        def job():
            import voxelise as V
            target = lis
            if not target:
                if not raw:
                    self.log('  this case has not been run')
                    return
                cyc = sorted(glob.glob(os.path.join(d, '*_fort.21')))
                self.log(f'\n$ ls *_fort.21 | usbsuw     ({len(cyc)} cycles)')
                stem = f'{name}_sum'
                subprocess.run(['usbsuw'], cwd=d, text=True,
                               input='\n'.join(os.path.basename(c) for c in cyc)
                                     + f'\n\n{stem}\n', capture_output=True)
                self.log('$ usbrea')
                subprocess.run(['usbrea'], cwd=d, text=True,
                               input=f'{stem}.bnn\n{stem}.lis\n\n',
                               capture_output=True)
                target = os.path.join(d, f'{stem}.lis')
                self.log('  ' + ('wrote ' + os.path.basename(target)
                                 if os.path.exists(target) else 'usbsuw failed'))
            if V.load(sex) is None:
                self.log(f'\n$ python3 voxelise.py {sex}   (once, about a minute)')
                V.build(sex, log=lambda m: self.log('  ' + m))
            else:
                self.log(f'  voxel cache for {sex} is already built')
        self.work(job, done=self.fill_view)

    def do_open_view(self):
        got = self.view_pick()
        if not got:
            return
        d, name, lis, _raw = got
        sex = os.path.basename(d).split('_')[0]
        lis = lis or (glob.glob(os.path.join(d, '*_sum.lis')) or [None])[0]
        cmd = [sys.executable, os.path.join(HERE, 'slicer.py'), sex]
        reg = os.path.join(d, f'{sex}_regions.csv')
        if lis and os.path.exists(reg):
            cmd += ['--lis', lis, '--regions', reg]
        else:
            self.view_hint.configure(
                text='no result yet: the viewer will show anatomy and airways only')
        self.log('\n$ ' + ' '.join(os.path.basename(c) if i == 1 else c
                                    for i, c in enumerate(cmd)))
        subprocess.Popen(cmd, cwd=HERE)

    # --------------------------------------------------------------------


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
