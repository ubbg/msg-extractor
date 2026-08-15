Just a collection of helper scripts for the development of the module.

detect-prop-overlap.py: A script to detect properties in a file that are using the same name or property ID. Looks for instances of `_ensureSetX` to find conflicts and outputs a list of anything that is duplicated. Takes in the path to a file.

difat_check.py: A script to verify the DIFAT sector arithmetic used by `OleWriter._writeBeginning`. Replays the entry emission for a range of sector counts and reports any output size where the number of entries written disagrees with the space the header accounts for. Takes an optional upper bound for the sector count.
