#!/usr/bin/env python

__author__ = "Bernd Gewehr"

# import python libraries
import logging
import os
import signal
import sys
import time
import random
import numpy as np

# import RPiMower libraries
import lib_l298n as move

# import RPiMower actions
import act_uln2003 as VSS
import act_esc as ESC

# import RPiMower libraries
import lib_mqtt as MQTT

# Initialize variables
APPNAME = os.path.splitext(os.path.basename(__file__))[0]
LOGFILE = os.getenv('LOGFILE', APPNAME + '.log')

DEBUG = False

MQTT_TOPIC_IN = "/RPiMower/#"
MQTT_QOS = 0

STOP = "/RPiMower/stop"
START = "/RPiMower/start"
TURN = "/RPiMower/turn"
HOME = "/RPiMower/return"

Stop = False

MIN_DISTANCE = 20

WORLD = ["FrontUS",0,"BackUS",0,"GroundColour",0, "Compass",0, "Pitch",0, "Roll",0, "map",[], "UserCMD","","Running",0]
W_FRONT_SONAR = 1
W_BACK_SONAR = 3
W_GROUND_COLOUR = 5
W_COMPASS = 7
W_PITCH = 9
W_ROLL = 11
W_MAP = 13
W_USERCMD = 15
W_RUNNING = 17

WEST_FENCE = 90
NORTH_FENCE = 180

data=[]

# Initialize logging
LOGFORMAT = '%(asctime)-15s %(levelname)-5s %(message)s'

if DEBUG:
    logging.basicConfig(filename=LOGFILE,
                        level=logging.DEBUG,
                        format=LOGFORMAT)
else:
    logging.basicConfig(filename=LOGFILE,
                        level=logging.INFO,
                        format=LOGFORMAT)

logging.info("Starting " + APPNAME)
logging.info("INFO MODE")
logging.debug("DEBUG MODE")
logging.debug("LOGFILE = %s" % LOGFILE)

def output():
    os.system('cls' if os.name == 'nt' else 'clear')
    print "FrontUS: %-5s Compass: %-5s\nPitch: %-5s Roll: %-5s\nGroundCOLOR: %-5s\nRunning: %-5s" % (WORLD[W_FRONT_SONAR], WORLD[W_COMPASS], WORLD[W_PITCH], WORLD[W_ROLL], WORLD[W_GROUND_COLOUR], WORLD[W_RUNNING]), "\n"

def on_message(mosq, obj, msg):
    """
    Handle incoming messages
    """

    if DEBUG:
        print msg.topic, msg.payload

    if msg.topic == START:
        logging.debug("RPiMower start...")
        WORLD[W_USERCMD] = "start"

    elif msg.topic == STOP:
        logging.debug("RPiMower stop...")
        WORLD[W_USERCMD] = "stop"

    elif msg.topic == TURN:
        logging.debug("RPiMower turn...")
        WORLD[W_USERCMD] = "turn"

    elif msg.topic == HOME:
        logging.debug("RPiMower return...")
        WORLD[W_USERCMD] = "return"
        
    topicparts = msg.topic.split("/")
    
    # if DEBUG:
    #    for i in range(0,len(topicparts)-1):
    #        print i, topicparts[i]
	
    if topicparts[2] == "FrontUS":
        WORLD[W_FRONT_SONAR] = msg.payload

    if topicparts[2] == "Ground_Colour":
        WORLD[W_GROUND_COLOUR] = msg.payload

    if topicparts[2] == "Compass":
        WORLD[W_COMPASS] = int(float(msg.payload))

    if topicparts[2] == "Pitch":
        WORLD[W_PITCH] = int(float(msg.payload))

    if topicparts[2] == "Roll":
        WORLD[W_ROLL] = int(float(msg.payload))
        
# End of MQTT callbacks


def cleanup(signum, frame):
    """
    Signal handler to ensure we disconnect cleanly
    in the event of a SIGTERM or SIGINT.
    """
    # Cleanup  modules
    logging.debug("Clean up modules")
    move.cleanup()
    VSS.cleanup()
    MQTT.cleanup()

    # Exit from application
    logging.info("Exiting on signal %d" % (signum))
    sys.exit(signum)


def detect_blocking(point):
    while len(data) > 10:
        data.pop()

    data.insert(0,point)

    if len(data) < 3:
        return False

    std = np.std(np.array(data).astype(np.float))
    #print std, data
    return std < 0.5

def compass_turn(target):
    DC = 20
    while abs(target - WORLD[W_COMPASS]) > 20:
        output()
        print "from - to: ", WORLD[W_COMPASS], target
        if WORLD[W_COMPASS] < target:
            if abs(WORLD[W_COMPASS] - target)<180:
                #Rechtsrum ist kuerzester Weg
                move.right180(DC, DC)
            else:
                #Linksrum ist kuerzester Weg
                move.left180(DC, DC)
        else:
            if abs(WORLD[W_COMPASS] - target)<180:
                #Linksrum ist kuerzester Weg
                move.left180(DC, DC)
            else:
                #Rechtsrum ist kuerzester Weg
                move.right180(DC, DC)
        time.sleep(0.02)
        move.stop()
        time.sleep(0.02)
	
def compass_turn_rel(angle):
    compass_turn(WORLD[W_COMPASS] + angle)

def build_map():
    global WORLD
    move.stop()
    # wait for the first real compass result
    time.sleep(2)
    current_angle = WORLD[W_COMPASS]
    print "Starting at angle: ", current_angle
    for angle in range(current_angle, current_angle + 359, 10):
        if angle > 360:
            target = angle - 360
        else:
            target = angle
        print "Turning to angle: ", target
        compass_turn(target)
        output()
        print "World Map: ", WORLD[W_COMPASS], WORLD[W_FRONT_SONAR]
        WORLD[W_MAP].append([WORLD[W_COMPASS], float(WORLD[W_FRONT_SONAR])+47])
    #print WORLD[W_MAP]
    WORLD_CARTESIAN = [[int(np.cos(np.radians(i[0]))*float(i[1])*10)/10, int(np.sin(np.radians(i[0]))*float(i[1])*10)/10] for i in WORLD[W_MAP]]
    #print WORLD_CARTESIAN
    MQTT.mqttc.publish("/RPiMower/World/Cartesian", str(WORLD_CARTESIAN))
    move.stop()
    WORLD[W_USERCMD]="start"

def return_home():
    global Stop

    move.stop()

    compass_turn(NORTH_FENCE)

    i = float(WORLD[W_FRONT_SONAR]) 
 
    while (i < 50.0):
        output()
        i = float(WORLD[W_FRONT_SONAR]) 
        print "Getting in 50cm distance to north fence. Current distance: ", i
        time.sleep(.05)
        if (abs(WORLD[W_COMPASS] - NORTH_FENCE) > 15):
            compass_turn(NORTH_FENCE)
        move.backward()

    move.stop()

    while (i > 50.0):
        output()
        i = float(WORLD[W_FRONT_SONAR]) 
        print "Getting in 50cm distance to north fence. Current distance: ", i
	time.sleep(.05)
        if (abs(WORLD[W_COMPASS] - NORTH_FENCE) > 15):
            compass_turn(NORTH_FENCE)
        move.forward()

    move.stop()

    compass_turn(WEST_FENCE)

  
    while (i > 15.0):
        output()
        print "Getting in 15cm distance to west fence. Current distance: ", i
        i = float(WORLD[W_FRONT_SONAR]) 
        time.sleep(.05)
        if (abs(WORLD[W_COMPASS] - WEST_FENCE - 90) > 10):
            compass_turn(WEST_FENCE - 90)
        move.forward()

    move.stop()

    compass_turn(WEST_FENCE + 90)

    while i > 15.0:
        output()
        print "Getting in 50cm distance to north fence. Current distance: ", i
        i = float(WORLD[W_FRONT_SONAR]) 
        time.sleep(.05)
        if (abs(WORLD[W_COMPASS] - WEST_FENCE + 90) > 10):
            compass_turn(WEST_FENCE + 90)
        move.forward()

    move.stop()

    compass_turn_rel(180)
    Stop = True

def mow():
    """
    The main loop in which we mow the lawn.
    """
    global Stop

    blocking = False
    running = False
 
    #Sendeverzoegerung fuer MQTT
    k = 0

    #Zaehler fuer die Maehdauer
    m = 0

    while True:
        output()
        time.sleep(0.05)

        k = k + 1
        m = m + 1

        if k == 50: #update WORLD information on MQTT every 50 loops
            if DEBUG:
                print WORLD[W_FRONT_SONAR], WORLD[W_GROUND_COLOUR], blocking, m
            MQTT.mqttc.publish("/RPiMower/World/Polar", str(WORLD[W_MAP]), qos=0, retain=True)
            MQTT.mqttc.publish("/RPiMower/World/Compass", str(WORLD[W_COMPASS]), qos=0, retain=True)
            MQTT.mqttc.publish("/RPiMower/World/FrontUS", str(WORLD[W_FRONT_SONAR]), qos=0, retain=True)
            #MQTT.mqttc.publish("/RPiMower/World/BackUS", WORLD[WORLD_BACK_SONAR], qos=0, retain=True)
            MQTT.mqttc.publish("/RPiMower/World/GroundColour", WORLD[W_GROUND_COLOUR], qos=0, retain=True)
            k = 1

        if WORLD[W_USERCMD] <> "":
            if WORLD[W_USERCMD] == "start":
                print "Command 'Start' received. Starting mower"
                move.forward()
                VSS.on([5])
                ESC.setThrottle(8.5)
                WORLD[W_RUNNING] = True
            elif WORLD[W_USERCMD] == "stop":
                print "Command 'Stop' received. Stopping mower"
                move.stop()
                VSS.off([5])
                ESC.setThrottle(7.5)
                WORLD[W_RUNNING] = False
            elif WORLD[W_USERCMD] == "turn":
                print "Usercommand 'turn' received. Turning mower 20*"
                move.turn(20)
            elif WORLD[W_USERCMD] == "return":
                print "Usercommand 'return' received. Return mower to home base"
                return_home()
            WORLD[W_USERCMD] = ""

        blocking = False;
        detect_blocking(WORLD[W_FRONT_SONAR])
        obstacle = (float(WORLD[W_FRONT_SONAR]) < MIN_DISTANCE)
        off_field = False;
        #(WORLD[W_GROUND_COLOUR] != 'green')
        tilt = ((abs(WORLD[W_PITCH]) > 35) or (abs(WORLD[W_ROLL]) > 35))

        if tilt:
            print "Stopping mower, RPiMower pitched at ", WORLD[W_PITCH]
            ESC.setThrottle(7.5)
            move.stop()

        if blocking or obstacle or off_field:
            if DEBUG:
                print WORLD[W_FRONT_SONAR], WORLD[W_GROUND_COLOUR], blocking
            print "Front obstacle detected or left the green, turning...", blocking, obstacle, off_field
            move.stop()
            VSS.off([5])
            move.turn(random.uniform(-1.0,1.0))
            move.forward()

        if m > 1000000: 
            print "Mowing max time reached, exiting!"
            move.stop()
            return
    move.stop()

# Use the signal module to handle signals
for sig in [signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGQUIT]:
    signal.signal(sig, cleanup)

# Initialise our libraries
move.init()
VSS.init([5])
ESC.init(12)
MQTT.init()
MQTT.mqttc.on_message = on_message
MQTT.mqttc.subscribe(MQTT_TOPIC_IN, qos=MQTT_QOS)

# start main procedure
build_map()
mow()
#return_home()
