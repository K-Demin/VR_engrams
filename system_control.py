# -*- coding: utf-8 -*-
"""
Created on Mon Feb 16 16:24:35 2026

@author: NeuRLab
"""

# Test
import nidaqmx
from nidaqmx.system import System

system = System.local()
for device in system.devices:
    print(device.name)
    
    
    
## Test air puff
# In NI MAX --> Devices and Interfaces (USB-6001) --> Digital I/O Switch port 0 line 5 to output
# Flick line to high/low to trigger
import nidaqmx
import time

AIRPUFF_LINE = "Dev1/port0/line5"

def deliver_air_puff(trigger_ms=10):
    with nidaqmx.Task() as task:
        task.do_channels.add_do_chan(AIRPUFF_LINE)

        task.write(False)  # ensure low
        time.sleep(0.01)

        task.write(True)   # rising edge
        time.sleep(trigger_ms / 1000)

        task.write(False)  # return low

print("Puff!")
deliver_air_puff()

# Multiple air puffs
for ii in range(1,10):
    deliver_air_puff(10)


## Test audio
import numpy as np
import sounddevice as sd

print(sd.query_devices())


AUDIO_DEVICE = 4        # WASAPI device
SAMPLERATE = 48000      # confirmed working

sd.default.device = AUDIO_DEVICE
sd.default.latency = 'low'

def play_tone(freq=1000, duration_ms=200, volume=0.5, side="both"):
    duration = duration_ms / 1000
    t = np.linspace(0, duration, int(SAMPLERATE * duration), False)
    tone = volume * np.sin(2 * np.pi * freq * t)

    # Create stereo signal
    stereo = np.zeros((len(tone), 2))

    if side == "left":
        stereo[:, 0] = tone
    elif side == "right":
        stereo[:, 1] = tone
    elif side == "both":
        stereo[:, 0] = tone
        stereo[:, 1] = tone

    sd.play(stereo, SAMPLERATE)

print("Playing tone...")
play_tone(1000, 500, volume=0.5, side="right")


# Try together
play_tone(1000, 500)
deliver_air_puff(10)



## Test lick sensor
# NI MAX --> Devices and Interfaces (USB-6001) --> Analog Input ai2
# Edge trigger - Once per beam break
import nidaqmx
import time

THRESHOLD = 1.0
last_state = False  # False = no lick

with nidaqmx.Task() as task:
    task.ai_channels.add_ai_voltage_chan("Dev1/ai2")

    print("Monitoring lick sensor...")

    while True:
        value = task.read()
        current_state = value < THRESHOLD

        # Detect transition from no lick -> lick
        if current_state and not last_state:
            print("LICK DETECTED")

        last_state = current_state
        time.sleep(0.01)


# Continuous monitor - continuous state print
import nidaqmx
import time

THRESHOLD = 1.0

with nidaqmx.Task() as task:
    task.ai_channels.add_ai_voltage_chan("Dev1/ai2")

    print("Monitoring lick sensor... Press Ctrl+C to stop")

    while True:
        value = task.read()
        print(f"{value:.3f}")

        if value < THRESHOLD:
            print("LICK!")

        time.sleep(0.05)
        
        
## Test Reward valve
import nidaqmx
import time

def deliver_reward(duration_ms=40):
    with nidaqmx.Task() as task:
        task.ao_channels.add_ao_voltage_chan("Dev1/ao1")

        task.write(5.0)  # open valve
        #time.sleep(duration_ms / 1000)
        time.sleep(2)
        task.write(0.0)  # close valve

print("Delivering reward...")
deliver_reward(100)

for ii in range(1,20):
    print("delivered")
    deliver_reward()

# Longer valve activation
import nidaqmx
import time

with nidaqmx.Task() as task:
    task.ao_channels.add_ao_voltage_chan("Dev1/ao0")

    print("Setting 0V")
    task.write(0.0)
    time.sleep(2)

    print("Setting 5V")
    task.write(10.0)
    time.sleep(2)

    print("Back to 0V")
    task.write(0.0)


## Test Shock
import nidaqmx
import time

class ShockController:
    def __init__(self, line="Dev1/port0/line0"):
        self.task = nidaqmx.Task()
        self.task.do_channels.add_do_chan(line)
        self.task.write(False)  # ensure low

    def shock(self, duration_ms=50):
        self.task.write(True)
        time.sleep(duration_ms / 1000)
        self.task.write(False)

    def close(self):
        self.task.close()


# Usage
shock = ShockController()

print("Sending 20 ms test trigger")
shock.shock(5)



# Testing lick and reward
import nidaqmx
import time

THRESHOLD = 1.0
last_state = False  # False = no lick

with nidaqmx.Task() as task:
    task.ai_channels.add_ai_voltage_chan("Dev1/ai2")

    print("Monitoring lick sensor...")

    while True:
        value = task.read()
        current_state = value < THRESHOLD

        # Detect transition from no lick -> lick
        if current_state and not last_state:
            print("LICK DETECTED")
            
            time.sleep(1)
            
            deliver_reward()
            print("REWARD DELIVERED")
            
        last_state = current_state
        time.sleep(0.01)



# Test overall controller
class BehaviorController:

    def __init__(self):
        pass

    def tone(self, freq, duration):
        play_tone(freq, duration)

    def air_puff(self):
        deliver_air_puff(10)

    def cs_us_trial(self):
        self.tone(2000, 500)
        time.sleep(0.4)
        self.air_puff()


