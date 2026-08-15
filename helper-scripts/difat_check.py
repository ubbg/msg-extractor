"""
Verifies the DIFAT sector arithmetic used by `OleWriter._writeBeginning`.

The writer lays the file out as [header][DIFAT sectors][FAT sectors][...]. The
header carries the first 109 DIFAT entries; every additional DIFAT sector holds
127 entries plus a pointer to the next DIFAT sector. This script replays the
entry emission of `ole_writer.py` for a range of sector counts and compares the
number of entries actually written against the number the header declares room
for, reporting any output size where the two disagree.

Run with no arguments to check sector counts 1..59999, or pass an upper bound.
"""

__all__ = [
    'difatEntriesEmitted',
    'fatSectors',
    'findMismatches',
]


import sys

from typing import List, Tuple


# Values for a version 3 (512 byte sector) file, matching OleWriter defaults.
LINKS_PER_SECTOR = 128
HEADER_DIFAT_ENTRIES = 109


def ceilDiv(n: int, d: int) -> int:
    """
    Ceiling division, matching `extract_msg.utils.ceilDiv`.
    """
    return -(n // -d)


def fatSectors(numberOfSectors: int) -> Tuple[int, int]:
    """
    Replays `OleWriter._getFatSectors`, returning the number of FAT sectors and
    the number of DIFAT sectors needed for the given data sector count.
    """
    numDifat = 0
    numFat = ceilDiv(numberOfSectors or 1, LINKS_PER_SECTOR - 1)
    newNumFat = 1
    while numFat != newNumFat:
        numFat = newNumFat
        numDifat = ceilDiv(max(numFat - HEADER_DIFAT_ENTRIES, 0), LINKS_PER_SECTOR - 1)
        newNumFat = ceilDiv(numberOfSectors + numDifat, LINKS_PER_SECTOR - 1)

    return (numFat, numDifat)


def difatEntriesEmitted(numFat: int) -> int:
    """
    Counts the 4 byte entries that `OleWriter._writeBeginning` writes for the
    header DIFAT array and the DIFAT sectors, for the given FAT sector count.
    """
    entries = 0
    for x in range(numFat):
        # The jump to the next DIFAT sector, written before the entry that
        # starts it.
        if x > HEADER_DIFAT_ENTRIES and (x - HEADER_DIFAT_ENTRIES) % (LINKS_PER_SECTOR - 1) == 0:
            entries += 1
        # The FAT sector location itself.
        entries += 1

    # Filling out the final DIFAT sector.
    if numFat > HEADER_DIFAT_ENTRIES:
        entries += (LINKS_PER_SECTOR - 1) - ((numFat - HEADER_DIFAT_ENTRIES) % (LINKS_PER_SECTOR - 1))
        entries += 1
    else:
        entries += HEADER_DIFAT_ENTRIES - numFat

    return entries


def findMismatches(limit: int) -> List[Tuple[int, int, int, int, int]]:
    """
    Returns a list of (numberOfSectors, numFat, numDifat, emitted, expected) for
    every sector count below the limit where the emitted entry count does not
    match the space the header accounts for.
    """
    mismatches = []
    for numberOfSectors in range(1, limit):
        numFat, numDifat = fatSectors(numberOfSectors)
        emitted = difatEntriesEmitted(numFat)
        expected = HEADER_DIFAT_ENTRIES + numDifat * LINKS_PER_SECTOR
        if emitted != expected:
            mismatches.append((numberOfSectors, numFat, numDifat, emitted, expected))

    return mismatches


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 60000
    mismatches = findMismatches(limit)

    print(f'Checked sector counts 1..{limit - 1}.')
    print(f'Mismatches: {len(mismatches)}')

    if not mismatches:
        print('DIFAT arithmetic is consistent over the checked range.')
        return

    print(f'FAT sector counts affected: {sorted({x[1] for x in mismatches})}')

    first = mismatches[0]
    print(f'First failure: numberOfSectors={first[0]}, numFat={first[1]}, '
          f'numDifat={first[2]}, emitted={first[3]} entries, '
          f'expected={first[4]} entries, overflow={(first[3] - first[4]) * 4} bytes')

    # Group the failures into contiguous runs so the affected size ranges are
    # easy to read.
    sectorCounts = [x[0] for x in mismatches]
    runs = []
    start = previous = sectorCounts[0]
    for sectorCount in sectorCounts[1:]:
        if sectorCount != previous + 1:
            runs.append((start, previous))
            start = sectorCount
        previous = sectorCount
    runs.append((start, previous))

    print('Affected output sizes:')
    for low, high in runs:
        # The header occupies one sector worth of space before sector 0.
        print(f'  sectors {low}-{high} => {((low + 1) * 512) / 1048576:.2f} MB '
              f'- {((high + 1) * 512) / 1048576:.2f} MB')


if __name__ == '__main__':
    main()
