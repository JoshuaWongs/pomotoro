#!/usr/bin/env python3
"""Pixel Totoro Pomodoro widget.

A frameless timer parked in the bottom-right corner of the desktop. Type the
minutes straight onto its belly, name the task, hit start. The belly is a clock
face: the elapsed slice fills in pale teal against dark. When time is up he
comes to the front and shivers in the rain, belly reading 00:00, while a beep
counts it out.

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

# When the timer ends it comes on to rain and he shivers in it until it
# passes. He is the same size throughout, so the window is no longer sized
# around a swell: it keeps HEADROOM worth of clear room up and to the left of
# where he rests, which is the room the rain falls through.
HEADROOM = 1.2                  # window size as a multiple of the sprite
SHOWER_MS = 3000                # the shiver and the rain, start to finish
SHOWER_STEP_MS = 45             # 37 frames; any slower and the rain strobes
SHOWER_RAIN = 46                # streaks falling at any one moment

# The shiver is measured frame by frame off the bouncing avocado in the video
# this is modelled on, at 9:24. Three things came out of that. It holds an
# offset for three or four frames and then jumps, rather than wobbling
# smoothly -- sampling a new offset every frame reads as a buzz, not a shiver.
# It travels about half again as far sideways as it does up and down. And the
# peak travel is only about 3% of its own width, which is far less than it
# looks: the eye reads the jumping, not the distance.
SHAKE_X = 1.5                   # sprite pixels, peak
SHAKE_Y = 1.0
SHAKE_HOLD = 3                  # frames per offset, which is about 3.5 Hz
SHAKE_SETTLE = 0.15             # of the shower spent easing off

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


def build_sprite():
    """Totoro, minus the clock face -- that is drawn as a true circle.

    Follows the bead-chart proportions: tall ears leaning outward from a single
    tapered body, eyes set wide, a small dark nose high between them, and a
    white belly carrying the marks.

    There is one face. He used to pull a furious one when the timer ran out --
    brows down, eyes narrowed, a jagged mouth -- to sell a tantrum that no
    longer happens. He stands in the rain now and takes it calmly.
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
    # nose: three dots across with one under the middle
    for x in range(21, 24):
        g[20][x] = "E"
    g[21][22] = "E"
    # blush, outboard and just under the eyes
    for bx in (11, 31):
        for dx in range(2):
            g[24][bx + dx] = "B"
    _outline(g)
    return ["".join(r) for r in g]


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

# Every number here is measured off a recording of the video this is modelled
# on, by filtering the audio at one frequency at a time:
#
#   partial      1      2      3      4      5      6      7
#   measured  1.000  0.008  0.334  0.006  0.207  0.002  0.150
#   a square  1.000  0.000  0.333  0.000  0.200  0.000  0.143
#
# which is a square wave at 880 Hz and not a near miss -- the odd partials
# land within two per cent of 1/k and the even ones are at half a per cent.
# The envelope peaks about 7 ms in and decays from there, down to a tenth of
# its peak by 90 ms. The gap is 500 ms, measured across six beeps: 490, 495,
# 503, 500, 502.
#
# Worth writing down because two earlier guesses went the other way. A plain
# sine was dismissed as sounding like a test tone, and short pips were pitched
# up at 1976 Hz on the reasoning that clock buzzers are high. Both were wrong
# in the same direction, and a single measurement settled what an argument
# about timbre could not.
#
# winsound.Beep is a bare square wave with no envelope: it clicks at both ends
# and cannot make noise at all. Everything below is synthesised into a WAV in
# memory and handed to PlaySound, which costs nothing extra and lets the beep
# have a shaped edge instead of a click at each end.
RATE = 22050
BEEP_HZ = 880                  # A5, measured
BEEP_MS = 120                  # it is down to a tenth of its peak by 90 ms
BEEP_PEAK = 0.55               # after normalising; a raw square sum overflows
BEEP_PERIOD_MS = 500


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
    """One square-wave beep, built to the measurements above.

    The square is summed from its own odd harmonics rather than taken as
    sign(sin). Both are square waves, but the naive one puts every partial
    above 11 kHz back into the audible range folded around Nyquist, which adds
    a gritty inharmonic edge that the recording does not have. Summing stops
    at the last partial that fits.

    The decay constant is not a taste: 3.2 across the note puts it at a tenth
    of peak at 90 ms, which is where the recording has it.
    """
    n = int(RATE * BEEP_MS / 1000)
    attack = int(RATE * 0.007)                  # measured, and it stops a click
    partials = [k for k in range(1, 12, 2) if BEEP_HZ * k < RATE / 2]
    out = []
    for i in range(n):
        t = i / RATE
        env = (i / attack) if i < attack else math.exp(-3.2 * (i - attack) /
                                                       (n - attack))
        out.append(env * sum(math.sin(2 * math.pi * BEEP_HZ * k * t) / k
                             for k in partials))
    loud = max(abs(v) for v in out) or 1.0
    return _wav([v * BEEP_PEAK / loud for v in out])


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


def warm_beep():
    """Render the beep before it is wanted, so the first one is not late.

    The first _play costs about 16 ms it never pays again: synthesising the
    waveform, making a private temp directory and writing the file. Paid at
    the finish, that is 16 ms of silence exactly where the beep is supposed
    to land, so it is paid when the timer starts instead.
    """
    global _SOUND_ERROR
    try:
        _sound_file("beep", _beep_wav)
    except Exception as exc:
        _SOUND_ERROR = exc


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
        self.bits = []                      # rain, once the timer is up
        self.shake = (0.0, 0.0)             # how far off his mark he is now
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
        # again from HEADROOM. The sprite is scaled to a whole number of
        # pixels per cell, so the two sums round differently and the window
        # comes out a few pixels too small -- which stays invisible for as
        # long as SCALE * HEADROOM lands on a whole number, and then does not.
        grown = max(SCALE, self.window_cell())      # pixels per cell, padded
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
        # "him" is everything that has to travel with the sprite when he
        # shivers: the clock face, the slice and, through rect() and label(),
        # every panel and letter drawn on him. The sprite image itself is not
        # tagged, because rest_at() places it by absolute coordinates.
        self.disc = self.canvas.create_oval(0, 0, 1, 1, fill=DISC_DARK,
                                            outline=DISC_EDGE,
                                            width=max(1, SCALE // 3),
                                            tags="him")
        self.wedge = self.canvas.create_polygon(0, 0, 0, 0, 0, 0,
                                                fill=DISC_LIT, outline="",
                                                state="hidden", tags="him")
        self.offset = (0, 0)                # how far rest_at has shifted him
        self.place_disc()
        # every text size derives from the disc, so it all scales together
        self.big = max(2, round(1.5 * self.R / 29))
        self.small = max(1, round(self.big * 0.46))
        self.tiny = max(1, round(self.big * 0.34))

        # Left click only. Right-click used to close him, but it fired on the
        # press: quit() destroyed the window before the button came back up,
        # the release landed on whatever was underneath, and on the desktop
        # that opened the desktop's own context menu. The X on his flank
        # replaces it.
        self.canvas.bind("<Button-1>", self.click)
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
                                            fill=fill, tags=("ui", "him"), **kw)

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

    def exit_button(self):
        """A drawn cross on his left flank, level with the layer arrow.

        Drawn rather than lettered, for the same reason the reset arrow is.
        The font's X lights all seven rows of its cell while the arrow lights
        three, so setting both as glyphs at one size made the cross look twice
        the weight and crowd its square.

        It sits at column 8 rather than 7, the exact mirror of the arrow at 37.
        One sprite pixel further in reads as better seated on the body, which
        narrows towards his left edge here.
        """
        s = max(2, SCALE)
        gx, gy = self.ox + 8 * SCALE, self.oy + 38 * SCALE
        self.rect(gx - s * 2, gy - s * 2, gx + s * 2, gy + s * 2, CREAM,
                  outline=DISC_EDGE, width=max(1, SCALE // 4))
        r = s * 0.72                            # half the cross, corner to middle
        for dx in (r, -r):
            self.canvas.create_line(gx - dx, gy - r, gx + dx, gy + r,
                                    fill=DISC_EDGE, width=max(1, round(s / 2.5)),
                                    capstyle="round", tags=("ui", "him"))
        self.hits["exit"] = (gx - s * 2, gy - s * 2, gx + s * 2, gy + s * 2)

    def reset_button(self):
        """A looping arrow, drawn rather than lettered -- no glyph reads at 4px."""
        s = max(2, SCALE)
        gx, gy = self.ox + 37 * SCALE, self.oy + 47 * SCALE
        self.rect(gx - s * 2, gy - s * 2, gx + s * 2, gy + s * 2, "#5a636e",
                  outline=DISC_EDGE, width=max(1, SCALE // 4))
        r = s * 0.9
        self.canvas.create_arc(gx - r, gy - r, gx + r, gy + r,
                               start=20, extent=290, style="arc", outline=CREAM,
                               width=max(1, round(s / 2.5)), tags=("ui", "him"))
        t = s * 0.55
        self.canvas.create_polygon(gx + r, gy - t, gx + r + t, gy + t * 0.3,
                                   gx + r - t, gy + t * 0.3, fill=CREAM,
                                   outline="", tags=("ui", "him"))
        self.hits["reset"] = (gx - s * 2, gy - s * 2, gx + s * 2, gy + s * 2)

    def repaint(self):
        self.canvas.delete("ui")
        self.hits = {}
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
        else:
            # DONE is drawn exactly as RUNNING, because that is what it is: a
            # timer with nothing left on it. left is zero by then, so the
            # digits read 00:00 over a face full of the spent colour.
            heading = (self.task or "focus").upper()[:14]
            self.label(heading, self.cy - 0.50 * R,
                       self.fit(heading, self.cy - 0.50 * R, self.small), TAN)
            self.label(fmt_clock(self.left), self.cy - 0.16 * R, self.big,
                       TAN if self.state == PAUSED else CREAM, bold=True)
            if self.state == PAUSED:
                self.label("PAUSED", self.cy + 0.44 * R, self.tiny, TAN)
        if self.state == DONE:
            # The face stays, the controls do not. Nothing is clickable while
            # it rains: a click anywhere clears the shower, so a button would
            # only be a smaller target for the thing the whole widget already
            # does. quit() refuses in this state for the same reason.
            return
        self.corner_button("pin", 38, "▲" if self.pinned else "▼", self.pinned)
        self.exit_button()              # level with the arrow, other flank
        if self.state in (RUNNING, PAUSED):
            self.reset_button()

    # -- interaction ------------------------------------------------------

    def hit(self, ev, name):
        b = self.hits.get(name)
        p = self.pad
        return bool(b) and b[0] - p <= ev.x <= b[2] + p and b[1] - p <= ev.y <= b[3] + p

    def click(self, ev):
        # Both flank buttons are tested before anything else, so neither can
        # also read as a tap on the belly behind them.
        if self.hit(ev, "exit"):
            self.quit()
            return
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
        """The X on his left flank puts him away.

        He has no frame, no taskbar button and no close box, so without this
        the only way out was Task Manager. It closes him mid-timer too: the
        button is small and deliberate, and being unable to shut a running
        timer was the worse half of the trade.

        DONE is refused rather than merely undrawn. During the tantrum an
        alarm thread is beeping and animation frames are queued against the
        window, and tearing it down underneath them raises from the callback.
        repaint() draws no button in that state, so this is a guard on a path
        nothing currently takes.
        """
        if self.state == DONE:
            return
        stop = getattr(self, "alarm_stop", None)
        if stop is not None:
            stop.set()                  # never leave a beep thread running
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
        warm_beep()                 # so the first beep is not 16 ms behind zero
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
        self.canvas.delete("shower")
        self.canvas.itemconfigure(self.disc, fill=DISC_DARK, state="normal")
        self.canvas.itemconfigure(self.body, image=self.normal, state="normal")
        self.state = IDLE
        self.editing = None
        self.draw_wedge(0.0)
        if self.pending:                     # the next pomodoro, ready to go
            self.minutes_text, self.task, kind = self.pending
            self.loaded = (self.minutes_text, self.task, kind)
            self.pending = None
        self.rest_at(SCALE)                  # back on his mark, face and all
        self.place_disc()
        self.repaint()
        self.apply_layer()
        self.last_paint = None

    def finish(self):
        """Time is up. It starts raining on him rather than anything louder.

        The belly is left exactly as the last second of the timer left it: the
        face full of the spent colour, the digits reading zero. It used to be
        hidden outright so the tantrum had the screen to itself, but there is
        no tantrum now, and a finished timer that shows no time is a worse
        thing to walk back to than one that does.
        """
        self.state = DONE
        self.left = 0
        # The alarm goes first. Everything below it costs milliseconds --
        # save_state writes a file, apply_layer and lift are Win32 round
        # trips -- and every one of them used to land between the clock
        # reading zero and the first beep being heard.
        self.alarm_stop = threading.Event()      # beeps run until the rain stops
        alarm(self.alarm_stop)
        self.draw_wedge(1.0)
        self.show_me()                          # front and centre, and stays
        if LOG_SESSIONS:                        # off unless aimed at a vault
            append_log(self.task or "focus", self.total, self.session_kind,
                       log_dir=LOG_SESSIONS)
        self.queue_next()
        self.dance_seq += 1
        self.shower(0, self.dance_seq)
        self.last_paint = None

    def rest_at(self, zoom, dx=0, dy=0):
        """Pin the sprite by its bottom-right corner, and move his face with it.

        Anchoring to that corner keeps his feet where they were and sends any
        offset up and left, into the padding rather than off the screen.

        The clock face and the lettering are canvas items of their own rather
        than part of the sprite image, so moving the image alone left them
        behind: he shivered out from under his own belly. They are shifted by
        the change in offset rather than to an absolute spot, because
        repaint() lays them out from cx/cy at moments this method does not
        control, and cx/cy therefore has to carry the offset too.
        """
        self.canvas.coords(self.body, self.win_w - GRID_W * zoom + dx,
                           self.win_h - GRID_H * zoom + dy)
        ddx, ddy = dx - self.offset[0], dy - self.offset[1]
        self.offset = (dx, dy)
        if ddx or ddy:
            self.cx += ddx
            self.cy += ddy
            self.canvas.move("him", ddx, ddy)

    @staticmethod
    def window_cell():
        """Pixels per cell the window is sized for.

        The sprite scales to a whole number of pixels per cell, so anything
        that has to agree with the window's size has to round the same way the
        sprite does. Working it out separately as SCALE * HEADROOM is the trap
        in DESIGN.md: the two sums agree only while that product lands on a
        whole number, and where it does not the padding came out short by up
        to 24 pixels.
        """
        return max(1, round(SCALE * HEADROOM))

    # Rain, in three depths. The colours are the film's night palette, which
    # is very nearly the clock face's already: indigo and blue-black. Kazuo
    # Oga's brief from Miyazaki was "subdued but beautiful" and specifically
    # not raw primary colour, so none of these is far off the greys he is
    # already drawn in.
    RAIN_COLOURS = ("#3f5f6b", "#56808e", "#7aa3ab")    # far, middle, near

    def shiver(self, t):
        """How far off his mark he is now, in pixels. Never right or down.

        He rests in the bottom-right corner with his own edges on the
        window's, and all the spare room is up and to the left of him. Shaking
        him evenly about his mark therefore put half of every shiver outside
        the window, where it was clipped against an edge nobody can see. The
        range is shifted instead of narrowed, so the distance he travels is
        still the distance measured off the reference -- he just travels it on
        the side where there is room.

        It damps to nothing over the tail, which lands him back exactly on his
        mark rather than stopping wherever the last offset happened to be.
        """
        calm = min(1.0, (1.0 - t) / SHAKE_SETTLE)
        return (round((self.shake[0] - SHAKE_X) * SCALE * calm),
                round((self.shake[1] - SHAKE_Y) * SCALE * calm))

    def shower(self, step, seq=None):
        """It rains on him, and he shivers in it until it passes.

        He stays exactly the size he is, and his belly keeps the clock face it
        had a moment ago, now reading zero. The finish used to swell him by a
        third and burst him, which is what the window's spare room was for;
        the room is still there and the rain falls through it.
        """
        if seq is not None and seq != self.dance_seq:
            return
        if step == 0:
            # seeded, so it is raining on the first frame rather than opening
            # on a clear sky with a sheet of drops arriving together
            self.bits = [self.new_streak(seeded=True)
                         for _ in range(SHOWER_RAIN)]
            self.shake = (0.0, 0.0)

        self.canvas.delete("shower")
        t = step * SHOWER_STEP_MS / SHOWER_MS
        if t >= 1.0:
            self.reset()
            return

        # A new offset every few frames, not every frame. Measured off the
        # reference, it holds one for three or four frames and then jumps;
        # resampling every frame reads as a buzz instead of a shiver.
        if step % SHAKE_HOLD == 0:
            self.shake = (random.uniform(-SHAKE_X, SHAKE_X),
                          random.uniform(-SHAKE_Y, SHAKE_Y))
        self.rest_at(SCALE, *self.shiver(t))

        # the rain thins out over the same tail the shiver damps over, so
        # the weather and his shivering stop together rather than one of them
        # carrying on alone after the other has finished
        wet = min(1.0, (1.0 - t) / SHAKE_SETTLE)
        self.rain(wet)
        self.root.after(SHOWER_STEP_MS, self.shower, step + 1, seq)

    def new_streak(self, seeded=False):
        """One streak of rain, in one of three depths.

        Far rain is dim, short, thin and slow; near rain is none of those.
        That difference is the whole illusion -- one colour at one speed looks
        like falling dashes rather than weather.
        """
        lane = random.randrange(3)
        return {
            "lane": lane,
            "x": random.uniform(0, self.win_w + 4 * SCALE),
            "y": (random.uniform(0, self.win_h) if seeded
                  else -random.uniform(0, 6) * SCALE),
            "len": (2.2 + 1.7 * lane) * SCALE,
            "vy": (3.2 + 2.3 * lane) * SCALE,
            "vx": -(0.5 + 0.25 * lane) * SCALE,         # a little wind
        }

    def rain(self, wet):
        """Fall, slanting, and wrap back to the top on landing.

        The wrap is what makes it rain. At these speeds a fixed set of drops
        has crossed the window in under a fifth of a second, which is a spray.
        """
        for i, st in enumerate(self.bits):
            st["x"] += st["vx"]
            st["y"] += st["vy"]
            if st["y"] - st["len"] > self.win_h or st["x"] + st["len"] < 0:
                self.bits[i] = st = self.new_streak()
            ln = st["len"] * wet
            if ln < 1.0:
                continue
            # the streak lies along its own path, so its slant and the slant
            # of its fall agree instead of fighting
            self.canvas.create_line(st["x"] - st["vx"] / st["vy"] * ln,
                                    st["y"] - ln, st["x"], st["y"],
                                    fill=self.RAIN_COLOURS[st["lane"]],
                                    width=max(1, round(SCALE *
                                                       (0.16 + 0.08 * st["lane"]))),
                                    tags=("shower", "shower-near" if st["lane"] == 2
                                          else "shower-far"))
        # the two far depths go behind him, the near one stays in front, which
        # is what puts him inside the weather rather than in a photograph of
        # it. Everything drawn this frame starts above him, so only the far
        # rain has to move; the clock face and the digits are his own items
        # and are left where they are.
        self.canvas.tag_lower("shower-far", self.body)

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
        # A 200 ms tick is plenty for a clock that counts in seconds, but it
        # made the finish up to 200 ms late, and the beep is the part you
        # notice: it arrived after the digits already read 00:00. When the end
        # is less than one tick away the next tick is aimed at it instead.
        gap = 200
        if self.state == RUNNING and 0 < self.left < 0.2:
            gap = max(1, round(self.left * 1000))
        self.root.after(gap, self.tick)


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
        # The X on his left flank is the only way to close him. Right-click is
        # gone deliberately: it fired on the press, so quit() tore the window
        # down before the button came back up and the release reached whatever
        # lay underneath -- on the desktop, that opened the desktop's menu.
        assert not w.canvas.bind("<Button-3>"), "right-click should not be bound"

        # The clock face has to shiver with him. It is a canvas item of its
        # own, so moving the sprite image alone left it pinned to the window
        # and he visibly slid out from under his own belly. The face is
        # checked against the sprite, not against a remembered number, so it
        # also catches a redraw that puts it back where it never moved from.
        w.state = DONE
        w.repaint()
        for dx, dy in ((0, 0), (-7, -5), (-SCALE, 0), (-3, -11), (0, 0)):
            w.rest_at(SCALE, dx, dy)
            w.repaint()
            bx, by = w.canvas.coords(w.body)
            x0, y0, x1, y1 = w.canvas.coords(w.disc)
            assert abs((x0 + x1) / 2 - (bx + DISC_CX * SCALE)) < 1.0 and \
                abs((y0 + y1) / 2 - (by + DISC_CY * SCALE)) < 1.0, \
                f"the clock face stayed behind at an offset of {(dx, dy)}"
        closed = []
        real_destroy = root.destroy
        root.destroy = lambda: closed.append(True)
        try:
            for st in (IDLE, RUNNING, PAUSED):
                w.state = st
                w.repaint()
                assert "exit" in w.hits, f"no X on his flank while {st}"
                closed.clear()
                w.quit()
                assert closed, f"the X did not close him while {st}"
            # during the tantrum he is swelling, an alarm thread is beeping and
            # animation frames are queued: no button, and quit refuses anyway
            w.state = DONE
            w.repaint()
            assert "exit" not in w.hits, "the X must not be drawn mid-tantrum"
            closed.clear()
            w.quit()
            assert not closed, "the X must not close him mid-tantrum"
        finally:
            root.destroy = real_destroy
            w.state = IDLE
        # the window has to hold the whole scene, or its edge clips along a
        # boundary nobody can see. The padding and the sprite size used to be
        # worked out by two separate sums that agreed only while
        # SCALE * HEADROOM landed on a whole number. test_timer.py catches this
        # too, but that suite does not run in CI, and this is the check that
        # would have caught it there.
        grown = w.window_cell()
        assert w.win_w >= GRID_W * grown, (
            f"window {w.win_w}px too narrow for its padding "
            f"of {GRID_W * grown}px")
        assert w.win_h >= GRID_H * grown, (
            f"window {w.win_h}px too short for its padding "
            f"of {GRID_H * grown}px")
        # he shivers up and to the left into that same padding, so the
        # window has to hold him at his furthest offset, not just at rest
        assert w.ox - 2 * SHAKE_X * SCALE >= 0 and w.oy - 2 * SHAKE_Y * SCALE >= 0, \
            "the shiver reaches off the top-left of the window"
    finally:
        STATE_FILE = keep
        root.destroy()

    # both corner buttons have to sit on his body, not hang beside it
    for name, bx, by in (("pin", 37, 38), ("reset", 37, 47), ("exit", 8, 38)):
        for dy in (-2, 2):
            for dx in (-2, 2):
                assert grid[by + dy][bx + dx] != ".", \
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

    # a waveform that starts or ends on a jump clicks in the speaker
    import io as _io
    import struct as _struct
    import wave as _wave
    for label, raw in (("beep", _beep_wav()),):
        wf = _wave.open(_io.BytesIO(raw))
        cnt = wf.getnframes()
        d = _struct.unpack(f"<{cnt}h", wf.readframes(cnt))
        assert cnt > 0, f"{label} is empty"
        assert abs(d[0]) < 2000, f"{label} starts on a jump and will click"
        assert abs(d[-1]) < 2000, f"{label} ends on a jump and will click"
        assert max(abs(v) for v in d) < 32700, f"{label} clips"
        # a beep longer than its gap would overlap the next one, and this one
        # is 120 ms of a 500 ms period
        if label == "beep":
            assert cnt / RATE * 1000 < BEEP_PERIOD_MS, \
                "the beep outlasts the gap between beeps and will overlap itself"

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
