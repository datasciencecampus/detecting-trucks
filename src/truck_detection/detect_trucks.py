"""
Functions for chipping images and predicting truck counts by applying model
prediction across the individual images chips and counting the number of
detected trucks across each observation.

This module is designed to used in conjunction with the predict_truck_counts
script.
"""

# Standard Library
from pathlib import Path
from typing import List, Tuple

# Third Party
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio as rio
from data_processing.image_processing import create_chips_from_grid
from rasterio.features import shapes
from tqdm import tqdm
from utils.file_handling import generate_file_list, set_data_dir

from .feature_engineering import create_stacked_img


def dissolve_contiguous(gdf: gpd.GeoDataFrame):
    """
    Dissolve contiguous features into one.

    Parameters
    ----------
    gdf : geopandas.GeoDataFrame
        The geodataframe to be dissolved.

    Returns
    -------
    geopandas.GeoDataFrame
        The resulting dissolved geodataframe as singlepart features.
    """
    gdf["diss"] = 1
    gdf = gdf.dissolve(by="diss", as_index=False)
    gdf = gdf.explode(index_parts=True)
    return gdf.reset_index(drop=True)


def get_mean_truck_probability(
    stacked_img: np.ndarray,
    model,
    scaler,
) -> float:
    """
    Calculate mean truck probability across all non-masked pixels in stacked image.

    Use model.predict_proba to get probability of each pixel classified as
    truck and non-truck and return average truck probability across full array.

    Parameters
    ----------
    stacked_img : numpy.ndarray
        Stacked array representation of image where each layer represents an
        array of feature values.
    model : model.fit
        The trained classifier model.

    scaler : scalar
        The scalar used in the modelling.

    Returns
    -------
    float
        Mean probability of truck classification across all pixels.

    """
    # reshape from 3D to 2D array with features as columns, row for each pixel
    dims = stacked_img.shape
    stacked_img = stacked_img.reshape(dims[0], -1).T

    # Get rid of the masked values -- initially fill the mask with -999
    stacked_img = stacked_img.filled(-999)
    # then using np.all on the row dimension (all column values should be > -999 to be road)
    stacked_img = stacked_img[np.all(stacked_img > -999, axis=1)]

    if stacked_img.shape == (0, 28):
        return 0
    else:
        # Scale the 2d array with the pre-fit scaler
        stacked_img = scaler.transform(stacked_img)
        # image prediction with same nrows as img_arr
        img_pred = model.predict_proba(stacked_img)
        # take the truck class probability
        img_pred = img_pred[:, 1]

        proba_mean = np.mean(img_pred)
        return proba_mean


def predict_image(stacked_img: np.ndarray, model, scaler) -> np.ndarray:
    """
    Apply model prediction to stacked image.

    Parameters
    ----------
    stacked_img : numpy.ndarray
        Stacked array representation of image where each layer represents an
        array of feature values.
    model : model.fit
        The trained classifier model.
    scaler : scalar
        The scalar used in the modelling.

    Returns
    -------
    numpy.ndarray
        Array of pixel-wise classification model predictions.

    """
    dims = stacked_img.shape
    img_arr = stacked_img.reshape(dims[0], -1).T
    img_arr_transformed = scaler.transform(img_arr)
    img_pred = model.predict(img_arr_transformed)
    img_pred_reshaped = img_pred.reshape(dims[1], dims[2]).astype("uint8")
    return img_pred_reshaped


def generate_prediction_geometry(
    img_meta: dict,
    class_img: np.ndarray,
    data_dir: Path,
):
    """
    Generate a shapefile of geometries associated with truck predictions.

    Polygons are formed of each contiguous set of pixels which are predicted to
    be trucks and a geodataframe generated where each row represents one such
    polygon. Each polygon in the dataframe corresponds to a predicted truck
    detection.

    Parameters
    ----------
    img_meta : rasterio.profile
        The meta data used to write image into GeoTIFF
    class_img : np.ndarray
        Array of model predictions (i.e. pixel-wise results of model.predict
        applied to the stacked features image).
    data_dir : Path
        Filepath to directory where data stored.

    Returns
    -------
    geopandas.GeoDataFrame or None
        Dataframe where each row is a polygon representing the boundary of a
        contiguous set of pixels associated with a positive truck detection.
        Or, returns None if no truck detections are made.

    """
    img_meta.update(count=1, nodata=0, dtype="uint8")
    with rio.open(data_dir.joinpath("temp_class.tif"), "w", **img_meta) as dst:
        dst.write(np.expand_dims(class_img, axis=0))
    with rio.open(data_dir.joinpath("temp_class.tif")) as src:
        classimg = src.read(1, masked=True).astype("uint8")
        rshapes = (
            {"properties": {"uniqueid": i}, "geometry": s}
            for i, (s, v) in enumerate(shapes(classimg, transform=src.transform))
        )
    geometry = list(rshapes)
    if len(geometry) > 0:
        polygons = gpd.GeoDataFrame.from_features(
            geometry, crs=img_meta["crs"].to_string()
        )
        polygons = dissolve_contiguous(polygons)
        return polygons
    else:
        print("No features")
        return None


def apply_model_to_chips(
    chips_dir,
    model,
    scaler,
    date_chip_list: List[Path],
    temporal_chip_list: List[Path],
    output_shp_fp: str,
) -> Tuple[gpd.GeoDataFrame, float]:
    """
    Predict truck counts in each chip image using trained model & output results.

    Parameters
    ----------
    chips_dir : Path
        Filepath to chips data directory.
    model : model.fit
        The trained classifier model.
    scaler : scalar
        The scalar used in the modelling.
    date_chip_list : List[Path]
        List of filepaths to each chipped image for the given observation date.
        This should be ordered in the same way as temporal_chip_list.
    temporal_chip_list : List[Path]
        List of filepaths to the temporal composite chipped images. This should
        be ordered in the same way as date_chip_list.
    output_shp_fp : str
        The desired filename for the output shapefile to be generated.

    Returns
    -------
    (geopandas.GeoDataFrame, float)
        1) Geodataframe where each row is a polygon representing the boundary of a
        contiguous set of pixels associated with a positive truck detection and
        2) The mean probability across all chips.

    """
    proba_chips = []

    merged_shapefile = gpd.GeoDataFrame(
        geometry=[], crs=rio.open(date_chip_list[0]).crs.to_string()
    )
    for i, (image_chip, temporal_chip) in enumerate(
        tqdm(zip(date_chip_list, temporal_chip_list), total=len(temporal_chip_list))
    ):
        stacked_img, profile = create_stacked_img(image_chip, temporal_chip)

        # calculate mean probability of positive class (truck) across image
        mean_truck_proba = get_mean_truck_probability(stacked_img, model, scaler)
        proba_chips.append(mean_truck_proba)

        model_predictions = predict_image(stacked_img, model, scaler)
        if model_predictions.max() > 0:
            pred_geom = generate_prediction_geometry(
                profile,
                model_predictions,
                chips_dir,
            )
            merged_shapefile = gpd.GeoDataFrame(
                pd.concat([merged_shapefile, pred_geom], ignore_index=True),
                crs=merged_shapefile.crs,
            )
        # print(f"Processed {i+1} chipped images of {len(date_chip_list)} total.")
    merged_shapefile = dissolve_contiguous(merged_shapefile)
    if len(merged_shapefile) > 0:
        merged_shapefile.to_file(output_shp_fp)

    # mean probability across all image chips
    mean_of_chips = np.mean(proba_chips)

    return merged_shapefile, mean_of_chips


def chip_and_predict(
    data_dir: Path,
    location_name: str,
    img_date: str,
    model,
    scaler,
    remove_date_chips: bool = False,
) -> Tuple[int, float]:
    """
    For given date, chip image and apply model to predict truck counts.

    Results are written out to file and count of rows in shapefile and mean
    probability across full observation image for given date returned.

    Parameters
    ----------
    data_dir : Path
        Data directory.
    location_name : str
        String representation of location of interest, as used on file naming.
    img_date : str
        Observation date of image being processed (in form YYYY-MM-DD)
    model : model.fit object
        Trained classification model (such as trained random forest classifier).
    scaler : scaler object
        The scaler used to transform model during training.
    remove_date_chips : bool, optional
        Optional argument that when True will remove the chipped images after
        applying the model prediction to them. This will keep the data directory
        more tidy and free up storage, however increases processing time when
        re-running this function as the chipping must be performed each time.
        By default the value is False.

    Returns
    -------
    Tuple[int, float]
        Returns the number of entries in the shapefiles generated (which
        corresponds to the number trucks detected) and returns the mean truck
        probability across all the non-masked pixels in all the chips (and thus
        across the observation for the given date).

    Raises
    ------
    FileNotFoundError
        The chipping process is reliant on the presence of a shapefile which
        controls the chipping geometry. An error is raised if the file is not
        found. Check the image_processing script has executed correctly if this
        happens.
    ValueError
        The number of chipped images for any given date need to equal the number
        of chipped images for the temporal composite image. If this is not the
        case a fatal error is raised. This indicates a problem with the execution
        of the image_chiping script.
    """
    img_date_fp = data_dir.joinpath("s2_images", f"s2a_{location_name}_{img_date}.tif")
    chips_dir = data_dir.joinpath("chips")
    grids_shapefile = chips_dir.joinpath(f"grids_use_{location_name}.shp")
    predictions_dir = data_dir.joinpath("predictions")

    if not grids_shapefile.exists():
        raise FileNotFoundError(
            f"Could not find grids_use_{location_name}.shp in data > chips "
            "directory. Have you run the image_processing process correctly?"
        )

    try:
        date_chips = generate_file_list(
            chips_dir.joinpath(img_date + "_chip_imgs"),
            "tif",
            [location_name, img_date],
        )
    except FileNotFoundError:
        date_chips = []

    if not date_chips:
        chips_img_dir = set_data_dir(chips_dir, img_date + "_chip_imgs")
        print(f"\nCreating chips for observation dated {img_date}.")
        create_chips_from_grid(
            img_date_fp,
            grids_shapefile,
            chips_img_dir.joinpath(f"s2a_{location_name}_{img_date}_"),
        )

        date_chips = generate_file_list(chips_img_dir, "tif", [location_name, img_date])

    temporal_mean_chips = generate_file_list(
        chips_dir.joinpath("temporal_mean_imgs"),
        "tif",
        [location_name, "temporal_mean"],
    )

    date_chips.sort()
    temporal_mean_chips.sort()
    if len(date_chips) != len(temporal_mean_chips):
        raise ValueError(
            f"{len(date_chips)} date chips does not equal "
            f"{len(temporal_mean_chips)} temporal chips"
        )

    try:
        previous_model_output = generate_file_list(
            predictions_dir, "shp", [location_name, img_date]
        )
    except FileNotFoundError:
        previous_model_output = []

    # Applies model prediction procedure only if never done before (i.e. output
    # files do not exist).
    if not previous_model_output:
        print(
            f"Applying model to the {len(temporal_mean_chips)} chips for the observation dated {img_date}:"
        )
        gdf, truck_prob_mean = apply_model_to_chips(
            chips_dir=chips_dir,
            model=model,
            scaler=scaler,
            date_chip_list=date_chips,
            temporal_chip_list=temporal_mean_chips,
            output_shp_fp=predictions_dir.joinpath(
                f"{location_name}_{img_date}_predictions.shp"
            ),
        )
        with open(
            predictions_dir.joinpath(f"{location_name}_{img_date}_mean_prediction.txt"),
            "w",
        ) as file:
            file.write(str(truck_prob_mean))
    else:
        gdf = gpd.read_file(previous_model_output[0])
        # If single test run is done, prediction shape file exists without corresponding
        # mean_prediction.txt file, throwing error.
        try:
            with open(
                predictions_dir.joinpath(
                    f"{location_name}_{img_date}_mean_prediction.txt"
                )
            ) as file:
                truck_prob_mean = float(file.read())
        except FileNotFoundError:
            gdf, truck_prob_mean = apply_model_to_chips(
                chips_dir=chips_dir,
                model=model,
                scaler=scaler,
                date_chip_list=date_chips,
                temporal_chip_list=temporal_mean_chips,
                output_shp_fp=predictions_dir.joinpath(
                    f"{location_name}_{img_date}_predictions.shp"
                ),
            )
            with open(
                predictions_dir.joinpath(
                    f"{location_name}_{img_date}_mean_prediction.txt"
                ),
                "w",
            ) as file:
                file.write(str(truck_prob_mean))

    if remove_date_chips:
        for file in date_chips:
            file.unlink()  # Deletes given file

    return len(gdf), truck_prob_mean


def predict_trucks_single_date(
    chips_dir: Path, model, scaler, location: str, date: str
):
    """
    Apply model prediction procedure to chipped images from given observation date.

    Parameters
    ----------
    chips_dir : Path
        Directory where chipped images stored.
    model : model.fit object
        Trained classification model (such as trained random forest classifier).
    scaler : scaler object
        The scaler used to transform model during training.
    location : str
        The location of interest.
    date : str
        Date of observation to be processed (as present in file names).

    Returns
    -------
    Where possible truck signal(s) predicted, shapefile generated containing
    geometry of the point(s). If no truck signal detected, nothing returned.

    """
    date_chips = generate_file_list(
        chips_dir.joinpath(date + "_chip_imgs"), "tif", [location, date]
    )

    temporal_mean_chips = generate_file_list(
        chips_dir.joinpath("temporal_mean_imgs"), "tif", [location, "temporal_mean"]
    )

    apply_model_to_chips(
        chips_dir,
        model,
        scaler,
        date_chips,
        temporal_mean_chips,
        chips_dir.parent.joinpath("predictions", f"{location}_{date}_predictions.shp"),
    )


def predict_trucks_across_all(
    data_dir: Path, list_of_dates: list, location: str, model, scaler
):
    """
    Predict the truck counts for all observations.

    Chip any outstanding images and predict the trained classification model
    across all chipped images for full set of available observation dates.

    Parameters
    ----------
    data_dir : Path
        Directory where data stored.
    list_of_dates : list
        List of dates in string format extracted from S2 image file. I.e. the dates
        where observations were taken.
    location : str
        The location of interest.
    model : model.fit object
        Trained classification model (such as trained random forest classifier).
    scaler : scaler object
        The scaler used to transform model during training.

    Returns
    -------
    Generates dataframe stored in a CSV file composed of date, estimated truck
    counts and the mean pixel-wise probability of a truck detection across image.
    """
    output_file = data_dir.joinpath(
        "predictions",
        f"{location}_model_predictions_results.csv",
    )

    if output_file.exists():
        output_file.unlink()  # Delete existing data file
        # Generate file of column headers
    pd.DataFrame(
        columns=["date", "truck_prediction_count", "mean_truck_probability"]
    ).to_csv(output_file, index=False)

    for date in list_of_dates:
        if date:
            date = date.pop()  # Retrieve string element
            truck_count, mean_prob = chip_and_predict(
                data_dir, location, date, model, scaler, remove_date_chips=False
            )
            d_res = [date, truck_count, mean_prob]
            date_df = pd.DataFrame(
                [d_res],
                columns=["date", "truck_prediction_count", "mean_truck_probability"],
            )
            date_df.to_csv(output_file, mode="a", index=False, header=False)
