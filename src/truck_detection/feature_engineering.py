"""
Script of functions for performing feature engineering.

This is intended to be run in conjunction with the "build_training_data.py"
script in order to generate the training data.

"""


# Standard library
import re
from pathlib import Path
from typing import List, Tuple

# Third party
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio as rio
from data_processing.masking import cloud_mask
from rasterio.io import MemoryFile
from rasterio.plot import reshape_as_image, reshape_as_raster
from skimage.color import rgb2hsv
from skimage.filters.rank import maximum
from skimage.morphology import dilation, local_maxima, square

# Project
from utils.column_headers import define_training_data_column_headers
from utils.file_handling import generate_file_list


def calc_normalized_diff(arr: np.ndarray, band_one: int, band_two: int) -> np.array:
    """
    Calculate normalised difference between two bands.

    Parameters
    ----------
    arr : numpy.ndarray
        Image array.
    band_one : int
        Index representation of first image band.
    band_two : int
        Index representation of second image band.

    Returns
    -------
    np.ndarray
        Normalized difference of the two different bands.

    Notes
    -----
    Indexing in rasterio.read() starts at 1, however the calculation uses
    numpy, where indexing starts at zero. So necessary to input zero-indexed
    band numbers.

    For reference: The S2 bands are ordered Blue, Green, Red such that
      Blue = Band 1 (i.e. index 0)
      Green = Band 2 (i.e. index = 1)
      Red = Band 3 (i.e. index = 2)

    """
    return (arr[band_one] - arr[band_two]) / (arr[band_one] + arr[band_two])


def calculate_z_score(arr: np.ndarray) -> np.ndarray:
    """Return Z-score across array of values."""
    mean_val = arr.mean()
    std_val = arr.std()
    z_score = (arr - mean_val) / std_val
    return z_score


def rescale_image_to_8bit(img_arr: np.ndarray) -> np.ndarray:
    """
    Rescale image from floating point to 8-bit range.

    Convert floating point values to within 0 to 255 8-bit integer range using
    min-max scaling. This is done because skimage max filter functions require
    8-bit precision only.

    Parameters
    ----------
    img_arr : numpy.ndarray
        Image array of multiple bands in floating point.

    Returns
    -------
    numpy.ndarray
        Image array of multiple bands as uint8.

    """
    rescale = lambda img: ((img - img.min()) / (img.max() - img.min())) * 255
    if img_arr.ndim == 3:
        for i, img_band in enumerate(img_arr):
            img_arr[i] = rescale(img_band)
    else:
        img_arr = rescale(img_arr)
    return img_arr.astype("uint8")


def dilate_band(band_arr: np.ma.array, kernel_size: int = 3) -> np.ma.array:
    """
    Find local maxima within a square of given kernel size around each pixel.

    Uses skimage filters.rank.maximum to find max pixel in kernel window. Then
    resets all masked pixels to zero and sets non-masked pixels to local maxima.
    Returns masked array.

    Parameters
    ----------
    band_arr : np.ma.array
        Array representation of a single band of an image.
    kernel_size : int, optional
        The width/height of the square kernel used, in unit of pixels.
        The default is 3.

    Returns
    -------
    numpy.ma.array
        Masked array with values masked values set to zero and non-masked values
        set to local maxima value.

    """
    max_arr = maximum(band_arr, square(kernel_size), mask=~band_arr.mask)
    max_arr = np.where(band_arr.mask, 0, max_arr)
    return np.ma.masked_array(max_arr, mask=band_arr.mask)


def get_temporal_based_zscores(
    color_band_index: tuple,
    temporal_mean_img_arr: np.ndarray,
    color1_to_color2: np.ndarray,
    color1_green: bool,
) -> np.ndarray:
    """
    Return Z-scores for the difference between colour bands in temporal mean image.
    """
    if color1_green:
        mean_color1_to_color2 = calc_normalized_diff(
            temporal_mean_img_arr, 1, color_band_index[0]
        )
    else:
        mean_color1_to_color2 = calc_normalized_diff(
            temporal_mean_img_arr, 2, color_band_index[1]
        )
    color_diff = color1_to_color2 - mean_color1_to_color2
    arr_color1_to_color2 = calculate_z_score(color_diff)
    return arr_color1_to_color2


def get_band_ratio_features(
    img_arr: np.ndarray,
    temporal_mean_img_arr: np.ndarray,
    temporal_analysis: bool = False,
    analyse_blue_band: bool = False,
    kernel_size: int = 3,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Capture max signal between colour bands.

    Take a spatial expansion around each pixel and return local maxima colour
    differences. This can be done on single image or against the temporal composite.

    Parameters
    ----------
    img_arr : numpy.ma.core.MaskedArray
        Array representation of single observation images.
    temporal_mean_img_arr : numpy.ndarray
        Array representation of the temporal mean composite image. Only used
        when temporal_analysis argument set to True.
    temporal_analysis : bool, optional
        Determines whether to perform spatial or temporal analysis. If True,
        the temporal composite image is used and features calculated relative to
        temporal mean. If False, the feature values are calculated within the
        spatial analysis of the single observation input image only.
    analyse_blue_band : bool, optional
        If True, the blue band is one of the bands being processed and the green
        to blue and red to blue values are extracted. If False, the green to red
        and red to green values are extracted.
    kernel_size : int, optional
        The diameter of the square kernel used in dilation, in unit of pixels.
        The default is 3.

    Returns
    -------
    green_to_color_max : numpy.ma.core.MaskedArray
        An array of the local maximum ratios between green another colour band
        (either red or blue). If a temporal run, then these are the Z-scores.
    red_to_color_max : numpy.ma.core.MaskedArray
        An array of the local maximum ratios between red another colour band
        (either green or blue). If a temporal run, then these are the Z-scores.

    Notes
    -----
    Takes a spatial expansion around each pixel and return local maxima colour
    differences. The aim is to capture the maximum signal between colour bands.
    We do this as a crucial property trucks in the images is that they form a
    sequential blue, green and red effect of pixels, which are connected within
    a limited kernel space of only a few pixels. Non-truck related colour
    sequences in the imagery are more likely to be randomly distributed.

    Rationale:
    The truck effect is a blue, green, red in that order. The labelled truck points
    are on the blue pixel only of the truck effect. In a truck signal there should
    be a green pixel near to this blue pixel and a red pixel quite near, but a bit
    further away than the green. This function is used to essentially ask "what is
    the nearest green pixel value" (defining greeness as its relative value to red / blue),
    then, "what is the most red pixel value (again relative to green / blue) connected
    to the most green pixel value" - the connectivity is to capture the true positive
    property of blue, green, red in that order.

    Procedure:
        1) Calculate normalised difference between bands ((b1-b2)/(b1+b2)))
        2) Rescale resulting arrays of diffs to 8-bit
        3) Dilate the diff arrays to locate local maxima
        4) Create mask from kernel around b1 maxima pixel
        5) Mask out pixels in b2 not in this kernel
        6) Within remaining b2 pixels dilate up to twice to capture local maxima
        7) Replace b2 maxima from step 3 with new maxima within permitted
           kernel of b1.

    """
    if analyse_blue_band:
        color_band_index = (0, 0)
    else:
        color_band_index = (2, 1)  # red and green bands respectively

    green_to_color = calc_normalized_diff(img_arr, 1, color_band_index[0])
    red_to_color = calc_normalized_diff(img_arr, 2, color_band_index[1])

    if temporal_analysis:
        green_to_color = get_temporal_based_zscores(
            color_band_index, temporal_mean_img_arr, green_to_color, color1_green=True
        )
        red_to_color = get_temporal_based_zscores(
            color_band_index, temporal_mean_img_arr, red_to_color, color1_green=False
        )
    green_to_color_8bit = rescale_image_to_8bit(green_to_color)
    red_to_color_8bit = rescale_image_to_8bit(red_to_color)

    # Expand green by kernel square
    green_to_color_max = dilate_band(green_to_color_8bit, kernel_size=kernel_size)
    # Expand red by 3 by 3 kernel
    red_to_color_max = dilate_band(red_to_color_8bit, kernel_size=kernel_size)
    # Hopefully for true hits green is a local maxima
    # Apply this to the expanded green image
    new_mask = local_maxima(green_to_color_max, square(3))
    # Make a new red image masked where not green local maxima - this allows some connectivity
    masked_red_to_color_max = np.ma.masked_array(red_to_color_max, mask=~new_mask)
    # Move the red over up to two times within the 'max green window'
    wider_red_to_color_max = dilate_band(dilate_band(masked_red_to_color_max))
    # Replace the red dilation within 'max green window' to original red dilation
    np.copyto(
        red_to_color_max, wider_red_to_color_max, where=~wider_red_to_color_max.mask
    )
    return green_to_color_max, red_to_color_max


def rgb_to_hsv(img_arr: np.ndarray) -> np.ndarray:
    """
    Convert RGB true colour image to hue, saturation, value colour space.

    Take a S2 masked array in 'blue, green, red, cloud' order. Convert b,g,r to
    skimage order and output three band image of hue, saturation, value.

    Parameters
    ----------
    img_arr : numpy.ndarray
        Array representing RGB true colour image.

    Returns
    -------
    hsv_img : numpy.ndarray
        Array representing image in hue, saturation, value format.

    Notes
    -----
    In S2 true colour images , the reflectances are coded between 1 and 255.
    The saturation level of 255 digital counts correspond to a level of 2000
    for L2A products (0.2 in reflectance value respectively).

    """
    rgb_img = np.ma.stack([img_arr[2], img_arr[1], img_arr[0]], 0)
    rgb_img = rgb_img / 0.2
    rgb_as_image = reshape_as_image(rgb_img)
    hsv_img = rgb2hsv(rgb_as_image)
    hsv_img = reshape_as_raster(hsv_img)
    hsv_img = np.ma.masked_array(hsv_img, mask=rgb_img.mask)
    return hsv_img


def create_stacked_img(
    img_fp: Path, temporal_composite_fp: Path, cloud_threshold: int = 25
) -> Tuple[np.ma.stack, dict]:
    """
    Create a stacked image where each layer is an array of pixel-wise feature values.

    Take an observation image and its equivalent temporal mean image and calculate
    the various feature values. Generate a stacked image, where each layer represents
    a feature, ready to be used for the ML method.

    Parameters
    ----------
    img_fp : Path
        Filepath to a single observation image.
    temporal_composite_fp : Path
        Filepath of temporal composite image covering same area as above.
    cloud_threshold : int, optional
        Cloud probability threshold above which pixels are masked. This is
        passed to the "cloud_mask" function. The default is 25.

    Returns
    -------
    numpy.ma.stack
        Stacked image where each layer is an array of pixel-wise feature values.
    profile : dict
        Basic metadata of input training image (img_fp).

    """
    with rio.open(img_fp) as file:
        filtered_img = file.read(masked=True)
        filtered_img = cloud_mask(filtered_img, cloud_threshold)
        profile = file.meta
        profile.update(count=1)

    with rio.open(temporal_composite_fp) as file:
        temporal_mean_img = file.read(masked=True)

    # Create bg_ratio
    bg_img = calc_normalized_diff(filtered_img, 0, 1)
    # Create br_ratio
    br_img = calc_normalized_diff(filtered_img, 0, 2)

    # Create composite mean
    bg_mean = calc_normalized_diff(temporal_mean_img, 0, 1)
    br_mean = calc_normalized_diff(temporal_mean_img, 0, 2)

    # Create difference img minus temporal mean
    bg_change = bg_img - bg_mean
    br_change = br_img - br_mean

    bg_img_z = calculate_z_score(bg_change)
    br_img_z = calculate_z_score(br_change)

    hsv_img = rgb_to_hsv(filtered_img)

    green_max, red_max = get_band_ratio_features(
        filtered_img,
        temporal_mean_img,
        temporal_analysis=False,
        analyse_blue_band=False,
        kernel_size=3,
    )

    green_max_temp, red_max_temp = get_band_ratio_features(
        filtered_img,
        temporal_mean_img,
        temporal_analysis=True,
        analyse_blue_band=False,
        kernel_size=3,
    )

    greenblue_max, redblue_max = get_band_ratio_features(
        filtered_img,
        temporal_mean_img,
        temporal_analysis=False,
        analyse_blue_band=True,
        kernel_size=3,
    )

    greenblue_max_temp, redblue_max_temp = get_band_ratio_features(
        filtered_img,
        temporal_mean_img,
        temporal_analysis=True,
        analyse_blue_band=True,
        kernel_size=3,
    )

    green_max5, red_max5 = get_band_ratio_features(
        filtered_img,
        temporal_mean_img,
        temporal_analysis=False,
        analyse_blue_band=False,
        kernel_size=5,
    )

    green_max_temp5, red_max_temp5 = get_band_ratio_features(
        filtered_img,
        temporal_mean_img,
        temporal_analysis=True,
        analyse_blue_band=False,
        kernel_size=5,
    )

    greenblue_max5, redblue_max5 = get_band_ratio_features(
        filtered_img,
        temporal_mean_img,
        temporal_analysis=False,
        analyse_blue_band=True,
        kernel_size=5,
    )

    greenblue_max_temp5, redblue_max_temp5 = get_band_ratio_features(
        filtered_img,
        temporal_mean_img,
        temporal_analysis=True,
        analyse_blue_band=True,
        kernel_size=5,
    )

    img_stack = np.ma.stack(
        [
            filtered_img[0],
            filtered_img[1],
            filtered_img[2],
            bg_change,
            br_change,
            bg_img_z,
            br_img_z,
            bg_img,
            br_img,
            hsv_img[0],
            hsv_img[1],
            hsv_img[2],
            green_max,
            red_max,
            green_max_temp,
            red_max_temp,
            greenblue_max,
            redblue_max,
            greenblue_max_temp,
            redblue_max_temp,
            green_max5,
            red_max5,
            green_max_temp5,
            red_max_temp5,
            greenblue_max5,
            redblue_max5,
            greenblue_max_temp5,
            redblue_max_temp5,
        ],
        0,
    )

    return (img_stack, profile)


def label_training_feature_values(
    stacked_img: np.ndarray,
    validation_points: gpd.GeoDataFrame,
    profile: dict,
    extract_truck_pixels: bool = True,
    sample: bool = False,
) -> pd.DataFrame:
    """
    Create training data from stacked image and labelled validation points.

    Combine pixel-wise feature values from stacked image with pixel labelling
    for suspected trucks to generate labelled training dataset for supervised
    ML model.

    Parameters
    ----------
    stacked_img : numpy.ndarray
        Stacked image of different bands.
    validation_points : gpd.GeoDataFrame
        Point geometry of pixels labelled as trucks in the image.
    profile : dict
        Image meta data.
    extract_truck_pixels : bool, optional
        If True, extracts pixels labelled as suspected trucks. If False,
        extracts unlabelled pixels. Default is True.
    sample : bool, optional
        If True, and number of unlabelled pixels exeeds
        10,000, then select sample of 10,000 from unlabelled pixels.
        If False, takes all unlabelled pixels. The default is False.

    Returns
    -------
    pandas.DataFrame
        Dataframe of pixel feature values labelled as either truck or non-truck
        pixels.

    """
    with MemoryFile() as memfile:
        with memfile.open(**profile) as dataset:
            dataset_arr = dataset.read(1)
            shapes = (
                (geom, value)
                for geom, value in zip(
                    validation_points.geometry, validation_points.truck_pixels
                )
            )
            points = rio.features.rasterize(
                shapes=shapes, fill=0, out=dataset_arr, transform=dataset.transform
            )
            if not extract_truck_pixels:
                points = dilation(points, square(3))

    points = np.reshape(points, (1,) + points.shape)
    stacked_img = np.concatenate((stacked_img, points))

    stacked_img = stacked_img.reshape(stacked_img.shape[0], -1)
    stacked_img = stacked_img.filled(np.nan)
    # Want to remove rows where all values of row are nan as this will be mask
    msk = np.all(np.isnan(stacked_img), axis=0)
    use = stacked_img.T[~msk]
    column_headers = define_training_data_column_headers()
    init_df = pd.DataFrame(use, columns=column_headers)
    # Drop rows where any one pixel column is null
    init_df = init_df.dropna()

    if extract_truck_pixels:
        init_df["ml_class"] = 1
        truck_pixels = init_df[(init_df["blue"] != -999) & (init_df["validation"] == 1)]
        return truck_pixels
    else:
        init_df["ml_class"] = 0
        non_truck_pixels = init_df[
            (init_df["blue"] != -999) & (init_df["validation"] != 1)
        ]
        if (len(non_truck_pixels["ml_class"]) > 10000) & sample:
            non_truck_pixels = non_truck_pixels.sample(10000)
        return non_truck_pixels


def generate_training_data(
    validation_points_fps: List[Path],
    location_name: str,
    sample: bool = True,
    data_dir: Path = Path(__file__).resolve().parent.parent.joinpath("data"),
) -> Tuple[pd.DataFrame, np.ma.stack]:
    """
    Perform feature engineering steps and generate training data.

    Parameters
    ----------
    validation_points_fps : List[Path]
        List of paths to training point shapefiles (i.e. positions of suspected
        truck locations in a specific image).
    location_name : str
        String representation of the location of interest, as used in file names.
    sample : bool, optional
        Decides whether to limit the maximum sample size of non-truck pixels to
        be returned by label_training_feature_values() function. The default is True.
    data_dir : Path, optional
        Filepath to the directory where data files are stored. The default is
        ../data from execution script.

    Returns
    -------
    pandas.DataFrame, numpy.ma.stack
        Dataframe of training data (with feature values labelled as truck and
        non-truck) and a stacked image where each layer is an array representation
        of feature values for the training image.

    """
    column_headers = define_training_data_column_headers()
    training_data = pd.DataFrame(columns=column_headers)
    stacked_imgs = []
    for i, validation_fp in enumerate(validation_points_fps):
        validation_points = gpd.read_file(validation_fp)
        if len(validation_points) == 0:
            continue
        date = re.split(r"[/_.]", str(validation_fp))[-2]

        labelled_img = generate_file_list(
            data_dir,
            "tif",
            [location_name, date],
        )
        temporal_img = data_dir.joinpath(
            f"s2a_{location_name}_temporal_mean_training_area.tif"
        )

        stacked_img, profile = create_stacked_img(labelled_img[0], temporal_img)

        validation_points["ml_class"] = 1
        validation_points["date"] = date
        validation_points["truck_pixels"] = 1

        non_truck_pixels = label_training_feature_values(
            stacked_img,
            validation_points,
            profile,
            extract_truck_pixels=False,
            sample=sample,
        )
        non_truck_pixels["date"] = date

        truck_pixels = label_training_feature_values(
            stacked_img, validation_points, profile, extract_truck_pixels=True
        )
        truck_pixels["date"] = date

        if i < (len(validation_points_fps) - 1):
            # Iterates through training validation point files to extract pixel values
            print(f"Training data: {location_name}-{date}")
            training_data = pd.concat([training_data, non_truck_pixels, truck_pixels])
            stacked_imgs.append(stacked_img)

        else:
            # If only testing one image and validation file
            training_data = pd.concat([training_data, non_truck_pixels, truck_pixels])
            training_data = training_data[training_data["bg_change"] > -999]
            stacked_imgs.append(stacked_img)

    return training_data, stacked_imgs
