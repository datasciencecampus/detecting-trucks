"""
Script for executing feature engineering to generate custom training features data.

Calculate feature values for labelled truck and non-truck training points
in the training images. Save output to generate a dataset of features for
training the classifier model.

This is intended to be run subsequent to the image processing stage and prior to
the model training stage.

This is an optional step and not needed if using the pre-supplied training data.
"""

from pathlib import Path
from typing import List

## Third Party
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio as rio

## Project
from data_processing.image_processing import create_temporal_chips_from_grid
from shapely.geometry import box
from truck_detection.feature_engineering import generate_training_data
from utils.file_handling import generate_file_list

## Third Party
from yaml import Loader, load


def save_training_features(
    training_features: pd.DataFrame,
    stacked_imgs: List[np.ndarray],
    data_dir: Path,
    location: str,
):
    """Write feature values to csv and stacked image to numpy compressed zip file."""
    training_features.to_csv(
        data_dir.joinpath(f"{location}_training_features.csv"), index=False
    )
    stacked_imgs = np.stack(stacked_imgs)
    np.savez_compressed(
        data_dir.joinpath(f"{location}_stacked_img.npz"),
        stacked_imgs=stacked_imgs,
    )


def main(location: str = None, num_trucks: str = None):
    training_data_dir = (
        Path(__file__)
        .resolve()
        .parent.parent.joinpath("data", location, "processed", "training")
    )

    imgs = generate_file_list(
        training_data_dir,
        "tif",
        [location],
    )

    with rio.open(imgs[0]) as img:
        bounds = img.bounds
    geom = box(*bounds)
    data_dir = Path(__file__).resolve().parent.parent.joinpath("data", location)
    training_dir = data_dir.joinpath("processed", "training")
    if num_trucks:
        df = pd.read_csv(training_dir.joinpath(f"{location}_training_features.csv"))
        print(f"Number of labelled trucks in training data: {int(df.ml_class.sum())}")
    else:
        gdf = gpd.GeoDataFrame({"location": "training_area", "geometry": [geom]})
        gdf.to_file(training_dir.joinpath("training_area_boundary.shp"))
        img_dir = data_dir.joinpath("processed", "s2_images")
        raster_list = generate_file_list(img_dir, "tif", [location])
        create_temporal_chips_from_grid(
            raster_list,
            training_dir,
            training_dir.joinpath("training_area_boundary.shp"),
            f"s2a_{location}_temporal_mean_",
        )

        validation_points = generate_file_list(
            training_data_dir, "shp", ["training_points", location]
        )

        #!! Ensure listed in date order or subsequent steps below will be incorrect
        sorting_index = np.array([file.name for file in validation_points]).argsort()
        validation_points = list(np.array(validation_points)[sorting_index])

        training_points, stacked_imgs = generate_training_data(
            validation_points, location, data_dir=training_dir
        )
        training_points["location"] = location

        save_training_features(training_points, stacked_imgs, training_dir, location)


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
        "-n_trucks",
        "--num_trucks",
        default=None,
        help=(
            'An optional argument with the affect of setting value to "yes" to print '
            "the total number of labelled trucks in the training data. This is "
            "useful for decision making on whether to label more training points."
            " The default value is None and has no affect."
        ),
    )
    args_pars = parser.parse_args()
    return vars(args_pars)


if __name__ == "__main__":
    run_dict = mk_arg_pars()
    main(**run_dict)
