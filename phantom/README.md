# ICRP data goes here

Nothing in this directory is distributed with the toolkit. ICRP Publication 145
is copyright ICRP, all rights reserved; the phantom must be obtained from ICRP.
See `../REQUIREMENTS.md` for the download link.

Expected layout:

    phantom/MRCP_AM/MRCP_AM.ele  .node  _media.dat  _bone.dat  _blood.dat
    phantom/MRCP_AF/MRCP_AF.ele  .node  _media.dat  _bone.dat  _blood.dat
    phantom/mcnp_tables/mrcp-am.cell  mrcp-am.material
                        mrcp-af.cell  mrcp-af.material

`setup_data.py` builds that layout from the archive as downloaded, and remembers
the location, so the data need not be here at all:

    python3 setup_data.py ~/Downloads/P145*.zip
    python3 setup_data.py /some/folder
    python3 setup_data.py --status

`python3 selftest.py` reports whether the files are where the code expects them.
