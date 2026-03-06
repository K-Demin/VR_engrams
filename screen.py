from psychopy import visual, event, core
import numpy as np

# === CONFIGURATION ===
trial_type = 'grating'  #  'grating' or 'dots'
frame_rate = 60
pixels_per_deg = 30  # Roughly 30 px = 1 deg (adjust for your screen)
desired_speed_deg_per_sec = 20
pixels_per_frame = desired_speed_deg_per_sec * pixels_per_deg / frame_rate / 20  # ≈10 px/frame

# === WINDOW ===
win = visual.Window(
    size=[1920, 1080],
    fullscr=True,
    units='pix',
    screen=0,
    allowGUI=False,
    color=[-1, -1, -1]
)

screen_size = win.size

# === DRIFTING DOT STIMULUS ===
dot_stim = visual.DotStim(
    win=win,
    fieldSize=screen_size[0],
    nDots=100,
    dotSize=100,
    speed=pixels_per_frame,               # Reasonable speed
    dir=0,                   # Ignored when coherence = 0
    coherence=0.0,           # <<<<< THIS = RANDOM DIRECTION
    signalDots='same',
    dotLife=1000,
    fieldShape='rectangle',
    color=1.0,
    colorSpace='rgb',
    units='pix'
)


# === DRIFTING GRATING STIMULUS ===
spatial_freq_cyc_per_deg = 0.2                     # 1 cycle every 20 deg
spatial_freq_cyc_per_px = spatial_freq_cyc_per_deg / pixels_per_deg  # ≈0.0017 cycles/px

grating_stim = visual.GratingStim(
    win=win,
    size=screen_size,
    sf=spatial_freq_cyc_per_px,
    ori=0,                  # 0° = horizontal stripes, drift left–right
    tex='sin',              # 'sqr' for square wave
    contrast=0.5,
    mask=None,
    units='pix'
)

# === FRAME LOOP ===
phase = 0
clock = core.Clock()
while not event.getKeys(['escape']):
    if trial_type == 'dots':
        dot_stim.draw()
    elif trial_type == 'grating':
        # Advance grating phase to simulate motion
        phase += spatial_freq_cyc_per_px * pixels_per_frame * 10
        grating_stim.phase = phase
        grating_stim.draw()

    win.flip()

win.close()
