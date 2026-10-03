#!/usr/bin/env python3
"""Pixel Totoro Pomodoro widget.

A frameless timer parked in the bottom-right corner of the desktop. Type the
minutes straight onto its belly, name the task, hit start. The belly is a clock
face: the elapsed slice fills in pale teal against dark. When time is up he
comes to the front, swells and reddens while a beep counts it out, then
bursts into leaves, acorns and soot sprites.

Stdlib only. Run `python pomodoro.py --selftest` to check the logic.
"""
from __future__ import annotations

import ctypes
import datetime as dt
import math
import json
import os
import random
import sys
import threading
import time
import tkinter as tk

import font5x7 as F

# ---------------------------------------------------------------- settings

# Nothing is written anywhere by default. append_log() below is a complete,
# tested writer kept ready for the day this points at an Obsidian vault:
# set LOG_SESSIONS to a folder and finished sessions start landing there.
LOG_SESSIONS = None
LOG_DIR = os.path.join(os.path.expanduser("~"), "Notes", "Pomodoro")
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "state.json")

DEFAULT_MINUTES = 50
MARGIN = 18                    # equal gap from the right edge and the taskbar
BASE_SCALE = 4                 # screen pixels per sprite pixel at 100% scaling
SCALE = BASE_SCALE
KEY = "#ff00ff"                # magenta stands in for transparent

GRID_W, GRID_H = 44, 63
DISC_CX, DISC_CY, DISC_R = 22, 47, 11.0     # belly clock, in sprite pixels

# When the timer ends he loses his temper: swells to GROW_TO, turning red, then
# bursts. The window has to be big enough to hold him at full size, so it keeps
# GROW_TO worth of transparent room up and to the left of where he rests.
# The swell was cut to three quarters of its old length, because the wait
# before the bang dragged: RAGE_MS was 3000 and the swell was +0.5. Both the
# time and the growth were cut by a quarter together, which leaves the rate of
# swell exactly as it was -- he now bursts part way up the same curve instead
# of racing to the old size in less time.
GROW_TO = 1.375                 # 1.0 + 0.75 * 0.5
RAGE_MS = 2250                  # 0.75 * 3000
RAGE_STEP_MS = 90               # 25 frames, exactly
BOOM_MS = 1500
BOOM_STEP_MS = 35
BOOM_LEAVES = 26
BOOM_ACORNS = 14
BOOM_SPRITES = 16

PALETTE = {
    ".": KEY, "O": "#2f2f2f",
    "D": "#4d4d4d",            # ear tips, arms, feet, shading
    "M": "#878787",            # main grey coat
    "L": "#9e9e9e",            # lit edge and inner ear
    "C": "#ffffff",            # belly
    "K": "#8c8c8c",            # the marks on it
    "E": "#2f2f2f",            # eyes and nose
    "W": "#ffffff", "B": "#ff6b81",
}

# the clock face moved off brown to sit with the grey coat and white belly
DISC_DARK = "#334a52"          # time remaining
DISC_LIT = "#7aa3ab"           # time already spent
DISC_EDGE = "#1e2c31"
CREAM = "#f3f8f9"
TAN = "#b3cbd0"
INK = "#22333a"

# ------------------------------------------------------------------ sprite


def _blank():
    return [["." for _ in range(GRID_W)] for _ in range(GRID_H)]


def _ellipse(g, cx, cy, rx, ry, ch):
    for y in range(GRID_H):
        for x in range(GRID_W):
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
                g[y][x] = ch


def _ear(g, tip_x, base_x, tip_y, base_y, half, ch):
    """A tall ear that leans: the centre slides from tip to base as it widens."""
    span = base_y - tip_y
    for y in range(tip_y, base_y + 1):
        t = (y - tip_y) / span
        cx = tip_x + (base_x - tip_x) * t
        w = 0.5 + (half - 0.5) * t
        for x in range(round(cx - w), round(cx + w) + 1):
            if 0 <= x < GRID_W and 0 <= y < GRID_H:
                g[y][x] = ch


def _outline(g, body="DMLCKBWE", ch="O"):
    src = [row[:] for row in g]
    for y in range(GRID_H):
        for x in range(GRID_W):
            if src[y][x] != ".":
                continue
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < GRID_H and 0 <= nx < GRID_W and src[ny][nx] in body:
                    g[y][x] = ch
                    break


def _line(g, x0, y0, x1, y1, ch, thick=2):
    """A short straight stroke, used for the angry brows."""
    steps = max(abs(x1 - x0), abs(y1 - y0)) or 1
    for i in range(steps + 1):
        x = x0 + (x1 - x0) * i / steps
        y = y0 + (y1 - y0) * i / steps
        for t in range(thick):
            xx, yy = round(x), round(y) + t
            if 0 <= xx < GRID_W and 0 <= yy < GRID_H:
                g[yy][xx] = ch


def build_sprite(angry=False):
    """Totoro, minus the clock face -- that is drawn as a true circle.

    Follows the bead-chart proportions: tall ears leaning outward from a single
    tapered body, eyes set wide, a small dark nose high between them, and a
    white belly carrying the marks. `angry` is the face he pulls when the timer
    runs out: heavy slanted brows, narrowed eyes and a jagged mouth.
    """
    g = _blank()
    # ears: tall, pointed, leaning out, with a lighter core
    _ear(g, 12, 16, 2, 18, 6.5, "D")
    _ear(g, 32, 28, 2, 18, 6.5, "D")
    _ear(g, 13, 16, 5, 17, 3.6, "L")
    _ear(g, 31, 28, 5, 17, 3.6, "L")
    # one tapered body, no separate head -- he has no neck
    _ellipse(g, 22, 24, 13.0, 12.0, "M")
    _ellipse(g, 22, 43, 18.0, 18.0, "M")
    # arms tucked against the sides, feet at the bottom
    _ellipse(g, 5, 44, 2.6, 4.4, "D")
    _ellipse(g, 39, 44, 2.6, 4.4, "D")
    _ellipse(g, 15, 59, 4.4, 2.6, "D")
    _ellipse(g, 29, 59, 4.4, 2.6, "D")
    # shading along the flanks
    for y in range(GRID_H):
        for x in range(GRID_W):
            if g[y][x] == "M" and abs(x - 22) > (10.0 if y < 30 else 15.0):
                g[y][x] = "D"
    # white belly, big enough to leave a band of it above the clock
    _ellipse(g, 22, 45, 14.5, 14.5, "C")
    # the marks: a scattered row, sparser at the edges as on the chart
    for cx, cy in ((14, 34), (18, 33), (22, 32), (26, 33), (30, 34)):
        g[cy][cx] = "K"
        for dx in (-1, 0, 1):
            g[cy + 1][cx + dx] = "K"
    # eyes: wide-set white patches with a dark pupil
    for ex in (15, 29):
        _ellipse(g, ex, 20, 3.0, 3.4, "W")
        _ellipse(g, ex, 20, 1.4, 1.6, "E")
    if angry:                                   # brows crash down over them
        _line(g, 11, 15, 18, 19, "E", 2)
        _line(g, 33, 15, 26, 19, "E", 2)
        for ex in (15, 29):                     # and the eyes narrow
            for x in range(ex - 3, ex + 4):
                for y in (17, 18):
                    if g[y][x] in ("W", "E"):
                        g[y][x] = "M"
    # nose: three dots across with one under the middle
    for x in range(21, 24):
        g[20][x] = "E"
    g[21][22] = "E"
    if angry:                                   # a jagged snarl under it
        for i, x in enumerate(range(17, 28)):
            g[24 + (i % 2)][x] = "E"
    # blush, outboard and just under the eyes
    for bx in (11, 31):
        for dx in range(2):
            g[24][bx + dx] = "B"
    _outline(g)
    return ["".join(r) for r in g]


def redden(colour, t):
    """Push a colour towards furious red, keeping its light and dark apart."""
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    r = min(255, round(r + (238 - r) * t * 0.92))
    g = round(g * (1 - 0.74 * t))
    b = round(b * (1 - 0.80 * t))
    return f"#{r:02x}{g:02x}{b:02x}"


def rage_photo(grid, heat, zoom):
    """One frame of the tantrum: the grid, reddened by `heat`, at `zoom`."""
    pal = {k: (v if k == "." else redden(v, heat)) for k, v in PALETTE.items()}
    img = tk.PhotoImage(width=GRID_W, height=GRID_H)
    img.put(" ".join("{" + " ".join(pal[c] for c in row) + "}" for row in grid))
    return img.zoom(max(1, zoom))


def sprite_photo(grid):
    img = tk.PhotoImage(width=GRID_W, height=GRID_H)
    img.put(" ".join("{" + " ".join(PALETTE[c] for c in row) + "}" for row in grid))
    return img.zoom(SCALE)


# -------------------------------------------------------------------- data


def parse_duration(text, default_minutes=DEFAULT_MINUTES):
    """Read what was typed on the belly into seconds.

    A dot separates minutes from seconds: "25" is 25 minutes, "5.3" is five and
    a half, ".3" is 30 seconds. One digit after the dot means tens of seconds,
    which is what makes ".3" read as thirty rather than three.
    """
    text = (text or "").strip()
    if not text or text == ".":
        return default_minutes * 60
    mins, _, secs = text.partition(".")
    digits = "".join(c for c in mins if c.isdigit())
    total = int(digits) * 60 if digits else 0
    sd = "".join(c for c in secs if c.isdigit())[:2]
    if sd:
        total += min(59, int(sd) * 10 if len(sd) == 1 else int(sd))
    return max(1, min(600 * 60, total)) if total else default_minutes * 60


def chord_room(radius, dy):
    """How wide a line of text may be at `dy` above or below a circle's centre.

    The 0.88 keeps the ends off the rim rather than touching it.
    """
    dy = min(abs(dy), radius)
    return 2 * (radius ** 2 - dy ** 2) ** 0.5 * 0.88


def fit_px(text, radius, dy, px):
    """Largest glyph size at or below `px` whose line fits inside the circle."""
    room = chord_room(radius, dy)
    while px > 1 and F.text_width(text, px) > room:
        px -= 1
    return px


def fmt_clock(seconds):
    # round up, not down: a 50 minute timer should read 50:00 for its first
    # second rather than dropping to 49:59 the instant it starts, and it must
    # land on 00:00 exactly as it finishes
    seconds = max(0, math.ceil(seconds - 1e-9))
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def fmt_length(seconds):
    """How the finished panel describes the session that just ran."""
    m, s = divmod(int(seconds), 60)
    if m and s:
        return f"{m} MIN {s} SEC"
    return f"{m} MIN" if m else f"{s} SEC"


def log_line(when, task, seconds, mode):
    """One session as Dataview inline fields, which is Obsidian's convention.

    `(key:: value)` pairs are what Dataview indexes. Carrying the mode is
    what keeps breaks out of a focus tally: a query over this file can say
    WHERE pomodoro = "WORK" and get the real total. Without that field a ten
    minute break is indistinguishable from ten minutes of work, which is the
    discrepancy this format exists to settle.
    """
    mins = max(1, round(seconds / 60))
    return (f"- (pomodoro:: {mode.upper()}) (duration:: {mins}m) "
            f"(task:: {task}) (end:: {when:%Y-%m-%d %H:%M})")


def append_log(task, seconds, mode="work", when=None, log_dir=LOG_DIR):
    """Append a finished session to that month's note.

    Never reached unless LOG_SESSIONS is set -- see the note at the top.
    """
    when = when or dt.datetime.now()
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f"{when:%Y-%m}.md")
    day = f"## {when:%Y-%m-%d}"
    existing = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            existing = fh.read()
    parts = []
    if not existing:
        parts.append(f"# Pomodoro {when:%B %Y}\n")
    if day not in existing:
        parts.append(f"\n{day}\n")
    parts.append(log_line(when, task, seconds, mode) + "\n")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("".join(parts))
    return path


def load_state():
    # utf-8-sig, not utf-8: a file written by another tool may carry a byte-order
    # mark, and json.load reads that as a syntax error and loses the settings.
    try:
        with open(STATE_FILE, encoding="utf-8-sig") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return {}
    # valid JSON is not always an object: a hand-edited "[]" used to crash
    # him on launch, so anything but a dict counts as no settings at all
    return state if isinstance(state, dict) else {}


def save_state(**kw):
    state = load_state()
    state.update(kw)
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except OSError:
        pass                        # a widget should never die over its own prefs


# ------------------------------------------------------------------ alarm

# Measured off the video's own audio: a single 880 Hz beep about 42 ms long,
# once every 500 ms. Not a triple -- an even, unhurried pulse, which is why it
# reads as a timer rather than a smoke alarm.
#
# winsound.Beep is a bare square wave with no envelope: it clicks at both ends
# and cannot make noise at all. Everything below is synthesised into a WAV in
# memory and handed to PlaySound, which costs nothing extra and lets the beep
# have a soft edge and the explosion be actual noise.
RATE = 22050
BEEP_HZ = 880
BEEP_MS = 90
BEEP_PERIOD_MS = 500
BOOM_TAIL_MS = 900


def _wav(samples):
    """Pack floats in -1..1 into a mono 16-bit WAV, in memory."""
    import io
    import struct
    import wave
    clipped = [max(-1.0, min(1.0, v)) for v in samples]
    frames = struct.pack(f"<{len(clipped)}h",
                         *(int(v * 32000) for v in clipped))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames)
    return buf.getvalue()


def _beep_wav():
    """A soft two-harmonic bip. The envelope is what stops it sounding cheap."""
    n = int(RATE * BEEP_MS / 1000)
    attack = int(RATE * 0.004)
    out = []
    for i in range(n):
        t = i / RATE
        env = (i / attack) if i < attack else math.exp(-4.5 * (i - attack) /
                                                       (n - attack))
        tone = (math.sin(2 * math.pi * BEEP_HZ * t)
                + 0.22 * math.sin(2 * math.pi * BEEP_HZ * 2 * t))
        out.append(0.78 * env * tone)
    return _wav(out)


def _boom_wav():
    """Noise through a closing filter over a falling sine: a real bang."""
    n = int(RATE * BOOM_TAIL_MS / 1000)
    attack = int(RATE * 0.002)              # tiny, but enough to stop a pop
    out = []
    lp = 0.0
    for i in range(n):
        t = i / RATE
        prog = i / n
        env = math.exp(-4.0 * prog) * (min(1.0, i / attack) if attack else 1.0)
        # noise, low-passed harder as it decays, so the crack becomes a rumble
        cutoff = 0.55 * (1 - prog) ** 2 + 0.02
        lp += cutoff * (random.uniform(-1.0, 1.0) - lp)
        # body: a sine dropping from 130 Hz to about 35 Hz
        freq = 130 * math.exp(-2.6 * prog) + 32
        body = math.sin(2 * math.pi * freq * t)
        v = 0.86 * env * (1.15 * lp + 0.75 * body)
        out.append(round(v * 24) / 24)          # a little crunch, kept retro
    return _wav(out)


_SOUNDS = {}
_SOUND_DIR = None
_SOUND_ERROR = None            # the tests read this; failures used to vanish
SOUND_PREFIX = "pomotoro-sounds-"


def _sound_file(name, make):
    """Render a sound once to a temp file and remember where it went.

    It has to be a file, not a buffer: winsound flatly refuses
    SND_MEMORY | SND_ASYNC, and playing from memory synchronously blocks for
    about 270 ms per sound, which would trample the half-second schedule.

    The file goes in a directory private to this process rather than under a
    predictable name in the shared temp folder, so nothing else can swap the
    sound out from under PlaySound. It deliberately outlives every beep:
    PlaySound re-reads the file asynchronously on each one. It is removed at
    exit; a run that never reaches exit is swept up by the next launch.
    """
    global _SOUND_DIR
    if name not in _SOUNDS:
        import atexit
        import shutil
        import tempfile
        if _SOUND_DIR is None:
            _SOUND_DIR = tempfile.mkdtemp(prefix=SOUND_PREFIX)
            atexit.register(shutil.rmtree, _SOUND_DIR, True)  # ignore_errors
        path = os.path.join(_SOUND_DIR, f"{name}.wav")
        with open(path, "wb") as fh:
            fh.write(make())
        _SOUNDS[name] = path
    return _SOUNDS[name]


def _play(name, make):
    """Play a cached sound without blocking."""
    global _SOUND_ERROR
    try:
        import winsound
        winsound.PlaySound(_sound_file(name, make),
                           winsound.SND_FILENAME | winsound.SND_ASYNC
                           | winsound.SND_NODEFAULT)
        _SOUND_ERROR = None
    except Exception as exc:
        _SOUND_ERROR = exc


def sweep_stale_sounds():
    """Delete sound folders left by runs that never reached their atexit.

    Shutting Windows down or ending him in Task Manager skips the clean-up in
    _sound_file, and each such run used to leave a folder in %TEMP%. Only the
    copy holding the single-instance lock calls this, so none of these folders
    belongs to a live copy.
    """
    import glob
    import shutil
    import tempfile
    pattern = os.path.join(glob.escape(tempfile.gettempdir()), SOUND_PREFIX + "*")
    for path in glob.glob(pattern):
        shutil.rmtree(path, ignore_errors=True)


def play_beep():
    _play("beep", _beep_wav)


def play_boom():
    _play("boom", _boom_wav)


def alarm(stop):
    """Beep on the half second until `stop` is set -- that is, until he bursts.

    Each beep is timed against a fixed schedule rather than by sleeping for the
    gap, so the small overhead of starting a sound cannot pile up and stretch
    the later gaps.
    """
    def run():
        start = time.monotonic()
        beat = 0
        while not stop.is_set():
            play_beep()
            beat += 1
            target = start + beat * BEEP_PERIOD_MS / 1000
            while not stop.is_set():
                rest = target - time.monotonic()
                if rest <= 0:
                    break
                time.sleep(min(rest, 0.02))     # so stopping is noticed at once
    threading.Thread(target=run, daemon=True).start()


# ----------------------------------------------------------------- windows


def work_area():
    """The desktop minus the taskbar, so he never hides under it."""
    class R(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                    ("r", ctypes.c_long), ("b", ctypes.c_long)]
    r = R()
    try:
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)
        if r.r > r.l and r.b > r.t:
            return r.l, r.t, r.r, r.b
    except Exception:
        return None
    return None


SUMMON_EVENT = "PomodoroTotoro.summon"


def summon_running_copy():
    """Tell the copy that is already open to come to the front."""
    try:
        k = ctypes.windll.kernel32
        h = k.OpenEventW(0x0002, False, SUMMON_EVENT)   # EVENT_MODIFY_STATE
        if not h:
            return False
        k.SetEvent(h)
        k.CloseHandle(h)
        return True
    except Exception:
        return False


def already_running():
    """True if another copy has the widget open.

    He starts from the Startup folder at login, so double-clicking the desktop
    shortcut later would otherwise leave two of him stacked in the corner,
    fighting over the same settings file.
    """
    try:
        # use_last_error=True is the whole point: without it ctypes never
        # captures the thread's error code, get_last_error() is always 0, and
        # the duplicate check silently reports "no other copy is running".
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        mutex = k32.CreateMutexW(None, False, "PomodoroTotoro.single")
        if not mutex:
            return False
        global _INSTANCE_LOCK
        _INSTANCE_LOCK = mutex              # hold it for the life of the process
        return ctypes.get_last_error() == 183        # ERROR_ALREADY_EXISTS
    except Exception:
        return False


_INSTANCE_LOCK = None


def sharpen_on_scaled_displays():
    """Handle DPI ourselves, then grow the sprite to match the display.

    Without this a display above 100% scaling stretches the window through a
    blur filter, which is the one thing pixel art must never get. Whole numbers
    only -- a fractional zoom would smear the grid.
    """
    global SCALE
    try:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
        SCALE = BASE_SCALE * max(1, round(ctypes.windll.user32.GetDpiForSystem() / 96))
    except Exception:
        pass


def write_icon(path, size=128, fatten=1.3, margin=3):
    """Write Totoro to an .ico -- a PNG in an .ico wrapper, stdlib only.

    Cropped to the pixels he actually occupies, then scaled to fill the square.
    He is tall and narrow, so drawn to proportion he came out smaller and
    thinner than the other taskbar icons; `fatten` stretches him sideways so he
    sits at the same weight as his neighbours. Nearest-neighbour sampling, so
    the pixels stay square.
    """
    import struct
    import zlib
    grid = build_sprite()
    cols = [x for x in range(GRID_W)
            if any(grid[y][x] != "." for y in range(GRID_H))]
    rows = [y for y in range(GRID_H) if any(c != "." for c in grid[y])]
    x0, x1, y0, y1 = cols[0], cols[-1], rows[0], rows[-1]
    gw, gh = x1 - x0 + 1, y1 - y0 + 1

    avail = size - margin * 2
    sy = avail / gh                     # height fills the icon
    sx = min(avail / gw, sy * fatten)   # width follows, up to the fatten limit
    ox, oy = (size - gw * sx) / 2, (size - gh * sy) / 2

    px = [[(0, 0, 0, 0)] * size for _ in range(size)]
    for iy in range(size):
        gy = int((iy - oy) / sy)
        if not 0 <= gy < gh:
            continue
        for ix in range(size):
            gx = int((ix - ox) / sx)
            if not 0 <= gx < gw:
                continue
            chi = grid[y0 + gy][x0 + gx]
            if chi == ".":
                continue
            r, g, b = (int(PALETTE[chi][i:i + 2], 16) for i in (1, 3, 5))
            px[iy][ix] = (r, g, b, 255)
    raw = b"".join(b"\x00" + bytes(v for p in row for v in p) for row in px)

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    head = struct.pack("<HHH", 0, 1, 1) + struct.pack(
        "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), 22)
    with open(path, "wb") as fh:
        fh.write(head + png)
    return path


# ------------------------------------------------------------------ widget

IDLE, RUNNING, PAUSED, DONE = "idle", "running", "paused", "done"


class Totoro:
    def __init__(self, root):
        self.root = root
        self.state = IDLE
        self.minutes_text = str(DEFAULT_MINUTES)
        self.task = ""
        self.editing = None          # no caret until a field is clicked into
        self.caret = True
        self.total = DEFAULT_MINUTES * 60
        self.left = float(self.total)
        self.ends_at = 0.0
        self.hits = {}                      # name -> (x0, y0, x1, y1)
        self.spent = 0.0                    # how much of the timer has gone
        self.dance_seq = 0                  # cancels an animation already in flight
        self.bits = []                      # what he bursts into
        self.alarm_stop = threading.Event()
        self.work_text = str(DEFAULT_MINUTES)   # the last focus length run
        self.work_task = ""
        self.pending = None                     # queued, not started
        self.loaded = None                      # what reset() put on screen
        self.session_kind = "work"              # what the running timer is
        try:
            self.summon = ctypes.windll.kernel32.CreateEventW(
                None, False, False, SUMMON_EVENT)
        except Exception:
            self.summon = None
        self.caret_at = 0                   # where the cursor sits in the field
        self.field = {}                     # name -> (left edge, glyph size, len)
        self.pad = max(1, SCALE // 2)       # click slop; the tests read this too
        self.last_paint = None
        self.pinned = bool(load_state().get("pinned", False))

        # room for the tantrum: he rests at the bottom-right of the window and
        # swells up and to the left into the transparent padding, so he never
        # grows off the screen edge.
        #
        # Ask the renderer how big he really gets rather than working it out
        # again from GROW_TO. The sprite is scaled to a whole number of pixels
        # per cell, so the two sums round differently and the window comes out
        # a few pixels too small -- which stays invisible for as long as
        # SCALE * GROW_TO happens to land on a whole number, and then does not.
        grown = max(SCALE, self.rage_zoom(1.0))     # pixels per cell, full swell
        pad_w = GRID_W * (grown - SCALE)
        pad_h = GRID_H * (grown - SCALE)
        self.ox, self.oy = pad_w, pad_h
        w, h = GRID_W * SCALE + pad_w, GRID_H * SCALE + pad_h
        root.overrideredirect(True)
        root.configure(bg=KEY)
        try:
            root.attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass

        area = work_area()
        m = MARGIN * (SCALE // BASE_SCALE or 1)
        right, bottom = (area[2], area[3]) if area else (
            root.winfo_screenwidth(), root.winfo_screenheight())
        root.geometry(f"{w}x{h}+{max(0, right - w - m)}+{max(0, bottom - h - m)}")

        self.canvas = tk.Canvas(root, width=w, height=h, bg=KEY,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        self.win_w, self.win_h = w, h
        self.normal = sprite_photo(build_sprite())
        self.body = self.canvas.create_image(self.ox, self.oy, image=self.normal,
                                             anchor="nw")

        self.cx = self.ox + DISC_CX * SCALE
        self.cy = self.oy + DISC_CY * SCALE
        self.R = DISC_R * SCALE
        self.disc = self.canvas.create_oval(0, 0, 1, 1, fill=DISC_DARK,
                                            outline=DISC_EDGE,
                                            width=max(1, SCALE // 3))
        self.wedge = self.canvas.create_polygon(0, 0, 0, 0, 0, 0,
                                                fill=DISC_LIT, outline="",
                                                state="hidden")
        self.place_disc()
        # every text size derives from the disc, so it all scales together
        self.big = max(2, round(1.5 * self.R / 29))
        self.small = max(1, round(self.big * 0.46))
        self.tiny = max(1, round(self.big * 0.34))

        self.canvas.bind("<Button-1>", self.click)
        self.canvas.bind("<Button-3>", self.quit)
        root.bind("<Key>", self.key)
        self.apply_layer()
        self.blink()
        self.watch_summon()
        self.tick()

    # -- window layer -----------------------------------------------------

    def hwnd(self):
        h = self.root.winfo_id()
        try:
            return ctypes.windll.user32.GetParent(h) or h
        except Exception:
            return h

    def apply_layer(self, force_top=False):
        """Pinned rides above every window; otherwise he sinks to the desktop."""
        on_top = self.pinned or force_top
        try:
            self.root.attributes("-topmost", bool(on_top))
        except tk.TclError:
            return
        if not on_top:
            try:            # HWND_BOTTOM with NOMOVE | NOSIZE | NOACTIVATE
                ctypes.windll.user32.SetWindowPos(self.hwnd(), 1, 0, 0, 0, 0, 0x13)
            except Exception:
                pass

    def show_me(self):
        """Bring him to the front and leave him there, arrow up."""
        if not self.pinned:
            self.pinned = True
            save_state(pinned=True)
        self.apply_layer()
        try:
            self.root.lift()
        except tk.TclError:
            pass
        self.last_paint = None

    def watch_summon(self):
        """Opening the shortcut again signals this; come out of hiding."""
        try:
            if self.summon and ctypes.windll.kernel32.WaitForSingleObject(
                    self.summon, 0) == 0:
                self.show_me()
        except Exception:
            pass
        self.root.after(350, self.watch_summon)

    def queue_next(self):
        """Load the other half of the pomodoro, ready but not started.

        A focus block is followed by a break a fifth of its length -- 50 gives
        10, 25 gives 5 -- and after a break the focus length comes back.

        This reads what actually just ran rather than flipping a toggle. An
        earlier version alternated blindly, so ignoring an offered break and
        starting another focus block left the toggle inverted: you were handed
        the old focus length back instead of the break you had earned.
        """
        if self.session_kind == "break":
            self.pending = (self.work_text, self.work_task, "work")
        else:
            self.work_text = self.minutes_text
            self.work_task = self.task
            mins = max(1, min(30, round(self.total / 60 / 5)))
            self.pending = (str(mins), "break", "break")

    def toggle_pin(self):
        self.pinned = not self.pinned
        save_state(pinned=self.pinned)
        self.apply_layer()
        self.last_paint = None

    # -- drawing ----------------------------------------------------------

    def fit(self, text, y, px):
        """Shrink px until the line fits the circle at that height.

        A round face has less room the further you get from the middle, so a
        long task name would otherwise poke out through the sides.
        """
        return fit_px(text, self.R, y + F.H * px / 2 - self.cy, px)

    def draw_wedge(self, spent):
        """Fill in the elapsed slice, drawn as a polygon.

        Tk paints a pieslice thinner than about a degree as a completely filled
        circle, so the arc this replaces had to stay hidden for the first ten
        seconds of a fifty minute timer -- exactly when you look at it to check
        it started. A polygon has no such floor: it is right from second one.
        """
        self.spent = min(1.0, max(0.0, spent))
        if self.spent <= 0.0:
            self.canvas.itemconfigure(self.wedge, state="hidden")
            return
        cx, cy = self.cx, self.cy
        sweep = 360.0 * self.spent
        steps = max(2, int(sweep / 3) + 1)      # smooth enough at any size
        pts = [cx, cy]
        for i in range(steps + 1):
            a = math.radians(sweep * i / steps)  # clockwise from twelve o'clock
            pts += [cx + self.R * math.sin(a), cy - self.R * math.cos(a)]
        self.canvas.coords(self.wedge, *pts)
        self.canvas.itemconfigure(self.wedge, state="normal")

    def caret_bar(self, x0, y, px, index):
        """A thin rule between two characters, rather than a whole glyph slot."""
        x = x0 + index * (F.W + F.GAP) * px - px * 0.5
        self.rect(x, y, x + max(2, round(px * 0.6)), y + F.H * px, CREAM,
                  outline="")

    def caret_from_click(self, name, ev):
        """Which gap in the text the click landed nearest."""
        x0, px, n = self.field.get(name, (self.cx, 1, 0))
        adv = (F.W + F.GAP) * px
        return max(0, min(n, round((ev.x - x0) / adv)))

    def editing_text(self):
        return self.minutes_text if self.editing == "min" else self.task

    def set_editing_text(self, value):
        if self.editing == "min":
            self.minutes_text = value
        else:
            self.task = value

    def place_disc(self):
        """Put the clock face where the body currently is, wobble included."""
        self.canvas.coords(self.disc, self.cx - self.R, self.cy - self.R,
                           self.cx + self.R, self.cy + self.R)
        self.draw_wedge(self.spent)          # the slice follows him

    def rect(self, x0, y0, x1, y1, fill, **kw):
        """Every panel rectangle goes through here, so one tag clears them."""
        return self.canvas.create_rectangle(x0, y0, x1, y1,
                                            fill=fill, tags="ui", **kw)

    def label(self, text, y, px, fill, cx=None, hit=None, bold=False):
        """Draw one line of bitmap text centred on cx; return its box."""
        text = str(text)
        w = F.text_width(text, px)
        x0 = (self.cx if cx is None else cx) - w / 2
        for rx, ry, rw, rh in F.runs(text, px, bold):
            self.rect(x0 + rx, y + ry, x0 + rx + rw, y + ry + rh, fill, outline="")
        box = (x0, y, x0 + w, y + F.H * px)
        if hit:
            self.hits[hit] = box
        return box

    def dotted(self, y, half_w, px, fill):
        """The dashed rule under the task line, as in the video."""
        x = self.cx - half_w
        while x < self.cx + half_w:
            self.rect(x, y, x + px * 2, y + px, fill, outline="")
            x += px * 4

    def corner_button(self, name, y_sprite, glyph, lit):
        """One of the small square buttons clipped to his right side."""
        s = max(2, SCALE)
        gx, gy = self.ox + 37 * SCALE, self.oy + y_sprite * SCALE
        self.rect(gx - s * 2, gy - s * 2, gx + s * 2, gy + s * 2,
                  CREAM if lit else "#5a636e", outline=DISC_EDGE,
                  width=max(1, SCALE // 4))
        px = max(1, s // 2)
        self.label(glyph, gy - F.H * px / 2, px, INK if lit else CREAM, cx=gx)
        self.hits[name] = (gx - s * 2, gy - s * 2, gx + s * 2, gy + s * 2)

    def reset_button(self):
        """A looping arrow, drawn rather than lettered -- no glyph reads at 4px."""
        s = max(2, SCALE)
        gx, gy = self.ox + 37 * SCALE, self.oy + 47 * SCALE
        self.rect(gx - s * 2, gy - s * 2, gx + s * 2, gy + s * 2, "#5a636e",
                  outline=DISC_EDGE, width=max(1, SCALE // 4))
        r = s * 0.9
        self.canvas.create_arc(gx - r, gy - r, gx + r, gy + r,
                               start=20, extent=290, style="arc", outline=CREAM,
                               width=max(1, round(s / 2.5)), tags="ui")
        t = s * 0.55
        self.canvas.create_polygon(gx + r, gy - t, gx + r + t, gy + t * 0.3,
                                   gx + r - t, gy + t * 0.3, fill=CREAM,
                                   outline="", tags="ui")
        self.hits["reset"] = (gx - s * 2, gy - s * 2, gx + s * 2, gy + s * 2)

    def repaint(self):
        self.canvas.delete("ui")
        self.hits = {}
        if self.state == DONE:
            return                      # the tantrum has the screen to itself
        R = self.R
        if self.state == IDLE:
            # laid out to match the avocado: number, MIN, task, rule, start
            y_num = self.cy - 0.70 * R
            box = self.label(self.minutes_text or " ", y_num, self.big, CREAM,
                             hit="min", bold=True)
            self.field["min"] = (box[0], self.big, len(self.minutes_text))
            if self.editing == "min" and self.caret:
                self.caret_bar(box[0], y_num, self.big, self.caret_at)
            self.label("MIN", self.cy - 0.26 * R, self.tiny, TAN)

            y_task = self.cy + 0.10 * R
            typed = self.task.lower()
            shown = typed or ("" if self.editing == "task" else "(task)")
            px = self.fit(shown or "(task)", y_task, self.small)
            box = self.label(shown or " ", y_task, px, TAN, hit="task")
            self.field["task"] = (box[0], px, len(typed))
            if self.editing == "task" and self.caret:
                self.caret_bar(box[0], y_task, px, self.caret_at)
            self.hits["task"] = (self.cx - 0.7 * R, self.cy + 0.04 * R,
                                 self.cx + 0.7 * R, self.cy + 0.26 * R)
            self.dotted(self.cy + 0.36 * R, 0.68 * R, max(1, self.small // 2), TAN)
            self.label("↵ START", self.cy + 0.52 * R, self.small, CREAM, hit="start")
            self.hits["start"] = (self.cx - 0.55 * R, self.cy + 0.48 * R,
                                  self.cx + 0.55 * R, self.cy + 0.68 * R)
        elif self.state in (RUNNING, PAUSED):
            heading = (self.task or "focus").upper()[:14]
            self.label(heading, self.cy - 0.50 * R,
                       self.fit(heading, self.cy - 0.50 * R, self.small), TAN)
            self.label(fmt_clock(self.left), self.cy - 0.16 * R, self.big,
                       TAN if self.state == PAUSED else CREAM, bold=True)
            if self.state == PAUSED:
                self.label("PAUSED", self.cy + 0.44 * R, self.tiny, TAN)
        self.corner_button("pin", 38, "▲" if self.pinned else "▼", self.pinned)
        if self.state in (RUNNING, PAUSED):
            self.reset_button()

    # -- interaction ------------------------------------------------------

    def hit(self, ev, name):
        b = self.hits.get(name)
        p = self.pad
        return bool(b) and b[0] - p <= ev.x <= b[2] + p and b[1] - p <= ev.y <= b[3] + p

    def click(self, ev):
        if self.hit(ev, "pin"):
            self.toggle_pin()
            return
        if self.state == IDLE:
            if self.hit(ev, "start"):
                self.begin()
            elif self.hit(ev, "task"):
                self.focus_field("task", self.caret_from_click("task", ev))
            elif self.hit(ev, "min"):
                self.focus_field("min", self.caret_from_click("min", ev))
            return
        if self.state == DONE:
            self.reset()                # a click cuts the tantrum short
            return
        if self.hit(ev, "reset"):
            self.reset_to_standard()
            return
        # running or paused: no buttons, the belly itself is the control
        if (ev.x - self.cx) ** 2 + (ev.y - self.cy) ** 2 <= self.R ** 2:
            if self.state == RUNNING:
                self.state, self.left = PAUSED, self.ends_at - time.monotonic()
            else:
                self.state = RUNNING
                self.ends_at = time.monotonic() + self.left
            self.last_paint = None

    def quit(self, ev=None):
        """Right-click puts him away -- but only between timers.

        He has no frame, no taskbar button and no close box, so without this
        the only way out was Task Manager. Mid-timer a stray right-click would
        throw the session away, so there it does nothing; the reset arrow
        comes first.
        """
        if self.state == IDLE:
            self.root.destroy()

    def focus_field(self, which, at=None):
        self.editing = which
        text = self.minutes_text if which == "min" else self.task
        self.caret_at = len(text) if at is None else max(0, min(len(text), at))
        self.caret = True
        self.last_paint = None
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def key(self, ev):
        if self.state == DONE:
            if ev.keysym == "Return":
                self.reset()
            return
        if self.state in (RUNNING, PAUSED):
            if ev.keysym == "Escape":
                self.reset_to_standard()
            return
        if ev.keysym == "Return":
            self.begin()
        elif ev.keysym == "Tab":
            self.focus_field("task" if self.editing == "min" else "min")
        elif ev.keysym == "Escape":
            self.editing = None
        elif self.editing:
            text = self.editing_text()
            self.caret_at = max(0, min(len(text), self.caret_at))
            if ev.keysym in ("Left", "Right", "Home", "End"):
                self.caret_at = {"Left": max(0, self.caret_at - 1),
                                 "Right": min(len(text), self.caret_at + 1),
                                 "Home": 0, "End": len(text)}[ev.keysym]
            elif ev.keysym == "BackSpace":
                if self.caret_at:
                    self.set_editing_text(text[:self.caret_at - 1]
                                          + text[self.caret_at:])
                    self.caret_at -= 1
            elif ev.keysym == "Delete":
                self.set_editing_text(text[:self.caret_at]
                                      + text[self.caret_at + 1:])
            elif ev.char and ev.char.isprintable():
                cap = 6 if self.editing == "min" else 14
                ok = (ev.char.isdigit() or ev.char == "."
                      if self.editing == "min" else True)
                if ok and len(text) < cap:
                    self.set_editing_text(text[:self.caret_at] + ev.char
                                          + text[self.caret_at:])
                    self.caret_at += 1
        self.last_paint = None

    # -- run --------------------------------------------------------------

    def begin(self):
        self.total = parse_duration(self.minutes_text)
        # it only counts as the queued break if it is still the queued break;
        # typing over it makes this a focus block like any other
        self.session_kind = "work"
        if self.loaded and (self.minutes_text, self.task) == self.loaded[:2]:
            self.session_kind = self.loaded[2]
        self.loaded = None
        self.editing = None
        self.left = float(self.total)
        self.ends_at = time.monotonic() + self.total
        self.state = RUNNING
        self.draw_wedge(0.0)
        self.last_paint = None

    def reset_to_standard(self):
        """Abandon a running timer and go back to the default screen."""
        self.pending = None                  # throwing it away breaks the chain
        self.loaded = None
        self.session_kind = "work"
        self.reset()
        self.minutes_text = str(DEFAULT_MINUTES)
        self.task = ""
        self.last_paint = None

    def reset(self):
        self.dance_seq += 1                  # stop any animation in flight
        self.alarm_stop.set()
        self.bits = []
        self.canvas.delete("boom")
        self.canvas.itemconfigure(self.disc, fill=DISC_DARK, state="normal")
        self.canvas.itemconfigure(self.body, image=self.normal, state="normal")
        self.state = IDLE
        self.editing = None
        self.draw_wedge(0.0)
        if self.pending:                     # the next pomodoro, ready to go
            self.minutes_text, self.task, kind = self.pending
            self.loaded = (self.minutes_text, self.task, kind)
            self.pending = None
        self.canvas.coords(self.body, self.ox, self.oy)
        self.place_disc()
        self.repaint()
        self.apply_layer()
        self.last_paint = None

    def finish(self):
        """Time is up. He loses his temper rather than celebrating."""
        self.state = DONE
        self.left = 0
        self.draw_wedge(0.0)
        self.canvas.itemconfigure(self.disc, state="hidden")
        self.show_me()                          # front and centre, and stays
        if LOG_SESSIONS:                        # off unless aimed at a vault
            append_log(self.task or "focus", self.total, self.session_kind,
                       log_dir=LOG_SESSIONS)
        self.queue_next()
        self.alarm_stop = threading.Event()      # beeps run until he bursts
        alarm(self.alarm_stop)
        self.dance_seq += 1
        self.angry = build_sprite(angry=True)
        self.rage(0, self.dance_seq)
        self.last_paint = None

    def rest_at(self, zoom, dx=0, dy=0):
        """Pin the sprite by its bottom-right corner, whatever size it is.

        Growing from that corner keeps his feet where they were and sends the
        swell up and left, into the padding rather than off the screen.
        """
        self.canvas.coords(self.body, self.win_w - GRID_W * zoom + dx,
                           self.win_h - GRID_H * zoom + dy)

    @staticmethod
    def rage_zoom(t):
        """Pixel size at `t` through the tantrum, from resting to GROW_TO."""
        t = min(1.0, max(0.0, t))
        return max(1, round(SCALE * (1.0 + (GROW_TO - 1.0) * t)))

    def rage(self, step, seq=None):
        """Swell, redden and shake for RAGE_MS, then burst."""
        if seq is not None and seq != self.dance_seq:
            return
        t = step * RAGE_STEP_MS / RAGE_MS
        if t >= 1.0:
            self.boom(0, seq)
            return
        zoom = self.rage_zoom(t)
        self.frame = rage_photo(self.angry, t, zoom)    # keep a reference
        self.canvas.itemconfigure(self.body, image=self.frame)
        shake = round(SCALE * 0.3 * t)                  # worse as he swells
        jitter = (random.randint(-shake, shake), random.randint(-shake, shake))
        self.rest_at(zoom, *(jitter if shake else (0, 0)))
        self.root.after(RAGE_STEP_MS, self.rage, step + 1, seq)

    # He bursts into the things he is actually made of in the film: acorns,
    # the leaves of his camphor tree, and a scatter of soot sprites.
    LEAF_COLOURS = ("#4a7c3f", "#6aa84f", "#8fbf5a", "#3d6633")
    ACORN_BODY = "#8a5a2b"
    ACORN_CAP = "#4a2f18"
    SOOT = "#141414"

    def burst_centre(self):
        big = SCALE * GROW_TO
        return (self.win_w - GRID_W * big / 2, self.win_h - GRID_H * big / 2)

    def boom(self, step, seq=None):
        """He pops, and out comes the forest: leaves, acorns, soot sprites."""
        if seq is not None and seq != self.dance_seq:
            return
        if step == 0:
            self.alarm_stop.set()               # the beeping stops on the pop
            play_boom()
            self.canvas.itemconfigure(self.body, state="hidden")
            cx, cy = self.burst_centre()
            self.bits = []
            for kind, count in (("leaf", BOOM_LEAVES), ("acorn", BOOM_ACORNS),
                                ("soot", BOOM_SPRITES)):
                for _ in range(count):
                    ang = random.uniform(0, 2 * math.pi)
                    speed = {"leaf": (1.4, 3.4), "acorn": (1.8, 4.2),
                             "soot": (1.0, 2.6)}[kind]
                    sp = random.uniform(*speed) * SCALE
                    self.bits.append({
                        "kind": kind,
                        "x": cx + random.uniform(-3, 3) * SCALE,
                        "y": cy + random.uniform(-3, 3) * SCALE,
                        "vx": math.cos(ang) * sp,
                        # leaves get thrown up first, then flutter back down
                        "vy": math.sin(ang) * sp - (random.uniform(0.8, 2.0)
                                                    * SCALE if kind == "leaf"
                                                    else 0.0),
                        "size": random.uniform(*{"leaf": (2.2, 3.6),
                                                 "acorn": (1.8, 2.6),
                                                 "soot": (1.6, 2.8)}[kind]) * SCALE,
                        "phase": random.uniform(0, 2 * math.pi),
                        "sway": random.uniform(0.5, 1.6),
                        "colour": random.choice(self.LEAF_COLOURS),
                    })

        self.canvas.delete("boom")
        t = step * BOOM_STEP_MS / BOOM_MS
        if t >= 1.0:
            self.canvas.itemconfigure(self.body, image=self.normal,
                                      state="normal")
            self.reset()
            return
        # everything shrinks away over the last stretch, so the screen clears
        # instead of the whole burst blinking out of existence at once
        fade = 1.0 if t < 0.72 else max(0.0, (1.0 - t) / 0.28)

        for b in self.bits:
            k = b["kind"]
            if k == "leaf":
                # leaves catch the air: they slow fast and flutter side to side
                b["vx"] *= 0.93
                b["vy"] = b["vy"] * 0.93 + 0.10 * SCALE
                b["x"] += b["vx"] + math.sin(t * 9 + b["phase"]) * b["sway"] * SCALE
                b["y"] += b["vy"]
                # the flutter also turns them edge-on and back again
                w = b["size"] * fade * abs(math.cos(t * 7 + b["phase"])) * 1.15 + 1
                h = b["size"] * fade * 0.62
                if h < 0.6:
                    continue
                self.canvas.create_oval(b["x"] - w, b["y"] - h, b["x"] + w,
                                        b["y"] + h, fill=b["colour"],
                                        outline="#2f4a28", tags="boom")
            elif k == "acorn":
                b["vx"] *= 0.985
                b["vy"] = b["vy"] + 0.30 * SCALE      # acorns just drop
                b["x"] += b["vx"]
                b["y"] += b["vy"]
                r = b["size"] * fade
                if r < 0.6:
                    continue
                self.canvas.create_oval(b["x"] - r * 0.72, b["y"] - r * 0.5,
                                        b["x"] + r * 0.72, b["y"] + r * 1.15,
                                        fill=self.ACORN_BODY, outline="#3c2512",
                                        tags="boom")
                self.canvas.create_oval(b["x"] - r * 0.8, b["y"] - r * 0.95,
                                        b["x"] + r * 0.8, b["y"] - r * 0.05,
                                        fill=self.ACORN_CAP, outline="",
                                        tags="boom")
            else:                                     # soot sprite
                b["vx"] *= 0.90
                b["vy"] = b["vy"] * 0.90 + 0.05 * SCALE
                b["x"] += b["vx"] + math.sin(t * 12 + b["phase"]) * 0.5 * SCALE
                b["y"] += b["vy"]
                r = b["size"] * fade
                if r <= 0.5:
                    continue
                self.canvas.create_oval(b["x"] - r, b["y"] - r, b["x"] + r,
                                        b["y"] + r, fill=self.SOOT, outline="",
                                        tags="boom")
                e = max(1.0, r * 0.30)
                for ex in (-r * 0.36, r * 0.36):
                    self.canvas.create_oval(b["x"] + ex - e, b["y"] - r * 0.2 - e,
                                            b["x"] + ex + e, b["y"] - r * 0.2 + e,
                                            fill="#ffffff", outline="",
                                            tags="boom")
        self.root.after(BOOM_STEP_MS, self.boom, step + 1, seq)

    def blink(self):
        if self.state == IDLE and self.editing:
            self.caret = not self.caret
            self.last_paint = None
        self.root.after(700, self.blink)

    def tick(self):
        if self.state == RUNNING:
            self.left = self.ends_at - time.monotonic()
            if self.left <= 0:
                self.finish()
        if self.state in (RUNNING, PAUSED) and self.total:
            self.draw_wedge(1.0 - max(0.0, self.left) / self.total)
        stamp = (self.state, self.minutes_text, self.task, self.editing, self.caret,
                 int(max(0, self.left)), self.pinned)
        if stamp != self.last_paint:
            self.last_paint = stamp
            self.repaint()
        self.root.after(200, self.tick)


# -------------------------------------------------------------------- test


def selftest():
    import tempfile

    assert fmt_clock(0) == "00:00"
    assert fmt_clock(3000) == "50:00"
    assert fmt_clock(-5) == "00:00", "a finished timer must not show negative time"
    assert fmt_clock(3661) == "1:01:01"

    assert parse_duration("25") == 25 * 60
    assert parse_duration("") == DEFAULT_MINUTES * 60
    assert parse_duration(".3") == 30, "one digit after the dot means tens of seconds"
    assert parse_duration("5.3") == 5 * 60 + 30
    assert parse_duration("5.45") == 5 * 60 + 45, "two digits are literal seconds"
    assert parse_duration("0.5") == 50
    assert parse_duration(".") == DEFAULT_MINUTES * 60
    assert parse_duration("9999") == 600 * 60, "absurd input is clamped, not crashed"
    assert parse_duration("abc") == DEFAULT_MINUTES * 60, "junk falls back to default"

    assert fmt_length(90) == "1 MIN 30 SEC"
    assert fmt_length(60) == "1 MIN"
    assert fmt_length(30) == "30 SEC"

    when = dt.datetime(2026, 9, 8, 15, 58)
    assert log_line(when, "write memo", 3000, "work") == (
        "- (pomodoro:: WORK) (duration:: 50m) (task:: write memo) "
        "(end:: 2026-09-08 15:58)")
    with tempfile.TemporaryDirectory() as d:
        p = append_log("first", 3000, "work", when, d)
        append_log("tea", 600, "break", when.replace(hour=17, minute=0), d)
        append_log("next day", 1500, "work", when.replace(day=9), d)
        body = open(p, encoding="utf-8").read()
        assert body.count("## 2026-09-08") == 1, "day header must not repeat"
        assert body.count("## 2026-09-09") == 1
        # the mode field is what lets a query tally focus without the breaks
        assert body.count("(pomodoro:: WORK)") == 2
        assert body.count("(pomodoro:: BREAK)") == 1
        assert LOG_SESSIONS is None, "logging ships off; it is opt-in"
        head = open(write_icon(os.path.join(d, "g.ico")), "rb").read(30)
        assert head[:4] == bytes([0, 0, 1, 0]), "not an .ico container"
        assert bytes([0x89]) + b"PNG" in head, "icon payload must be a PNG"

    grid = build_sprite()
    assert len(grid) == GRID_H and len(grid[0]) == GRID_W
    assert set("".join(grid)) <= set(PALETTE), "sprite uses a colour not in the palette"
    # the clock face has to land on him, not hang off him
    for ang in range(0, 360, 15):
        x = int(round(DISC_CX + (DISC_R + 1.5) * math.cos(math.radians(ang))))
        y = int(round(DISC_CY + (DISC_R + 1.5) * math.sin(math.radians(ang))))
        assert grid[y][x] != ".", f"clock face overhangs the body at {ang} degrees"
    # the belly has to dominate, the way the avocado's does
    belly = sum(1 for y in range(21, GRID_H) for x in range(GRID_W)
                if grid[y][x] != ".")
    head = sum(1 for y in range(0, 21) for x in range(GRID_W) if grid[y][x] != ".")
    assert belly > head * 1.4, "belly should be clearly bigger than the head"

    # nothing may spill out of the circle, however long the task name is
    R = DISC_R * 8
    for text, dyf, px in (("00:00", -0.14, 5), ("COMPLETED", -0.66, 2),
                          ("50 MIN 30 SEC DONE", -0.32, 2),
                          ('"' + "W" * 16 + '"', -0.08, 2),
                          ("W" * 14, -0.54, 2)):
        got = fit_px(text, R, dyf * R, px)
        assert F.text_width(text, got) <= chord_room(R, dyf * R), \
            f"{text!r} still overflows the disc at size {got}"
    assert chord_room(10, 0) > chord_room(10, 8), "a circle narrows towards the rim"
    assert chord_room(10, 99) == 0, "past the rim there is no room at all"

    # build the real widget once: a missing colour or a typo in the drawing
    # code is invisible to every check above, and only shows up on launch
    root = tk.Tk()
    root.withdraw()
    global STATE_FILE
    keep, STATE_FILE = STATE_FILE, os.path.join(tempfile.gettempdir(),
                                                "pomodoro_st.json")
    try:
        # valid JSON that is not an object used to crash him on launch
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            fh.write("[]")
        assert load_state() == {}, "a non-object state.json must read as empty"
        w = Totoro(root)
        for st in (IDLE, RUNNING, PAUSED, DONE):
            w.state = st
            w.repaint()
        root.update()
        # right-click is the only way to close him, and must never fire
        # mid-timer, where a stray click would throw the session away
        assert w.canvas.bind("<Button-3>"), "right-click is not bound"
        closed = []
        real_destroy = root.destroy
        root.destroy = lambda: closed.append(True)
        try:
            w.state = RUNNING
            w.quit()
            assert not closed, "right-click closed him with a timer running"
            w.state = IDLE
            w.quit()
            assert closed, "right-click while idle did not close him"
        finally:
            root.destroy = real_destroy
        # the window has to hold him at full swell, or he bursts out of his own
        # edges. The padding and the sprite size used to be worked out by two
        # separate sums that agreed only while SCALE * GROW_TO landed on a
        # whole number. test_timer.py catches this too, but that suite does not
        # run in CI, and this is the check that would have caught it there.
        grown = w.rage_zoom(1.0)
        assert w.win_w >= GRID_W * grown, (
            f"window {w.win_w}px too narrow for his full swell "
            f"of {GRID_W * grown}px")
        assert w.win_h >= GRID_H * grown, (
            f"window {w.win_h}px too short for his full swell "
            f"of {GRID_H * grown}px")
    finally:
        STATE_FILE = keep
        root.destroy()

    # both corner buttons have to sit on his body, not hang beside it
    for name, by in (("pin", 38), ("reset", 47)):
        for dy in (-2, 2):
            for dx in (-2, 2):
                assert grid[by + dy][37 + dx] != ".", \
                    f"the {name} button hangs off the body at corner {(dx, dy)}"

    # a second copy has to bow out, or two of him stack in the corner. Only the
    # second call is asserted: the widget may well be running while this does.
    already_running()
    assert already_running() is True, "a second copy must detect the first"

    # actually play both, and fail loudly if the platform refuses. Swallowing
    # this is how the beeps went silent without anything noticing.
    #
    # A machine with no sound card cannot answer the question either way, and a
    # CI runner is such a machine, so there the playback is skipped by setting
    # POMODORO_SKIP_AUDIO_CHECK. The waveform checks below need no device and
    # always run.
    if os.environ.get("POMODORO_SKIP_AUDIO_CHECK"):
        print("no audio device assumed: skipping the playback check")
    else:
        play_beep()
        assert _SOUND_ERROR is None, f"the beep would not play: {_SOUND_ERROR}"
        play_boom()
        assert _SOUND_ERROR is None, f"the bang would not play: {_SOUND_ERROR}"

    # a waveform that starts or ends on a jump clicks in the speaker
    import io as _io
    import struct as _struct
    import wave as _wave
    for label, raw in (("beep", _beep_wav()), ("boom", _boom_wav())):
        wf = _wave.open(_io.BytesIO(raw))
        cnt = wf.getnframes()
        d = _struct.unpack(f"<{cnt}h", wf.readframes(cnt))
        assert cnt > 0, f"{label} is empty"
        assert abs(d[0]) < 2000, f"{label} starts on a jump and will click"
        assert abs(d[-1]) < 2000, f"{label} ends on a jump and will click"
        assert max(abs(v) for v in d) < 32700, f"{label} clips"

    assert F.text_width("", 3) == 0
    assert F.text_width("AB", 2) == (2 * 6 - 1) * 2
    assert set("0123456789:.- ") <= set(F.GLYPHS), "font missing a clock character"
    assert all(len(r) == F.W for g in F.GLYPHS.values() for r in g), "bad glyph row"
    assert all(len(g) == F.H for g in F.GLYPHS.values()), "bad glyph height"
    assert list(F.runs("-", 1)) == [(0, 3 * 1, 5 * 1, 1)], "runs should merge a row"
    print("all checks passed")


def main():
    if "--selftest" in sys.argv:
        selftest()
        return
    if "--make-icon" in sys.argv:
        print(write_icon(os.path.join(HERE, "totoro.ico")))
        return
    running = already_running()
    if running and "--force" not in sys.argv:
        # Opening the shortcut again is how you summon him: the copy already
        # running comes to the front, and this one bows out.
        summon_running_copy()
        return
    if not running:
        sweep_stale_sounds()        # the lock is ours, so no live copy owns them
    sharpen_on_scaled_displays()
    root = tk.Tk()
    Totoro(root)
    root.mainloop()


if __name__ == "__main__":
    main()
