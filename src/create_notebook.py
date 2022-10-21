"""
Generate data extraction notebook.

Executes jupytext in the OS in order to generate the data extraction notebook
from the supplied python script.

A notebook is required for this stage due to the various manual interventions
necessary to extract the data.

This is the first procedure to execute.
"""

import subprocess
from pathlib import Path


def main():
    """Generate data extraction notebook."""
    this_script_dir = Path(__file__).resolve().parent
    subprocess.run(
        "jupytext --to notebook extract_satellite_imagery.py", cwd=this_script_dir
    )


if __name__ == "__main__":
    main()
