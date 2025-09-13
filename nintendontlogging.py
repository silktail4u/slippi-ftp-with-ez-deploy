#!/usr/bin/python3
""" slippi-debug
use me when things get REALLY BAD
Writes logging messages to stdout.
"""

from socket import *
import datetime

def ticksToMs(ticks): 
    return ((ticks * 526.7) / 1000000)

sock = socket(AF_INET, SOCK_DGRAM)
sock.bind(("255.255.255.255", 20000))
sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)

while True:
    data, addr = sock.recvfrom(2048)
    if (data):
        print(data.decode('utf8'), end='')
