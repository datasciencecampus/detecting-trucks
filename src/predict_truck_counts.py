"""
Script for completing final truck detection and counting trucks.

The process chips each image (where not already chipped) and applies the trained
model to each in order to predict the total number of trucks in each chipped image.

The total truck counts per date are tallied across the chipped images.

The truck counts per date are then corrected for cloud coverage in that observation.

A final dataframe of the number of raw and corrected truck counts is exported
to a CSV file in the "final" subdir of data, with each row corresponding to date
where an S2 observation was analysed.

Can be executed in two modes:
    1) Single date: predicts truck numbers for given date. Useful for testing.
    2) All dates: predicts truck numbers for all observations to give CSV time
       series of cloud corrected truck counts for each observation date.

Returns
-------
new files
    In "all dates" mode, generates shapefiles of each positive truck detection
    for each observation and stores them in "data/<location>/processed/predictions"
    AND a final CSV data file of cloud corrected truck counts in "data/<location>/final".
new files
    In "single date" mode, generates the shapefile only and does not execute cloud
    correction.
"""

# Standard Library
import pickle
import re
import warnings
from datetime import datetime
from pathlib import Path

## Project
from truck_detection.cloud_time_series import (
    apply_correction_for_cloud,
    create_cloud_dataframe,
)
from truck_detection.detect_trucks import (
    predict_trucks_across_all,
    predict_trucks_single_date,
)
from utils.file_handling import generate_file_list, set_data_dir

## Third Party
from yaml import Loader, load


def main(location: str = None, test_date: str = None):
    """
    Execute process for predicting truck counts using trained model.

    Can be executed in two modes:
    1) Single date: predicts truck numbers for given date. Useful for testing.
    2) All dates: predicts truck numbers for all observations to give CSV time
    series of cloud corrected truck counts for each observation date.

    Parameters
    ----------
    test_single_date : bool, optional
        If True, predict_trucks_single_date() is executed which chips and
        performs model prediction on the image from the specified date. If
        False, the full process is executed and all images are chipped with the
        model prediction applied. The default value is False. It is recommended
        this be set to True when running for the first time to test.
    test_date : str
       The specified date for execution of predict_trucks_single_date() when
       test_single_date set to True. The string should be in form "<YYYY-MM-DD>".
       Default value is "YYYY-MM-DD", which is ignored if test_single_date = False.
       But this must be changed to valid observation date if performing test run.

    Returns
    -------
    new files
       In "all dates" mode, generates shapefiles of each positive truck detection
       for each observation and stores them in "data/<location>/processed/predictions"
       AND a final CSV data file of cloud corrected truck counts in "data/<location>/final".
    new files
       In "single date" mode, generates the shapefile only and does not execute cloud
       correction.
    """
    this_script_dir = Path(__file__).resolve().parent
    data_dir = this_script_dir.parent.joinpath("data", location, "processed")
    models_dir = this_script_dir.parent.joinpath("outputs", location, "models")
    predictions_dir = set_data_dir(data_dir, "predictions")
    whole_image_list = generate_file_list(
        data_dir.joinpath("s2_images"), "tif", [location]
    )
    list_of_dates = [re.findall(r"(\d+-\d+-\d+)", str(img)) for img in whole_image_list]

    with open(models_dir.joinpath("trained_model.pkl"), "rb") as file:
        model = pickle.load(file)
    with open(models_dir.joinpath("scaler.pkl"), "rb") as file:
        scaler = pickle.load(file)

    if test_date:
        datetime.strptime(test_date, "%Y-%m-%d")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            predict_trucks_single_date(
                data_dir.joinpath("chips"), model, scaler, location, date=test_date
            )
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            predict_trucks_across_all(data_dir, list_of_dates, location, model, scaler)

        create_cloud_dataframe(whole_image_list, predictions_dir, location)
        apply_correction_for_cloud(predictions_dir, location)
        print(
            f"\nCloud corrected truck counts saved to 'data/{location}/final/cloud_corrected_truck_counts.csv"
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
        "-test_date",
        "--test_date",
        default=None,
        help=(
            "Optional argument that, if used, will apply the prediction"
            " process to a single date. This date should be pre-chipped."
            " This is advisable for running this script"
            " for the first time, as a test case. The expected date should be in the"
            " following format YYYY-MM-DD and match one of the S2 images. The "
            "default value is None, in which case the full set of images will be "
            "processed."
        ),
    )
    args_pars = parser.parse_args()
    return vars(args_pars)


if __name__ == "__main__":
    run_dict = mk_arg_pars()
    main(**run_dict)
