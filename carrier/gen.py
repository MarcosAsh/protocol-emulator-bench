#!/usr/bin/env python3
"""protocol-emulator bench carrier v1: board generator.

Builds carrier.kicad_pcb from the PARTS and NETS tables below, autoroutes it with
freerouting, pours GND, then writes DRC, Gerbers, drill, BOM, netlist and renders.
A net change is one edit in NETS and a rerun. Coordinates are carrier mm, origin top left.

  python3 gen.py            # full run (routes again only when placement or nets changed)
  python3 gen.py --reroute  # force a new freerouting pass
"""

import csv, hashlib, json, os, subprocess, sys, zipfile, shutil, math
import pcbnew
from pcbnew import FromMM, VECTOR2I

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "carrier"
PCB = os.path.join(HERE, NAME + ".kicad_pcb")
FREEROUTING = os.path.join(os.path.dirname(HERE), "tools", "freerouting.jar")
FPLIB = "/usr/share/kicad/footprints"
# never open a window: no display for anything this script launches
HEADLESS_ENV = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}

W, H = 100.0, 100.0          # board size
OX, OY = 50.0, 40.0          # board origin on the KiCad page
CORNER_R = 3.0
TITLE = "protocol-emulator bench carrier v1.2"

# ---------------------------------------------------------------- parts
# ref: (footprint, x, y, rot, value, bom description, part number)
# footprint is "Lib:Name" from the KiCad library, or "custom:<builder>" built below.
# x, y is the footprint origin (pin 1 for every connector here).
PARTS = {
    # sockets for the three boards
    "J1": ("custom:icepi", 25.875, 74.275, 0, "Icepi Zero",
           "2x20 female header 2.54 mm, 8.5 mm tall (Icepi Zero socket)", "Sullins PPTC202LFBN-RC"),
    # each Pico H sits in two 1x20 sockets; J13/J15 carry pins 1..20, J14/J16 pins 40..21 top down
    "J13": ("Connector_PinSocket_2.54mm:PinSocket_1x20_P2.54mm_Vertical", 9.61, 2.37, 0, "Pico A left",
            "1x20 female header 2.54 mm, 8.5 mm (Pico A pins 1-20)", "Kinghelm KH-2.54FH-1X20P-H8.5"),
    "J14": ("Connector_PinSocket_2.54mm:PinSocket_1x20_P2.54mm_Vertical", 27.39, 2.37, 0, "Pico A right",
            "1x20 female header 2.54 mm, 8.5 mm (Pico A pins 40-21)", "Kinghelm KH-2.54FH-1X20P-H8.5"),
    "J15": ("Connector_PinSocket_2.54mm:PinSocket_1x20_P2.54mm_Vertical", 72.61, 2.37, 0, "Pico B left",
            "1x20 female header 2.54 mm, 8.5 mm (Pico B pins 1-20)", "Kinghelm KH-2.54FH-1X20P-H8.5"),
    "J16": ("Connector_PinSocket_2.54mm:PinSocket_1x20_P2.54mm_Vertical", 90.39, 2.37, 0, "Pico B right",
            "1x20 female header 2.54 mm, 8.5 mm (Pico B pins 40-21)", "Kinghelm KH-2.54FH-1X20P-H8.5"),
    # analyser headers and other connectors
    "J2": ("Connector_PinHeader_2.54mm:PinHeader_1x09_P2.54mm_Vertical", 5.0, 56.0, 0, "ANALYSER A",
           "1x9 male header 2.54 mm", "generic 2.54 mm break-away header"),
    "J3": ("Connector_PinHeader_2.54mm:PinHeader_1x09_P2.54mm_Vertical", 88.0, 56.0, 0, "ANALYSER B",
           "1x9 male header 2.54 mm", "generic 2.54 mm break-away header"),
    "J4": ("Connector_PinSocket_2.54mm:PinSocket_1x04_P2.54mm_Vertical", 46.81, 3.0, -90, "CAN A",
           "1x4 female header 2.54 mm (Waveshare SN65HVD230 board A)", "Sullins PPTC041LFBN-RC"),
    "J5": ("Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", 40.0, 18.0, 0, "CAN A BUS",
           "1x2 male header 2.54 mm (CANH/CANL jumpers to board A)", "generic 2.54 mm break-away header"),
    "J6": ("Connector_PinSocket_2.54mm:PinSocket_1x04_P2.54mm_Vertical", 64.31, 3.0, -90, "CAN B",
           "1x4 female header 2.54 mm (Waveshare SN65HVD230 board B)", "Sullins PPTC041LFBN-RC"),
    "J7": ("Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", 60.0, 18.0, 0, "CAN B BUS",
           "1x2 male header 2.54 mm (CANH/CANL jumpers to board B)", "generic 2.54 mm break-away header"),
    "J8": ("Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 60.0, 50.5, 90, "SWD",
           "1x3 male header 2.54 mm (Pico debug cable jumper ends)", "generic 2.54 mm break-away header"),
    "J9": ("Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 44.0, 52.0, 90, "NEOPIXEL",
           "1x3 male header 2.54 mm", "generic 2.54 mm break-away header"),
    "J10": ("Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", 58.0, 30.0, 90, "EEPROM",
            "1x4 male header 2.54 mm (Gravity cable dupont ends)", "generic 2.54 mm break-away header"),
    "J11": ("Connector_PinHeader_2.00mm:PinHeader_2x03_P2.00mm_Vertical", 79.0, 55.0, 0, "ETHERNET",
            "2x3 male header 2.00 mm (PJRC kit ribbon cable)", "Sullins NRPN032PAEN-RC"),
    "J12": ("Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", 5.0, 81.0, 0, "SPARE",
            "1x4 male header 2.54 mm", "generic 2.54 mm break-away header"),
    # on-board parts
    "U3": ("Package_DIP:DIP-14_W7.62mm_Socket", 45.0, 27.0, 0, "74AHCT125",
           "quad buffer, 5 V, DIP-14 (+ DIP-14 socket)", "TI SN74AHCT125N + Mill-Max 110-43-314-41-001000"),
    "U4": ("Package_DIP:DIP-8_W7.62mm_Socket", 33.5, 27.0, 0, "W25Q64 breakout",
           "Adafruit QSPI DIP breakout W25Q64 (+ DIP-8 socket)", "Adafruit 5633 + Mill-Max 110-43-308-41-001000"),
    "U5": ("Package_TO_SOT_THT:TO-92_Inline_Wide", 58.0, 42.0, 0, "DS18B20",
           "1-Wire temperature sensor, TO-92", "Analog Devices DS18B20+"),
    # resistors (R_Axial 7.62 mm unless noted)
    "R1": ("RV", 47.5, 16.3, 0, "120R",
           "CAN terminator, in series with JP1 (cap on = terminated)", ""),
    "R2": ("R7", 33.5, 38.0, 0, "10k", "flash /CS pull-up", ""),
    "R3": ("R7", 42.0, 45.5, 0, "10k", "NEO_3V3 pull-down", ""),
    "R4": ("R7", 42.0, 48.5, 0, "330R", "NeoPixel DIN series", ""),
    "R5": ("R7", 58.0, 34.5, 0, "2k2", "SDA pull-up", ""),
    "R6": ("R7", 58.0, 37.5, 0, "2k2", "SCL pull-up", ""),
    "R7": ("R7", 58.0, 47.2, 0, "4k7", "DQ pull-up", ""),
    "R8": ("R7", 23.0, 85.0, 0, "1k", "UART_B series", ""),
    "R9": ("R7", 33.5, 85.0, 0, "1k", "CAN_TX series", ""),
    "R10": ("R7", 44.0, 85.0, 0, "1k", "CAN_RX series", ""),
    "R11": ("R7", 54.5, 85.0, 0, "220R", "SWCLK series", ""),
    "R12": ("R7", 65.0, 85.0, 0, "220R", "SWDIO series", ""),
    "R13": ("R7", 68.5, 43.0, -90, "4k7", "SWDIO pull-up to 3V3_B", ""),
    "R14": ("R7", 72.4, 68.4, 90, "47R", "Ethernet TX+ series", ""),
    "R15": ("R7", 75.6, 68.4, 90, "47R", "Ethernet TX- series", ""),
    "R16": ("Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P2.54mm_Vertical", 79.5, 63.5, 0, "470R", "Ethernet TX+/TX- load", ""),
    # capacitors
    "C1": ("C10U", 30.5, 2.37, 0, "10u", "5V_A bulk, leaded MLCC 10 uF 25 V X5R, 5.08 mm", "Dersonic CD1E106MC9BER2F100"),
    "C2": ("C100N", 30.5, 5.5, 0, "100n", "5V_A decoupling", "Fenghua CT4-0805B104K500F1"),
    "C3": ("C10U", 30.5, 12.53, 0, "10u", "3V3_A bulk, leaded MLCC 10 uF 25 V X5R, 5.08 mm", "Dersonic CD1E106MC9BER2F100"),
    "C4": ("C100N", 30.5, 9.4, 0, "100n", "3V3_A decoupling", "Fenghua CT4-0805B104K500F1"),
    "C5": ("C100N", 56.0, 26.0, 0, "100n", "74AHCT125 VCC decoupling", "Fenghua CT4-0805B104K500F1"),
    # v1.1: CAN terminator jumper, rail LEDs, REPLUG button, spare I2C, probe points
    "JP1": ("Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", 50.04, 22.6, 90, "TERM",
            "1x2 male header 2.54 mm (CAN terminator on/off) + shunt", "generic 2.54 mm header + jumper cap"),
    "D1": ("LED_THT:LED_D3.0mm", 84.2, 80.6, 0, "green", "3 mm green LED, 3V3_A on", "Everlight 204-10SYGD/S530-E2-L"),
    "D2": ("LED_THT:LED_D3.0mm", 84.2, 85.1, 0, "green", "3 mm green LED, 3V3_B on", "Everlight 204-10SYGD/S530-E2-L"),
    "D3": ("LED_THT:LED_D3.0mm", 84.2, 89.6, 0, "red", "3 mm red LED, 5V_A on", "Everlight 204-10SDRD/S530-A3-L"),
    "R17": ("RV", 90.6, 80.6, 0, "1k", "LED resistor 3V3_A", ""),
    "R18": ("RV", 90.6, 85.1, 0, "1k", "LED resistor 3V3_B", ""),
    "R19": ("RV", 90.6, 89.6, 0, "1k", "LED resistor 5V_A", ""),
    "SW1": ("Button_Switch_THT:SW_PUSH_6mm", 19.6, 58.3, 0, "REPLUG",
            "6 mm THT tactile switch, Pico A GP9 to GND", "HRO K2-1102DP-C4SW-04"),
    "J17": ("Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", 34.0, 55.8, 0, "I2C",
            "1x4 male header 2.54 mm, spare I2C (GND 3V3 SDA SCL)", "generic 2.54 mm break-away header"),
    "TP1": ("TP", 36.8, 67.2, 0, "GND", "test loop GND, black", "Keystone 5001"),
    "TP2": ("TP", 36.0, 44.0, 0, "GND", "test loop GND, black", "Keystone 5001"),
    "TP3": ("TP", 87.0, 94.0, 0, "GND", "test loop GND, black", "Keystone 5001"),
    "TP4": ("TP", 19.8, 67.2, 0, "CANH", "test loop, white", "Keystone 5002"),
    "TP5": ("TP", 23.2, 67.2, 0, "CANL", "test loop, white", "Keystone 5002"),
    "TP6": ("TP", 26.6, 67.2, 0, "DQ", "test loop, white", "Keystone 5002"),
    "TP7": ("TP", 30.0, 67.2, 0, "SDA", "test loop, white", "Keystone 5002"),
    "TP8": ("TP", 33.4, 67.2, 0, "SCL", "test loop, white", "Keystone 5002"),
    # mounting
    "H1": ("MountingHole:MountingHole_3.2mm_M3", 4.0, 4.0, 0, "M3", "M3 mounting hole", ""),
    "H2": ("MountingHole:MountingHole_3.2mm_M3", 96.0, 4.0, 0, "M3", "M3 mounting hole", ""),
    "H3": ("MountingHole:MountingHole_3.2mm_M3", 4.0, 96.0, 0, "M3", "M3 mounting hole", ""),
    "H4": ("MountingHole:MountingHole_3.2mm_M3", 96.0, 96.0, 0, "M3", "M3 mounting hole", ""),
    # Icepi's own M2.5 holes, for optional standoffs under it
    "H5": ("MountingHole:MountingHole_2.7mm_M2.5", 21.0, 73.0, 0, "M2.5", "Icepi standoff hole", ""),
    "H6": ("MountingHole:MountingHole_2.7mm_M2.5", 79.0, 73.0, 0, "M2.5", "Icepi standoff hole", ""),
    "H7": ("MountingHole:MountingHole_2.7mm_M2.5", 21.0, 96.0, 0, "M2.5", "Icepi standoff hole", ""),
    "H8": ("MountingHole:MountingHole_2.7mm_M2.5", 79.0, 96.0, 0, "M2.5", "Icepi standoff hole", ""),
}
ALIASES = {
    "R7": "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal",
    "C10U": "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm",
    "C100N": "Capacitor_THT:C_Disc_D3.0mm_W1.6mm_P2.50mm",
    "RV": "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P2.54mm_Vertical",
    "TP": "TestPoint:TestPoint_Keystone_5000-5004_Miniature",
}
DNP = set()

# ---------------------------------------------------------------- nets
# Pico pin n (physical 1..40) to its socket pad.
PICO = {"U1": ("J13", "J14"), "U2": ("J15", "J16")}


def pico_pad(pp):
    ref, n = pp.split(".")
    if ref not in PICO:
        return pp
    n = int(n)
    left, right = PICO[ref]
    return "%s.%d" % (left, n) if n <= 20 else "%s.%d" % (right, 41 - n)


# net: pads. J1 = Icepi header (Pi numbering), U1/U2 = Pico A/B physical pins.
PICO_GND = [3, 8, 13, 18, 23, 28, 33, 38]
NETS = {
    "GND": ["J1.%d" % p for p in (6, 9, 14, 20, 25, 30, 34, 39)]
           + ["U1.%d" % p for p in PICO_GND] + ["U2.%d" % p for p in PICO_GND]
           + ["J2.9", "J3.9", "J4.3", "J6.3", "J8.2", "J9.3", "J10.2", "J11.3", "J12.4",
              "U3.1", "U3.5", "U3.7", "U3.9", "U3.12", "U4.4", "U5.1", "R3.2",
              "C1.2", "C2.2", "C3.2", "C4.2", "C5.2",
              "D1.1", "D2.1", "D3.1", "SW1.2", "TP1.1", "TP2.1", "TP3.1", "J17.1"],
    "5V_A": ["R19.1", "U1.40", "U3.4", "U3.10", "U3.13", "U3.14", "J9.1", "C1.1", "C2.1", "C5.1"],
    "3V3_A": ["R17.1", "J17.2", "U1.36", "J4.4", "U4.3", "U4.7", "U4.8", "R2.2", "R5.2", "R6.2", "R7.2",
              "J10.1", "U5.3", "C3.1", "C4.1"],
    "3V3_B": ["U2.36", "J6.4", "R13.2", "R18.1"],
    # rail LEDs, cathode to GND
    "LED_3V3A": ["R17.2", "D1.2"],
    "LED_3V3B": ["R18.2", "D2.2"],
    "LED_5V": ["R19.2", "D3.2"],
    # REPLUG button on Pico A GP9 (pin 12), not on USB_DETACH
    "REPLUG": ["U1.12", "SW1.1"],
    # host SPI (analyser A D0..D3)
    "HOST_SCK": ["J1.23", "U1.4", "J2.1"],
    "HOST_MOSI": ["J1.19", "U1.5", "J2.2"],
    "HOST_MISO": ["J1.21", "U1.6", "J2.3"],
    "HOST_CS_N": ["J1.24", "U1.7", "J2.4"],
    # UART to Pico B (analyser A D4, Icepi side)
    "UART_B": ["J1.8", "R8.1", "J2.5"],
    "UART_B_PICO": ["R8.2", "U2.2"],
    # CAN, module A on the chip, module B on Pico B (analyser A D5 = CAN_RX, Icepi side)
    "CAN_TX": ["J1.10", "R9.1"],
    "CANA_CTX": ["R9.2", "J4.1"],
    "CANA_CRX": ["J4.2", "R10.2"],
    "CAN_RX": ["R10.1", "J1.5", "J2.6"],
    "CANH": ["J5.1", "J7.1", "R1.1", "TP4.1"],
    "CANL": ["J5.2", "J7.2", "JP1.2", "TP5.1"],
    "CAN_TERM": ["R1.2", "JP1.1"],
    "CANB_RX": ["J6.2", "U2.9"],
    "CANB_TX": ["J6.1", "U2.10"],
    # SWD into Pico B (analyser A D6/D7, Icepi side)
    "SWCLK": ["J1.12", "R11.1", "J2.7"],
    "SWCLK_PICO": ["R11.2", "J8.1"],
    "SWDIO": ["J1.36", "R12.1", "J2.8"],
    "SWDIO_PICO": ["R12.2", "J8.3", "R13.1"],
    # NeoPixel through the 5 V buffer (analyser B D4)
    "NEO_3V3": ["J1.18", "U3.2", "R3.1", "J3.5"],
    "NEO_5V": ["U3.3", "R4.1"],
    "NEO_DIN": ["R4.2", "J9.2"],
    # SPI flash (analyser B D0..D3)
    "FLASH_CLK": ["J1.26", "U4.6", "J3.1"],
    "FLASH_DI": ["J1.22", "U4.5", "J3.2"],
    "FLASH_DO": ["J1.3", "U4.2", "J3.3"],
    "FLASH_CS_N": ["J1.28", "U4.1", "J3.4", "R2.1"],
    # I2C (analyser B D6/D7)
    "I2C_SDA": ["J1.33", "U2.4", "J10.4", "J3.7", "R5.1", "TP7.1", "J17.3"],
    "I2C_SCL": ["J1.35", "U2.5", "J10.3", "J3.8", "R6.1", "TP8.1", "J17.4"],
    # 1-Wire (analyser B D5)
    "DQ": ["J1.37", "U5.2", "R7.1", "J3.6", "TP6.1"],
    # 10BASE-T transmit
    "ETH_TXP": ["J1.38", "R14.1"],
    "ETH_TXN": ["J1.40", "R15.1"],
    "ETH_TXP_J": ["R14.2", "R16.1", "J11.5"],
    "ETH_TXN_J": ["R15.2", "R16.2", "J11.6"],
    # USB mirrors and detach to Pico A
    "USB_MIR0": ["J1.29", "U1.9"],
    "USB_MIR1": ["J1.31", "U1.10"],
    "USB_DETACH": ["J1.15", "U1.11"],
    # free chip inputs
    "SPARE_IN2": ["J1.7", "J12.1"],
    "SPARE_IN3": ["J1.11", "J12.2"],
    "SPARE_IN4": ["J1.13", "J12.3"],
}
POWER_NETS = {"GND": 0.6, "5V_A": 0.8, "3V3_A": 0.6, "3V3_B": 0.6}
# Pads deliberately left open (unused Pico pins are open too): Icepi 3V3/5V (1, 2, 4, 17) and unused, Ethernet RX/LED, buffer outputs.
NO_CONNECT = ["J1.1", "J1.2", "J1.4", "J1.16", "J1.17", "J1.27", "J1.32",
              "J11.1", "J11.2", "J11.4", "U3.6", "U3.8", "U3.11"]

# Hand routes drawn before autorouting (locked): the CAN pair, straight across.
HAND_TRACKS = [
    # terminator: R1 hangs off CANH above the pair, JP1 sits on CANL below it, linked on B.Cu
    ("CANH", "F.Cu", 0.3, [(47.5, 16.3), (47.5, 18.0)]),
    ("CAN_TERM", "B.Cu", 0.3, [(50.04, 16.3), (50.04, 22.6)]),
    ("CANL", "F.Cu", 0.3, [(52.58, 22.6), (52.58, 20.54)]),
    # Pico A supply pins straight onto their capacitors
    ("5V_A", "F.Cu", 0.8, [(27.39, 2.37), (30.5, 2.37)]),
    ("5V_A", "B.Cu", 0.8, [(30.5, 2.37), (30.5, 5.5)]),
    ("3V3_A", "F.Cu", 0.6, [(27.39, 12.53), (30.5, 12.53)]),
    ("3V3_A", "B.Cu", 0.6, [(30.5, 12.53), (30.5, 9.4)]),
    ("CANH", "F.Cu", 0.3, [(40.0, 18.0), (60.0, 18.0)]),
    ("CANL", "F.Cu", 0.3, [(40.0, 20.54), (60.0, 20.54)]),
]

# ---------------------------------------------------------------- silk labels
# ref: (side, [label per pad 1..n]); side is where the text sits relative to the pads.
PIN_LABELS = {
    "J2": ("R", ["D0 HOST_SCK", "D1 HOST_MOSI", "D2 HOST_MISO", "D3 HOST_CS_N", "D4 UART_B",
                 "D5 CAN_RX", "D6 SWCLK", "D7 SWDIO", "GND"]),
    "J3": ("R", ["D0 FLASH_CLK", "D1 FLASH_DI", "D2 FLASH_DO", "D3 FLASH_CS", "D4 NEO_3V3",
                 "D5 DQ", "D6 SDA", "D7 SCL", "GND"]),
    "J4": ("U", ["CTX", "CRX", "GND", "3V3"]),
    "J6": ("U", ["CTX", "CRX", "GND", "3V3"]),
    "J5": ("L", ["CANH", "CANL"]),
    "J7": ("R", ["CANH", "CANL"]),
    "J8": ("D", ["CLK", "GND", "DIO"], 2.5),
    "J9": ("D", ["5V", "DIN", "GND"], 2.5),
    "J10": ("D", ["+", "-", "C", "D"], 2.5),
    "J12": ("R", ["IN2 (7)", "IN3 (11)", "IN4 (13)", "GND"]),
    "J17": ("L", ["GND", "3V3", "SDA", "SCL"]),
    "U5": ("D", ["GND", "DQ", "VDD"], 2.9),
}
# labels printed inside the Pico outlines, next to the pins the carrier uses
PICO_LABELS = {
    "U1": {12: "GP9 REPLUG", 4: "GP2 SCK", 5: "GP3 MOSI", 6: "GP4 MISO", 7: "GP5 CS_N", 9: "GP6 USB_MIR0",
           10: "GP7 USB_MIR1", 11: "GP8 DETACH", 36: "3V3_A OUT", 40: "VBUS 5V_A"},
    "U2": {2: "GP1 UART RX", 4: "GP2 SDA", 5: "GP3 SCL", 9: "GP6 CAN RX", 10: "GP7 CAN TX",
           36: "3V3_B OUT"},
}


# ---------------------------------------------------------------- helpers
def P(x, y):
    return VECTOR2I(FromMM(OX + x), FromMM(OY + y))


def seg(parent, layer, a, b, width=0.15):
    s = pcbnew.PCB_SHAPE(parent, pcbnew.SHAPE_T_SEGMENT)
    s.SetLayer(layer)
    s.SetStart(a)
    s.SetEnd(b)
    s.SetWidth(FromMM(width))
    parent.Add(s)
    return s


def rect(parent, layer, x0, y0, x1, y1, width=0.15, local=False):
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    f = (lambda x, y: VECTOR2I(FromMM(x), FromMM(y))) if local else P
    for a, b in zip(pts, pts[1:]):
        seg(parent, layer, f(*a), f(*b), width)


def dashed_rect(board, layer, x0, y0, x1, y1, dash=1.0, gap=0.8, width=0.15):
    for (ax, ay), (bx, by) in [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
                               ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]:
        length = math.hypot(bx - ax, by - ay)
        t = 0.0
        while t < length:
            t1 = min(t + dash, length)
            seg(board, layer, P(ax + (bx - ax) * t / length, ay + (by - ay) * t / length),
                P(ax + (bx - ax) * t1 / length, ay + (by - ay) * t1 / length), width)
            t = t1 + gap


def text(board, s, x, y, size=1.0, layer=pcbnew.F_SilkS, rot=0, just="C", thick=0.15, bold=False):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(s)
    t.SetLayer(layer)
    t.SetTextSize(VECTOR2I(FromMM(size), FromMM(size)))
    t.SetTextThickness(FromMM(thick if not bold else max(thick, size * 0.2)))
    t.SetTextAngleDegrees(rot)
    t.SetHorizJustify({"L": pcbnew.GR_TEXT_H_ALIGN_LEFT, "R": pcbnew.GR_TEXT_H_ALIGN_RIGHT,
                       "C": pcbnew.GR_TEXT_H_ALIGN_CENTER}[just])
    if layer == pcbnew.B_SilkS:
        t.SetMirrored(True)
    t.SetPosition(P(x, y))
    board.Add(t)
    return t


def add_pad(fp, num, x, y, drill=1.0, size=1.7, square=False):
    pad = pcbnew.PAD(fp)
    pad.SetNumber(str(num))
    pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
    pad.SetShape(pcbnew.PAD_SHAPE_RECT if square else pcbnew.PAD_SHAPE_CIRCLE)
    pad.SetSize(VECTOR2I(FromMM(size), FromMM(size)))
    pad.SetDrillSize(VECTOR2I(FromMM(drill), FromMM(drill)))
    pad.SetLayerSet(pcbnew.PAD.PTHMask())
    pad.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    fp.Add(pad)


def fp_text(fp, s, x, y, size=1.0, layer=pcbnew.F_SilkS, rot=0, just="C"):
    t = pcbnew.PCB_TEXT(fp)
    t.SetText(s)
    t.SetLayer(layer)
    t.SetTextSize(VECTOR2I(FromMM(size), FromMM(size)))
    t.SetTextThickness(FromMM(0.15))
    t.SetTextAngleDegrees(rot)
    t.SetHorizJustify({"L": pcbnew.GR_TEXT_H_ALIGN_LEFT, "R": pcbnew.GR_TEXT_H_ALIGN_RIGHT,
                       "C": pcbnew.GR_TEXT_H_ALIGN_CENTER}[just])
    t.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    fp.Add(t)


def build_icepi(board):
    """Icepi Zero 2x20 socket for a face-down Icepi (header pins soldered pointing up, out of its
    component side). Origin = left end of the odd row; pin 1 at the right end, odd row at y=0,
    even row at y=-2.54. The Icepi's own header (cheyao/icepi-zero v1.3/v1.4 J1) mirrored in x."""
    fp = pcbnew.FOOTPRINT(board)
    fp.SetFPID(pcbnew.LIB_ID("carrier", "IcepiZero_Socket_2x20_FaceDown"))
    fp.SetAttributes(pcbnew.FP_THROUGH_HOLE)
    for n in range(1, 41):
        k = (n - 1) // 2
        x = (19 - k) * 2.54
        y = 0.0 if n % 2 else -2.54
        add_pad(fp, n, x, y, square=(n == 1))
    # socket body
    rect(fp, pcbnew.F_SilkS, -1.4, -3.94, 49.66, 1.4, local=True)
    rect(fp, pcbnew.F_CrtYd, -1.8, -4.3, 50.1, 1.8, 0.05, local=True)
    # Icepi board outline: 65 x 30, pin 1 at 8.375 from its edge (here the right), 4.775 from its header edge
    ix0, iy0 = 48.26 + 8.375 - 65, -4.775
    rect(fp, pcbnew.F_Fab, ix0, iy0, ix0 + 65, iy0 + 30, 0.1, local=True)
    return fp


def load_fp(spec):
    lib, name = spec.split(":")
    fp = pcbnew.FootprintLoad(os.path.join(FPLIB, lib + ".pretty"), name)
    if fp is None:
        raise SystemExit("footprint not found: " + spec)
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


# ---------------------------------------------------------------- build
DRU = """(version 1)
(rule "thermal spokes"
  (condition "A.Type == 'Pad'")
  (constraint min_resolved_spokes 1))
"""


def build():
    open(os.path.join(HERE, NAME + ".kicad_dru"), "w").write(DRU)
    board = pcbnew.NewBoard(PCB)
    board.SetCopperLayerCount(2)
    ds = board.GetDesignSettings()
    ds.SetBoardThickness(FromMM(1.6))
    ds.SetAuxOrigin(P(0, H))   # bottom-left corner: placement files read in board mm, y up
    ds.m_TrackMinWidth = FromMM(0.2)
    ds.m_MinClearance = FromMM(0.2)
    ds.m_ViasMinSize = FromMM(0.6)
    ds.m_MinThroughDrill = FromMM(0.3)
    ds.m_HoleClearance = FromMM(0.25)
    ds.m_HoleToHoleMin = FromMM(0.5)
    ds.m_CopperEdgeClearance = FromMM(0.4)
    ds.m_SilkClearance = FromMM(0.0)
    ns = ds.m_NetSettings
    d = ns.GetDefaultNetclass()
    d.SetTrackWidth(FromMM(0.25)); d.SetClearance(FromMM(0.2))
    d.SetViaDiameter(FromMM(0.6)); d.SetViaDrill(FromMM(0.3))
    for name, width in sorted(set((("Power%g" % w).replace(".", "_"), w) for w in POWER_NETS.values())):
        nc = pcbnew.NETCLASS(name)
        nc.SetTrackWidth(FromMM(width)); nc.SetClearance(FromMM(0.2))
        nc.SetViaDiameter(FromMM(0.9)); nc.SetViaDrill(FromMM(0.45))
        nc.SetPriority(0)
        ns.SetNetclass(name, nc)
    for net, width in POWER_NETS.items():
        ns.SetNetclassPatternAssignment(net, ("Power%g" % width).replace(".", "_"))

    # outline with rounded corners
    r = CORNER_R
    seg(board, pcbnew.Edge_Cuts, P(r, 0), P(W - r, 0), 0.1)
    seg(board, pcbnew.Edge_Cuts, P(W, r), P(W, H - r), 0.1)
    seg(board, pcbnew.Edge_Cuts, P(W - r, H), P(r, H), 0.1)
    seg(board, pcbnew.Edge_Cuts, P(0, H - r), P(0, r), 0.1)
    k = r * (1 - math.sqrt(0.5))
    for a_, m_, e_ in [((0, r), (k, k), (r, 0)), ((W - r, 0), (W - k, k), (W, r)),
                       ((W, H - r), (W - k, H - k), (W - r, H)), ((r, H), (k, H - k), (0, H - r))]:
        a = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_ARC)
        a.SetLayer(pcbnew.Edge_Cuts)
        a.SetWidth(FromMM(0.1))
        a.SetArcGeometry(P(*a_), P(*m_), P(*e_))
        board.Add(a)

    nets = {}
    for name in NETS:
        n = pcbnew.NETINFO_ITEM(board, name)
        board.Add(n)
        nets[name] = n

    fps = {}
    for ref, (spec, x, y, rot, value, _desc, _pn) in PARTS.items():
        spec = ALIASES.get(spec, spec)
        if spec == "custom:icepi":
            fp = build_icepi(board)
        else:
            fp = load_fp(spec)
        if ref in ("J13", "J14", "J15", "J16"):
            # the Pico outline drawn in silk() replaces the socket's own silk
            for item in list(fp.GraphicalItems()):
                if item.GetLayer() == pcbnew.F_SilkS:
                    fp.Remove(item)
            fp.SetFPID(pcbnew.LIB_ID("carrier", "PinSocket_1x20_P2.54mm_Vertical_NoSilk"))
        fp.SetReference(ref)
        fp.SetValue(value)
        fp.Value().SetVisible(False)
        fp.Value().SetLayer(pcbnew.F_Fab)
        if ref in DNP:
            fp.SetDNP(True)
            fp.SetExcludedFromBOM(True)
        board.Add(fp)
        fp.SetPosition(P(x, y))
        fp.SetOrientationDegrees(rot)
        fps[ref] = fp
        refsize = 0.9
        fp.Reference().SetTextSize(VECTOR2I(FromMM(refsize), FromMM(refsize)))
        fp.Reference().SetTextThickness(FromMM(0.15))

    padmap = {}
    for ref, fp in fps.items():
        for pad in fp.Pads():
            if pad.GetNumber():
                padmap.setdefault("%s.%s" % (ref, pad.GetNumber()), []).append(pad)
    used = set()
    for name, pads in NETS.items():
        for pp in map(pico_pad, pads):
            if pp not in padmap:
                raise SystemExit("no pad %s (net %s)" % (pp, name))
            if pp in used:
                raise SystemExit("pad %s in two nets" % pp)
            used.add(pp)
            for pad in padmap[pp]:
                pad.SetNet(nets[name])
    for pp, pad in padmap.items():
        if pp not in used and pp not in NO_CONNECT and not pp.startswith(("J13.", "J14.", "J15.", "J16.")):
            raise SystemExit("pad %s neither connected nor listed in NO_CONNECT" % pp)

    for net, layer, width, pts in HAND_TRACKS:
        for a, b in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(P(*a)); t.SetEnd(P(*b))
            t.SetWidth(FromMM(width))
            t.SetLayer(board.GetLayerID(layer))
            t.SetNet(nets[net])
            t.SetLocked(True)
            board.Add(t)

    silk(board, fps)
    write_libs(board, fps)
    return board, fps, nets


def write_libs(board, fps):
    """Project fp-lib-table: KiCad's stock libraries plus carrier.pretty for the two custom sockets."""
    libdir = os.path.join(HERE, "carrier.pretty")
    os.makedirs(libdir, exist_ok=True)
    done = set()
    for ref in ("J1", "J13"):
        fp = pcbnew.FOOTPRINT(fps[ref])
        fp.SetPosition(VECTOR2I(0, 0))
        fp.SetOrientationDegrees(0)
        name = fp.GetFPID().GetLibItemName().wx_str()
        fp.SetReference("REF**")
        for pad in fp.Pads():
            pad.SetNetCode(0)
        pcbnew.PCB_IO_KICAD_SEXPR().FootprintSave(libdir, fp)
        done.add(name)
    libs = sorted({ALIASES.get(p[0], p[0]).split(":")[0] for p in PARTS.values()} - {"custom"})
    rows = ['  (lib (name "carrier")(type "KiCad")(uri "${KIPRJMOD}/carrier.pretty")(options "")(descr "custom sockets"))']
    rows += ['  (lib (name "%s")(type "KiCad")(uri "%s/%s.pretty")(options "")(descr ""))' % (l, FPLIB, l) for l in libs]
    open(os.path.join(HERE, "fp-lib-table"), "w").write("(fp_lib_table\n  (version 7)\n" + "\n".join(rows) + "\n)\n")


def pad_xy(fp, num):
    for pad in fp.Pads():
        if pad.GetNumber() == str(num):
            p = pad.GetPosition()
            return pcbnew.ToMM(p.x) - OX, pcbnew.ToMM(p.y) - OY
    raise KeyError(num)


def place_refs(fps):
    """Move reference text to sensible spots."""
    custom = {
        "J1": (50.0, 77.6, 0), "J13": (13.0, 49.6, 0), "J14": (23.8, 49.6, 0),
        "J15": (76.0, 49.6, 0), "J16": (86.8, 49.6, 0),
        "J2": (5.0, 54.0, 0), "J3": (88.0, 54.0, 0),
        "J4": (36.8, 3.0, 0), "J6": (54.6, 3.0, 0),
        "J5": (40.0, 15.4, 0), "J7": (60.0, 15.4, 0),
        "J8": (57.8, 50.5, 0), "J9": (41.6, 52.0, 0), "J10": (55.2, 30.0, 0),
        "J11": (79.0, 61.0, 0), "J12": (2.3, 81.0, 0),
        "U3": (48.8, 34.6, 90), "U4": (37.3, 30.8, 90), "U5": (56.2, 42.0, 0),
        "R16": (84.6, 63.5, 0), "SW1": (22.85, 60.55, 0), "J17": (37.2, 63.4, 0),
        "C2": (35.0, 5.5, 0), "C4": (35.0, 9.4, 0),
        "C5": (60.2, 26.0, 0),
    }
    for ref, fp in fps.items():
        if ref.startswith(("H", "TP", "D")) or ref in ("R1", "JP1", "R17", "R18", "R19"):
            fp.Reference().SetVisible(False)
            continue
        if ref in custom:
            x, y, rot = custom[ref]
            fp.Reference().SetPosition(P(x, y))
            fp.Reference().SetTextAngleDegrees(rot)
            continue
        if ref.startswith(("R", "C")):
            # centre of the body, rotated along it
            (x1, y1), (x2, y2) = pad_xy(fp, 1), pad_xy(fp, 2)
            fp.Reference().SetPosition(P((x1 + x2) / 2, (y1 + y2) / 2))
            fp.Reference().SetTextAngleDegrees(90 if abs(x1 - x2) < 0.01 else 0)
            fp.Reference().SetTextSize(VECTOR2I(FromMM(0.8), FromMM(0.8)))
            fp.Reference().SetTextThickness(FromMM(0.12))


def silk(board, fps):
    place_refs(fps)
    S = pcbnew.F_SilkS
    # per-pin labels
    for ref, spec in PIN_LABELS.items():
        side, labels = spec[0], spec[1]
        off = spec[2] if len(spec) > 2 else 1.9
        fp = fps[ref]
        for i, lab in enumerate(labels, 1):
            x, y = pad_xy(fp, i)
            if side == "R":
                text(board, lab, x + 1.5, y, 0.9, just="L")
            elif side == "L":
                text(board, lab, x - 1.5, y, 0.9, just="R")
            elif side == "U":
                text(board, lab, x, y - off, 0.8)
            elif side == "D":
                text(board, lab, x, y + off, 0.8)

    def pico_xy(ref, pin):
        r, n = pico_pad("%s.%d" % (ref, pin)).split(".")
        return pad_xy(fps[r], n)

    for ref, labs in PICO_LABELS.items():
        x, y = pico_xy(ref, 1)
        # board outline of the Pico, its USB connector and a pin 1 mark
        rect(board, S, x - 1.61, y - 1.37, x + 19.39, y + 49.63)
        rect(board, S, x + 5.0, y - 1.37, x + 12.8, y + 1.8)
        seg(board, S, P(x - 2.3, y - 1.0), P(x - 2.3, y + 1.0), 0.2)
        for pin, lab in labs.items():
            x, y = pico_xy(ref, pin)
            if pin <= 20:
                text(board, lab, x + 1.6, y, 0.8, just="L")
            else:
                text(board, lab, x - 1.6, y, 0.8, just="R")
        x, y = pico_xy(ref, 1)
        name = {"U1": "PICO A", "U2": "PICO B"}[ref]
        text(board, name, x + 8.9, y + 38.0, 1.2, bold=True)
        text(board, "Pico H, face up", x + 8.9, y + 40.0, 0.8)
        text(board, "USB to the edge", x + 8.9, y + 41.5, 0.8)
    text(board, "40", 23.5, 71.7, 0.8)
    for hx in (21.0, 79.0):
        text(board, "M2.5", hx, 75.6, 0.8)

    # titles
    text(board, TITLE, 55.5, 57.5, 1.2, bold=True)
    text(board, OWNER_LINE, 55.5, 59.5, 1.0, bold=True)
    # v1.1 labels
    for ref in ("TP1", "TP2", "TP3", "TP4", "TP5", "TP6", "TP7", "TP8"):
        x, y = pad_xy(fps[ref], 1)
        if ref in ("TP2", "TP3"):
            text(board, "GND", x + 2.0, y, 0.8, just="L")
        else:
            text(board, PARTS[ref][4], x, y + 2.0, 0.8)
    text(board, "PROBES", 26.6, 65.0, 0.8)
    for ref, lab in (("D1", "3V3 A"), ("D2", "3V3 B"), ("D3", "5V")):
        x, y = pad_xy(fps[ref], 1)
        text(board, lab, x + 10.4, y, 0.8, just="L")
    text(board, "TERM: cap = on", 54.0, 22.6, 0.8, just="L")
    text(board, "REPLUG (GP9)", 22.85, 55.7, 0.8)
    text(board, "I2C", 34.0, 53.8, 0.8)
    cat(board)
    text(board, "ANALYSER A", 10.0, 54.0, 1.0, just="L")
    text(board, "ANALYSER B", 90.0, 54.0, 1.0, just="L")
    text(board, "SPARE INPUTS", 7.0, 79.0, 0.9, just="L")
    text(board, "NEOPIXEL 5V", 50.6, 52.0, 0.8, just="L")
    text(board, "EEPROM DFR0117", 61.8, 27.7, 0.8)
    text(board, "SWD to Pico B debug cable", 62.5, 54.5, 0.8)
    text(board, "PJRC ETH KIT", 80.0, 52.8, 0.8)
    for i, lab in enumerate(["RX-", "GND", "TX+"]):
        text(board, lab, 77.7, 55.0 + 2 * i, 0.8, just="R")
    for i, lab in enumerate(["RX+", "LED", "TX-"]):
        text(board, lab, 82.3, 55.0 + 2 * i, 0.8, just="L")
    text(board, "DS18B20", 65.3, 41.2, 0.8, just="L")

    # CAN module keep-clear areas: the Waveshare boards stand in J4/J6, parts side toward y+
    for ref, cx in (("J4", 43.6), ("J6", 60.5)):
        dashed_rect(board, S, cx - 6.6, 5.0, cx + 7.6, 14.6)
        text(board, "Waveshare CAN " + {"J4": "A", "J6": "B"}[ref], cx, 7.6, 0.8)
        text(board, "board stands here,", cx, 9.1, 0.8)
        text(board, "parts side this way", cx, 10.6, 0.8)
        seg(board, S, P(cx, 12.1), P(cx, 13.9), 0.2)
        seg(board, S, P(cx, 13.9), P(cx - 0.7, 13.1), 0.2)
        seg(board, S, P(cx, 13.9), P(cx + 0.7, 13.1), 0.2)
    text(board, "CAN: jumper J5/J7 to boards", 39.4, 24.7, 0.8)

    # power and placement warnings
    text(board, "Picos: USB to the edge. 5V_A = Pico A VBUS, 3V3_A = Pico A 3V3(OUT), 3V3_B = Pico B 3V3(OUT)",
         50.0, 98.4, 0.8, layer=pcbnew.B_SilkS)
    # Icepi
    ix0, iy0 = 17.5, 69.5
    rect(board, S, ix0, iy0 + 9.5, ix0 + 65, iy0 + 30) if False else None
    for (a, b) in [((ix0, iy0 + 7.0), (ix0, iy0 + 30.0)), ((ix0 + 65, iy0 + 7.0), (ix0 + 65, iy0 + 30.0))]:
        seg(board, S, P(*a), P(*b), 0.15)
    text(board, "ICEPI ZERO FACE DOWN, its chip and USB-C ports toward this board", 50.0, 80.3, 0.9)
    text(board, "Icepi powers itself from its own USB-C. Pins 1, 2, 4, 17 (3V3/5V) are NOT connected", 50.0, 82.0, 0.8)
    text(board, "Icepi USB-C ports at this edge", 50.0, 91.5, 0.9)
    for ux in (29.5, 42.0, 54.5):
        rect(board, S, ux - 4.5, 93.5, ux + 4.5, 99.0, 0.15)
        text(board, "USB-C", ux, 96.2, 0.8)
    text(board, "pin 1", 74.1, 77.1, 0.8)
    text(board, "2", 25.9, 70.4, 0.8) if False else None


# Surprised cat face, front view, drawn for this board (mm, origin top left of the head box
# 15 x 9.2; whiskers reach 1.6 mm past each side). Outline strokes plus filled pupils and nose.
CAT_HEAD = [(1.2, 7.2), (2.4, 8.3), (4.2, 8.85), (7.5, 9.05), (10.8, 8.85), (12.6, 8.3), (13.8, 7.2),
            (14.4, 5.6), (14.3, 4.0), (13.6, 2.6), (12.6, 0.25), (10.2, 1.85), (7.5, 1.55), (4.8, 1.85),
            (2.4, 0.25), (1.4, 2.6), (0.7, 4.0), (0.6, 5.6), (1.2, 7.2)]
CAT_FILLED = [[(2.65, 1.05), (4.05, 2.15), (2.15, 2.75)],        # inner ears
              [(12.35, 1.05), (10.95, 2.15), (12.85, 2.75)],
              [(6.95, 5.7), (8.05, 5.7), (7.5, 6.3)]]            # nose
CAT_EYES = [(4.9, 4.3), (10.1, 4.3)]                             # wide open: r 1.5, pupil r 0.6
CAT_MOUTH = (7.5, 7.4)                                           # the "o", r 0.55
CAT_WHISKERS = [((3.4, 6.2), (-1.5, 5.5)), ((3.4, 6.75), (-1.6, 6.85)), ((3.4, 7.3), (-1.3, 8.1)),
                ((11.6, 6.2), (16.5, 5.5)), ((11.6, 6.75), (16.6, 6.85)), ((11.6, 7.3), (16.3, 8.1))]
CAT_AT = (48.0, 60.5)
CAT_KEEPOUT = (-2.0, -0.5, 17.0, 9.6)   # box (x0, y0, x1, y1) kept free of stitching vias
OWNER_LINE = "Marcos Ashton Iglesias  2026-10-07"


def cat(board):
    ox, oy = CAT_AT
    S = pcbnew.F_SilkS

    def circle(cx, cy, r, filled, width=0.25):
        c = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_CIRCLE)
        c.SetLayer(S)
        c.SetCenter(P(ox + cx, oy + cy))
        c.SetEnd(P(ox + cx + r, oy + cy))
        c.SetWidth(FromMM(width))
        c.SetFilled(filled)
        board.Add(c)

    for a, b in zip(CAT_HEAD, CAT_HEAD[1:]):
        seg(board, S, P(ox + a[0], oy + a[1]), P(ox + b[0], oy + b[1]), 0.3)
    for pts in CAT_FILLED:
        sh = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_POLY)
        sh.SetLayer(S)
        sh.SetPolyPoints([P(ox + x, oy + y) for x, y in pts])
        sh.SetFilled(True)
        sh.SetWidth(FromMM(0.15))
        board.Add(sh)
    for ex, ey in CAT_EYES:
        circle(ex, ey, 1.5, False)
        circle(ex, ey, 0.6, True, 0.15)
    circle(CAT_MOUTH[0], CAT_MOUTH[1], 0.55, False)
    for a, b in CAT_WHISKERS:
        seg(board, S, P(ox + a[0], oy + a[1]), P(ox + b[0], oy + b[1]), 0.2)


# ---------------------------------------------------------------- routing
def placement_hash():
    h = hashlib.sha256()
    h.update(json.dumps([PARTS, NETS, HAND_TRACKS, POWER_NETS, NO_CONNECT], sort_keys=True).encode())
    h.update(open(__file__, "rb").read().split(b"# ---------------------------------------------------------------- silk labels")[0])
    return h.hexdigest()[:16]


def route(force=False):
    dsn = os.path.join(HERE, NAME + ".dsn")
    ses = os.path.join(HERE, NAME + ".ses")
    stamp = os.path.join(HERE, NAME + ".ses.stamp")
    hsh = placement_hash()
    if not force and os.path.exists(ses) and os.path.exists(stamp) and open(stamp).read() == hsh:
        print("routing: reusing", ses)
        return ses
    board = pcbnew.LoadBoard(PCB)
    if not pcbnew.ExportSpecctraDSN(board, dsn):
        raise SystemExit("DSN export failed")
    if os.path.exists(ses):
        os.remove(ses)
    # freerouting is not deterministic: run a few in parallel, keep the one with fewest unrouted
    best = None
    for rnd in range(4):
        procs = []
        for i in range(4):
            out = os.path.join(HERE, "route_try%d.ses" % i)
            log = os.path.join(HERE, "route_try%d.log" % i)
            for f in (out, log):
                if os.path.exists(f):
                    os.remove(f)
            cmd = ["java", "-Djava.awt.headless=true", "-jar", FREEROUTING, "--gui.enabled=false",
                   "-de", dsn, "-do", out, "--router.autorouter.max_passes=80", "-mt", "4",
                   "--router.automatic_neckdown=false", "--router.copper_to_edge_clearance_um=500",
                   "--router.hole_clearance_um=300"]
            procs.append((subprocess.Popen(cmd, cwd=HERE, env=HEADLESS_ENV, stdin=subprocess.DEVNULL,
                                           stdout=open(log, "w"), stderr=subprocess.STDOUT), out, log))
        for p, out, log in procs:
            p.wait()
            txt = open(log).read()
            import re as _re
            m = _re.findall(r"final score: [\d.]+ \((\d+) unrouted", txt)
            if m and os.path.exists(out):
                left = int(m[-1])
                print("routing attempt: %d unrouted" % left)
                if best is None or left < best[0]:
                    best = (left, out, log)
        if best and best[0] <= 2 + 1:   # the hand-routed CAN pair and terminator count as 3
            break
    if best is None:
        raise SystemExit("freerouting wrote no session; see route_try*.log")
    shutil.copy(best[1], ses)
    shutil.copy(best[2], os.path.join(HERE, "freerouting.log"))
    print("routing: kept attempt with %d unrouted (GND left to the pour)" % best[0])
    open(stamp, "w").write(hsh)
    return ses


# ---------------------------------------------------------------- finishing
def drop_dangling_vias(board):
    """freerouting sometimes leaves a via with a track on one side only."""
    tracks = [t for t in board.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T]
    for v in [t for t in board.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]:
        p = v.GetPosition()
        ends = sum((t.GetStart() == p) + (t.GetEnd() == p) for t in tracks)
        if ends < 2:
            board.Remove(v)


def add_zones(board, nets):
    gnd = nets["GND"]
    zones = []
    m = 0.5
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(gnd)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in [(m, m), (W - m, m), (W - m, H - m), (m, H - m)]:
            ol.Append(FromMM(OX + x), FromMM(OY + y))
        z.SetLocalClearance(FromMM(0.3))
        z.SetMinThickness(FromMM(0.25))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(FromMM(0.4))
        z.SetThermalReliefSpokeWidth(FromMM(0.5))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        z.SetZoneName("GND_" + ("TOP" if layer == pcbnew.F_Cu else "BOT"))
        board.Add(z)
        zones.append(z)
    return zones


def fill(board):
    board.BuildConnectivity()
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())


def stitch(board, nets, pitch=5.0, via=0.6, drill=0.3, clear=0.35):
    """GND vias on a grid wherever nothing else is near and both pours have copper."""
    gnd = nets["GND"]
    zones = list(board.Zones())
    acc = FromMM(via / 2 + clear)
    others = [t for t in board.GetTracks()
              if t.GetNetCode() != gnd.GetNetCode() or t.Type() == pcbnew.PCB_VIA_T]
    pads = [p for fp in board.GetFootprints() for p in fp.Pads()]
    n = 0
    y = 2.5
    while y < H - 2.0:
        x = 2.5
        while x < W - 2.0:
            pt = P(x, y)
            bx, by = CAT_AT
            kx0, ky0, kx1, ky1 = CAT_KEEPOUT
            if bx + kx0 - 1 < x < bx + kx1 + 1 and by + ky0 - 1 < y < by + ky1 + 1:
                x += pitch
                continue
            ok = all(z.HitTestFilledArea(z.GetLayer(), pt, FromMM(via / 2 + 0.1)) for z in zones)
            ok = ok and not any(t.HitTest(pt, acc) for t in others)
            ok = ok and not any(p.HitTest(pt, FromMM(via / 2 + 0.5)) or
                                (p.GetDrillSize().x and
                                 (p.GetPosition() - pt).EuclideanNorm() < p.GetDrillSize().x / 2 + FromMM(via / 2 + 0.6))
                                for p in pads)
            if ok:
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(pt)
                v.SetWidth(FromMM(via))
                v.SetDrill(FromMM(drill))
                v.SetNet(gnd)
                board.Add(v)
                n += 1
            x += pitch
        y += pitch
    return n


def run(cmd):
    print("$", " ".join(cmd))
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, env=HEADLESS_ENV, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
    return r


def outputs(board):
    out = os.path.join(HERE, "out")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    # netlist table from the board itself
    with open(os.path.join(HERE, "netlist.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["net", "pads"])
        bynet = {}
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetNumber():
                    nn = pad.GetNetname() or "(unconnected)"
                    bynet.setdefault(nn, []).append("%s.%s" % (fp.GetReference(), pad.GetNumber()))
        def k(p):
            import re as _re
            r, n = p.split(".")
            a, b = _re.match(r"([A-Z]+)(\d+)", r).groups()
            return (a, int(b), int(n))
        for nn in sorted(bynet):
            w.writerow([nn, " ".join(sorted(bynet[nn], key=k))])
    # BOM
    groups = {}
    for ref, (spec, x, y, rot, value, desc, pn) in PARTS.items():
        if ref.startswith("H"):
            continue
        spec = ALIASES.get(spec, spec)
        key = (value, desc if not ref.startswith("R") else "resistor, 1/4 W metal film 1 %", pn, spec, ref in DNP)
        groups.setdefault(key, []).append(ref)
    with open(os.path.join(HERE, "bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["qty", "refs", "value", "description", "part number", "footprint", "fit"])
        for (value, desc, pn, spec, dnp), refs in sorted(groups.items(), key=lambda kv: kv[1][0]):
            w.writerow([0 if dnp else len(refs), " ".join(refs), value, desc,
                        pn or ("Yageo MFR-25FBF52-" + value.replace("R", "R").replace("k", "K") if refs[0].startswith("R") else ""),
                        spec.replace("custom:", "carrier:"), "DNP" if dnp else "fit"])
        # the boards and modules that plug in (not soldered)
        w.writerow([])
        w.writerow(["qty", "plug-in", "value", "description", "part number", "", ""])
        for row in [
            (1, "J1", "Icepi Zero", "ECP5 FPGA board playing the chip (v1.3/v1.4)", "cheyao Icepi Zero (Elecrow)"),
            (2, "U1 U2", "Pico H", "Raspberry Pi Pico H, headers fitted", "Raspberry Pi SC0917"),
            (2, "J4 J6", "CAN board", "Waveshare SN65HVD230 CAN Board", "Waveshare SKU 3945"),
            (1, "U4", "flash", "Adafruit QSPI DIP breakout W25Q64", "Adafruit 5633"),
            (1, "J10", "EEPROM", "DFRobot Gravity 24LC256 I2C EEPROM module + Gravity-to-dupont cable", "DFRobot DFR0117"),
            (1, "J11", "MagJack", "PJRC Ethernet Kit for Teensy 4.1 (with its ribbon cable)", "PJRC ETHERNET_KIT"),
            (1, "JP1", "shunt", "2.54 mm jumper cap for the CAN terminator (cap on = terminated)", "BOOMELE C100114"),
            (4, "H1-H4", "M3", "M3 standoff + screw (corners)", "generic"),
            (4, "H5-H8", "M2.5", "optional M2.5 standoffs under the Icepi, height = socket stack", "generic"),
        ]:
            w.writerow(list(row) + ["", ""])

    pcb = PCB
    gdir = os.path.join(out, "gerbers")
    os.makedirs(gdir)
    run(["kicad-cli", "pcb", "export", "gerbers", "-o", gdir + "/", "--layers",
         "F.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts",
         "--subtract-soldermask", pcb])
    run(["kicad-cli", "pcb", "export", "drill", "-o", gdir + "/", "--format", "excellon",
         "--excellon-separate-th", "--generate-map", "--map-format", "gerberx2", pcb])
    zp = os.path.join(HERE, NAME + "_jlcpcb_gerbers.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in sorted(os.listdir(gdir)):
            z.write(os.path.join(gdir, fn), fn)
    rdir = os.path.join(HERE, "renders")
    shutil.rmtree(rdir, ignore_errors=True)
    os.makedirs(rdir)
    for side in ("top", "bottom"):
        run(["kicad-cli", "pcb", "render", "--side", side, "--width", "2400", "--height", "2400",
             "--quality", "high", "-o", os.path.join(rdir, "render_%s.png" % side), pcb])
    for name, layers in [("F_Cu", "F.Cu,Edge.Cuts"), ("B_Cu", "B.Cu,Edge.Cuts"),
                         ("F_Silk", "F.Silkscreen,Edge.Cuts"), ("B_Silk", "B.Silkscreen,Edge.Cuts"),
                         ("F_Cu_Silk", "F.Cu,F.Silkscreen,Edge.Cuts"), ("Fab", "F.Fab,F.Silkscreen,Edge.Cuts")]:
        svg = os.path.join(rdir, name + ".svg")
        run(["kicad-cli", "pcb", "export", "svg", "--layers", layers, "--mode-single",
             "--page-size-mode", "2", "--exclude-drawing-sheet", "-o", svg, pcb])
        pdf = os.path.join(rdir, name + ".pdf")
        run(["kicad-cli", "pcb", "export", "pdf", "--layers", layers, "--mode-single", "-o", pdf, pcb])
        if os.path.exists(pdf):
            pdf_png(pdf, os.path.join(rdir, name + ".png"))
            os.remove(pdf)


def pdf_png(pdf, png, dpi=250):
    """Rasterise a KiCad A4 plot and crop it to the board."""
    from PIL import Image
    base = png[:-4]
    run(["pdftoppm", "-png", "-r", str(dpi), "-singlefile", pdf, base])
    im = Image.open(png)
    k = dpi / 25.4
    im.crop((int((OX - 2) * k), int((OY - 2) * k), int((OX + W + 2) * k), int((OY + H + 2) * k))).save(png)


def drc():
    rep = os.path.join(HERE, "drc.json")
    run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--units", "mm",
         "-o", rep, PCB])
    run(["kicad-cli", "pcb", "drc", "--format", "report", "--severity-all", "--units", "mm",
         "-o", os.path.join(HERE, "drc.rpt"), PCB])
    j = json.load(open(rep))
    errs = [v for v in j.get("violations", []) if v["severity"] == "error"]
    warns = [v for v in j.get("violations", []) if v["severity"] == "warning"]
    unc = j.get("unconnected_items", [])
    print("DRC: %d errors, %d warnings, %d unconnected" % (len(errs), len(warns), len(unc)))
    from collections import Counter
    print(" errors:", Counter(v["type"] for v in errs))
    print(" warnings:", Counter(v["type"] for v in warns))
    return errs, warns, unc


def main():
    force = "--reroute" in sys.argv
    board, fps, nets = build()
    pcbnew.SaveBoard(PCB, board)
    if "--place-only" in sys.argv:
        pdf = os.path.join(HERE, "place.pdf")
        run(["true", "pcb", "export", "pdf", "--layers", "F.Cu,F.Silkscreen,F.Fab,F.Courtyard,Edge.Cuts",
             "--mode-single", "-o", pdf, PCB])
        pdf_png(pdf, os.path.join(HERE, "place.png"))
        return
    ses = route(force)
    board = pcbnew.LoadBoard(PCB)
    if not pcbnew.ImportSpecctraSES(board, ses):
        raise SystemExit("SES import failed")
    nets = {n: board.FindNet(n) for n in NETS}
    drop_dangling_vias(board)
    add_zones(board, nets)
    fill(board)
    print("stitching vias:", stitch(board, nets))
    fill(board)
    pcbnew.SaveBoard(PCB, board)
    drc()
    if "--no-out" not in sys.argv:
        outputs(pcbnew.LoadBoard(PCB))


if __name__ == "__main__":
    main()
