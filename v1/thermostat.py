#!/usr/bin/python

import pcf8523
import si705X
import wiringpi2
import atexit
import cPickle as pickle
import json
import codecs
import errno
import fnmatch
import io
import os
import sys
import signal
import pygame
from pygame.locals import *
from subprocess import call  
import time
import datetime
import syslog
import threading
import calendar
from itertools import izip, count
import math

# Globals

DEBUG = True
simulation = 0.0
simulation_period = 180.0
simulation_flux = 10.0
simulation_center = 70.0

iconPath = 'icons'
icons = []
screenMode = "main"
screenModePrior = "none"
fgcolor = (0,0,0)
bgcolor = (0,0,0)
    
display_temp = "72.0"
last_temp_fetch = datetime.datetime.now() - datetime.timedelta(1)
rolling_temp_values = []
current_temp = 72.0

# maxCenterText
lastfont = None
lastfontname = ''
lastfontsize = 16

# silly constants

MODE_HEAT = 1
MODE_OFF = 0
MODE_COOL = 2
MODE_AUTO = 3
MODES = { MODE_OFF: "Off", MODE_HEAT: "Heating", MODE_COOL: "Cooling", MODE_AUTO: "Automatic"}

# persistant config variables

v = {
    "mode-24hour": False,
    "sensor_compensation": 0.0,
    "FontIndex": 0, 
    "leading-zero": False,
    "temperature_in_F": True,
    "number_of_temps_to_avg": 10,
    "minimum_target_temp": 10.0,
    "maximum_target_temp": 110.0,
    "target_temp": 70.0,
    "target_increment": 0.5,
    "heat1_on_hysteresis": 2.5,
    "heat1_off_hysteresis": 1,
    "heat2_on_hysteresis": 2.5,
    "heat2_off_hysteresis": 0.5,
    "heat3_on_hysteresis": 2.5,
    "heat3_off_hysteresis": 0,
    "cool1_on_hysteresis": 2.5,
    "cool1_off_hysteresis": 1,
    "cool2_on_hysteresis": 2.5,
    "cool2_off_hysteresis": 0,
    "minimum_cool1_on_secs": 1,
    "minimum_cool2_on_secs": 1,
    "minimum_cool1_off_secs": 1,
    "minimum_cool2_off_secs": 1,
    "minimum_heat1_on_secs": 1,
    "minimum_heat2_on_secs": 1,
    "minimum_heat3_on_secs": 1,
    "minimum_heat1_off_secs": 1,
    "minimum_heat2_off_secs": 1,
    "minimum_heat3_off_secs": 1,
    "hot_cold_hysteresis": 5.0,
    "switch_heat-off-cool": 0, # MODE_ constants
    "auto_hot_or_cold_mode": 1, # MODE_ constants
    "relays": {
        "W1": { "gpio": 17, "pin": 11, "active": False, "do-not-use": False,
            "last-on": datetime.datetime.now() - datetime.timedelta(1), "last-off": datetime.datetime.now() - datetime.timedelta(1) },
        "W2": { "gpio": 15, "pin": 10, "active": False, "do-not-use": False,
            "last-on": datetime.datetime.now() - datetime.timedelta(1), "last-off": datetime.datetime.now() - datetime.timedelta(1) },
        "W3": { "gpio": 14, "pin":  8, "active": False, "do-not-use": False,
            "last-on": datetime.datetime.now() - datetime.timedelta(1), "last-off": datetime.datetime.now() - datetime.timedelta(1) },
        "G" : { "gpio": 18, "pin": 12, "active": False, "do-not-use": False,
            "last-on": datetime.datetime.now() - datetime.timedelta(1), "last-off": datetime.datetime.now() - datetime.timedelta(1) },
        "Y1": { "gpio": 27, "pin": 13, "active": False, "do-not-use": False,
               "last-on": datetime.datetime.now() - datetime.timedelta(1), "last-off": datetime.datetime.now() - datetime.timedelta(1) },
        "Y2": { "gpio": 22, "pin": 15, "active": False, "do-not-use": False,
               "last-on": datetime.datetime.now() - datetime.timedelta(1), "last-off": datetime.datetime.now() - datetime.timedelta(1) }
    }
}

class Icon:
    def __init__(self, name):
      self.name = name
      try:
        self.bitmap = pygame.image.load(iconPath + '/' + name + '.png')
      except:
        pass

class Button:
    def __init__(self, rect, **kwargs):
        self.rect     = rect # Bounds
        self.color    = None # Background fill color, if any
        self.iconBg   = None # Background Icon (atop color fill)
        self.iconFg   = None # Foreground Icon (atop background)
        self.bg       = None # Background Icon name
        self.fg       = None # Foreground Icon name
        self.callback = None # Callback function
        self.value    = None # Value passed to callback
        for key, value in kwargs.iteritems():
            if   key == 'color': self.color    = value
            elif key == 'bg'   : self.bg       = value
            elif key == 'fg'   : self.fg       = value
            elif key == 'cb'   : self.callback = value
            elif key == 'value': self.value    = value

    def selected(self, pos):
        x1 = self.rect[0]
        y1 = self.rect[1]
        x2 = x1 + self.rect[2] - 1
        y2 = y1 + self.rect[3] - 1
        if ((pos[0] >= x1) and (pos[0] <= x2) and (pos[1] >= y1) and (pos[1] <= y2)):
            if self.callback:
                if self.value is None:
                    self.callback(self)
                else:
                    self.callback(self, self.value)
            return True
        return False

    def draw(self, screen):
        if self.bg is not None:
            for i in icons:      #   For each icon...
                if self.bg == i.name: #    Compare names; match?
                    self.iconBg = i     #     Assign Icon to Button
                    self.bg     = None  #     Name no longer used; allow garbage collection
                    break
        if self.fg is not None:
            for i in icons:      #   For each icon...
                if self.fg == i.name:
                    self.iconFg = i
                    self.fg     = None
                    break
        if self.color:
            screen.fill(self.color, self.rect)
        if self.iconBg:
            screen.blit(self.iconBg.bitmap,
                (self.rect[0]+(self.rect[2]-self.iconBg.bitmap.get_width())/2,
                self.rect[1]+(self.rect[3]-self.iconBg.bitmap.get_height())/2))
        if self.iconFg:
            screen.blit(self.iconFg.bitmap,
                (self.rect[0]+(self.rect[2]-self.iconFg.bitmap.get_width())/2,
                self.rect[1]+(self.rect[3]-self.iconFg.bitmap.get_height())/2))

    def setBg(self, name):
        if name is None:
            self.iconBg = None
        else:
            for i in icons:
                if name == i.name:
                    self.iconBg = i
                    break

class Panel:
    
    buttons = []
    
    def __init__(self, name, isstatic, draw_func, buttons):
        self.name = name
        self.isstatic = isstatic
        self.draw_func = draw_func
        self.buttons = buttons

    def draw(self, screen):
        # Overlay buttons on display and update
        for i,b in enumerate(self.buttons):
            b.draw(screen)
        if self.draw_func:
            self.draw_func(self)

###############################################################################################################

def screen_main_cb(button, n):
    global screenMode
    global v
    
    if n == 2: # up
        v['target_temp'] = v.get('target_temp', 72.0) + v.get('target_increment', 0.5)
        if v['target_temp'] > v.get("maximum_target_temp", 110.0):
            v['target_temp'] = v.get("minimum_target_temp", 110.0)
    elif n == 3:
        v['target_temp'] = v.get('target_temp', 72.0) - v.get('target_increment', 0.5)
        if v['target_temp'] < v.get("minimum_target_temp", 0.0):
            v['target_temp'] = v.get("minimum_target_temp", 0.0)

def screen_sysfunc_cb(button, n): # normal display
    global screenMode
    global v

    #v['switch_heat-off-cool'] = n
    if n == MODE_OFF:
        v['switch_heat-off-cool'] = MODE_OFF
    elif n == MODE_HEAT:
        v['switch_heat-off-cool'] = MODE_HEAT
    elif n == MODE_COOL:
        v['switch_heat-off-cool'] = MODE_COOL
    elif n == MODE_AUTO:
        v['auto_hot_or_cold_mode'] = MODE_HEAT
        if v['switch_heat-off-cool'] == MODE_COOL:
            v['auto_hot_or_cold_mode'] = MODE_COOL
        v['switch_heat-off-cool'] = MODE_AUTO
        
def screen_fb_cb(button, n):
    global screenMode

    if n == 1:
        screenMode = "main"
    elif n == 2:
        screenMode = "system-function"
    elif n == 3:
        screenMode = "empty"    

def screen_empty_cb(button, n): # normal display
    global screenMode
    global v

def screen_main_draw(panel): # normal display
    global screenMode
    global v
    
    when = datetime.datetime.now()

    z = "{0:3.1f}".format(v.get('target_temp', 72.0))
    v['fontsize_main_0'] = centerMaxText(screen, z, fgcolor, (50, 20, 160, 120), allfonts[v['FontIndex']], v.get('fontsize_main_0', 82))
    z = "currently {0} {1}".format(get_display_temp(when), "F" if v.get('temperature_in_F', True) else "C")
    v['fontsize_main_1'] = centerMaxText(screen, z, fgcolor, (50, 145, 160, 35), allfonts[v['FontIndex']], v.get('fontsize_main_1', 28))
    z = "System is {0}".format(MODES[v.get("switch_heat-off-cool", MODE_OFF)])
    v['fontsize_main_2'] = centerMaxText(screen, z, fgcolor, (70, 180, 180, 30), allfonts[v['FontIndex']], v.get('fontsize_main_2', 14))

    z = 0
    ic = "blank30x30"
    if v.get("switch_heat-off-cool", MODE_OFF) == MODE_HEAT \
            or (v.get("switch_heat-off-cool", MODE_OFF) == MODE_AUTO and v.get("auto_hot_or_cold_mode", MODE_HEAT) == MODE_HEAT):
        ic = "blueflame30x30"
        z += 1 if v["relays"]["W1"]["active"] else 0
        z += 1 if v["relays"]["W2"]["active"] else 0
        z += 1 if v["relays"]["W3"]["active"] else 0
    elif v.get("switch_heat-off-cool", MODE_OFF) == MODE_COOL \
            or (v.get("switch_heat-off-cool", MODE_OFF) == MODE_AUTO and v.get("auto_hot_or_cold_mode", MODE_HEAT) == MODE_COOL):
        ic = "snowflake30x30"
        z += 1 if v["relays"]["Y1"]["active"] else 0
        z += 1 if v["relays"]["Y2"]["active"] else 0
    for b in panel.buttons:
        if b.iconBg and b.iconBg.name.endswith('30x30'):
            if z >= b.value:
                b.bg = ic
            else:
                b.bg = "blank30x30"

def screen_sysfunc_draw(panel):
    global screenMode
    global v
    
    z = "auto"
    v['fontsize_sysfunc_0'] = centerMaxText(screen, z, fgcolor, (65, 0, 90, 60), allfonts[v['FontIndex']], v.get('fontsize_sysfunc_0', 28))
    z = "off"
    v['fontsize_sysfunc_0'] = centerMaxText(screen, z, fgcolor, (65, 65, 90, 60), allfonts[v['FontIndex']], v.get('fontsize_sysfunc_0', 28))
    z = "heat"
    v['fontsize_sysfunc_0'] = centerMaxText(screen, z, fgcolor, (225, 0, 90, 60), allfonts[v['FontIndex']], v.get('fontsize_sysfunc_0', 28))
    z = "cool"
    v['fontsize_sysfunc_0'] = centerMaxText(screen, z, fgcolor, (225, 65, 90, 60), allfonts[v['FontIndex']], v.get('fontsize_sysfunc_0', 28))
    
    for b in panel.buttons:
        if b.iconBg and b.iconBg.name.endswith('selected'):
            if b.value == v.get("switch_heat-off-cool", MODE_OFF):
                b.bg = 'selected'
            else:
                b.bg = 'unselected'

def screen_clock_draw(panel): # normal display
    global screenMode
    global v
    
    fontsugsz0 = 12
    
    z = get_display_time(datetime.datetime.now())
    try:
        fontsugsz0 = centerMaxText(screen, z, fgcolor, (20, 30, 280, 160), allfonts[v['FontIndex']], fontsugsz0)
    except IndexError:
        v['FontIndex'] = 1
        fontsugsz0 = centerMaxText(screen, z, fgcolor, (20, 30, 280, 160), allfonts[0], fontsugsz0)

###############################################################################################################

panels = {
    "main": Panel("main", False, screen_main_draw, 
        [Button((0,  0, 320, 240), bg='box', color=(0,0,0), cb=screen_main_cb, value=1),
        Button((50, 20, 160, 120), color=(20,20,20)),
        Button((230, 20, 60, 60), bg='up', cb=screen_main_cb, value=2),
        Button((230, 90, 60, 60), bg='down', cb=screen_main_cb, value=3),
        Button((65, 210, 30, 30), bg='blank30x30', value=1),
        Button((95, 210, 30, 30), bg='blank30x30', value=2),
        Button((0, 180, 60, 60), bg='left', cb=screen_fb_cb, value=3),
        Button((260, 180, 60, 60), bg='right', cb=screen_fb_cb, value=2)]),
    "system-function": Panel("system-function", False, screen_sysfunc_draw, 
        [Button((0,  0, 320, 240), bg='box', color=(80,0,80)),
        Button((0, 0, 60, 60), bg='unselected', cb=screen_sysfunc_cb, value=3),
        Button((0, 70, 60, 60), bg='unselected', cb=screen_sysfunc_cb, value=0),
        Button((160, 0, 60, 60), bg='unselected', cb=screen_sysfunc_cb, value=1),
        Button((160, 70, 60, 60), bg='unselected', cb=screen_sysfunc_cb, value=2),
        Button((0, 180, 60, 60), bg='left', cb=screen_fb_cb, value=1),
        Button((90, 180, 140, 60), bg='ok', cb=screen_fb_cb, value=1),
        Button((260, 180, 60, 60), bg='right', cb=screen_fb_cb, value=3)]),
    "empty": Panel("empty", False, None, 
        [Button((0,  0, 320, 240), bg='box', color=(0,0,0), cb=screen_empty_cb, value=1),
        Button((0, 180, 60, 60), bg='left', cb=screen_fb_cb, value=2),
        Button((90, 180, 140, 60), bg='ok', cb=screen_fb_cb, value=1),
        Button((260, 180, 60, 60), bg='right', cb=screen_fb_cb, value=1)]),
}

###############################################################################################################
# Assorted utility functions -----------------------------------------------
###############################################################################################################

def log_info(msg):
    syslog.syslog(syslog.LOG_INFO, msg)
    if DEBUG: print msg

def log_error(msg):
    syslog.syslog(syslog.LOG_ERR, msg)
    if DEBUG: print msg

def killitwithfire(n, stack):
    write_persistent_vars()
    if n == signal.SIGINT:    
        log_info("SIGNAL: Program halted with ^C")
    elif n == signal.SIGTERM:
        log_info("SIGNAL: Program Terminated")
    elif n == signal.SIGQUIT:
        log_info("SIGNAL: Program Quit")
    sys.exit(0)
    
def handle_sighup(n, stack):
    log_info("Reading persistent configuration variables")
    read_persistent_vars()

def write_persistent_vars():
    global v

    with open('/etc/{0}.conf'.format(os.path.splitext(os.path.basename(__file__))[0]), 'w') as output:
        json.dump(v, output, indent=3, default=outputJSON)
        output.flush()
        output.close()

def read_persistent_vars():
    global v
    global config_last_read
    
    try:
        with codecs.open('/etc/{0}.conf'.format(os.path.splitext(os.path.basename(__file__))[0]), 'r', encoding='utf-8') as duhput:
            v = json.load(duhput, object_hook=inputJSON)
    except IOError:
        write_persistent_vars()
    config_last_read = datetime.datetime.now()

def outputJSON(obj):
    """Default JSON serializer."""

    if isinstance(obj, datetime.datetime):
        if obj.utcoffset() is not None:
            obj = obj - obj.utcoffset()

        return obj.strftime('%Y-%m-%d %H:%M:%S.%f')
    return str(obj)

def inputJSON(obj):
    newDic = {}

    for key in obj:
        try:
            if float(key) == int(float(key)):
                newKey = int(key)
            else:
                newKey = float(key)

            newDic[newKey] = obj[key]
            continue
        except ValueError:
            pass

        try:
            newDic[str(key)] = datetime.datetime.strptime(obj[key], '%Y-%m-%d %H:%M:%S.%f')
            continue
        except TypeError:
            pass

        newDic[str(key)] = obj[key]

    return newDic

def get_display_temp(when):
    global v
    global display_temp
    global last_temp_fetch
    global simulation
    global current_temp
    
    if (when - last_temp_fetch) > datetime.timedelta(0, 1):
        if simulation >= 0.0:
            simulation += (360.0 / simulation_period)
            if simulation >= 360.0:
                simulation -= 360.0
            current_temp = simulation_center + simulation_flux * math.sin(math.radians(simulation)) # - v.get("sensor_compensation", 0.0)
        else:
            if v.get('temperature_in_F', True): # Fahrenheit
                current_temp = si705X.get_tempF()
            else: # Centigrade
                current_temp = si705X.get_tempC()
            
        rolling_temp_values.append({'temp': current_temp, 'when': when})
        last_temp_fetch = when
        while len(rolling_temp_values) > v.get('number_of_temps_to_avg', 60):
            del rolling_temp_values[0]
        #log_info("Sampled: {0:3.3f} ({1})".format(current_temp, len(rolling_temp_values)))

        i = 0
        z = 0
        for tv in rolling_temp_values:
            z += tv["temp"]
            i += 1
            
        display_temp = "{0:3.1f}".format((z/i) + v.get("sensor_compensation", 0.0))
        
    return display_temp

def get_display_time(when):
    global v

    hour = when.hour
    if not v.get('mode-24hour', False): # 12-hour AM/PM mode
        hour = hour if hour <= 12 else hour - 12
        hour = hour if hour > 0 else 12
        if v.get('leading-zero', False): # leading zero?
            z = "{0:02}:{1:02}".format(hour, when.minute)
        else:
            z = "{0}:{1:02}".format(hour, when.minute)
    else: # 24-hour mode
        z = "{0:02}:{1:02}".format(hour, when.minute)
    return z

def centerMaxText(surface, text, color, rectTP, fontname, fontsizesuggestion, coast=True, aa=True, bkg=None):
    global lastfont
    global lastfontname
    global lastfontsize

    rect = Rect(rectTP)
    fontsize = fontsizesuggestion
    if fontname == lastfontname and fontsize == lastfontsize:
        font = lastfont
    else:
        # this operation costs file I/O
        font = pygame.font.SysFont(fontname, fontsize)
        
        # determine minimum
        while font.size(text)[1] < rect.height or font.size(text)[0] < rect.width:
            fontsize += 2
            font = pygame.font.SysFont(fontname, fontsize)
            if not coast: break
        
        # determine maximum
        while font.size(text)[1] >= rect.height or font.size(text)[0] >= rect.width:
            fontsize -= 2
            font = pygame.font.SysFont(fontname, fontsize)
            if not coast: break
        
        lastfontname = fontname  
        lastfontsize = fontsize
        lastfont = font

    # render the line and blit it to the surface
    if bkg:
        image = font.render(text, 1, color, bkg)
        image.set_colorkey(bkg)
    else:
        image = font.render(text, aa, color)

    #surface.blit(image, (rect.left, rect.top))
    surface.blit(image,
      (rect.left + (rect.width - image.get_width() ) / 2,
       rect.top + (rect.height - image.get_height()) / 2))

    return fontsize

def act_on_temp(when):
    global v
    global current_temp
    global gpio
    
    comparable_temp = current_temp + v.get("sensor_compensation", 0.0)
    #log_info("target: {0:3.1f}, temp: {1:3.1f}, diff: {2:3.1f}".format(v['target_temp'], comparable_temp, comparable_temp - v['target_temp']))
    
    # is the environment lower/colder than our target?
    if comparable_temp < v.get('target_temp', 72.0):
        #log_info("It is colder than we want it to be")
        # are any cool stages on?
        if (v["relays"]["Y1"]["active"] or v["relays"]["Y2"]["active"]):
            #log_info("We should turn off the cool!")
            # Has it been on long enough?
            if v["relays"]["Y2"]["active"] \
                    and (when - v["relays"]["Y2"]["last-on"]) > datetime.timedelta(0, v.get("minimum_cool2_on_secs", 240)) \
                    and (v['target_temp'] - comparable_temp) > v.get('cool2_off_hysteresis', 2.5):
                log_info("It's cold (target: {0:3.1f}, now: {1:3.1f}) and stage 2 cooling is on, so turning it off".format(v['target_temp'], comparable_temp))
                gpio.digitalWrite(v["relays"]["Y2"]["gpio"], 0)
                v["relays"]["Y2"]["last-off"] = when
                v["relays"]["Y2"]["active"] = False
            if v["relays"]["Y1"]["active"] \
                    and (when - v["relays"]["Y1"]["last-on"]) > datetime.timedelta(0, v.get("minimum_cool1_on_secs", 240)) \
                    and (v['target_temp'] - comparable_temp) > (v.get('cool1_off_hysteresis', 2.5) + v.get('cool2_off_hysteresis', 2.5)):
                log_info("it's cold (target: {0:3.1f}, now: {1:3.1f}) and stage 1 cooling is on, so turning it off".format(v['target_temp'], comparable_temp))
                gpio.digitalWrite(v["relays"]["Y1"]["gpio"], 0)
                v["relays"]["Y1"]["last-off"] = when
                v["relays"]["Y1"]["active"] = False
        # adjust automatic
        if v.get("auto_hot_or_cold_mode", MODE_HEAT) == MODE_COOL and v.get("switch_heat-off-cool", MODE_OFF) == MODE_AUTO \
                and (v.get('target_temp', 72.0) - comparable_temp) > v.get("hot_cold_hysteresis", 5.0):
            log_info("it's cold (target: {0:3.1f}, now: {1:3.1f}), switching to heat (automatic) mode".format(v['target_temp'], comparable_temp))
            v["auto_hot_or_cold_mode"] = MODE_HEAT
        # are any heat stages off?
        if (v.get("switch_heat-off-cool", MODE_OFF) == MODE_HEAT \
                or (v.get("switch_heat-off-cool", MODE_OFF) == MODE_AUTO and v.get("auto_hot_or_cold_mode", MODE_HEAT) == MODE_HEAT)) \
                and ((not v["relays"]["W1"]["active"] and not v["relays"]["W1"]["do-not-use"]) \
                or (not v["relays"]["W2"]["active"] and not v["relays"]["W2"]["do-not-use"]) \
                or (not v["relays"]["W3"]["active"] and not v["relays"]["W3"]["do-not-use"])):
            #log_info("We should turn on the heat!")
            # Has it been off long enough?
            if not v["relays"]["W1"]["active"] \
                    and not v["relays"]["W1"]["do-not-use"] \
                    and (when - v["relays"]["W1"]["last-off"]) > datetime.timedelta(0, v.get("minimum_heat1_off_secs", 120)) \
                    and not v["relays"]["Y1"]["active"] \
                    and (when - v["relays"]["Y1"]["last-off"]) > datetime.timedelta(0, v.get("minimum_cool1_off_secs", 120)) \
                    and not v["relays"]["Y2"]["active"] \
                    and (when - v["relays"]["Y2"]["last-off"]) > datetime.timedelta(0, v.get("minimum_cool2_off_secs", 120)) \
                    and (v['target_temp'] - comparable_temp) > v.get('heat1_on_hysteresis', 2.5):
                log_info("it's cold (target: {0:3.1f}, now: {1:3.1f}) and stage 1 heating is off, so turning it on".format(v['target_temp'], comparable_temp))
                v["relays"]["W1"]["active"] = True
                v["relays"]["W1"]["last-on"] = when
                gpio.digitalWrite(v["relays"]["W1"]["gpio"], 1)
            if not v["relays"]["W2"]["active"] \
                    and not v["relays"]["W2"]["do-not-use"] \
                    and (when - v["relays"]["W2"]["last-off"]) > datetime.timedelta(0, v.get("minimum_heat2_off_secs", 120)) \
                    and not v["relays"]["Y1"]["active"] \
                    and (when - v["relays"]["Y1"]["last-off"]) > datetime.timedelta(0, v.get("minimum_cool1_off_secs", 120)) \
                    and not v["relays"]["Y2"]["active"] \
                    and (when - v["relays"]["Y2"]["last-off"]) > datetime.timedelta(0, v.get("minimum_cool2_off_secs", 120)) \
                    and (v['target_temp'] - comparable_temp) > (v.get('heat2_on_hysteresis', 2.5) + v.get('heat1_on_hysteresis', 2.5)):
                log_info("it's cold (target: {0:3.1f}, now: {1:3.1f}) and stage 2 heating is off, so turning it on".format(v['target_temp'], comparable_temp))
                v["relays"]["W2"]["active"] = True
                v["relays"]["W2"]["last-on"] = when
                gpio.digitalWrite(v["relays"]["W2"]["gpio"], 1)
            if not v["relays"]["W3"]["active"] \
                    and not v["relays"]["W3"]["do-not-use"] \
                    and (when - v["relays"]["W3"]["last-off"]) > datetime.timedelta(0, v.get("minimum_heat3_off_secs", 120)) \
                    and not v["relays"]["Y1"]["active"] \
                    and (when - v["relays"]["Y1"]["last-off"]) > datetime.timedelta(0, v.get("minimum_cool1_off_secs", 120)) \
                    and not v["relays"]["Y2"]["active"] \
                    and (when - v["relays"]["Y2"]["last-off"]) > datetime.timedelta(0, v.get("minimum_cool2_off_secs", 120)) \
                    and (v['target_temp'] - comparable_temp) > (v.get('heat3_on_hysteresis', 2.5) + v.get('heat2_on_hysteresis', 2.5) + v.get('heat1_on_hysteresis', 2.5)):
                log_info("it's cold (target: {0:3.1f}, now: {1:3.1f}) and stage 3 heating is off, so turning it on".format(v['target_temp'], comparable_temp))
                v["relays"]["W3"]["active"] = True
                v["relays"]["W3"]["last-on"] = when
                gpio.digitalWrite(v["relays"]["W3"]["gpio"], 1)
    # is the environment lower/colder than our target?
    elif comparable_temp > v.get('target_temp', 72.0):
        #log_info("It is warmer than we want it to be")
        # are any heat stages on?
        if (v["relays"]["W1"]["active"] or v["relays"]["W2"]["active"] or v["relays"]["W3"]["active"]):
            #log_info("We should turn off the heat!")
            # Has it been on long enough?
            if v["relays"]["W3"]["active"] \
                    and (when - v["relays"]["W3"]["last-on"]) > datetime.timedelta(0, v.get("minimum_heat3_on_secs", 240)) \
                    and (comparable_temp - v['target_temp']) > v.get('heat3_off_hysteresis', 2.5):
                log_info("It's hot (target: {0:3.1f}, now: {1:3.1f}) and stage 3 heating is on, so turning it off".format(v['target_temp'], comparable_temp))
                gpio.digitalWrite(v["relays"]["W3"]["gpio"], 0)
                v["relays"]["W3"]["last-off"] = when
                v["relays"]["W3"]["active"] = False
            if v["relays"]["W2"]["active"] \
                    and (when - v["relays"]["W2"]["last-on"]) > datetime.timedelta(0, v.get("minimum_heat2_on_secs", 240)) \
                    and (comparable_temp - v['target_temp']) > (v.get('heat2_off_hysteresis', 2.5) + v.get('heat3_off_hysteresis', 2.5)):
                log_info("It's hot (target: {0:3.1f}, now: {1:3.1f}) and stage 2 heating is on, so turning it off".format(v['target_temp'], comparable_temp))
                gpio.digitalWrite(v["relays"]["W2"]["gpio"], 0)
                v["relays"]["W2"]["last-off"] = when
                v["relays"]["W2"]["active"] = False
            if v["relays"]["W1"]["active"] \
                    and (when - v["relays"]["W1"]["last-on"]) > datetime.timedelta(0, v.get("minimum_heat1_on_secs", 240)) \
                    and (comparable_temp - v['target_temp']) > (v.get('heat1_off_hysteresis', 2.5) + v.get('heat2_off_hysteresis', 2.5) + v.get('heat3_off_hysteresis', 2.5)):
                log_info("it's hot (target: {0:3.1f}, now: {1:3.1f}) and stage 1 heating is on, so turning it off".format(v['target_temp'], comparable_temp))
                gpio.digitalWrite(v["relays"]["W1"]["gpio"], 0)
                v["relays"]["W1"]["last-off"] = when
                v["relays"]["W1"]["active"] = False
        # adjust automatic
        if v.get("auto_hot_or_cold_mode", MODE_HEAT) == MODE_HEAT and v.get("switch_heat-off-cool", MODE_OFF) == MODE_AUTO \
                and (comparable_temp - v.get('target_temp', 72.0)) > v.get("hot_cold_hysteresis", 5.0):
            log_info("it's hot (target: {0:3.1f}, now: {1:3.1f}), switching to cool (automatic) mode".format(v['target_temp'], comparable_temp))
            v["auto_hot_or_cold_mode"] = MODE_COOL
        # are any cool stages off?
        if (v.get("switch_heat-off-cool", MODE_OFF) == MODE_COOL \
                or (v.get("switch_heat-off-cool", MODE_OFF) == MODE_AUTO and v.get("auto_hot_or_cold_mode", MODE_HEAT) == MODE_COOL)) \
                and (((not v["relays"]["Y1"]["active"]) and (not v["relays"]["Y1"]["do-not-use"])) \
                or ((not v["relays"]["Y2"]["active"]) and (not v["relays"]["Y2"]["do-not-use"]))):
            #log_info("We should turn on the cool!")
            # Has it been off long enough?
            if not v["relays"]["Y1"]["active"] \
                    and not v["relays"]["Y1"]["do-not-use"] \
                    and (when - v["relays"]["Y1"]["last-off"]) > datetime.timedelta(0, v.get("minimum_cool1_off_secs", 120)) \
                    and not v["relays"]["W1"]["active"] \
                    and (when - v["relays"]["W1"]["last-off"]) > datetime.timedelta(0, v.get("minimum_heat1_off_secs", 120)) \
                    and not v["relays"]["W2"]["active"] \
                    and (when - v["relays"]["W2"]["last-off"]) > datetime.timedelta(0, v.get("minimum_heat2_off_secs", 120)) \
                    and not v["relays"]["W3"]["active"] \
                    and (when - v["relays"]["W3"]["last-off"]) > datetime.timedelta(0, v.get("minimum_heat3_off_secs", 120)) \
                    and (comparable_temp - v['target_temp']) > v.get('cool1_on_hysteresis', 2.5):
                log_info("it's hot (target: {0:3.1f}, now: {1:3.1f}) and stage 1 cooling is off, so turning it on".format(v['target_temp'], comparable_temp))
                v["relays"]["Y1"]["active"] = True
                v["relays"]["Y1"]["last-on"] = when
                gpio.digitalWrite(v["relays"]["Y1"]["gpio"], 1)
            if not v["relays"]["Y2"]["active"] \
                    and not v["relays"]["Y2"]["do-not-use"] \
                    and (when - v["relays"]["Y2"]["last-off"]) > datetime.timedelta(0, v.get("minimum_cool2_off_secs", 120)) \
                    and not v["relays"]["W1"]["active"] \
                    and (when - v["relays"]["W1"]["last-off"]) > datetime.timedelta(0, v.get("minimum_heat1_off_secs", 120)) \
                    and not v["relays"]["W2"]["active"] \
                    and (when - v["relays"]["W2"]["last-off"]) > datetime.timedelta(0, v.get("minimum_heat2_off_secs", 120)) \
                    and not v["relays"]["W3"]["active"] \
                    and (when - v["relays"]["W3"]["last-off"]) > datetime.timedelta(0, v.get("minimum_heat3_off_secs", 120)) \
                    and (comparable_temp - v['target_temp']) > (v.get('cool2_on_hysteresis', 2.5) + v.get('cool1_on_hysteresis', 2.5)):
                log_info("it's hot (target: {0:3.1f}, now: {1:3.1f}) and stage 2 cooling is off, so turning it on".format(v['target_temp'], comparable_temp))
                v["relays"]["Y2"]["active"] = True
                v["relays"]["Y2"]["last-on"] = when
                gpio.digitalWrite(v["relays"]["Y2"]["gpio"], 1)
    
###############################################################################################################
###############################################################################################################
###############################################################################################################
###############################################################################################################

if __name__ == '__main__':

    log_info("Hello, I am a computer.  Whir, click, beep!")

    # handle PID file
    pid = str(os.getpid())
    pidfile = os.path.join("/var", "run", os.path.splitext(os.path.basename(__file__))[0]+".pid")
    
    log_error("PID file: %s" % pidfile)
    if os.path.isfile(pidfile):
        log_error("%s already exists, exiting" % pidfile)
        sys.exit(2)

    with file(pidfile, "w") as pidf:
        pidf.write(pid)
        pidf.flush()
        pidf.close()
    
    # Initialization -----------------------------------------------------------
    log_info("Initializing...")
    read_persistent_vars()
    
    if not v["relays"]:
        log_error("Relays not defined")
        try:
            os.unlink(pidfile)
        except:
            pass
        exit(-1)

    # Init framebuffer/touchscreen environment variables
    os.putenv('SDL_VIDEODRIVER', 'fbcon')
    os.putenv('SDL_FBDEV'      , '/dev/fb1')
    os.putenv('SDL_MOUSEDRV'   , 'TSLIB')
    os.putenv('SDL_MOUSEDEV'   , '/dev/input/touchscreen')
    
    # Init pygame and screen
    pygame.init()
    log_info("Setting Mouse invisible...")
    pygame.mouse.set_visible(False)
    log_info("Setting fullscreen...")
    modes = pygame.display.list_modes(16, pygame.FULLSCREEN)
    screen = pygame.display.set_mode(modes[0], pygame.FULLSCREEN, 16)

    log_info("Loading Fonts...")
    allfonts = pygame.font.get_fonts()
    
    log_info("Loading Icons...")

    # Load all icons at startup.
    for file in os.listdir(iconPath):
        if fnmatch.fnmatch(file, '*.png'):
            icons.append(Icon(file.split('.')[0]))

    # Assign Icons to Buttons, now that they're loaded
    log_info("Assigning Buttons")
    for p in panels.values():
        for b in p.buttons:
            for i in icons:
                if b.bg == i.name:
                    b.iconBg = i # Assign Icon to Button
                    b.bg = None # Name no longer used; allow garbage collection
                if b.fg == i.name:
                    b.iconFg = i
                    b.fg = None # Name no longer used; allow garbage collection
    
    # Set up GPIO pins
    log_info("Initializing GPIO pins...")
    when = datetime.datetime.now()
    gpio = wiringpi2.GPIO(wiringpi2.GPIO.WPI_MODE_GPIO)
    for name,relay in v["relays"].iteritems():
        gpio.pinMode(relay.get('gpio'), gpio.OUTPUT)
        gpio.pullUpDnControl(relay.get('gpio'), gpio.PUD_OFF)
        gpio.digitalWrite(relay.get('gpio'), relay.get("active"))
        if relay.get("active"):
            relay["last-on"] = when
        else:
            relay["last-off"] = when
        log_info("Relay {0} set to {1}".format(name, relay.get("active")))

    log_info("Initializing temperature sensor...")
    si705X.startup(1, 0x40)
    si705X.reset()
    si705X.set_reg1(0x7E) # 14-bit

    log_info("loading background")
    try:
        img = pygame.image.load("icons/bg.png")
    except:
        img = None
    
    if img is None or img.get_height() < 240: # Letterbox, clear background
        screen.fill(0)
    if img:
        screen.blit(img, ((320 - img.get_width() ) / 2, (240 - img.get_height()) / 2))
    pygame.display.flip()
    
    calendar.setfirstweekday(calendar.SUNDAY)

    signal.signal(signal.SIGINT, killitwithfire)
    signal.signal(signal.SIGQUIT, killitwithfire)
    signal.signal(signal.SIGTERM, killitwithfire)
    signal.signal(signal.SIGHUP, handle_sighup)

###############################################################################################################
# Main loop ------------------------------------------------------------------
###############################################################################################################
    
    go = True
    log_info("Main loop...")
    try:
        # process current screen
        while go:
            # Process touchscreen input
            while go:
                when = datetime.datetime.now()
                act_on_temp(when)
                for event in pygame.event.get():
                    if (event.type is MOUSEBUTTONDOWN):
                        pos = pygame.mouse.get_pos()
                        for i,b in izip(count(len(panels[screenMode].buttons) - 1, -1), reversed(panels[screenMode].buttons)):
                            #for b in panels[screenMode].buttons:
                            if b.selected(pos):
                                break
                    elif (event.type is MOUSEBUTTONUP):
                        pass
                if not panels[screenMode].isstatic or screenMode != screenModePrior:
                    break
                time.sleep(0.01)
            
            fgcolor = (255,255,255)
            bgcolor = (0,0,0)
            screen.fill(bgcolor)

###############################################################################################################

            panels[screenMode].draw(screen)

###############################################################################################################

            pygame.display.flip()
            time.sleep(0.01)
        
            screenModePrior = screenMode

###############################################################################################################

    except SystemExit:
        log_info("System Exiting")
        go = False
    #except:
    #    log_error("Unexpected system error: {0}".format(sys.exc_info()[0]))
    #    go = False
    finally:
        pygame.quit()
        
        try:
            os.unlink(pidfile)
        except:
            pass
        go = False
        log_info("601.")
