#!/usr/bin/env python3

import sys

if len(sys.argv) == 1:
	print('Usage:', sys.argv[0], '<dictionary filename>')
	sys.exit(1)

print('COPY highlights(guild, "user", highlight) FROM stdin;')
with open(sys.argv[1]) as f:
	for line in f:
		print(473721145057607710, 140516693242937345, line.rstrip(), sep='\t')
print('\.')
