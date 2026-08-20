# Not a package anyone imports: the scripts here reach each other through the directory this
# file sits in. It exists because pytest's default import mode names a test module after its
# file's basename, and two skills deliberately carry an identical test_secret_detect.py.
# Marking this directory a package lengthens the name of every test module under it, so the
# two no longer collide when the whole tree is collected in one run.
