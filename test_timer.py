"""Hammer the timer's state machine and assert the progress wedge stays sane.

Run with: python test_timer.py

Drives real clicks through Totoro.click() at real coordinates, mixing in the
corner buttons, pause taps and resets, then checks the invariants the wedge has
to hold no matter what order things happen in.
"""
import ctypes
import math
import random
import sys
import tkinter as tk

import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pomodoro as P

if sys.platform != "win32":
    # Same reason pomodoro.py refuses: this drives real Win32 window layering
    # and a named mutex, so off Windows it fails on checks that are not wrong,
    # they are inapplicable. Say that instead of reporting failures.
    sys.exit("test_timer.py is Windows only, like the widget it tests.")

# a private summon channel, so the copy actually running on the desktop cannot
# swallow the test's signal -- the event is auto-reset, so only one waiter gets it
P.SUMMON_EVENT = f"PomodoroTotoro.test.{os.getpid()}"
P.sharpen_on_scaled_displays()
P.STATE_FILE = os.path.join(tempfile.gettempdir(), "pomodoro_test_state.json")

root = tk.Tk()
g = P.Totoro(root)
root.update()

failures = []


def note(msg):
    failures.append(msg)
    print("FAIL:", msg)


class Ev:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.keysym, self.char = "", ""


def wedge_extent():
    """Negative degrees, the way the old arc reported it."""
    return -359.99 * g.spent if wedge_shown() else 0.0


def wedge_sweep_drawn():
    """The swept angle the polygon actually covers, measured off its points."""
    pts = g.canvas.coords(g.wedge)
    if len(pts) < 6:
        return 0.0
    cx, cy = pts[0], pts[1]
    ax, ay = pts[-2], pts[-1]
    deg = math.degrees(math.atan2(ax - cx, cy - ay)) % 360
    return deg


def wedge_shown():
    return g.canvas.itemcget(g.wedge, "state") != "hidden"


def check(label):
    """Invariants that must hold in every state."""
    ext = wedge_extent()
    if not (-360.0 <= ext <= 0.0):
        note(f"{label}: extent {ext} outside -360..0")
    if g.state in (P.RUNNING, P.PAUSED):
        if g.left > g.total + 0.5:
            note(f"{label}: left {g.left:.2f} exceeds total {g.total}")
        if g.left < -0.5:
            note(f"{label}: left {g.left:.2f} went negative")
        want = -359.99 * (1.0 - max(0.0, g.left) / g.total)
        if abs(ext - want) > 0.05:
            note(f"{label}: extent {ext:.4f} does not match clock "
                 f"(want {want:.4f})")
        if want < -0.0001 and not wedge_shown():
            note(f"{label}: wedge hidden while {g.state} with {want:.4f} deg run")
    elif g.state == P.DONE:
        # a finished timer keeps its face, filled right up with the spent
        # colour. It used to be hidden for the tantrum; there is no tantrum
        # now, and a finished timer showing no time is a poor thing to walk
        # back to
        if not wedge_shown():
            note(f"{label}: the finished timer has no face left")
        elif ext > -359.0:
            note(f"{label}: finished, but the face is only {-ext:.1f} deg full")
    else:
        if wedge_shown():
            note(f"{label}: wedge still visible while {g.state}")


# where the clickable things actually are
def pt(name):
    b = g.hits.get(name)
    return Ev((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) if b else None


print("--- 1. plain run, no interference ---")
g.minutes_text = "2"
g.begin()
g.left = 120.0
g.tick(); root.update(); check("just started")
for frac in (0.25, 0.5, 0.75, 0.99):
    g.left = 120.0 * (1 - frac)
    g.tick(); root.update()
    check(f"at {int(frac * 100)}% spent")

print("--- 2. pausing and resuming must not move the wedge ---")
g.state = P.RUNNING
g.total = 120
g.left = 60.0
g.ends_at = P.time.monotonic() + 60.0
g.tick(); root.update()
before = wedge_extent()
g.repaint()
tap = Ev(g.cx, g.cy)
g.click(tap)                       # pause
root.update(); check("paused")
if abs(wedge_extent() - before) > 1.0:
    note(f"pausing moved the wedge: {before:.2f} -> {wedge_extent():.2f}")
g.click(tap)                       # resume
root.update(); check("resumed")
if abs(wedge_extent() - before) > 1.0:
    note(f"resuming moved the wedge: {before:.2f} -> {wedge_extent():.2f}")

print("--- 3. the corner buttons must not touch the timer ---")
g.repaint()
for name in ("pin", "reset"):
    if not g.hits.get(name):
        note(f"{name} button missing while running")
g.repaint()
p = pt("pin")
snapshot = (g.state, round(g.left, 1), wedge_extent())
g.click(p)                         # layer toggle
root.update()
after = (g.state, round(g.left, 1), wedge_extent())
if snapshot[0] != after[0] or abs(snapshot[1] - after[1]) > 1.0:
    note(f"layer button changed the timer: {snapshot} -> {after}")
check("after layer toggle")
g.click(p)
root.update(); check("after layer toggle back")

print("--- 4. the corner buttons must not also register as belly taps ---")
g.repaint()
for name in ("pin", "reset", "exit"):
    b = g.hits[name]
    corners = [(b[0], b[1]), (b[2], b[1]), (b[0], b[3]), (b[2], b[3])]
    for cx, cy in corners:
        d2 = (cx - g.cx) ** 2 + (cy - g.cy) ** 2
        if d2 <= g.R ** 2:
            note(f"{name} button overlaps the belly at ({cx:.0f},{cy:.0f}) "
                 f"- clicking it would also pause")

print("--- 5. reset from a running timer ---")
g.repaint()
g.click(pt("reset"))
root.update(); check("after reset")
if g.state != P.IDLE:
    note(f"reset left state as {g.state}")
if g.minutes_text != str(P.DEFAULT_MINUTES):
    note(f"reset left minutes as {g.minutes_text!r}")

print("--- 6. idle hit boxes must not overlap ---")
g.repaint()
pad = g.pad                        # the same slop the click handler uses
boxes = {n: g.hits[n] for n in ("min", "task", "start", "exit") if n in g.hits}
names = list(boxes)
for i, a in enumerate(names):
    for b in names[i + 1:]:
        ax0, ay0, ax1, ay1 = boxes[a]
        bx0, by0, bx1, by1 = boxes[b]
        if (ax0 - pad < bx1 + pad and bx0 - pad < ax1 + pad
                and ay0 - pad < by1 + pad and by0 - pad < ay1 + pad):
            note(f"idle targets {a} and {b} overlap once padding is applied")

print("--- 7. random mashing ---")
random.seed(7)
# The X on his flank really does close him, so mashing lands on it sooner or
# later and tears the window down mid-section. Hold the teardown for the
# duration: this section asks whether his state stays coherent under abuse,
# not whether closing works -- section 21 covers that.
mash_closed = []
real_destroy = root.destroy
root.destroy = lambda: mash_closed.append(True)
try:
    for i in range(400):
        if g.state == P.IDLE:
            g.repaint()
            g.minutes_text = random.choice(["1", "2", ".3", "5.3", "10"])
            g.begin()
            g.left = g.total * random.random()
        g.repaint()
        spots = [Ev(g.cx, g.cy)]
        for n in ("pin", "reset", "exit", "log", "skip", "min", "task", "start"):
            p = pt(n)
            if p:
                spots.append(p)
        spots.append(Ev(random.randint(0, GRID := g.cx * 2),
                        random.randint(0, g.cy * 2)))
        g.click(random.choice(spots))
        if g.state in (P.RUNNING, P.PAUSED) and random.random() < 0.3:
            g.left = max(0.0, g.left - g.total * random.random())
            g.ends_at = P.time.monotonic() + g.left
        g.tick()
        root.update()
        check(f"mash step {i}")
        if failures:
            break
finally:
    root.destroy = real_destroy
if not mash_closed:
    note("400 random clicks never once hit the X; the mash is not reaching it")

print("--- 8. he shivers without ever leaving his corner ---")
g.reset_to_standard()
# driven through the real shiver() rather than a copy of its sums, which is
# the only way this catches a change to how the offset is worked out
far = 0
for i in range(400):
    g.shake = (P.random.uniform(-P.SHAKE_X, P.SHAKE_X),
               P.random.uniform(-P.SHAKE_Y, P.SHAKE_Y))
    dx, dy = g.shiver(P.random.random() * 0.999)
    g.rest_at(P.SCALE, dx, dy)
    x, y = g.canvas.coords(g.body)
    far = max(far, abs(x - g.ox), abs(y - g.oy))
    if x < 0 or y < 0:
        note(f"an offset of {(dx, dy)} shook him off the top-left")
    if x + P.GRID_W * P.SCALE > g.win_w or y + P.GRID_H * P.SCALE > g.win_h:
        note(f"an offset of {(dx, dy)} shook him out of the window")
if far < P.SCALE:
    note(f"400 offsets never moved him one whole sprite pixel ({far}px)")
# the very end of the shower has to land him back exactly on his mark
g.rest_at(P.SCALE, *g.shiver(1.0))
x, y = g.canvas.coords(g.body)
if (round(x), round(y)) != (g.ox, g.oy):
    note(f"the shiver does not settle back onto his mark, at {(x, y)}")
g.rest_at(P.SCALE)

print("--- 9. real clock, with pauses, must never run backwards ---")
g.reset_to_standard()
g.minutes_text = ".1"
g.begin()
last = 0.0
for i in range(40):
    if i in (10, 25):
        g.click(Ev(g.cx, g.cy))          # pause
    if i in (15, 30):
        g.click(Ev(g.cx, g.cy))          # resume
    g.tick(); root.update()
    ext = abs(wedge_extent())
    if ext < last - 0.5:
        note(f"step {i}: wedge went backwards, {last:.2f} -> {ext:.2f} ({g.state})")
    last = ext
    check(f"realtime step {i} ({g.state})")
    P.time.sleep(0.05)

print("--- 10. a long timer shows colour from the very first second ---")
g.reset_to_standard()
g.minutes_text = "50"
g.begin()
g.state = P.PAUSED                    # hold the clock where we put it
for elapsed in (1, 2, 5, 10, 30, 60, 600):
    g.left = g.total - elapsed
    g.tick(); root.update()
    if not wedge_shown():
        note(f"{elapsed}s into 50 minutes there is still no coloured slice")
    drawn = wedge_sweep_drawn()
    want = 360.0 * elapsed / g.total
    if abs(drawn - want) > 0.6:
        note(f"{elapsed}s in, the slice covers {drawn:.3f} deg, expected "
             f"{want:.3f}")
    # and it must never be the whole disc, which is how the old bug looked
    if drawn > 350 and want < 350:
        note(f"{elapsed}s in, the slice filled the whole face")
    check(f"50 min, {elapsed}s in")
g.reset_to_standard()

print("--- 11. the caret goes where you click, and edits happen there ---")
class Key:
    def __init__(self, keysym="", char=""):
        self.keysym, self.char = keysym, char

g.reset_to_standard(); g.repaint()
x0, px, n = g.field["min"]
adv = (5 + 1) * px                       # glyph width + gap, in screen pixels
for want, x in ((0, x0), (1, x0 + adv), (2, x0 + 2 * adv)):
    got = g.caret_from_click("min", Ev(x, g.cy))
    if got != want:
        note(f"click at offset {x - x0:.0f} gave caret {got}, expected {want}")

g.focus_field("min", 0)                  # cursor before the 5
g.key(Key(char="1")); g.repaint()
if g.minutes_text != "150":
    note(f"typing at the front gave {g.minutes_text!r}, expected '150'")
if g.caret_at != 1:
    note(f"caret should follow the typed character, at {g.caret_at}")

g.focus_field("min", 2)                  # between 5 and 0
g.key(Key(keysym="BackSpace")); g.repaint()
if g.minutes_text != "10":
    note(f"backspace mid-string gave {g.minutes_text!r}, expected '10'")

g.key(Key(keysym="Home"))
if g.caret_at != 0:
    note("Home did not move the caret to the start")
g.key(Key(keysym="End"))
if g.caret_at != len(g.minutes_text):
    note("End did not move the caret to the finish")
g.key(Key(keysym="Left"))
if g.caret_at != len(g.minutes_text) - 1:
    note("Left did not step the caret back")

g.focus_field("min", 99)                 # a click past the end clamps
if g.caret_at != len(g.minutes_text):
    note(f"caret past the end was not clamped, at {g.caret_at}")
g.reset_to_standard()

print("--- 12. the shower leaves nothing behind ---")
g.reset_to_standard()
hushed = False
real_stop = P.stop_alarm
def _spy_stop():
    global hushed
    hushed = True
    real_stop()
P.stop_alarm = _spy_stop
g.minutes_text = ".1"; g.begin(); g.left = 0.0
g.finish(); root.update()
if g.state != P.DONE:
    note("finish did not start the shower")
if g.canvas.itemcget(g.disc, "state") == "hidden":
    note("the clock face should still be up while it rains")
if P.fmt_clock(g.left) != "00:00":
    note(f"the finished belly reads {P.fmt_clock(g.left)}, should read 00:00")
g.repaint()
if g.hits:
    note(f"nothing should be clickable mid-shower, found {sorted(g.hits)}")
moved = False
deadline = P.time.monotonic() + P.SHOWER_MS / 1000 + 2.0
while g.state != P.IDLE and P.time.monotonic() < deadline:
    root.update()
    x, y = g.canvas.coords(g.body)
    if (round(x), round(y)) != (g.ox, g.oy):
        moved = True
    # short against SHOWER_STEP_MS, not near it: polling every 30 ms serviced
    # about one frame a poll and stretched a 4 s shower past its own deadline
    P.time.sleep(0.005)
if not moved:
    note("he never actually shivered off his resting spot")
if g.state != P.IDLE:
    note(f"the shower did not settle back to idle, left in {g.state}")
if g.canvas.find_withtag("shower"):
    note("rain or umbrella was left on screen")
if not hushed:
    note("the alarm was left playing after the shower")
if g.canvas.itemcget(g.body, "state") == "hidden":
    note("he is still hidden after the shower")
if g.canvas.itemcget(g.disc, "state") == "hidden":
    note("the clock face never came back")
x, y = g.canvas.coords(g.body)
if (round(x), round(y)) != (g.ox, g.oy):
    note(f"he came back at {(x, y)}, should rest at {(g.ox, g.oy)}")
P.stop_alarm = real_stop

print("--- 13. the shower is long enough to read, and to be heard ---")
frames = int(P.SHOWER_MS / P.SHOWER_STEP_MS)
if frames < 20:
    note(f"only {frames} frames in the shower; the rain will stutter")
shivers = frames / P.SHAKE_HOLD
if shivers < 8:
    note(f"only {shivers:.0f} offsets over the shower; too few to read as a shiver")
# the damping has to start before the last frame or he stops mid-shiver
if P.SHAKE_SETTLE <= 1.0 / frames:
    note("the shiver is not damped for long enough to settle before it ends")
expected_beeps = P.SHOWER_MS / P.BEEP_PERIOD_MS
if expected_beeps < 3:
    note(f"only {expected_beeps:.1f} beeps fit in the shower; too few to register")
# the window has to be able to hold the whole scene
need_w = P.GRID_W * g.window_cell()
need_h = P.GRID_H * g.window_cell()
if g.win_w < need_w or g.win_h < need_h:
    note(f"window {(g.win_w, g.win_h)} cannot hold its padding {(need_w, need_h)}")

print("--- 14. the alarm is started once, and never left running ---")
# The beeps used to come from a thread, one PlaySound each against a fixed
# schedule, and this section measured the gaps between them off the wall
# clock -- which is why it has never been safe to run in CI. They are now one
# buffer whose gaps are sample positions, so --selftest reads the spacing off
# the waveform exactly and this section is left with the behaviour: the alarm
# starts when the timer ends, once, and nothing is still playing afterwards.
plays, purges = [], []
real_play, real_stop = P.play_alarm, P.stop_alarm
P.play_alarm = lambda: plays.append(P.time.monotonic())
P.stop_alarm = lambda: purges.append(P.time.monotonic())
try:
    g.reset()
    g.minutes_text = "5"
    g.task = "alarm"
    g.begin()
    g.ends_at = P.time.monotonic()
    g.left = 0.0
    began = P.time.monotonic()
    deadline = began + P.SHOWER_MS / 1000 + 2.0
    while g.state != P.IDLE and P.time.monotonic() < deadline:
        root.update()
        P.time.sleep(0.005)
    if len(plays) != 1:
        note(f"the alarm was started {len(plays)} times, expected once")
    if plays and (plays[0] - began) * 1000 > 250:
        note(f"the alarm started {(plays[0] - began) * 1000:.0f} ms after zero")
    if not purges:
        note("the alarm was never purged, so it can outlast the rain")
finally:
    P.play_alarm, P.stop_alarm = real_play, real_stop

print("--- 15. the arrow chooses his layer, and a manual reset keeps it ---")
def topmost():
    return bool(ctypes.windll.user32.GetWindowLongW(g.hwnd(), -20) & 0x8)

for want in (True, False, True):
    g.pinned = not want
    g.toggle_pin()                     # the arrow on his side
    root.update()
    if g.pinned is not want:
        note(f"the arrow did not switch him to pinned={want}")
    if topmost() is not want:
        note(f"pinned={want} but the window is topmost={topmost()}")
    if P.load_state().get("pinned") is not want:
        note(f"pinned={want} was not remembered")

# abandoning a timer by hand must not change which layer he is on
for want in (False, True):
    g.pinned = want
    g.apply_layer()
    g.minutes_text = "5"
    g.begin()
    root.update()
    g.reset_to_standard()
    root.update()
    if g.pinned is not want or topmost() is not want:
        note(f"a manual reset moved him off his layer (wanted {want})")
g.pinned = False
g.apply_layer()

print("--- 16. the coloured slice and the digits agree with the clock ---")
g.reset_to_standard()
g.minutes_text = "50"
g.begin()
total = g.total
g.state = P.PAUSED           # so tick reports the time we set, not the wall clock
for frac, digits in ((0.0, "50:00"), (0.25, "37:30"), (0.5, "25:00"),
                     (0.75, "12:30"), (0.9, "05:00"), (1.0, "00:00")):
    g.left = total * (1 - frac)
    g.tick(); root.update()
    if P.fmt_clock(g.left) != digits:
        note(f"{frac:.0%} through, the clock reads {P.fmt_clock(g.left)}, "
             f"expected {digits}")
    want = -359.99 * frac
    ext = wedge_extent()
    if frac > 0 and not wedge_shown():
        note(f"{frac:.0%} through, no slice is drawn at all")
    if abs(ext - want) > 0.05:
        note(f"{frac:.0%} through, the slice is {ext:.3f} deg, expected "
             f"{want:.3f}")
    if 0 < frac < 1:
        drawn = wedge_sweep_drawn()
        if abs(drawn - 360.0 * frac) > 0.6:
            note(f"{frac:.0%} through, the drawn slice covers {drawn:.2f} deg, "
                 f"expected {360.0 * frac:.2f}")
        pts = g.canvas.coords(g.wedge)
        # the slice has to begin at twelve o'clock and fill clockwise
        if abs(pts[2] - pts[0]) > 0.6 or pts[3] >= pts[1]:
            note("the slice does not start at twelve o'clock")
        if pts[4] < pts[0] - 0.6:
            note("the slice runs anticlockwise; it should fill clockwise")

# a fresh timer must read its full length, not a second less
for mins in ("50", "25", "1"):
    g.reset_to_standard(); g.minutes_text = mins; g.begin()
    shown = P.fmt_clock(g.left)
    want = f"{int(mins):02d}:00"
    if shown != want:
        note(f"a {mins} minute timer starts showing {shown}, expected {want}")
g.reset_to_standard()

print("--- 17. the next pomodoro is loaded in, but not started ---")
def run_to_idle(mins, task=""):
    g.minutes_text = mins
    g.task = task
    g.begin()
    g.left = 0.0
    g.finish()
    root.update()
    end = P.time.monotonic() + P.SHOWER_MS / 1000 + 2.5
    while g.state != P.IDLE and P.time.monotonic() < end:
        root.update()
        P.time.sleep(0.005)
    return g.state == P.IDLE

g.reset_to_standard()
if not run_to_idle("50", "deep work"):
    note("a 50 minute run never settled back to idle")
if g.minutes_text != "10":
    note(f"after 50 minutes it queued {g.minutes_text!r}, expected '10'")
if g.task != "break":
    note(f"the queued break is labelled {g.task!r}, expected 'break'")
if g.state != P.IDLE:
    note("the queued timer must not start on its own")

if not run_to_idle(g.minutes_text, g.task):      # now run the break
    note("the break never settled back to idle")
if g.minutes_text != "50":
    note(f"after the break it queued {g.minutes_text!r}, expected '50' back")
if g.task != "deep work":
    note(f"after the break the task is {g.task!r}, expected 'deep work' back")

g.reset_to_standard()
if not run_to_idle("25"):
    note("a 25 minute run never settled back to idle")
if g.minutes_text != "5":
    note(f"after 25 minutes it queued {g.minutes_text!r}, expected '5'")

g.reset_to_standard()
if g.pending is not None:
    note("a manual reset should throw the queued timer away")

print("--- 18. the timer going off always leaves him in front ---")
for started_pinned in (False, True):
    g.reset_to_standard()
    g.pinned = started_pinned
    g.apply_layer()
    root.update()
    run_to_idle(".1")
    root.update()
    if not g.pinned:
        note(f"started pinned={started_pinned}: he should be left pinned up")
    if not topmost():
        note(f"started pinned={started_pinned}: he should still be in front")
if P.load_state().get("pinned") is not True:
    note("the forced pin was not remembered")
g.reset_to_standard()

print("--- 19. opening the shortcut again summons him ---")
g.pinned = False
g.apply_layer()
root.update()
if topmost():
    note("he should be behind windows before being summoned")
if not P.summon_running_copy():
    note("the summon signal could not be delivered")
for _ in range(12):                    # the widget polls for it
    root.update()
    P.time.sleep(0.06)
if not g.pinned or not topmost():
    note("summoning him did not bring him to the front and pin him")
g.pinned = False
g.apply_layer()
g.reset_to_standard()

print("--- 20. skipping the offered break does not invert the chain ---")
g.reset_to_standard()

def finish_session(mins, task):
    """Run a session to its end and hand back what got queued next."""
    g.minutes_text, g.task = mins, task
    g.begin()
    g.queue_next()
    pend = g.pending
    g.minutes_text, g.task, kind = pend      # what reset() puts on screen
    g.loaded = (g.minutes_text, g.task, kind)
    g.pending = None
    return pend

pend = finish_session("50", "deep work")
if pend[:2] != ("10", "break"):
    note("50 minutes should queue a 10 minute break, got " + repr(pend))

# ignore the offered break and run another focus block instead: the old
# version flipped a toggle here and handed back the 50 minute block
pend = finish_session("25", "email")
if pend[:2] != ("5", "break"):
    note("a 25 minute focus block should queue a 5 minute break even when the "
         "previous break was skipped, got " + repr(pend))

pend = finish_session(pend[0], pend[1])   # actually take this one
if pend[:2] != ("25", "email"):
    note("after a break the focus block and its task should return, got "
         + repr(pend))
g.reset_to_standard()

print("--- 21. the X on his flank closes him, mid-timer included ---")
closed = []
real_destroy = root.destroy
root.destroy = lambda: closed.append(True)
try:
    for label in ("idle", "running"):
        g.reset_to_standard()
        if label == "running":
            g.minutes_text = "25"
            g.begin()
        g.repaint()
        if "exit" not in g.hits:
            note(f"no X on his flank while {label}")
            continue
        b = g.hits["exit"]
        closed.clear()
        g.click(Ev((b[0] + b[2]) / 2, (b[1] + b[3]) / 2))
        if not closed:
            note(f"clicking the X while {label} did not close him")
    # while it is raining there is no button at all: repaint() clears the
    # UI and returns, an alarm thread is beeping and frames are queued
    g.state = P.DONE
    g.repaint()
    if "exit" in g.hits:
        note("the X must not be drawn during the shower")
    closed.clear()
    g.quit()
    if closed:
        note("quit must refuse while the shower is running")
finally:
    root.destroy = real_destroy
    g.reset_to_standard()

print()
print("FAILURES:", len(failures))
root.destroy()
sys.exit(1 if failures else 0)
