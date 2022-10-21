"""
Collection of functions for handling commonly needed file related procedures.
Including:
- generate a list of files based on some parameters
- generate a named subdirectory on OS and output path to it
"""

from pathlib import Path
from typing import List, Tuple


def generate_file_list(
    data_dir: Path, file_extension: str, keyword_list: list
) -> List[Path]:
    """
    Generate a list of detected files.

    Returns list of files containing given keywords, of given file extension
    in the given directory.

    Parameters
    ----------
    data_dir : pathlib.Path
        Directory to search for files in.
    file_extension : str
        The file extension of the desired files, without the dot ".".
        (e.g. "tif" or "png" or "txt").
    keyword_list : list(str)
        List of keyword(s) that should be present in selected file names.

    Returns
    -------
    file_list : list(pathlib.Path)
        List of files containing given keywords, of given file extension
        in the given directory.

    Raises
    ------
    FileNotFoundError
        Error returned if empty list generated while executing procedure.
        If this happens, check searching in the correct place and correct
        search terms are in file_extension and keyword_list.

    """
    file_list = [
        file
        for file in list(data_dir.glob(f"*.{file_extension}"))
        if all(keyword in file.name for keyword in keyword_list)
    ]
    if file_list:
        return file_list
    else:
        message = (
            f"No files were found of extension '.{file_extension}' with "
            f"{keyword_list} in the name in the directory {data_dir}."
        )
        raise FileNotFoundError(message)


def set_data_dir(data_dir: Path, sub_dir_name: str) -> Path:
    """
    Check if subdirectory of given name exists and create if not, return path.

    Parameters
    ----------
    data_dir : pathlib.Path
        Path to current data directory.
    sub_dir_name : str
        Name of desired subdirectory within data directory.

    Returns
    -------
    sub_dir : pathlib.Path
        Path to the newly created, or pre-existing, subdirectory of given name.

    """
    sub_dir = data_dir.joinpath(sub_dir_name)
    if not sub_dir.is_dir():
        sub_dir.mkdir(parents=True, exist_ok=True)
    return sub_dir


def set_up_data_structure(location: str) -> Tuple[Path, Path]:
    """
    Generate subdirs in data dir based on location string and relocate file.

    Parameters
    ----------
    location : str
        The user defined string representing location of interest. This must match
        the filename for the PBF file extracted (which should have been renamed).

    Returns
    -------
    tuple(Path, Path)
        Directories generated in system's file system and data file located to
        "data/<location>/raw/." position. Path to this newly located data file
        and path to the "data/<location" directory returned.

    Raises
    ------
    FileNotFoundError
        If file not found in top level data directory as expected with name matching
        format "<location_str>.osm.pbf"

    """
    # Define data directory path
    data_dir = Path.cwd().parent.joinpath("data")

    # Relocate newly downloaded file into "<loc_data_dir>/raw" directory
    pbf_file = data_dir.joinpath(f"{location}.osm.pbf")

    if not pbf_file.exists() and not data_dir.joinpath(location).is_dir():
        raise FileNotFoundError(
            f"The osm.pbf file was not found in the data directory. This is likely because the file "
            f'name does not match the location variable above (i.e. "{location}"). Ensure you have named your '
            f'file "{location}.osm.pbf" or redefine the location variable to match your file name. \nAlternatively, '
            f"your file may be saved in the wrong location; expected location: {data_dir}."
        )

    # Create location specific data subdirectory
    loc_data_dir = set_data_dir(data_dir, location)

    # Create raw subdirectory in location data directory
    raw_dir = set_data_dir(loc_data_dir, "raw")
    raw_pbd_file = raw_dir.joinpath(pbf_file.name)
    set_data_dir(raw_dir, "s2_images")

    processed_data_dir = set_data_dir(loc_data_dir, "processed")
    set_data_dir(processed_data_dir, "s2_images")

    try:
        pbf_file.replace(raw_dir.joinpath(pbf_file.name))
    except FileNotFoundError:
        if raw_pbd_file.exists():
            pass
        else:
            raise FileNotFoundError(
                f"The osm.pbf file was not found in the data directory. This is likely because the file "
                f'name does not match the location variable above (i.e. "{location}"). Ensure you have named your '
                f'file "{location}.osm.pbf" or redefine the location variable to match your file name. \nAlternatively, '
                f"your file may be saved in the wrong location; expected location: {data_dir}."
            ) from None

    return raw_pbd_file, processed_data_dir
