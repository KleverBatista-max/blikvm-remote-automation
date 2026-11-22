#!/usr/bin/env python3
"""Log in and click at a screen coordinate of the remote machine:  python click.py 847 530"""
import sys

from blikvm import BliKVM

if len(sys.argv) != 3:
    sys.exit(__doc__)
r = BliKVM().login().click(int(sys.argv[1]), int(sys.argv[2]))
print("click:", r.status_code)
