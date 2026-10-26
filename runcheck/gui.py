"""RunCheck desktop window (tkinter, so there is nothing extra to install)."""
from __future__ import annotations
import queue, threading, tkinter as tk
from tkinter import ttk, font as tkfont

from . import __version__
from .advice import build_report, pc_tier
from .cli import load_requirements
from .compare import compare, BELOW, BORDERLINE, MINIMUM, RECOMMENDED, EXCEEDS
from .specs import Specs, detect
from .steam import search_game

C = dict(bg="#12141a", card="#1b1f29", line="#2a2f3d", text="#e8eaf0", muted="#9aa3b5",
         accent="#5b8def", accent_dark="#4673c9", field="#0f1117")
VERDICT_COLOR = {BELOW: "#e5534b", BORDERLINE: "#e08a3c", MINIMUM: "#d6b42e",
                 RECOMMENDED: "#3fb27f", EXCEEDS: "#2bb5a0", None: "#7a8399"}
LEVEL_COLOR = {BELOW: "#e5534b", BORDERLINE: "#e08a3c", MINIMUM: "#d6b42e",
               RECOMMENDED: "#3fb27f", EXCEEDS: "#2bb5a0", None: "#4a5163"}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"RunCheck {__version__} - Can your PC run it?")
        self.geometry("1000x760")
        self.minsize(820, 600)
        self.configure(bg=C["bg"])
        self.specs: Specs | None = None
        self.q: queue.Queue = queue.Queue()
        self._wrap_labels: list[tk.Label] = []
        self._part_labels: list[tk.Label] = []
        self._suggest_job = None
        self._suggest_items: list[dict] = []
        self._busy = False
        self._edited = False          # user edited specs: don't let a late auto-detect overwrite them

        fam = "Segoe UI" if "Segoe UI" in tkfont.families() else "Helvetica"
        self.f_base = (fam, 10)
        self.f_small = (fam, 9)
        self.f_bold = (fam, 10, "bold")
        self.f_h2 = (fam, 13, "bold")
        self.f_h1 = (fam, 22, "bold")
        self.f_big = (fam, 17, "bold")

        self._build()
        self.after(100, self._poll)
        self.rescan()

    # ---------- layout ----------
    def _build(self):
        head = tk.Frame(self, bg=C["bg"])
        head.pack(fill="x", padx=24, pady=(20, 6))
        tk.Label(head, text="RunCheck", font=self.f_h1, fg=C["text"], bg=C["bg"]).pack(side="left")
        tk.Label(head, text="  Can your PC run it?", font=(self.f_base[0], 12), fg=C["muted"], bg=C["bg"]).pack(side="left", pady=(10, 0))

        # PC card
        self.pc_card = tk.Frame(self, bg=C["card"], highlightbackground=C["line"], highlightthickness=1)
        self.pc_card.pack(fill="x", padx=24, pady=8)
        top = tk.Frame(self.pc_card, bg=C["card"])
        top.pack(fill="x", padx=16, pady=(12, 2))
        tk.Label(top, text="YOUR PC", font=self.f_small, fg=C["muted"], bg=C["card"]).pack(side="left")
        self.tier_badge = tk.Label(top, text="", font=self.f_bold, fg="#0b0d12", bg=C["accent"], padx=8, pady=1)
        self.tier_badge.pack(side="left", padx=10)
        self._link(top, "Edit", self.edit_specs).pack(side="right")
        self._link(top, "Rescan", self.rescan).pack(side="right", padx=14)
        self.pc_text = tk.Label(self.pc_card, text="Detecting your hardware...", font=self.f_base, fg=C["text"],
                                bg=C["card"], justify="left", anchor="w")
        self.pc_text.pack(fill="x", padx=16, pady=(0, 4))
        self.tier_text = tk.Label(self.pc_card, text="", font=self.f_small, fg=C["muted"], bg=C["card"],
                                  justify="left", anchor="w")
        self.tier_text.pack(fill="x", padx=16, pady=(0, 12))
        self._wrap_labels += [self.tier_text]

        # Search row
        row = tk.Frame(self, bg=C["bg"])
        row.pack(fill="x", padx=24, pady=(10, 0))
        self.entry = tk.Entry(row, font=(self.f_base[0], 13), bg=C["field"], fg=C["text"], insertbackground=C["text"],
                              relief="flat", highlightthickness=1, highlightbackground=C["line"], highlightcolor=C["accent"])
        self.entry.pack(side="left", fill="x", expand=True, ipady=9)
        self.entry.bind("<Return>", lambda e: self.check())
        self.entry.bind("<KeyRelease>", self._on_type)
        self.entry.bind("<Down>", lambda e: self._focus_suggestions())
        self.btn = tk.Button(row, text="Check", font=(self.f_base[0], 11, "bold"), bg=C["accent"], fg="white",
                             activebackground=C["accent_dark"], activeforeground="white", relief="flat",
                             padx=26, command=self.check, cursor="hand2")
        self.btn.pack(side="left", padx=(10, 0), ipady=5)
        self.hint = tk.Label(self, text="Type a Steam game name (or its Steam ID) and press Enter.",
                             font=self.f_small, fg=C["muted"], bg=C["bg"], anchor="w")
        self.hint.pack(fill="x", padx=26, pady=(4, 0))
        self.entry.focus_set()

        self.suggest = tk.Listbox(self, font=self.f_base, bg=C["card"], fg=C["text"], selectbackground=C["accent"],
                                  selectforeground="white", relief="flat", highlightthickness=1,
                                  highlightbackground=C["line"], activestyle="none", height=0)
        self.suggest.bind("<<ListboxSelect>>", lambda e: None)
        self.suggest.bind("<Return>", lambda e: self._pick_suggestion())
        self.suggest.bind("<Double-Button-1>", lambda e: self._pick_suggestion())
        self.suggest.bind("<ButtonRelease-1>", lambda e: self._pick_suggestion())

        # Results (scrollable)
        wrap = tk.Frame(self, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=(24, 8), pady=(10, 0))
        self.canvas = tk.Canvas(wrap, bg=C["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.results = tk.Frame(self.canvas, bg=C["bg"])
        self._win = self.canvas.create_window((0, 0), window=self.results, anchor="nw")
        self.results.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(ev, self._on_wheel)

        self.status = tk.Label(self, text="", font=self.f_small, fg=C["muted"], bg=C["card"], anchor="w", padx=24, pady=5)
        self.status.pack(fill="x", side="bottom")
        self._welcome()

    def _link(self, parent, text, cmd):
        l = tk.Label(parent, text=text, font=self.f_small, fg=C["accent"], bg=C["card"], cursor="hand2")
        l.bind("<Button-1>", lambda e: cmd())
        return l

    def _on_canvas_resize(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)
        self._rewrap(e.width)

    def _rewrap(self, width=None):
        width = width or self.canvas.winfo_width()
        for l in list(self._wrap_labels):
            try:
                l.configure(wraplength=max(260, width - 90))
            except tk.TclError:
                self._wrap_labels.remove(l)
        for l in list(self._part_labels):          # leave room for the status bar on the right
            try:
                l.configure(wraplength=max(200, width - 380))
            except tk.TclError:
                self._part_labels.remove(l)

    def _on_wheel(self, e):
        if self.canvas.winfo_height() >= self.results.winfo_reqheight():
            return
        if e.num == 4: d = -3
        elif e.num == 5: d = 3
        else: d = -1 * int(e.delta / 40) or (-1 if e.delta > 0 else 1)
        self.canvas.yview_scroll(d, "units")

    # ---------- results helpers ----------
    def _clear(self):
        for w in self.results.winfo_children():
            w.destroy()
        self._wrap_labels = [l for l in self._wrap_labels if l is self.tier_text]
        self._part_labels = []
        self.canvas.yview_moveto(0)

    def _card(self, parent=None, pad=(0, 10)):
        f = tk.Frame(parent or self.results, bg=C["card"], highlightbackground=C["line"], highlightthickness=1)
        f.pack(fill="x", padx=(0, 16), pady=pad)
        return f

    def _wlabel(self, parent, text, font=None, fg=None, bg=None, **kw):
        l = tk.Label(parent, text=text, font=font or self.f_base, fg=fg or C["text"], bg=bg or parent["bg"],
                     justify="left", anchor="w", **kw)
        self._wrap_labels.append(l)
        return l

    def _welcome(self):
        self._clear()
        c = self._card()
        self._wlabel(c, "Find out if a game will run on this PC", self.f_h2).pack(fill="x", padx=18, pady=(16, 4))
        self._wlabel(c, "Search for any game on Steam. RunCheck compares its requirements with your hardware and tells you "
                        "what to expect: settings, resolution, frame rate, what is holding you back, and what to do about it. "
                        "It works for every kind of PC, including older laptops.", fg=C["muted"]).pack(fill="x", padx=18, pady=(0, 16))
        self._rewrap()

    def _message(self, title, body, color=None):
        self._clear()
        c = self._card()
        tk.Frame(c, bg=color or C["accent"], height=4).pack(fill="x")
        self._wlabel(c, title, self.f_h2).pack(fill="x", padx=18, pady=(14, 4))
        self._wlabel(c, body, fg=C["muted"]).pack(fill="x", padx=18, pady=(0, 16))
        self._rewrap()

    # ---------- PC detection ----------
    def rescan(self):
        self._edited = False
        self.pc_text.config(text="Detecting your hardware...")
        self.tier_badge.config(text="")
        threading.Thread(target=lambda: self.q.put(("specs", self._safe(detect))), daemon=True).start()

    @staticmethod
    def _safe(fn, *a):
        try:
            return fn(*a)
        except Exception as e:      # shown to the user, never crashes the window
            return e

    def set_specs(self, s: Specs):
        self.specs = s
        gpu = s.best_gpu()
        gpu_txt = "unknown" if not gpu else gpu["name"] + (f"  ({gpu['vram_gb']:g} GB)" if gpu.get("vram_gb") else "")
        self.pc_text.config(text=f"CPU: {s.cpu}\nGPU: {gpu_txt}\nRAM: {s.ram_gb:g} GB     Free disk: {s.free_disk_gb:g} GB")
        tier, blurb, _ = pc_tier(s)
        self.tier_badge.config(text=f" {tier} ")
        self.tier_text.config(text=blurb)
        self._rewrap()

    def edit_specs(self):
        if not self.specs:
            return
        s = self.specs
        gpu = s.best_gpu() or {"name": "", "vram_gb": None}
        win = tk.Toplevel(self, bg=C["card"])
        win.title("Edit PC specs")
        win.transient(self)
        win.geometry(f"+{self.winfo_rootx() + 140}+{self.winfo_rooty() + 90}")
        self._hide_suggestions()
        win.resizable(False, False)
        tk.Label(win, text="Fix wrong values, or type in a different PC to check.", font=self.f_small,
                 fg=C["muted"], bg=C["card"]).grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 8), sticky="w")
        fields = [("CPU", s.cpu), ("GPU", gpu["name"]), ("VRAM (GB)", gpu.get("vram_gb") or ""),
                  ("RAM (GB)", s.ram_gb), ("Free disk (GB)", s.free_disk_gb)]
        vars_ = []
        for i, (label, val) in enumerate(fields, start=1):
            tk.Label(win, text=label, font=self.f_base, fg=C["text"], bg=C["card"]).grid(row=i, column=0, padx=(16, 8), pady=4, sticky="e")
            v = tk.StringVar(value=str(val))
            tk.Entry(win, textvariable=v, width=44, font=self.f_base, bg=C["field"], fg=C["text"],
                     insertbackground=C["text"], relief="flat", highlightthickness=1,
                     highlightbackground=C["line"], highlightcolor=C["accent"]).grid(row=i, column=1, padx=(0, 16), pady=4, ipady=4)
            vars_.append(v)

        def num(v, default):
            try:
                return float(v.get().replace(",", "."))
            except ValueError:
                return default

        def save():
            self._edited = True
            self.set_specs(Specs(os=s.os, cpu=vars_[0].get().strip() or s.cpu, cpu_cores=s.cpu_cores,
                                 cpu_threads=s.cpu_threads,
                                 gpus=[{"name": vars_[1].get().strip(), "vram_gb": num(vars_[2], None)}],
                                 ram_gb=num(vars_[3], s.ram_gb), free_disk_gb=num(vars_[4], s.free_disk_gb)))
            win.destroy()

        tk.Button(win, text="Save", command=save, font=self.f_bold, bg=C["accent"], fg="white", relief="flat",
                  activebackground=C["accent_dark"], activeforeground="white", padx=22, pady=4).grid(
            row=len(fields) + 1, column=1, sticky="e", padx=16, pady=14)

    # ---------- searching ----------
    def _on_type(self, e):
        if e.keysym in ("Return", "Down", "Up", "Escape"):
            return
        if self._suggest_job:
            self.after_cancel(self._suggest_job)
        text = self.entry.get().strip()
        if len(text) < 3 or text.isdigit():
            self._hide_suggestions()
            return
        self._suggest_job = self.after(450, lambda: self._suggest_for(text))

    def _suggest_for(self, text):
        threading.Thread(target=lambda: self.q.put(("suggest", (text, self._safe(search_game, text)))), daemon=True).start()

    def _show_suggestions(self, items):
        self._suggest_items = items[:6]
        self.suggest.delete(0, "end")
        for it in self._suggest_items:
            self.suggest.insert("end", "  " + it["name"])
        if not self._suggest_items:
            return self._hide_suggestions()
        self.suggest.configure(height=len(self._suggest_items))
        self.suggest.place(in_=self.entry, x=0, rely=1.0, relwidth=1.0, y=1)
        self.suggest.lift()

    def _hide_suggestions(self):
        self.suggest.place_forget()
        self._suggest_items = []

    def _focus_suggestions(self):
        if self._suggest_items:
            self.suggest.focus_set()
            self.suggest.selection_set(0)

    def _pick_suggestion(self):
        sel = self.suggest.curselection()
        if not sel:
            return
        item = self._suggest_items[sel[0]]
        self.entry.delete(0, "end")
        self.entry.insert(0, item["name"])
        self._hide_suggestions()
        self._run_check(item["id"], item["name"])

    # ---------- checking ----------
    def check(self):
        text = self.entry.get().strip()
        self._hide_suggestions()
        if not text or self._busy:
            return
        if not self.specs:
            self._message("Still detecting your PC", "Give it a second, then try again.")
            return
        if text.isdigit():
            return self._run_check(int(text), text)
        self._set_busy(True, "Searching Steam...")
        threading.Thread(target=lambda: self.q.put(("search_done", (text, self._safe(search_game, text)))), daemon=True).start()

    def _run_check(self, app_id, name):
        if self._busy and self.btn["state"] == "disabled" and self.status["text"].startswith("Checking"):
            return
        self._set_busy(True, f"Checking {name}...")
        specs = self.specs

        def work():
            req = self._safe(load_requirements, app_id)
            if isinstance(req, Exception):
                self.q.put(("error", req))
            else:
                res = compare(specs, req)
                self.q.put(("result", (specs, res)))
        threading.Thread(target=work, daemon=True).start()

    def _set_busy(self, busy, text=""):
        self._busy = busy
        self.btn.config(state="disabled" if busy else "normal")
        self.status.config(text=text)

    # ---------- event loop ----------
    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                getattr(self, "_on_" + kind)(payload)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _on_specs(self, s):
        if self._edited:
            return
        if isinstance(s, Exception):
            self.pc_text.config(text="Couldn't detect your hardware automatically. Click Edit to enter it.")
            self.specs = Specs()
        else:
            self.set_specs(s)

    def _on_suggest(self, payload):
        text, items = payload
        if text != self.entry.get().strip() or isinstance(items, Exception):
            return
        self._show_suggestions(items)

    def _on_search_done(self, payload):
        text, items = payload
        self._set_busy(False, "")
        if isinstance(items, Exception):
            return self._message("Couldn't reach Steam", "Check your internet connection. Games you've checked before still work offline "
                                 "if you type their Steam ID.", VERDICT_COLOR[BELOW])
        if not items:
            return self._message("No game found", f"Steam has nothing matching '{text}'. Try a different spelling.", VERDICT_COLOR[BORDERLINE])
        exact = [i for i in items if i["name"].lower() == text.lower()]
        if exact or len(items) == 1:
            it = (exact or items)[0]
            return self._run_check(it["id"], it["name"])
        self._message("Which one did you mean?", "Pick a game from the list under the search box.", C["accent"])
        self._show_suggestions(items)

    def _on_error(self, e):
        self._set_busy(False, "")
        self._message("Couldn't check this game", f"{e}\n\nSome games don't list PC requirements on Steam. If you're offline, "
                      "only games you've checked before are available.", VERDICT_COLOR[BELOW])

    def _on_result(self, payload):
        specs, res = payload
        self._set_busy(False, "")
        self.render(build_report(specs, res), res)

    # ---------- result rendering ----------
    def render(self, rep, res):
        self._clear()
        color = VERDICT_COLOR[rep.verdict]
        # Verdict banner
        b = tk.Frame(self.results, bg=color)
        b.pack(fill="x", padx=(0, 16), pady=(0, 10))
        tk.Label(b, text=rep.game.upper(), font=self.f_small, fg="#0b0d12", bg=color, anchor="w").pack(fill="x", padx=18, pady=(12, 0))
        self._wlabel(b, rep.headline, self.f_big, fg="#0b0d12").pack(fill="x", padx=18)
        self._wlabel(b, rep.summary, fg="#0b0d12").pack(fill="x", padx=18, pady=(2, 14))

        # Expected experience tiles
        tiles = tk.Frame(self.results, bg=C["bg"])
        tiles.pack(fill="x", padx=(0, 16), pady=(0, 10))
        for i, (lab, val) in enumerate((("SETTINGS", rep.settings), ("RESOLUTION", rep.resolution), ("FRAME RATE", rep.fps))):
            tiles.columnconfigure(i, weight=1, uniform="t")
            t = tk.Frame(tiles, bg=C["card"], highlightbackground=C["line"], highlightthickness=1)
            t.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            tk.Label(t, text=lab, font=self.f_small, fg=C["muted"], bg=C["card"]).pack(anchor="w", padx=14, pady=(10, 0))
            tk.Label(t, text=val, font=self.f_bold, fg=C["text"], bg=C["card"], wraplength=200, justify="left").pack(
                anchor="w", padx=14, pady=(2, 10))

        # Component breakdown
        card = self._card()
        tk.Label(card, text="Part by part", font=self.f_h2, fg=C["text"], bg=C["card"]).pack(anchor="w", padx=18, pady=(14, 6))
        for p in res.parts:
            self._part_row(card, p)
        tk.Frame(card, bg=C["card"], height=8).pack()

        # Advice sections
        for title, bullets in rep.sections:
            c = self._card()
            tk.Label(c, text=title, font=self.f_h2, fg=C["text"], bg=C["card"]).pack(anchor="w", padx=18, pady=(14, 4))
            for t in bullets:
                r = tk.Frame(c, bg=C["card"])
                r.pack(fill="x", padx=18, pady=2)
                tk.Label(r, text="•", font=self.f_base, fg=color, bg=C["card"]).pack(side="left", anchor="n", padx=(0, 8))
                self._wlabel(r, t).pack(side="left", fill="x", expand=True)
            tk.Frame(c, bg=C["card"], height=10).pack()

        self._wlabel(self.results, rep.confidence, self.f_small, fg=C["muted"]).pack(fill="x", pady=(0, 20))
        self._rewrap()
        self.canvas.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _part_row(self, parent, p):
        row = tk.Frame(parent, bg=C["card"])
        row.pack(fill="x", padx=18, pady=5)
        row.columnconfigure(1, weight=1)
        tk.Label(row, text=p.name, font=self.f_bold, fg=C["text"], bg=C["card"], width=6, anchor="w").grid(row=0, column=0, rowspan=2, sticky="nw")
        yours = tk.Label(row, text=p.yours, font=self.f_base, fg=C["text"], bg=C["card"], anchor="w", justify="left")
        yours.grid(row=0, column=1, sticky="w")
        need = "Needs: " + (f"{p.min_req or '-'}  \u2192  {p.rec_req}" if p.rec_req and p.rec_req != p.min_req else (p.min_req or "not listed"))
        need_l = tk.Label(row, text=need, font=self.f_small, fg=C["muted"], bg=C["card"], anchor="w", justify="left")
        need_l.grid(row=1, column=1, sticky="w")
        self._part_labels += [yours, need_l]
        status = {BELOW: "Below minimum", BORDERLINE: "Just under", MINIMUM: "Meets minimum",
                  RECOMMENDED: "Recommended", EXCEEDS: "Exceeds", None: "Can't compare"}[p.level]
        right = tk.Frame(row, bg=C["card"])
        right.grid(row=0, column=2, rowspan=2, sticky="e", padx=(12, 0))
        if p.level is None:
            tk.Label(right, text=status, font=self.f_small, fg=C["muted"], bg=C["card"]).pack(anchor="e")
            if p.note:
                tk.Label(right, text=p.note, font=self.f_small, fg=C["muted"], bg=C["card"], wraplength=230, justify="right").pack(anchor="e")
            return
        bar = tk.Canvas(right, width=200, height=14, bg=C["card"], highlightthickness=0)
        bar.pack(anchor="e")
        bar.create_rectangle(0, 4, 200, 10, fill=C["line"], outline="")
        if p.vs_rec:
            frac, rec_x, min_x = min(p.vs_rec / 2, 1), 100, 100 * (p.vs_rec / p.vs_min)
        else:
            frac, rec_x, min_x = min(p.vs_min / 2, 1), None, 100
        bar.create_rectangle(0, 4, max(3, 200 * frac), 10, fill=LEVEL_COLOR[p.level], outline="")
        if rec_x: bar.create_line(rec_x, 0, rec_x, 14, fill=C["muted"])
        if min_x != rec_x: bar.create_line(min_x, 2, min_x, 12, fill=C["muted"], dash=(2, 2))
        tk.Label(right, text=status, font=self.f_small, fg=LEVEL_COLOR[p.level], bg=C["card"]).pack(anchor="e")


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
