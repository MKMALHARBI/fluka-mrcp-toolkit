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

__version__ = '1.1.0'

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
os.chdir(HERE)
sys.path.insert(0, HERE)

import make_umesh as M                                        # noqa: E402
import make_examples as X                                     # noqa: E402
import setup_data as D                                        # noqa: E402
import build_exe as B                                         # noqa: E402
import targets as T                                           # noqa: E402
import read_doses as R                                        # noqa: E402

COMMON = ['PHOTON', 'ELECTRON', 'POSITRON', 'NEUTRON', 'PROTON', 'ALPHA',
          'DEUTERON', 'TRITON', '3-HELIUM', 'MUON+', 'MUON-', 'ISOTOPE']


def particle_names():
    import re
    try:
        s = open('/usr/local/flair/db/fluka.ini', encoding='utf-8',
                 errors='replace').read()
        pid = {int(m.group(1)): m.group(2)
               for m in re.finditer(r'^pid\.(-?\d+)=\s*(\S+)', s, re.M)}
        names = [pid[k] for k in sorted(pid)
                 if k >= 1 and pid[k] not in ('RAY', 'OPTIPHOT')]
    except OSError:
        names = list(COMMON)
    head = [p for p in COMMON if p in names]
    return head + [p for p in names if p not in head]


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.busy = False
        self.alive = True
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.organs = {}
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
                                  '4  Run', '5  Results')):
            f = ttk.Frame(self.nb, padding=12)
            self.nb.add(f, text=name)
            self.tabs[i] = f

        self.build_data(self.tabs[0])
        self.build_phantom(self.tabs[1])
        self.build_case(self.tabs[2])
        self.build_run(self.tabs[3])
        self.build_results(self.tabs[4])

        ttk.Label(root, text='Log', foreground='#555').pack(anchor='w', padx=12)
        self.out = scrolledtext.ScrolledText(root, height=11, wrap='word')
        self.out.pack(fill='both', expand=False, padx=10, pady=(0, 10))

        self.refresh_where()
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
                    try:
                        self.root.after(0, done)
                    except (RuntimeError, tk.TclError):
                        pass          # window closed while the job was running
        threading.Thread(target=wrap, daemon=True).start()

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
            'The zip as downloaded, or an unpacked folder. Takes 900 MB of it '
            'and remembers\nwhere. Not distributed with the toolkit; see '
            'REQUIREMENTS.md.')).pack(anchor='w', pady=(4, 10))
        row = ttk.Frame(f)
        row.pack(fill='x')
        self.src = tk.StringVar()
        ttk.Entry(row, textvariable=self.src).pack(side='left', fill='x',
                                                   expand=True)
        ttk.Button(row, text='Zip...', command=self.pick_zip).pack(side='left', padx=4)
        ttk.Button(row, text='Folder...', command=self.pick_dir).pack(side='left')
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

    def pick_dir(self):
        p = filedialog.askdirectory(title='Folder holding the ICRP data')
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
        if self.refresh_where():
            self.log('  ready')
            self.nb.select(1)

    # ----------------------------------------------------------- 2 phantom
    def build_phantom(self, f):
        ttk.Label(f, text='Build the phantom',
                  font=('', 11, 'bold')).pack(anchor='w')
        ttk.Label(f, justify='left', foreground='#555', text=(
            'Writes the FLUKA cards and the region tables. Stops if the masses '
            'do not match\nICRP: 73.0 and 60.0 kg, red marrow 1170 and 900 g.')
                  ).pack(anchor='w', pady=(4, 10))
        ttk.Button(f, text='Build', command=self.do_build).pack(anchor='w')

    def do_build(self):
        if not self.refresh_where():
            messagebox.showwarning('No data', 'Set the data up on tab 1 first.')
            return
        self.log('\n$ python3 make_umesh.py')

        def job():
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                ok = all(M.build(s) for s in ('AM', 'AF'))
            for line in buf.getvalue().splitlines():
                self.log('  ' + line)
            self.log('  built.' if ok else '  FAILED -- see above')
        self.work(job, done=lambda: (self.load_organs(), self.nb.select(2)))

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

        self.sex = tk.StringVar(value='both')
        row('Phantom', ttk.Combobox(f, textvariable=self.sex, state='readonly',
            values=['both', 'AM  adult male, 73 kg', 'AF  adult female, 60 kg']))
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

        b = ttk.Frame(f)
        b.grid(row=r, column=0, columnspan=3, sticky='w', pady=10)
        ttk.Button(b, text='ICRP benchmark defaults',
                   command=self.reset_case).pack(side='left')
        ttk.Button(b, text='Write the input',
                   command=self.do_generate).pack(side='left', padx=8)

    def load_organs(self):
        def job():
            for sex in ('AM', 'AF'):
                d = M.assemble(sex)
                if d is None:
                    continue
                self.organs[sex] = [
                    (o, f'{o:<6} {d["mats"][o][0]}   ({d["mass"][o]:.0f} g)')
                    for o in d['ids']]
            self.root.after(0, self.fill_organs)
        self.work(job)

    def fill_organs(self):
        sex = 'AM' if self.sex.get() == 'both' else self.sex.get()[:2]
        items = self.organs.get(sex) or self.organs.get('AM') or []
        self.organ_box['values'] = [t for _, t in items]
        if items and self.organ.get() not in self.organ_box['values']:
            self.organ.set(next((t for o, t in items if o == X.ICRP_ORGAN),
                                items[0][1]))

    def reset_case(self):
        self.sex.set('both'); self.case.set('both')
        self.particle.set(X.ICRP_PARTICLE)
        self.energy.set(f'{X.ICRP_ENERGY:g}')
        self.px.set('0'); self.py.set('-100'); self.pz.set('0')
        self.primaries.set(str(X.PRIMARIES))
        self.fill_organs()

    def case_argv(self):
        a = []
        if self.sex.get() != 'both':
            a += ['--sex', self.sex.get()[:2]]
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
        return a

    def do_generate(self):
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
            'Cores are separate FLUKA processes. Cores above the number of '
            'cycles sit idle.')).pack(anchor='w', pady=(4, 8))
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
        ttk.Button(b, text='Run selected (or all)',
                   command=self.do_run).pack(side='left', padx=8)
        self.prog = ttk.Progressbar(f, mode='indeterminate')
        self.prog.pack(fill='x')

    def do_build_exe(self):
        self.log('\n$ python3 build_exe.py')
        self.work(lambda: self.log('  ' + B.build(log=self.log)[1]))

    def cases(self):
        return [(os.path.dirname(p), os.path.basename(p)[:-4])
                for p in sorted(glob.glob('A[MF]/*/*.inp'))]

    def fill_cases(self):
        self.caselist.delete(0, 'end')
        for d, n in self.cases():
            done = ' - done' if glob.glob(os.path.join(d, '*_sum.lis')) else ''
            self.caselist.insert('end', f'{d}{done}')

    def do_run(self):
        allc = self.cases()
        sel = [allc[i] for i in self.caselist.curselection()] or allc
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
        exe = os.path.join(HERE, 'flukamrcp')
        needs = '\nSOURCE' in '\n' + open(os.path.join(d, name + '.inp')).read()
        if needs and not os.access(exe, os.X_OK):
            self.log('  this case needs flukamrcp; building it from your FLUKA')
            ok, msg = B.build(log=self.log)
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
        cols = ('name', 'mass', 'dose', 'err')
        self.tree = ttk.Treeview(f, columns=cols, show='headings')
        for c, t, w in zip(cols, ('region', 'mass (g)', 'Gy per primary',
                                  'error %'), (300, 100, 150, 90)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor='w' if c == 'name' else 'e')
        self.tree.pack(fill='both', expand=True)

    def fill_results(self):
        done = [d for d, _n in self.cases() if glob.glob(os.path.join(d, '*_sum.lis'))]
        self.rbox['values'] = done
        if done and self.rcase.get() not in done:
            self.rcase.set(done[0])

    def show(self, as_targets):
        d = self.rcase.get()
        if not d:
            messagebox.showinfo('No result', 'No merged result yet.')
            return
        lis = glob.glob(os.path.join(d, '*_sum.lis'))[0]
        sex = d.split(os.sep)[0]
        self.tree.delete(*self.tree.get_children())
        if as_targets:
            self.log(f'\n$ python3 targets.py {sex} {lis}')
            for o in T.compute(sex, lis):
                self.tree.insert('', 'end', values=(
                    f'{o["target"]}  {o["name"]}', f'{float(o["mass_g"]):.2f}',
                    f'{float(o["dose_Gy"]):.4e}', f'{float(o["err_pct"]):.2f}'))
        else:
            self.log(f'\n$ python3 read_doses.py {sex} {lis}')
            vals, errs = R.read_usrbin_ascii(lis)
            rows = R.load_regions(sex)
            for v, e, r in zip(vals, errs, rows):
                dose = v / float(r['volume_cm3']) * R.GEV_J * 1000.0
                self.tree.insert('', 'end', values=(
                    f'{r["region"]}  {r["organ"]}', f'{float(r["mass_g"]):.2f}',
                    f'{dose:.4e}', f'{e:.2f}'))


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
