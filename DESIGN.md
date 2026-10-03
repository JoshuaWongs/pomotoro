# How Pomodoro Totoro works, and why

README.md tells you how to use him. This file is the record of how he is built
and the reasons behind the odd-looking decisions, so nobody has to rediscover
them. Written at the end of the first build.

## Where this came from

Modelled on the pixel avocado Pomodoro timer Tina Huang demos in "Learn 10X
Faster In 10 Minutes" (youtube.com/watch?v=sbmP6i-MChk, around 8:50). The
layout copies hers deliberately: a chunky character with a clock face on his
belly holding the number, a MIN label, a task line, a dotted rule and START.
The beep pitch and spacing, and the original blink-on-finish, were measured
from that video's audio and frames rather than guessed.

The character was a gorilla first, then switched to Totoro from a bead chart.
The finish was a dance, then a blink, then the current tantrum.

## What it needs to run

Windows, and a Python with tkinter. Nothing else: no dependencies, no build
step, no install. The sprite proportions and the beep timing were measured off
the source video's own frames and audio with ffmpeg, but that was a one-off
while building and is not needed to run him.

Keep the folder out of a synced location such as OneDrive's Documents or
Desktop. `state.json` is rewritten every time the side button is pressed, and
sync clients handle small frequent writes badly -- upload churn, and
occasionally a file lock landing exactly on a write.

## The pieces

| File | What it is |
|---|---|
| pomodoro.py | The whole application, about 1400 lines |
| font5x7.py | A hand-drawn pixel alphabet, 81 characters |
| test_timer.py | 20 sections of behaviour tests |
| totoro.ico | His taskbar icon, generated from the sprite |
| state.json | One setting: which way his arrow points |

Nothing is installed and nothing goes online. It runs on the Python already on
the machine, standard library only.

On the machine he was built on, two shortcuts launch him: one in the Startup
folder so he appears at login, one pinned to the taskbar. Both were made by
hand. The program itself creates neither.

## The timer itself

**Idle.** His belly shows the minutes, the word MIN, a task line, a dotted
rule and START. Click the number to type a new one; the cursor lands exactly
where you clicked, so you can insert between digits. Click the task line to
name the session. START or Enter begins it.

**Time entry.** A plain number is minutes. A dot separates minutes from
seconds, where one digit after the dot means tens of seconds:

- 50 is fifty minutes
- .3 is thirty seconds
- .45 is forty-five seconds
- 5.3 is five minutes thirty

**Running.** The belly becomes a clock face. The pale slice grows as time is
spent, dark is what remains. No buttons: clicking the belly pauses, clicking
again resumes. A small circular arrow on his side throws the timer away and
returns to the standard screen. Escape does the same.

**The countdown rounds up.** A fifty minute timer reads 50:00 for its whole
first second and hits 00:00 exactly as it ends. Rounding down made it drop to
49:59 the instant it started, which looked broken.

**Finishing.** He comes to the front of everything, the clock face vanishes,
his brows crash down, and over a couple of seconds he swells by about a third
while reddening and shaking harder. Then he bursts into camphor
leaves, acorns and soot sprites — the three things he is associated with in the
film. Clicking him or pressing Return cuts it short.

**Quitting.** Right-click him while idle. He has no frame, taskbar button or
close box, so before this the only way out was Task Manager. Mid-timer the
right-click is ignored, so a stray one cannot throw a session away.

**The chain.** Finishing a focus block loads the break without starting it: a
break is a fifth of the block, so 50 gives 10 and 25 gives 5. Finishing the
break loads your focus length and its task back. The chain reads what actually
ran, not a toggle, so ignoring an offered break and running another focus block
still earns you a break afterwards.

## Where he sits

Fixed in the bottom-right, eighteen logical pixels from the right edge and the
same above the taskbar, measured against the work area so the taskbar never
covers him. He cannot be dragged.

The window is larger than he is: it holds a transparent margin up and to the
left big enough for him at full tantrum size. He is anchored to the window's
bottom-right corner, so swelling pushes him up and left into that margin
instead of off the screen edge. Transparent areas pass clicks through, so the
oversized window does not block the desktop behind it.

**The arrow** on his side chooses his layer. Up means he floats above every
window. Down means he sits behind them, which is the normal state. A finished
timer always brings him up and leaves him there, whatever the arrow said.

**Summoning him.** With the arrow down you cannot reach him without clearing
the screen, so opening the shortcut again brings the running copy to the front
rather than starting a second one. That is the taskbar button's whole job.

**One copy only.** He starts at login, so opening the shortcut afterwards would
otherwise stack two of him in the corner sharing one settings file. A named
Windows mutex stops that; the second copy signals the first and exits.

## How he is drawn

He is drawn in code from ellipses and triangles, not loaded from an image, so
he stays sharp at any display scaling. One tapered body rather than a head on a
torso — he has no neck, and splitting the two made him look stacked.

The lettering is a 5x7 pixel alphabet written by hand in font5x7.py. Windows
ships no pixel font, and a normal typeface spoiled the retro look. Bold is done
by smearing each stroke one pixel sideways, the usual trick for bitmap type.

**Display scaling.** The machine he was built on runs at 200%. Handling that ourselves and
then multiplying the sprite by a whole number keeps the pixels square. Letting
Windows scale the window instead ran it through a blur filter, which is the one
thing pixel art must never get.

**The icon** is deliberately drawn wider than his true proportions. He is a
tall narrow shape, and at honest proportions he looked smaller and thinner than
the other icons on the taskbar.

## Sound

A beep every half second from the moment the timer ends until he bursts, then a
low crunch as he does. Both are synthesised into a WAV the first time they play
and kept in a temp folder for the rest of the run. The folder is deleted on
exit. A run that never reaches exit -- Windows shutting down, or Task Manager --
leaves it behind, so each launch that wins the single-copy lock sweeps up any
it finds. Before that, every such run left one more folder in %TEMP%.

The beep pitch and spacing were measured from the video that inspired this: a
single 880 Hz tone about 42 ms long, once every 500 ms. Steady, not a triple.

## Traps found the hard way

These each cost real debugging. Changing the code near them without knowing
will reintroduce the bug.

**Tk fills the whole circle for a thin pie slice.** Any arc under about one
degree paints as a complete filled disc. A fifty minute timer is under a degree
for its first ten seconds, so the belly flashed solid at the start. Hiding the
slice until it grew past a degree fixed the flash but left no colour at all for
ten seconds. The slice is now a polygon, which has no minimum size and is exact
from the first second.

**winsound refuses to play asynchronously from memory.** It raises outright.
Playing synchronously from memory instead blocks about 270 ms a time, which
would trample the half-second beep schedule. Hence the temp file. A blanket
exception handler hid this failure for a while and the beeps simply went
silent, so playback failures are now recorded and asserted in the self-test.

**ctypes needs use_last_error=True.** Without it ctypes never captures the
thread's error code and get_last_error always returns zero. The duplicate-copy
check depended on reading it, and silently reported "no other copy running".

**Sleeping for the gap makes beeps drift.** Starting a sound costs more than it
promises, and that error accumulates. Each beep is timed against a fixed
schedule instead. Measured: the drifting version wandered 358 ms off by the
sixth beep, the scheduled one stays within 5 ms.

**Animations must carry a sequence number.** Pressing a button mid-tantrum used
to leave the queued animation frames firing afterwards, parking him off-centre.
Each animation now carries the number it started with and stops if it changes.

**The window padding must be asked for, not recalculated.** The sprite scales
to a whole number of pixels per cell, so his width at full swell is
`GRID_W * round(SCALE * GROW_TO)`. The transparent padding was originally
worked out by a separate sum -- cells of growth, times SCALE -- and the two
agreed only while `SCALE * GROW_TO` happened to land on a whole number. At
`GROW_TO = 1.5` it always did, so the bug sat there invisibly; checked
afterwards, the old sum was short by 4 to 24 pixels at scales 2, 4, 8 and 10,
and merely oversized at 6 and 12. Shortening the tantrum to `1.375` made him
swell out through his own window edge. The padding is now taken from
`rage_zoom(1.0)`, the same call the renderer uses, so the two cannot drift
apart again. The matching assertion lives in `--selftest` rather than only in
`test_timer.py`, because the latter does not run in CI.

## Logging is switched off

He writes nothing down except state.json. The writer is built and tested but
disabled: set LOG_SESSIONS in pomodoro.py to a folder to turn it on.

The format is Obsidian's Dataview inline fields, one note per month:

```
- (pomodoro:: WORK) (duration:: 50m) (task:: review deck) (end:: 2026-09-08 15:58)
- (pomodoro:: BREAK) (duration:: 10m) (task:: break) (end:: 2026-09-08 16:08)
```

The mode field is the point. Breaks and focus blocks land in the same file, so
with nothing naming which is which, any total you query is inflated by every
break you took. With it, a query can ask for focus alone.

## Tests

Two commands, both worth running after any change:

```
python pomodoro.py --selftest
python test_timer.py
```

The self-test covers the timer maths, the duration parser, the log format, the
font, the sounds, the sprite proportions, and that the widget still builds — a
missing colour or a typo in the drawing code is invisible to everything else
and only shows up on launch.

test_timer.py has 20 sections and feeds clicks at real on-screen coordinates
through the click handler. The
ones worth knowing about: the progress slice must match the clock to within a
twentieth of a degree and must show colour from the first second; the beeps
must not drift; he must come back from the tantrum with nothing left on screen
and on the right layer; and skipping an offered break must not invert the
chain.

Timing-sensitive checks measure cumulative drift rather than gap-to-gap jitter,
because jitter just measures how busy the machine is. One section retries once
before failing for the same reason.

## Known limits

- Windows only. The transparency, the layering, the sound and the single-copy
  check are all Win32.
- The finish notification is gone by choice; he comes to the front instead.
- Explosion fragments are clipped at the window edge.
- Changing the taskbar icon needs an unpin and re-pin, because Windows caches
  pinned icons.
