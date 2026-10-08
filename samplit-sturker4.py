import sys
import random

filename = sys.argv[1] #different tiny change

with open(filename) as f:
    for line in f:
        if random.random() < 0.01:
            print(line, end="")
