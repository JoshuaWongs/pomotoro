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
The finish was a dance, then a blink, then a tantrum that swelled him and
burst him, then the rain he now stands in.

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
| pomodoro.py | The whole application, about 1600 lines |
| font5x7.py | A hand-drawn pixel alphabet, 81 characters |
| test_timer.py | 21 sections of behaviour tests |
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

**Finishing.** It comes on to rain. He comes to the front of everything and
shivers in place for three seconds, the same size throughout, while
rain falls past him in three depths — the far two behind him, the nearest in
front, which is what puts him inside the weather rather than in a picture of
it. The belly keeps its clock face, filled with the spent colour and reading
00:00. Then the shiver damps out and he settles back onto his mark. Clicking
him or pressing Return cuts it short.

He used to lose his temper instead: swell by a third, redden, and burst into
camphor leaves, acorns and soot sprites. Three palettes, none of them his, all
fired at once and in a full circle, and at four sprite pixels a frame most of
it crossed the window edge within a quarter second and was clipped mid-flight
against a boundary nobody can see. It read as three effects going off together.
The version before this one replaced it with an umbrella at the bus stop, which
is kept at the tag `rain-explosion` if it is ever wanted back.

**Quitting.** The `X` on his left flank, mirroring the layer arrow on his
right at the same height. He has no frame, taskbar button or close box, so
before this the only way out was Task Manager. It closes him mid-timer too;
the button is small and deliberate enough that the risk of a stray hit is
smaller than the cost of being unable to shut a running timer.

It replaced a right-click, which had two problems. It was invisible, so nobody
could discover it. And it was bound to the press rather than the release, so
the window was destroyed before the button came back up and the release landed
on whatever lay beneath -- on the desktop, that opened the desktop's own
context menu every single time he was closed.

The button is absent while it rains rather than merely ignored. A click
anywhere clears the shower, so a button would only be a smaller target for what
the whole widget already does, and an alarm thread and queued frames are both
live. `quit()` refuses in that state as well as going undrawn.

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
left, originally sized to hold him at full tantrum size and now the room the
rain falls through. He is anchored to the window's bottom-right corner, with
his own edges against the window's, which is why the shiver is only ever up and
to the left — there is nowhere else to go. Transparent areas pass clicks
through, so the oversized window does not block the desktop behind it.

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

A beep every half second from the moment the timer ends until the rain stops,
and all of them in **one buffer**, exactly `SHOWER_MS` long.

It began as a thread firing one `PlaySound` per beep against a fixed schedule,
which is the obvious shape and is wrong twice over. Windows opens the audio
device on the first play of a run and can take a good fraction of a second over
it, so the beep you are actually listening for -- the first -- arrives late and
the next one or two land unevenly behind it. And a schedule a thread has to hit
is something a test can only measure against the wall clock, loosely, which is
why this suite's beep section could never run in CI.

One buffer has no first play but its own. The gaps are sample counts rather
than sleeps, so the spacing is exact by construction and `--selftest` reads it
straight off the waveform; the alarm cannot outlast or fall short of the
animation, because they are the same number. A click during the shower ends it
with `PlaySound(None, SND_PURGE)`.

What is left is getting it started on zero rather than after it. The countdown
drives the slice as well as the digits, so it ticks at `TICK_MS` -- 33 ms, not
the 200 ms it used to, which made the slice step visibly round for short
timers -- and the last tick before the end is aimed at the end rather than at
the usual interval. Rendering the buffer and opening the device are paid in
`begin()` instead of `finish()`, the latter by playing a few milliseconds of
silence. Measured across six runs with the deadline landing at different
points between ticks, the alarm now starts 0.7 to 1.7 ms after zero, against
up to 216 ms before.
It is synthesised into a WAV the first time it plays and kept in a temp folder
for the rest of the run. The folder is deleted on
exit. A run that never reaches exit -- Windows shutting down, or Task Manager --
leaves it behind, so each launch that wins the single-copy lock sweeps up any
it finds. Before that, every such run left one more folder in %TEMP%.

The beep is measured off the video that inspired this, by filtering a
recording of it one frequency at a time:

| partial | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| measured | 1.000 | 0.008 | 0.334 | 0.006 | 0.207 | 0.002 | 0.150 |
| a square wave | 1.000 | 0.000 | 0.333 | 0.000 | 0.200 | 0.000 | 0.143 |

That is a square wave at 880 Hz, not a near miss. The envelope peaks about 7 ms
in and is down to a tenth of its peak by 90 ms, and the gap is 500 ms, measured
across six beeps as 490, 495, 503, 500, 502. Steady, not a triple.

It is worth recording that two attempts to improve on this by ear both failed
in the same direction. A plain sine was rejected for sounding like a test tone,
and short pips were pitched up at 1976 Hz on the reasoning that clock buzzers
are high. Both were nearly two octaves above the real thing. One measurement
settled what an argument about timbre could not.

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

**Beeps must not be played one at a time.** Sleeping for the gap drifts,
because starting a sound costs more than it promises and the error
accumulates: measured, 358 ms off by the sixth beep. Aiming each beep at a
fixed schedule fixes the drift and not the rest of it -- Windows opens the
audio device on the first play of a run, so the first beep is heard late and
the next ones unevenly behind it however well the schedule is kept. The alarm
is one buffer with the gaps written into it as silence.

**Animations must carry a sequence number.** Pressing a button mid-finish used
to leave the queued animation frames firing afterwards, parking him off-centre.
Each animation now carries the number it started with and stops if it changes.

**The window padding must be asked for, not recalculated.** The sprite scales
to a whole number of pixels per cell, so the window's width is
`GRID_W * round(SCALE * HEADROOM)`. The transparent padding was originally
worked out by a separate sum -- cells of padding, times SCALE -- and the two
agreed only while `SCALE * HEADROOM` happened to land on a whole number. At the
old value of 1.5 it always did, so the bug sat there invisibly; checked
afterwards, the old sum was short by 4 to 24 pixels at scales 2, 4, 8 and 10,
and merely oversized at 6 and 12. Changing the value to `1.375` made him swell
out through his own window edge. The padding is now taken from
`window_cell()`, the same call the renderer rounds with, so the two cannot
drift apart again. The matching assertion lives in `--selftest` rather than
only in `test_timer.py`, because the latter does not run in CI.

The same sum reappeared later in the code that placed the burst, and was found
the same way: checked across display scales it was out by up to 11 pixels, and
by exactly 0 at scale 8, which is the scale of the machine this was written on.
A sum that is right on the only machine you test on is the worst kind.

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

test_timer.py has 21 sections and feeds clicks at real on-screen coordinates
through the click handler. The
ones worth knowing about: the progress slice must match the clock to within a
twentieth of a degree and must show colour from the first second; the alarm
must start once and never be left playing; the shiver must never carry him
outside his own window and must settle back onto his mark; he must come back
from the rain with nothing left on screen and on the right layer; and skipping
an offered break must not invert the chain.

The beep spacing used to be measured here against the wall clock, loosely,
with one section retrying before it failed because jitter mostly measures how
busy the machine is. It is now a property of one waveform and `--selftest`
reads it off the samples exactly, which is both stricter and runs in CI.

Waiting out an animation has to poll well inside its frame: a loop that polled
every 30 ms against a 45 ms frame serviced about one frame a poll and
stretched a three second shower past the deadline the same loop had set.

## Known limits

- Windows only. The transparency, the layering, the sound and the single-copy
  check are all Win32.
- The finish notification is gone by choice; he comes to the front instead.
- The rain is confined to his window, so it falls in a rectangle rather than
  across the whole screen.
- Changing the taskbar icon needs an unpin and re-pin, because Windows caches
  pinned icons.
