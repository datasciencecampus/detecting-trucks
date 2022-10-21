"""
Script for estimating proportion of road pixels that are cloud.
"""

# Standard library
import re
from pathlib import Path
from typing import List

# Third party
import pandas as pd
import rasterio as rio

# Project
from utils.file_handling import set_data_dir


def cloud_percentage(image_list: List[Path], threshold: int = 25) -> pd.DataFrame:
    """
    Return the proportion of cloud pixels for each image in a list of images.

    Parameters
    ----------
    image_list : list[Path]
        List of filepaths to the unchipped observation images.
    threshold : int, optional
        Threshold for cloud probability. The default is 25.

    Returns
    -------
    percentage_cloud_pix : pandas.DataFrame
        Dataframe containing the date of each obseravation with the percentage
        of pixels which have a cloud probability above the given threshold.

    Notes
    -----
    For each image, this does the following:
    1. Take forth image layer (cloud probability).
    2. Remove masked pixels from band.
    3. Return the proportion of these pixels for which cloud probability >25%.

    """
    perc_cloud = []
    for img in image_list:
        print(f"Calculating cloud percentage of image {img.name}")
        with rio.open(img) as file:
            filtered_img = file.read(masked=True)
            cloud = filtered_img[3].astype("uint8")  # Forth layer = cloud probability
            cloud_unmask = cloud[~cloud.mask]
            date = re.search(r"(\d+-\d+-\d+)", str(img))
            num_cloud_pixels = len(cloud_unmask[cloud_unmask > threshold])
            percent = 100 * (num_cloud_pixels / len(cloud_unmask))
            perc_cloud.append([date[0], percent])
    percentage_cloud_pix = pd.DataFrame(perc_cloud, columns=["date", "perc_cloud"])
    return percentage_cloud_pix


def create_cloud_dataframe(
    image_list: List[Path], data_dir: Path, location: str
) -> pd.DataFrame:
    """
    Calculate percentage of image pixels which are cloud for each observation.

    Create a CSV file of the date of each obseravation with the percentage of
    pixels which have a cloud probability above the given threshold (default
    value 25 %).

    Parameters
    ----------
    image_list : list[Path]
        List of filepaths to the unchipped observation images.
    data_dir : pathlib.Path
        Directory where image files stored.
    location : str
        The string identifying geo-location of images, as used in filenames.

    Returns
    -------
    df_percent_cloud : pandas.DataFrame
        Dataframe containing the date of each obseravation with the
        percentage of pixels which have a cloud probability above the given
        threshold. CSV file of this dataframe is saved at data_dir directory.

    """

    df_percent_cloud = cloud_percentage(image_list)
    df_percent_cloud.to_csv(
        data_dir.joinpath(f"{location}_percent_cloud.csv"), index=False
    )
    return df_percent_cloud


def apply_correction_for_cloud(data_dir, location):
    """
    Apply correction to truck counts based on cloud coverage of images.

    Parameters
    ----------
    data_dir : Path
        Filepath to directory where data files stored.
    location : str
        String representation of location of interest, as used on file naming.
    """
    truck_counts_df = pd.read_csv(
        data_dir.joinpath(f"{location}_model_predictions_results.csv")
    )

    df_percent_cloud = pd.read_csv(data_dir.joinpath(f"{location}_percent_cloud.csv"))

    truck_counts_df["date"] = pd.to_datetime(truck_counts_df["date"])
    df_percent_cloud["date"] = pd.to_datetime(df_percent_cloud["date"])

    df_percent_cloud.set_index("date").plot.line(
        figsize=(12, 7),
        legend=False,
        xticks=df_percent_cloud["date"],
        rot=90,
        title="cloud percent",
    )

    truck_counts_df = truck_counts_df.merge(df_percent_cloud, how="inner", on="date")

    # Correct truck count prediction by percentage cloud cover
    correction_factor = 100 / (100 - truck_counts_df["perc_cloud"])
    truck_counts_df["count_cloud_weighted"] = truck_counts_df[
        "truck_prediction_count"
    ].mul(correction_factor)

    final_predictions_dir = set_data_dir(data_dir.parent.parent, "final")
    truck_counts_df.to_csv(
        final_predictions_dir.joinpath("cloud_corrected_truck_counts.csv"), index=False
    )

    return truck_counts_df
