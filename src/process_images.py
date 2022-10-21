"""
Procedure to execute the required preprocessing and chipping of images.

Script can be executed in two modes:
  1) Normal mode
  2) Chip focussed mode.

Normal mode must be executed first and includes:
    - Add a no data layer to all S2 images.
    - Create a grid shapefile in order to chip images into tiles.
    - Generate the chipped images for a single date.
    - Calculate the temporal mean across all dates and generate temporal
      mean chip images.

Chip focus model focusses on generating the chips for a specific date (with date
controlled by "date" parameter). This should only be used when the full
functionality of this script in normal mode has been previously run and the
necessary grid shapefile exist.
"""
# Standard library
from pathlib import Path

# Third party
import rasterio as rio

# Project
from data_processing.image_processing import (
    add_nodata_layer,
    create_chips_from_grid,
    create_road_buffer_shp_file,
    create_temporal_chips_from_grid,
    generate_grid_shp,
)
from utils.file_handling import generate_file_list, set_data_dir

## Third Party
from yaml import Loader, load


def main(location: str = None, date: str = None, chip_focussed: str = None):
    """
    Procedure to execute the required preprocessing and chipping of images.

    These steps include:
        - Add a no data layer to S2 images.
        - Create a grid shapefile in order to chip images into tiles.
        - Generate the chipped images for a single date.
        - Calculate the temporal mean across all dates and generate temporal
          mean chip images.

    Parameters
    ----------
    location : str, optional
        String representing location of interest. By default value extracted from
        config.yaml .
    date : str, optional
        The observation date of any one of the extracted S2 images in yyyy-MM-dd format.
        In normal execution, the choice of date is inconsequential, but it must
        match one of the images. Defaults to parameter defined in config.yaml .
        If executing in "chip focussed" mode this date parameter specifies which
        image date to chip.
    chip_focussed : str, optional
        If True, subroutine executed which focusses on generating the chips for a
        specific date (date controlled by "date" parameter). If False,
        full process executes generating the required grid shapefiles etc and
        chips on date parameter.
        This should only be used when the full functionality of this script has
        been previously run and the necessary grid shapefile exist.

    Raises
    ------
    AttributeError
        Error raised if "location" or "date" variables cannot be found.

    """
    data_dir = Path(__file__).resolve().parent.parent.joinpath("data", location)
    raw_img_dir = data_dir.joinpath("raw", "s2_images")
    processed_data_dir = data_dir.joinpath("processed")
    img_dir = set_data_dir(processed_data_dir, "s2_images")
    chips_dir = set_data_dir(processed_data_dir, "chips")
    chips_temporal_dir = set_data_dir(chips_dir, "temporal_mean_imgs")
    if not location or not date:
        raise AttributeError(
            'You have not specified a location and date. Check script call help by executing "python image_processing.py -h"'
        )

    # If True, execute subroutine that generates chips for a specific date.
    if chip_focussed:
        img_file = img_dir.joinpath(f"s2a_{location}_{date}.tif")
        chips_img_dir = set_data_dir(chips_dir, date + "_chip_imgs")
        create_chips_from_grid(
            raster_file=img_file,
            grid_shp_fp=chips_dir.joinpath(f"grids_use_{location}.shp"),
            chip_output_fp=chips_img_dir.joinpath(f"s2a_{location}_{date}_"),
        )

    # Otherwise, execute full procedure of image processing.
    else:
        print("Removing the non-road portions of the images.")
        add_nodata_layer(location, raw_img_dir, img_dir)
        img_file = img_dir.joinpath(f"s2a_{location}_{date}.tif")
        create_road_buffer_shp_file(img_file, location, processed_data_dir)

        raster_list = generate_file_list(img_dir, "tif", [location])
        print("Labelling bands in rasters.")
        for raster in raster_list:
            with rio.open(raster, "r+") as img:
                img.descriptions = tuple(
                    ["Blue", "Green", "Red", "Cloud", "Cloud Shadow"]
                )

        print("\nGenerating the grid shapefile for chipping.")
        generate_grid_shp(
            raster_file=img_file,
            road_buffershp_fp=processed_data_dir.joinpath(
                f"road_buffer_{location}.shp"
            ),
            output_path=chips_dir,
            output_file=f"grids_use_{location}.shp",
            dimensions_metres=1280,
            interval_metres=640,
            clip_grid_to_img=True,
        )
        print("\nGenerated grid shapefile.")

        chips_img_dir = set_data_dir(chips_dir, date + "_chip_imgs")
        create_chips_from_grid(
            raster_file=img_file,
            grid_shp_fp=chips_dir.joinpath(f"grids_use_{location}.shp"),
            chip_output_fp=chips_img_dir.joinpath(f"s2a_{location}_{date}_"),
        )
        print("\nGenerated chipped image files.")

        imgs = generate_file_list(img_dir, "tif", [location])

        create_temporal_chips_from_grid(
            img_file_list=imgs,
            chips_temporal_dir=chips_temporal_dir,
            grid_shp_fp=chips_dir.joinpath(f"grids_use_{location}.shp"),
            output_partial_filename=f"s2a_{location}_temporal_mean_",
        )
        print("\nGenerated temporal mean chipped image files.")

        single_observation_chips = generate_file_list(
            chips_img_dir, "tif", [location, date]
        )
        temporal_mean_chips = generate_file_list(
            chips_temporal_dir, "tif", [location, "temporal_mean"]
        )

        # Check the number of chipped images and temporal mean chipped images are equal
        print(
            f"There are {len(single_observation_chips)} chips for the single date "
            f"processed and {len(temporal_mean_chips)} temporal chips."
            f"These are expected to be equal."
        )


def mk_arg_pars():
    """
    Create a comand line arg parse.

    Returns
    -------
    _dict_
        Argparse argument dictionary containing either user inputted args or
        default values extracted from config file.
    """
    import argparse

    config_file = Path(__file__).resolve().parent.joinpath("config.yaml")
    params = load(open(config_file), Loader=Loader)

    parser = argparse.ArgumentParser(
        description="Process image and chip into smaller extents."
    )
    parser.add_argument(
        "-l",
        "--location",
        default=params["location"],
        help=(
            "The string representing the location of interest, as used in image"
            " extraction file naming. Defaults to parameter defined in config.yaml ."
        ),
    )
    parser.add_argument(
        "-d",
        "--date",
        default=str(params["single_date"]),
        help=(
            "The observation date of any one of the extracted S2 images in yyyy-MM-dd format."
            " In normal execution, the choice of date is inconsequential, but it must match one of the images."
            ' Defaults to parameter defined in config.yaml . If executing in "chip focussed" mode'
            " this date parameter specifies which image date to chip."
        ),
    )
    parser.add_argument(
        "-chip_focussed",
        "--chip_focussed",
        default=None,
        help=(
            "If called, will chip the specified date in the -d 'date' parameter."
            " This option is designed for when it is desired to chip a specific image."
            " This should only be used when the full functionality of this script has"
            " been previously run and the necessary grid shapefile exist."
        ),
    )
    args_pars = parser.parse_args()
    return vars(args_pars)


if __name__ == "__main__":
    run_dict = mk_arg_pars()
    main(**run_dict)
