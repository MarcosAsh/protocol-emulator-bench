#!/usr/bin/env python3
"""JLCPCB through-hole assembly files for the carrier: BOM, CPL and a cost/stock note.

Reads ../carrier.kicad_pcb (run ../gen.py first), checks each LCSC part's live stock on
jlcpcb.com's parts search, and writes jlc_bom.csv, jlc_cpl.csv, parts_check.csv, assembly_note.txt.
Headless: pcbnew and kicad-cli only.
"""
import csv, os, subprocess, sys
import pcbnew
from jlcparts import search

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(HERE, "..", "carrier.kicad_pcb")
OX, OY, H = 50.0, 40.0, 100.0     # gen.py board origin and height

# ref group -> (comment, LCSC part). Everything soldered on the board; modules stay owner-fitted.
LCSC = [
    ("J1", "2x20 female header 2.54 mm 8.5 mm (Icepi)", "C5124634"),
    ("J13 J14 J15 J16", "1x20 female header 2.54 mm 8.5 mm (Pico sockets)", "C2905423"),
    ("J4 J6", "1x4 female header 2.54 mm (Waveshare CAN boards)", "C2718488"),
    ("J2 J3", "1x9 male header 2.54 mm (analysers)", "C27985193"),
    ("J10 J12", "1x4 male header 2.54 mm", "C32713270"),
    ("J8 J9", "1x3 male header 2.54 mm", "C49257"),
    ("J5 J7", "1x2 male header 2.54 mm (CANH/CANL)", "C42431798"),
    ("J11", "2x3 male header 2.00 mm (PJRC Ethernet kit cable)", "C32713234"),
    ("U3", "DIP-14 IC socket 7.62 mm (74AHCT125 goes in by hand)", "C2325"),
    ("U4", "DIP-8 IC socket 7.62 mm (Adafruit flash breakout goes in by hand)", "C72124"),
    ("U5", "DS18B20+ TO-92", "C9753"),
    ("R14 R15", "47R 1/4W 1% metal film", "C58604"),
    ("R11 R12", "220R 1/4W 1% metal film", "C57439"),
    ("R4", "330R 1/4W 1% metal film", "C58608"),
    ("R16", "470R 1/4W 1% metal film", "C58592"),
    ("R8 R9 R10 R17 R18 R19", "1k 1/4W 1% metal film", "C57435"),
    ("R1", "120R 1/4W 1% metal film (CAN terminator, via JP1)", "C58619"),
    ("JP1", "1x2 male header 2.54 mm (CAN terminator jumper)", "C42431798"),
    ("J17", "1x4 male header 2.54 mm (spare I2C)", "C32713270"),
    ("D1 D2", "3 mm green LED (3V3_A, 3V3_B)", "C181864"),
    ("D3", "3 mm red LED (5V_A)", "C84774"),
    ("SW1", "6x6 mm THT tactile switch, 5 mm (REPLUG)", "C110153"),
    ("TP1 TP2 TP3", "Keystone 5001 black test point (GND)", "C238122"),
    ("TP4 TP5 TP6 TP7 TP8", "Keystone 5002 white test point (CANH CANL DQ SDA SCL)", "C238123"),
    ("R5 R6", "2k2 1/4W 1% metal film", "C58595"),
    ("R7 R13", "4k7 1/4W 1% metal film", "C57204"),
    ("R2 R3", "10k 1/4W 1% metal film", "C57436"),
    ("C1 C3", "10uF 25V X5R leaded MLCC 5.08 mm", "C2761733"),
    ("C2 C4 C5", "100nF 50V X7R leaded MLCC 2.54 mm", "C168753"),
]
NOT_ASSEMBLED = {}
OWNER_FITTED = [
    "jumper cap on JP1 (LCSC C100114, order loose with the boards; on = 120R across CANH/CANL)",
    "Icepi Zero (into J1), face down: chip and USB-C toward the carrier, buttons up",
    "2x Raspberry Pi Pico H SC0917 (into J13/J14 and J15/J16)",
    "2x Waveshare SN65HVD230 CAN Board SKU 3945 (into J4, J6) + 4 jumper wires J5/J7 to their CANH/CANL",
    "TI SN74AHCT125N (into the U3 socket)",
    "Adafruit 5633 W25Q64 DIP breakout (into the U4 socket)",
    "DFRobot DFR0117 EEPROM (Gravity cable dupont ends onto J10)",
    "PJRC ETHERNET_KIT MagJack board (ribbon cable onto J11)",
    "Pico debug cable jumper ends onto J8, NeoPixel lead onto J9",
    "M3 standoffs (H1-H4), optional M2.5 standoffs under the Icepi (H5-H8)",
]


def main():
    board = pcbnew.LoadBoard(PCB)
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    refs_in_bom = [r for g, _, _ in LCSC for r in g.split()]
    missing = [r for r in fps if not r.startswith("H") and r not in refs_in_bom and r not in NOT_ASSEMBLED]
    if missing:
        sys.exit("footprints without an LCSC part: %s" % missing)

    # BOM, JLC columns
    with open(os.path.join(HERE, "jlc_bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for group, comment, code in LCSC:
            refs = group.split()
            fpname = fps[refs[0]].GetFPID().GetLibItemName().wx_str()
            w.writerow([comment, ",".join(refs), fpname, code])

    # CPL: centre of the pads (the part body), board mm with y up from the bottom-left corner
    with open(os.path.join(HERE, "jlc_cpl.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for ref in refs_in_bom:
            fp = fps[ref]
            pads = [p.GetPosition() for p in fp.Pads()]
            x = sum(pcbnew.ToMM(p.x) for p in pads) / len(pads) - OX
            y = OY + H - sum(pcbnew.ToMM(p.y) for p in pads) / len(pads)
            w.writerow([ref, "%.3fmm" % x, "%.3fmm" % y, "Top", "%g" % (fp.GetOrientationDegrees() % 360)])
    # KiCad's own position file (footprint origins) for reference
    subprocess.run(["kicad-cli", "pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "front",
                    "--use-drill-file-origin", "--exclude-dnp", "-o", os.path.join(HERE, "kicad_pos_origins.csv"), PCB],
                   check=True, capture_output=True,
                   env={k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")})

    # live stock and cost
    joints = 0
    parts_cost = 0.0
    rows = []
    for group, comment, code in LCSC:
        refs = group.split()
        n = len(refs)
        pads = sum(len([p for p in fps[r].Pads() if p.GetNumber()]) for r in refs)
        joints += pads
        hit = [c for c in search(code, 3) if c["lcsc"] == code]
        c = hit[0] if hit else {}
        price = c.get("price1") or 0.0
        parts_cost += n * price
        rows.append([group, n, code, c.get("brand", "?"), c.get("mfr", "?"),
                     {"base": "basic", "expand": "extended"}.get(c.get("type"), c.get("type", "?")),
                     c.get("stock", "?"), price, pads])
    with open(os.path.join(HERE, "parts_check.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["designators", "qty per board", "LCSC", "brand", "mfr part", "JLC library", "stock now",
                    "unit price USD (1+)", "THT joints"])
        w.writerows(rows)

    boards = 2   # JLC's minimum assembled quantity
    setup, stencil_note = 25.56, 8.21
    per_joint = 0.0164
    labour = joints * per_joint
    lines = [
        "JLCPCB through-hole assembly estimate (not a quote; check the live quote before ordering)",
        "pricing source: jlcpcb.com/help/article/pcb-assembly-price, read 2026-10-06",
        "",
        "THT solder joints per board: %d (%d parts on %d LCSC lines)" % (joints, len(refs_in_bom), len(LCSC)),
        "parts per board at 1+ prices: $%.2f" % parts_cost,
        "manual THT soldering: %d joints x $%.4f = $%.2f per board" % (joints, per_joint, labour),
        "setup fee (single side): $%.2f per order" % setup,
        "stencil: $%.2f only if JLC insists for a THT-only job (no SMD parts here)" % stencil_note,
        "extended-part feeder loading ($1.53 each) is listed for SMT; likely not charged for hand-fitted THT",
        "",
        "for %d boards: setup $%.2f + parts $%.2f + soldering $%.2f = about $%.0f, plus the bare PCBs and shipping"
        % (boards, setup, boards * parts_cost, boards * labour, setup + boards * (parts_cost + labour)),
        "",
        "every part is a JLC 'extended' part (connectors, sockets and THT passives are never basic)",
        "",
        "not assembled: %s" % (", ".join("%s (%s)" % kv for kv in NOT_ASSEMBLED.items()) or "nothing, every footprint is fitted"),
        "", "owner-fitted after delivery:"] + \
        ["  " + s for s in OWNER_FITTED] + [
        "",
        "notes:",
        "  CPL Mid X/Y is the centre of each part's pads, board mm from the bottom-left corner, y up.",
        "  THT connector rotations often need a nudge in JLC's placement preview; check pin 1 of",
        "  J1, J13-J16, U3, U4 and U5 there before paying.",
    ]
    open(os.path.join(HERE, "assembly_note.txt"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
